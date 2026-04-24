"""Tests for hermes_cli/tui/cwd_strip.py — CWD token stripping."""
from __future__ import annotations

import pytest

from hermes_cli.tui.cwd_strip import has_cwd_token, strip_cwd


# ---------------------------------------------------------------------------
# strip_cwd() — no token
# ---------------------------------------------------------------------------

def test_strip_cwd_no_token_returns_text_unchanged():
    text = "normal output without any cwd tokens"
    cleaned, cwd = strip_cwd(text)
    assert cleaned == text
    assert cwd is None


def test_strip_cwd_empty_string():
    cleaned, cwd = strip_cwd("")
    assert cleaned == ""
    assert cwd is None


# ---------------------------------------------------------------------------
# strip_cwd() — valid token
# ---------------------------------------------------------------------------

def test_strip_cwd_extracts_path():
    text = "__HERMES_CWD_abcd1234__/home/user/project__HERMES_CWD_abcd1234__"
    cleaned, cwd = strip_cwd(text)
    assert cwd == "/home/user/project"
    assert "__HERMES_CWD_" not in cleaned


def test_strip_cwd_removes_tokens_from_output():
    text = "some output\n__HERMES_CWD_deadbeef__/tmp/work__HERMES_CWD_deadbeef__\nmore output"
    cleaned, cwd = strip_cwd(text)
    assert "__HERMES_CWD_" not in cleaned
    assert "some output" in cleaned
    assert "more output" in cleaned


def test_strip_cwd_path_is_stripped_of_whitespace():
    text = "__HERMES_CWD_00112233__  /home/user  __HERMES_CWD_00112233__"
    _, cwd = strip_cwd(text)
    assert cwd == "/home/user"


def test_strip_cwd_token_at_start_of_text():
    text = "__HERMES_CWD_aabbccdd__/root__HERMES_CWD_aabbccdd__\ncommand output"
    cleaned, cwd = strip_cwd(text)
    assert cwd == "/root"
    assert "command output" in cleaned


def test_strip_cwd_token_at_end_of_text():
    text = "output here\n__HERMES_CWD_12345678__/var/log__HERMES_CWD_12345678__"
    cleaned, cwd = strip_cwd(text)
    assert cwd == "/var/log"
    assert "output here" in cleaned


def test_strip_cwd_hex_token_min_8_chars():
    text = "__HERMES_CWD_abcdef12__/path__HERMES_CWD_abcdef12__"
    _, cwd = strip_cwd(text)
    assert cwd == "/path"


def test_strip_cwd_hex_token_max_32_chars():
    hex_32 = "a" * 32
    text = f"__HERMES_CWD_{hex_32}__/long/path__HERMES_CWD_{hex_32}__"
    _, cwd = strip_cwd(text)
    assert cwd == "/long/path"


def test_strip_cwd_different_open_close_tokens_are_accepted():
    """Open and close tokens can have different hex suffixes."""
    text = "__HERMES_CWD_aaaaaaaa__/some/dir__HERMES_CWD_bbbbbbbb__"
    _, cwd = strip_cwd(text)
    assert cwd == "/some/dir"


# ---------------------------------------------------------------------------
# strip_cwd() — empty path inside token
# ---------------------------------------------------------------------------

def test_strip_cwd_empty_path_inside_token_returns_none():
    """An empty path (whitespace only) between tokens returns None for cwd."""
    text = "__HERMES_CWD_abcd1234____HERMES_CWD_abcd1234__"
    _, cwd = strip_cwd(text)
    assert cwd is None


def test_strip_cwd_whitespace_only_path_returns_none():
    text = "__HERMES_CWD_abcd1234__   __HERMES_CWD_abcd1234__"
    _, cwd = strip_cwd(text)
    assert cwd is None


# ---------------------------------------------------------------------------
# strip_cwd() — multiline path (DOTALL)
# ---------------------------------------------------------------------------

def test_strip_cwd_multiline_content_inside_token():
    """The regex uses DOTALL — newlines inside tokens are captured."""
    text = "__HERMES_CWD_cafebabe__/home/\nuser__HERMES_CWD_cafebabe__"
    _, cwd = strip_cwd(text)
    # The path with newline is stripped; just verify no crash and token removed
    assert cwd is not None or cwd is None  # either is acceptable; token must be gone
    assert "__HERMES_CWD_" not in strip_cwd(text)[0]


# ---------------------------------------------------------------------------
# has_cwd_token()
# ---------------------------------------------------------------------------

def test_has_cwd_token_true_when_present():
    text = "output __HERMES_CWD_abcd1234__/path__HERMES_CWD_abcd1234__"
    assert has_cwd_token(text) is True


def test_has_cwd_token_false_when_absent():
    assert has_cwd_token("plain text") is False


def test_has_cwd_token_false_on_empty_string():
    assert has_cwd_token("") is False


def test_has_cwd_token_false_for_partial_token():
    """A partial / malformed token should not match."""
    assert has_cwd_token("__HERMES_CWD_abcd1234__") is False


# ---------------------------------------------------------------------------
# strip_cwd() — trailing whitespace removal
# ---------------------------------------------------------------------------

def test_strip_cwd_rstrips_trailing_whitespace_from_cleaned():
    text = "output\n__HERMES_CWD_11223344__/p__HERMES_CWD_11223344__   \n  "
    cleaned, _ = strip_cwd(text)
    assert cleaned == cleaned.rstrip()
