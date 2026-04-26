"""Tests for Tool Pipeline Spec A: Header Tail Consolidation & Grammar.

Covers A-1 through A-8 (27 tests, all unit-level, no Textual app mount).
"""
from __future__ import annotations

import types
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from rich.text import Text
from textual.geometry import Size
from textual.widget import Widget


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seg(name: str, text: str, style: str = "") -> tuple[str, Text]:
    t = Text()
    t.append(text, style=style)
    return (name, t)


def _bare_header(**kwargs):
    """ToolHeader via __new__ with minimal DOM stubs for _render_v4 testing."""
    from hermes_cli.tui.tool_blocks._header import ToolHeader
    h = ToolHeader.__new__(ToolHeader)
    defaults = dict(
        _label="test", _tool_name="bash", _line_count=0, _panel=None,
        _spinner_char=None, _is_complete=True, _tool_icon_error=False,
        _primary_hero=None, _header_chips=[], _stats=None, _duration="",
        _has_affordances=False, _label_rich=None, _is_child_diff=False,
        _header_args={}, _flash_msg=None, _flash_expires=0.0, _flash_tone="success",
        _error_kind=None, _tool_icon="", _full_path=None, _path_clickable=False,
        _is_child=False, _exit_code=None, _browse_badge="", _elapsed_ms=None,
        _no_underline=False, _bold_label=False, _hidden=False, _shell_prompt=False,
        _compact_tail=False, _is_url=False, _classes=frozenset(),
        _focused_gutter_color="#5f87d7",
        _diff_add_color="#4caf50", _diff_del_color="#ef4444",
        _running_icon_color="#82aaff", _remediation_hint=None,
        _pulse_t=0.0, _pulse_tick=0,
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(h, k, v)
    return h


def _render(h, *, width: int = 80, css_vars: dict | None = None, accessible: bool = False):
    """Call _render_v4 with mocked size and app."""
    mock_app = MagicMock()
    mock_app.get_css_variables.return_value = css_vars or {}
    with patch.object(Widget, "size", new_callable=PropertyMock,
                      return_value=Size(width, 24)):
        with patch.object(type(h), "app", new_callable=PropertyMock,
                          return_value=mock_app):
            with patch.object(h, "_accessible_mode", return_value=accessible):
                return h._render_v4()


def _plain(h, **kwargs) -> str:
    result = _render(h, **kwargs)
    return result.plain if result is not None else ""


def _spans_covering(result: Text, substring: str) -> list:
    plain = result.plain
    pos = plain.find(substring)
    if pos == -1:
        return []
    end = pos + len(substring)
    return [s for s in result._spans if s.start < end and s.end > pos]


# ---------------------------------------------------------------------------
# A-1: _DROP_ORDER keeps exit last
# ---------------------------------------------------------------------------

class TestDropOrder:
    def _trim(self, segs, budget):
        from hermes_cli.tui.tool_blocks._header import _trim_tail_segments
        return _trim_tail_segments(segs, budget)

    def test_exit_survives_narrow(self):
        """exit survives when linecount must drop to fit budget."""
        segs = [
            _seg("linecount", "  42L", "dim"),       # 5 cells
            _seg("duration", "  1.2s", "dim"),       # 6 cells
            _seg("exit", "  ok", "dim green"),       # 4 cells — total=15
        ]
        # budget=12: total(15) > 12, so trim; drop linecount first → 10 <= 12, done
        result = self._trim(segs, 12)
        names = [n for n, _ in result]
        assert "exit" in names
        assert "linecount" not in names

    def test_flash_drops_first(self):
        """flash drops before chevron and exit when budget is tight."""
        segs = [
            _seg("flash", "  ✓ saved", "dim #5f87d7"),  # ~9 cells
            _seg("chevron", "  ▸", "dim"),              # ~3 cells
            _seg("exit", "  ok", "dim green"),           # 4 cells — total ~16
        ]
        flash_w = segs[0][1].cell_len
        chev_w = segs[1][1].cell_len
        exit_w = segs[2][1].cell_len
        # budget: drop flash (largest, first in DROP_ORDER), keep chevron+exit
        budget = chev_w + exit_w + 1
        result = self._trim(segs, budget)
        names = [n for n, _ in result]
        assert "flash" not in names
        assert "exit" in names
        assert "chevron" in names

    def test_chip_drops_before_exit(self):
        """When budget forces one drop, chip drops before exit (ER-2: remediation/stderrwarn removed)."""
        segs = [
            _seg("chip", "  TOOL", "dim"),
            _seg("exit", "  ok", "dim green"),
        ]
        chip_w = segs[0][1].cell_len
        ex_w = segs[1][1].cell_len
        # Budget only fits exit
        budget = ex_w + 1
        result = self._trim(segs, budget)
        names = [n for n, _ in result]
        assert "chip" not in names
        assert "exit" in names

    def test_chevron_drops_before_exit(self):
        """Sub-chevron budget: chevron absent, exit present."""
        segs = [
            _seg("chevron", "  ▸", "dim"),
            _seg("exit", "  exit 1", "bold red"),
        ]
        ex_w = segs[1][1].cell_len
        budget = ex_w + 1
        result = self._trim(segs, budget)
        names = [n for n, _ in result]
        assert "chevron" not in names
        assert "exit" in names

    def test_all_fit_normal_width(self):
        """budget=60; all provided segments survive."""
        segs = [
            _seg("flash", "  ✓ ok", "dim"),
            _seg("duration", "  1.2s", "dim"),
            _seg("exit", "  ok", "dim green"),
            _seg("chevron", "  ▸", "dim"),
        ]
        result = self._trim(segs, 60)
        names = [n for n, _ in result]
        assert set(names) == {"flash", "duration", "exit", "chevron"}


# ---------------------------------------------------------------------------
# A-2: No double $ in shell header
# ---------------------------------------------------------------------------

class TestDoubleShellDollar:
    def test_shell_no_double_dollar_nerd(self):
        """Nerd-font SHELL header: no consecutive $$ in plain text."""
        h = _bare_header(
            _tool_name="bash",
            _tool_icon="",  # nerd-font shell glyph
            _label="git status",
            _focused_gutter_color="",  # suppress label $ prefix
        )
        text = _plain(h)
        assert "$$" not in text
        assert "$ $" not in text

    def test_shell_no_double_dollar_ascii(self):
        """ASCII fallback SHELL header: icon $ appears once; no extra header $."""
        h = _bare_header(
            _tool_name="bash",
            _tool_icon="$",  # ASCII fallback
            _label="git status",
            _focused_gutter_color="",  # suppress label $ prefix so icon $ is isolated
        )
        text = _plain(h)
        assert text.count("$") == 1, f"Expected exactly 1 $ (icon); got: {text!r}"

    def test_fixed_prefix_excludes_shell_prompt(self):
        """FIXED_PREFIX_W for SHELL == FIXED_PREFIX_W for FILE (no shell_prompt_w term)."""
        import inspect
        from hermes_cli.tui.tool_blocks._header import ToolHeader
        src = inspect.getsource(ToolHeader._render_v4)
        assert "shell_prompt_w" not in src


# ---------------------------------------------------------------------------
# A-3: · grammar separator between tail segments
# ---------------------------------------------------------------------------

class TestGrammarSeparator:
    def _make_header_with_hero_and_duration(self, accessible=False):
        h = _bare_header(
            _tool_name="read_file",
            _primary_hero="Read 10 lines",
            _duration="1.2s",
            _is_complete=True,
        )
        return h

    def test_separator_between_two_segments(self):
        """Two tail segments produce · between them."""
        h = self._make_header_with_hero_and_duration()
        text = _plain(h, width=120)
        assert "·" in text

    def test_no_separator_single_segment(self):
        """Single tail segment (chevron only) produces no separator ' · '."""
        h = _bare_header(
            _tool_name="bash",
            _exit_code=None,
            _is_complete=False,   # avoids hero/exit segments
            _duration="",
            _has_affordances=False,
            _primary_hero=None,
            _line_count=0,
        )
        text = _plain(h, width=120)
        # Only chevron present; separator ' · ' (with surrounding spaces) must not appear
        assert " · " not in text

    def test_separator_accessibility_ascii(self):
        """In accessible mode (constants.accessibility_mode) separator is '-' not '·'."""
        h = self._make_header_with_hero_and_duration()
        with patch("hermes_cli.tui.constants.accessibility_mode", return_value=True):
            text = _plain(h, width=120)
        # The separator glyph '-' must appear (ASCII fallback for '·')
        assert " - " in text

    def test_separator_not_doubled(self):
        """Three tail segments produce exactly 2 separator patterns ' · '."""
        h = _bare_header(
            _tool_name="read_file",
            _primary_hero="Read 10 lines",
            _duration="1.2s",
            _is_complete=True,
            _exit_code=0,  # suppressed because hero is present
        )
        text = _plain(h, width=200)
        # Segments: hero, chevron, duration = 3 segments -> 2 separators ' · '
        # (The chevron itself is '·' but without surrounding spaces as separator)
        assert text.count(" · ") == 2, f"Expected 2 separators in {text!r}"


# ---------------------------------------------------------------------------
# A-4: Hero text: muted (dim), not dim green
# ---------------------------------------------------------------------------

class TestHeroStyling:
    def _hero_spans(self, h, hero_text: str, **kwargs):
        result = _render(h, **kwargs)
        assert result is not None
        return _spans_covering(result, hero_text)

    def test_hero_not_green_on_success(self):
        """Success hero — no 'green' in any span covering the hero text."""
        h = _bare_header(
            _tool_name="read_file",
            _primary_hero="Read 120 lines",
            _is_complete=True,
            _tool_icon_error=False,
        )
        spans = self._hero_spans(h, "Read 120 lines", width=120)
        for s in spans:
            assert "green" not in str(s.style), f"Span style should not contain 'green': {s.style!r}"

    def test_hero_dim_on_success(self):
        """Success hero — span style is exactly 'dim' (no color, no bold)."""
        h = _bare_header(
            _tool_name="read_file",
            _primary_hero="Read 120 lines",
            _is_complete=True,
            _tool_icon_error=False,
        )
        result = _render(h, width=120)
        assert result is not None
        plain = result.plain
        pos = plain.find("Read 120 lines")
        assert pos != -1, "Hero text not found in rendered output"
        hero_text = "Read 120 lines"
        hero_spans = [s for s in result._spans
                      if s.start <= pos and s.end >= pos + len(hero_text)]
        assert any(s.style == "dim" for s in hero_spans), (
            f"Expected a 'dim' span covering hero; got: {[s.style for s in hero_spans]}"
        )

    def test_error_hero_still_red(self):
        """Error hero — span style contains 'red' or a hex color."""
        h = _bare_header(
            _tool_name="bash",
            _primary_hero="Permission denied",
            _is_complete=True,
            _tool_icon_error=True,
        )
        result = _render(h, width=120)
        assert result is not None
        plain = result.plain
        pos = plain.find("Permission denied")
        assert pos != -1, "Error hero text not found"
        hero_text = "Permission denied"
        hero_spans = [s for s in result._spans
                      if s.start <= pos and s.end >= pos + len(hero_text)]
        styles = [str(s.style) for s in hero_spans]
        assert any("red" in st or "#" in st for st in styles), (
            f"Error hero must have red/hex style; got: {styles}"
        )


# ---------------------------------------------------------------------------
# A-5: Always-visible exit code (no is_collapsed guard)
# ---------------------------------------------------------------------------

class TestAlwaysVisibleExit:
    def _make_expanded_panel(self):
        panel = MagicMock()
        panel.collapsed = False
        panel._block = MagicMock()
        panel._result_summary_v4 = None
        panel._resolver = None
        return panel

    def test_exit_ok_visible_expanded(self):
        """is_collapsed=False, exit_code=0, no hero → 'ok' in rendered text."""
        panel = self._make_expanded_panel()
        h = _bare_header(
            _tool_name="bash",
            _is_complete=True,
            _exit_code=0,
            _primary_hero=None,
            _panel=panel,
        )
        text = _plain(h, width=120)
        assert "ok" in text

    def test_exit_N_visible_expanded(self):
        """is_collapsed=False, exit_code=2 → 'exit 2' in rendered text."""
        panel = self._make_expanded_panel()
        h = _bare_header(
            _tool_name="bash",
            _is_complete=True,
            _exit_code=2,
            _panel=panel,
        )
        text = _plain(h, width=120)
        assert "exit 2" in text

    def test_exit_ok_suppressed_when_hero(self):
        """exit_code=0 with non-empty hero → no 'ok' segment (avoids redundancy)."""
        panel = self._make_expanded_panel()
        h = _bare_header(
            _tool_name="read_file",
            _is_complete=True,
            _exit_code=0,
            _primary_hero="Read 120 lines",
            _panel=panel,
        )
        text = _plain(h, width=120)
        # 'ok' segment should be suppressed; hero "Read 120 lines" is there instead
        assert "Read 120 lines" in text
        # "ok" should not appear as a standalone chip
        # (it may appear inside "Read 120 lines" if substring, but not as separate "  ok")
        import re
        assert not re.search(r"\bok\b", text.replace("Read 120 lines", "")), (
            f"Standalone 'ok' should not appear when hero is present: {text!r}"
        )


# ---------------------------------------------------------------------------
# A-6: 4 display tiers for category visual identity
# ---------------------------------------------------------------------------

class TestDisplayTierMapping:
    def test_file_tier(self):
        from hermes_cli.tui.tool_category import display_tier_for, ToolCategory
        assert display_tier_for(ToolCategory.FILE) == "file"

    def test_exec_tier(self):
        from hermes_cli.tui.tool_category import display_tier_for, ToolCategory
        assert display_tier_for(ToolCategory.SHELL) == "exec"
        assert display_tier_for(ToolCategory.CODE) == "exec"

    def test_query_tier(self):
        from hermes_cli.tui.tool_category import display_tier_for, ToolCategory
        assert display_tier_for(ToolCategory.SEARCH) == "query"
        assert display_tier_for(ToolCategory.WEB) == "query"
        assert display_tier_for(ToolCategory.MCP) == "query"


# ---------------------------------------------------------------------------
# A-7: Post-completion icon tinted with tier accent
# ---------------------------------------------------------------------------

class TestCompletionIconTint:
    def _icon_styles(self, result: Text, icon_str: str) -> list[str]:
        plain = result.plain
        pos = plain.find(icon_str)
        if pos == -1:
            return []
        return [str(s.style) for s in result._spans if s.start <= pos < s.end]

    def test_file_icon_uses_tier_accent(self):
        """read_file completed → icon style contains tool-tier-file-accent color."""
        h = _bare_header(
            _tool_name="read_file",
            _tool_icon="",  # nerd-font file icon
            _is_complete=True,
            _tool_icon_error=False,
        )
        result = _render(h, width=120, css_vars={"tool-tier-file-accent": "#4DB6AC"})
        assert result is not None
        # Find any span with the tier accent color
        accent_found = any("#4DB6AC" in str(s.style) for s in result._spans)
        assert accent_found, f"Expected #4DB6AC in spans; got: {[str(s.style) for s in result._spans]}"

    def test_exec_icon_uses_tier_accent(self):
        """bash completed → icon style contains tool-tier-exec-accent color."""
        h = _bare_header(
            _tool_name="bash",
            _tool_icon="",  # nerd-font shell icon
            _is_complete=True,
            _tool_icon_error=False,
        )
        result = _render(h, width=120, css_vars={"tool-tier-exec-accent": "#81C784"})
        assert result is not None
        accent_found = any("#81C784" in str(s.style) for s in result._spans)
        assert accent_found, f"Expected #81C784 in spans; got: {[str(s.style) for s in result._spans]}"

    def test_error_icon_still_red(self):
        """Error icon path uses _diff_del_color (red), not tier accent."""
        h = _bare_header(
            _tool_name="bash",
            _tool_icon="",
            _is_complete=True,
            _tool_icon_error=True,
            _diff_del_color="#ef4444",
        )
        result = _render(h, width=120, css_vars={"tool-tier-exec-accent": "#81C784"})
        assert result is not None
        # Tier accent must NOT appear; del color must appear
        assert not any("#81C784" in str(s.style) for s in result._spans), (
            "Error icon must not use tier accent"
        )
        assert any("#ef4444" in str(s.style) for s in result._spans), (
            "Error icon must use _diff_del_color"
        )

    def test_streaming_icon_lerp_unaffected(self):
        """Spinner/streaming path produces lerp color, not tier accent."""
        h = _bare_header(
            _tool_name="bash",
            _tool_icon="",
            _spinner_char="⠸",
            _is_complete=False,
            _tool_icon_error=False,
        )
        result = _render(h, width=120, css_vars={"tool-tier-exec-accent": "#81C784"})
        assert result is not None
        # Tier accent color must not appear during streaming
        assert not any("#81C784" in str(s.style) for s in result._spans), (
            "Streaming icon must use lerp color, not tier accent"
        )


# ---------------------------------------------------------------------------
# A-8: Emoji icon bias + ASCII fallback collision fixes
# ---------------------------------------------------------------------------

class TestIconHygiene:
    def test_code_emoji_is_laptop(self):
        """CODE emoji is 💻 (language-agnostic), not 🐍 (Python-biased)."""
        from hermes_cli.tui.tool_category import _EMOJI_ICONS, ToolCategory
        assert _EMOJI_ICONS[ToolCategory.CODE] == "💻"

    def test_ascii_fallback_no_collision(self):
        """All ASCII fallbacks are unique, single char, and true ASCII (<128)."""
        from hermes_cli.tui.tool_category import _CATEGORY_DEFAULTS
        fallbacks = [d.ascii_fallback for d in _CATEGORY_DEFAULTS.values()]
        # All single chars
        for fb in fallbacks:
            assert len(fb) == 1, f"ascii_fallback must be 1 char, got {fb!r}"
        # All true ASCII
        for fb in fallbacks:
            assert ord(fb) < 128, f"ascii_fallback must be ASCII, got {fb!r} (ord={ord(fb)})"
        # All unique
        assert len(set(fallbacks)) == len(fallbacks), (
            f"ascii_fallbacks must be unique; duplicates found: {fallbacks}"
        )
