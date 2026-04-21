"""Tests for hermes_cli/tui/osc8.py — OSC 8 hyperlink injection."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from hermes_cli.tui.osc8 import inject_osc8, is_supported


# ---------------------------------------------------------------------------
# _osc8_supported() / is_supported()
# ---------------------------------------------------------------------------

def _clean_env(**overrides):
    """Return a clean env dict with OSC-8-related vars stripped, plus overrides."""
    keys = {"HERMES_OSC8", "TERM_PROGRAM", "VTE_VERSION", "KITTY_WINDOW_ID", "WT_SESSION"}
    base = {k: v for k, v in os.environ.items() if k not in keys}
    base.update(overrides)
    return base


def test_is_supported_env_override_1_returns_true():
    with patch.dict("os.environ", _clean_env(HERMES_OSC8="1"), clear=True):
        from hermes_cli.tui import osc8 as _m
        _m._osc8_supported.cache_clear()
        assert _m._osc8_supported() is True


def test_is_supported_env_override_0_returns_false():
    with patch.dict("os.environ", _clean_env(HERMES_OSC8="0"), clear=True):
        from hermes_cli.tui import osc8 as _m
        _m._osc8_supported.cache_clear()
        assert _m._osc8_supported() is False


@pytest.mark.parametrize("term", ["iterm.app", "hyper", "wezterm", "ghostty", "vscode"])
def test_is_supported_known_good_term_programs(term):
    with patch.dict("os.environ", _clean_env(TERM_PROGRAM=term), clear=True):
        from hermes_cli.tui import osc8 as _m
        _m._osc8_supported.cache_clear()
        assert _m._osc8_supported() is True


def test_is_supported_vte_version_returns_true():
    with patch.dict("os.environ", _clean_env(VTE_VERSION="6702"), clear=True):
        from hermes_cli.tui import osc8 as _m
        _m._osc8_supported.cache_clear()
        assert _m._osc8_supported() is True


def test_is_supported_kitty_window_id_returns_true():
    with patch.dict("os.environ", _clean_env(KITTY_WINDOW_ID="1"), clear=True):
        from hermes_cli.tui import osc8 as _m
        _m._osc8_supported.cache_clear()
        assert _m._osc8_supported() is True


def test_is_supported_foot_term_program_returns_true():
    with patch.dict("os.environ", _clean_env(TERM_PROGRAM="foot"), clear=True):
        from hermes_cli.tui import osc8 as _m
        _m._osc8_supported.cache_clear()
        assert _m._osc8_supported() is True


def test_is_supported_unknown_terminal_returns_false():
    with patch.dict("os.environ", _clean_env(TERM_PROGRAM="xterm"), clear=True):
        from hermes_cli.tui import osc8 as _m
        _m._osc8_supported.cache_clear()
        assert _m._osc8_supported() is False


def test_is_supported_alias_is_same_function():
    from hermes_cli.tui import osc8 as _m
    assert is_supported is _m._osc8_supported


# ---------------------------------------------------------------------------
# inject_osc8() — disabled path
# ---------------------------------------------------------------------------

def test_inject_osc8_disabled_returns_text_unchanged():
    text = "see /usr/local/bin and https://example.com"
    assert inject_osc8(text, _enabled=False) == text


def test_inject_osc8_disabled_plain_text_unchanged():
    text = "no paths here"
    assert inject_osc8(text, _enabled=False) == text


# ---------------------------------------------------------------------------
# inject_osc8() — URL wrapping
# ---------------------------------------------------------------------------

def test_inject_osc8_wraps_http_url():
    url = "https://example.com/page"
    result = inject_osc8(url, _enabled=True)
    assert "\033]8;;" in result
    assert url in result
    assert "\033\\" in result


def test_inject_osc8_wraps_https_url():
    result = inject_osc8("see https://docs.python.org/3/ for details", _enabled=True)
    assert "https://docs.python.org/3/" in result
    assert "\033]8;;" in result


def test_inject_osc8_url_trailing_punctuation_stripped_from_link():
    """Trailing comma/period should not be included inside the OSC 8 link."""
    result = inject_osc8("check https://example.com/page, please", _enabled=True)
    # The URL inside the OSC 8 sequence should not end with a comma
    # Extract the URL from the OSC 8 open sequence
    # Format: ESC]8;;<URL>ESC\
    import re
    m = re.search(r'\033\]8;;([^\033]+)\033\\', result)
    assert m is not None
    assert not m.group(1).endswith(",")


def test_inject_osc8_url_close_sequence_present():
    result = inject_osc8("https://example.com", _enabled=True)
    # Should have open and close
    assert result.count("\033]8;;") == 2
    # Close is ESC]8;;ESC\  (empty URL)
    assert "\033]8;;\033\\" in result


# ---------------------------------------------------------------------------
# inject_osc8() — absolute path wrapping
# ---------------------------------------------------------------------------

def test_inject_osc8_wraps_absolute_path():
    result = inject_osc8("see /etc/hosts for details", _enabled=True)
    assert "\033]8;;" in result
    assert "file:///etc/hosts" in result


def test_inject_osc8_absolute_path_url_scheme_is_file():
    result = inject_osc8("/tmp/foo.txt", _enabled=True)
    assert "file:///tmp/foo.txt" in result


def test_inject_osc8_relative_path_uses_cwd():
    with patch("os.getcwd", return_value="/home/user/project"):
        result = inject_osc8("./src/main.py", _enabled=True)
    assert "file:///home/user/project/./src/main.py" in result or \
           "file:///home/user/project/src/main.py" in result or \
           "/home/user/project" in result


def test_inject_osc8_does_not_wrap_key_equals_path():
    """key=path should NOT be linkified (assignment context)."""
    result = inject_osc8("key=/some/path", _enabled=True)
    # The _PATH_RE has a negative lookbehind for '=', so /some/path after '=' is excluded
    # Result should not contain an OSC 8 sequence wrapping /some/path
    # (the = guard should prevent it)
    import re
    osc_matches = re.findall(r'\033\]8;;file://([^\033]+)\033\\', result)
    # If anything wrapped, the path should not be '/some/path' tied to 'key='
    for match in osc_matches:
        assert "key=" not in result[:result.find(match)]


def test_inject_osc8_does_not_wrap_https_path():
    """https://host/path should be handled by URL regex, not path regex."""
    result = inject_osc8("https://example.com/path/to/page", _enabled=True)
    # Should have exactly 2 OSC 8 markers (one open, one close) from URL handler
    assert result.count("\033]8;;") == 2
    # The link target should be the full URL, not just the path
    import re
    m = re.search(r'\033\]8;;([^\033]+)\033\\', result)
    assert m is not None
    assert m.group(1).startswith("https://")


# ---------------------------------------------------------------------------
# inject_osc8() — text without matches
# ---------------------------------------------------------------------------

def test_inject_osc8_no_paths_or_urls_returns_unchanged():
    text = "hello world, no links here"
    assert inject_osc8(text, _enabled=True) == text


def test_inject_osc8_empty_string():
    assert inject_osc8("", _enabled=True) == ""


# ---------------------------------------------------------------------------
# inject_osc8() — multiple matches in one string
# ---------------------------------------------------------------------------

def test_inject_osc8_multiple_urls_both_wrapped():
    result = inject_osc8("see https://a.com and https://b.com", _enabled=True)
    assert result.count("\033]8;;") == 4  # 2 open + 2 close


def test_inject_osc8_url_and_path_both_wrapped():
    result = inject_osc8("visit https://example.com or open /etc/hosts", _enabled=True)
    assert result.count("\033]8;;") >= 4
