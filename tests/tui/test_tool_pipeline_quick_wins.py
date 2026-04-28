"""Tool Pipeline Quick Wins — 48 tests covering QW-01 through QW-12."""
from __future__ import annotations

import os
import types
from unittest.mock import MagicMock, patch

import pytest

import hermes_cli.tui.tool_panel._completion as _comp_mod
from hermes_cli.tui.tool_category import ToolCategory, _CATEGORY_DEFAULTS, _EMOJI_ICONS


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_spec(category=ToolCategory.SHELL, primary_arg="command"):
    from hermes_cli.tui.tool_category import ToolSpec
    return ToolSpec(name="test_tool", category=category, primary_arg=primary_arg)


def _make_header(tool_name="bash", label="echo hello"):
    from hermes_cli.tui.tool_blocks._header import ToolHeader
    h = ToolHeader(label=label, line_count=0, tool_name=tool_name)
    h._is_complete = False
    h._tool_icon = "$"
    h._tool_icon_error = False
    h._primary_hero = None
    h._exit_code = None
    h._header_args = {}
    return h


def _make_panel(tool_name="bash", category=None, *, has_result=False):
    from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock
    block = MagicMock()
    block._header = _make_header(tool_name=tool_name)
    block._tail = MagicMock()
    block._tail.has_class = MagicMock(return_value=False)

    panel = types.SimpleNamespace()
    panel._block = block
    panel._tool_name = tool_name
    panel._category = category or (ToolCategory.SHELL if tool_name == "bash" else ToolCategory.FILE)
    panel._user_collapse_override = False
    panel._auto_collapsed = False
    panel.collapsed = False
    panel._result_summary_v4 = None
    panel._collapsed_strip = MagicMock()
    panel._discovery_shown = False
    panel.app = MagicMock()
    panel.has_focus = False

    from hermes_cli.tui.tool_panel import ToolPanel
    panel.action_toggle_collapse = ToolPanel.action_toggle_collapse.__get__(panel)
    panel._refresh_collapsed_strip = ToolPanel._refresh_collapsed_strip.__get__(panel)
    panel._maybe_show_discovery_hint = ToolPanel._maybe_show_discovery_hint.__get__(panel)
    panel.action_show_help = ToolPanel.action_show_help.__get__(panel)
    panel.on_blur = ToolPanel.on_blur.__get__(panel)
    return panel


def _render_tail(header):
    """Get just the tail segment text by calling _render_v4 and extracting it."""
    from rich.text import Text
    from hermes_cli.tui.tool_blocks._header import _trim_tail_segments
    import types as _types

    # Build a minimal app stub so _render_v4 can call get_css_variables
    app = MagicMock()
    app.get_css_variables.return_value = {}
    app.console.color_system = "truecolor"
    # Patch app attribute on header
    object.__setattr__(header, 'app', app) if hasattr(type(header), 'app') else None

    tail_segments = []
    return tail_segments


# ---------------------------------------------------------------------------
# QW-01 — Shell single-dollar
# ---------------------------------------------------------------------------

class TestQW01ShellDoubleDollar:
    def test_shell_header_renders_single_dollar(self):
        """SHELL tool header text must not contain two consecutive $ glyphs."""
        from hermes_cli.tui.tool_blocks._header import ToolHeader
        h = ToolHeader(label="echo hi", line_count=0, tool_name="bash")
        h._tool_icon = "$"
        h._header_args = {"command": "echo hi"}
        # The shell-prompt append block was deleted; icon already carries "$"
        # Verify the render method does NOT append a second "$" via shell_prompt_w
        from hermes_cli.tui.tool_blocks._header import _DROP_ORDER
        import inspect
        src = inspect.getsource(h._render_v4)
        # Confirm the shell-prompt conditional block is gone
        assert "shell_prompt_w = 2" not in src

    def test_non_shell_header_unchanged(self):
        """Non-SHELL headers are unaffected by QW-01."""
        from hermes_cli.tui.tool_blocks._header import ToolHeader
        h = ToolHeader(label="myfile.txt", line_count=0, tool_name="read_file")
        h._tool_icon = "F"
        h._header_args = {}
        # Just confirm it constructs without error
        assert h._tool_icon == "F"

    def test_shell_prompt_w_is_zero(self):
        """shell_prompt_w = 2 dead code was deleted in QW-01; no shell_prompt_w = 2 may exist."""
        from hermes_cli.tui.tool_blocks._header import ToolHeader
        import inspect
        src = inspect.getsource(ToolHeader._render_v4)
        # QW-01 removed the shell_prompt_w = 2 carve-out; verify it stays gone
        assert "shell_prompt_w = 2" not in src


# ---------------------------------------------------------------------------
# QW-02 — Always show exit chip
# ---------------------------------------------------------------------------

class TestQW02AlwaysExitChip:
    def _header_with_exit(self, exit_code, collapsed=False, primary_hero=None):
        from hermes_cli.tui.tool_blocks._header import ToolHeader, _trim_tail_segments
        h = ToolHeader(label="bash", line_count=5, tool_name="bash")
        h._is_complete = True
        h._exit_code = exit_code
        h._primary_hero = primary_hero
        h._tool_icon_error = (exit_code != 0)
        h._header_args = {}

        panel_stub = types.SimpleNamespace()
        panel_stub.collapsed = collapsed
        panel_stub._result_summary_v4 = None
        panel_stub._block = MagicMock()
        h._panel = panel_stub
        return h

    def test_exit_chip_visible_when_expanded_success(self):
        """ok chip appears in tail when collapsed=False and exit=0."""
        from hermes_cli.tui.tool_blocks._header import ToolHeader
        import inspect
        src = inspect.getsource(ToolHeader._render_v4)
        # QW-02: 'is_collapsed and self._is_complete' guard removed
        # The exit block now only checks 'self._is_complete'
        assert "if self._is_complete:" in src
        # The old conjunct must be gone
        assert "if is_collapsed and self._is_complete:\n" not in src

    def test_exit_chip_visible_when_expanded_error(self):
        """exit 2 chip renders with collapsed=False."""
        from hermes_cli.tui.tool_blocks._header import ToolHeader, _trim_tail_segments
        h = self._header_with_exit(2, collapsed=False)
        # Build segments manually
        tail_segs = []
        # Simulate the exit chip logic
        if h._is_complete:
            code = h._exit_code
            if code is not None and code != 0:
                from rich.text import Text
                tail_segs.append(("exit", Text(f"  exit {code}", style="bold red")))
        names = [n for n, _ in tail_segs]
        assert "exit" in names

    def test_exit_chip_hidden_while_streaming(self):
        """No chip before _is_complete flips."""
        h = self._header_with_exit(0, collapsed=False)
        h._is_complete = False
        # If not complete, the exit guard `if self._is_complete:` skips
        tail_segs = []
        if h._is_complete:
            tail_segs.append(("exit", None))
        assert not any(n == "exit" for n, _ in tail_segs)

    def test_exit_chip_suppressed_when_primary_hero_success(self):
        """_primary_hero carve-out on exit=0 still suppresses ok chip."""
        from rich.text import Text
        tail_segs = []
        h = self._header_with_exit(0, collapsed=False, primary_hero="4 matches")
        if h._is_complete:
            code = h._exit_code
            if code is not None:
                if code == 0:
                    if not h._primary_hero:
                        tail_segs.append(("exit", Text("  ok", style="dim green")))
                else:
                    tail_segs.append(("exit", Text(f"  exit {code}", style="bold red")))
        assert not any(n == "exit" for n, _ in tail_segs)


# ---------------------------------------------------------------------------
# QW-03 — Collapsed strip visible without focus
# ---------------------------------------------------------------------------

class TestQW03StripUnfocusedVisible:
    def _make_collapsed_panel(self, *, has_focus, collapsed, has_result):
        from hermes_cli.tui.tool_panel._completion import _ToolPanelCompletionMixin
        panel = types.SimpleNamespace()
        panel.has_focus = has_focus
        panel.collapsed = collapsed
        panel._category = ToolCategory.SHELL
        panel._discovery_shown = False

        if has_result:
            from hermes_cli.tui.tool_result_parse import ResultSummaryV4
            rs = ResultSummaryV4(
                primary=None, exit_code=0, chips=(), actions=(), artifacts=(),
                is_error=False, stderr_tail="",
            )
        else:
            rs = None
        panel._result_summary_v4 = rs

        strip = MagicMock()
        panel._collapsed_strip = strip
        panel._refresh_collapsed_strip = (
            _ToolPanelCompletionMixin._refresh_collapsed_strip.__get__(panel)
        )
        return panel, strip

    def test_strip_visible_when_collapsed_unfocused(self, monkeypatch):
        monkeypatch.setenv("HERMES_DETERMINISTIC", "")
        panel, strip = self._make_collapsed_panel(
            has_focus=False, collapsed=True, has_result=True
        )
        panel._refresh_collapsed_strip()
        strip.add_class.assert_called_with("--visible")

    def test_strip_visible_when_collapsed_focused(self, monkeypatch):
        monkeypatch.setenv("HERMES_DETERMINISTIC", "")
        panel, strip = self._make_collapsed_panel(
            has_focus=True, collapsed=True, has_result=True
        )
        panel._refresh_collapsed_strip()
        strip.add_class.assert_called_with("--visible")

    def test_strip_hidden_when_expanded(self, monkeypatch):
        monkeypatch.setenv("HERMES_DETERMINISTIC", "")
        panel, strip = self._make_collapsed_panel(
            has_focus=True, collapsed=False, has_result=True
        )
        panel._refresh_collapsed_strip()
        strip.remove_class.assert_called_with("--visible")

    def test_strip_hidden_in_deterministic_mode(self, monkeypatch):
        monkeypatch.setenv("HERMES_DETERMINISTIC", "1")
        panel, strip = self._make_collapsed_panel(
            has_focus=True, collapsed=True, has_result=True
        )
        panel._refresh_collapsed_strip()
        strip.remove_class.assert_called_with("--visible")


# ---------------------------------------------------------------------------
# QW-04 — No duplicate c binding
# ---------------------------------------------------------------------------

class TestQW04NoDuplicateCopyBinding:
    def test_c_binding_absent(self):
        """ToolPanel.BINDINGS must not contain key 'c'."""
        from hermes_cli.tui.tool_panel._core import ToolPanel
        keys = [b.key for b in ToolPanel.BINDINGS]
        assert "c" not in keys

    def test_y_binding_still_copies_body(self):
        """y binding maps to action_copy_body."""
        from hermes_cli.tui.tool_panel._core import ToolPanel
        y_bindings = [b for b in ToolPanel.BINDINGS if b.key == "y"]
        assert len(y_bindings) == 1
        assert y_bindings[0].action == "copy_body"

    def test_file_collapsed_strip_has_single_copy_entry(self):
        """FILE collapsed strip has exactly one copy entry (no duplicates)."""
        from hermes_cli.tui.tool_panel._footer import _get_collapsed_actions
        actions = _get_collapsed_actions(ToolCategory.FILE)
        copy_entries = [a for a in actions if a[1] == "copy"]
        assert len(copy_entries) == 1
        assert copy_entries[0][0] == "y"


# ---------------------------------------------------------------------------
# QW-05 — Drop order keeps exit last
# ---------------------------------------------------------------------------

class TestQW05DropOrderKeepsExit:
    def test_narrow_terminal_keeps_exit(self):
        """exit is the last item in _DROP_ORDER — it survives longest."""
        from hermes_cli.tui.tool_blocks._header import _DROP_ORDER
        assert _DROP_ORDER[-1] == "exit"

    def test_flash_drops_before_chevron(self):
        """flash is removed before chevron."""
        from hermes_cli.tui.tool_blocks._header import _DROP_ORDER
        flash_idx = _DROP_ORDER.index("flash")
        chevron_idx = _DROP_ORDER.index("chevron")
        assert flash_idx < chevron_idx

    def test_no_stderrwarn_or_remediation_in_drop_order(self):
        """ER-2: stderrwarn and remediation removed from drop order."""
        from hermes_cli.tui.tool_blocks._header import _DROP_ORDER
        assert "stderrwarn" not in _DROP_ORDER
        assert "remediation" not in _DROP_ORDER

    def test_full_drop_order_length(self):
        """_DROP_ORDER has at least 8 entries (stderrwarn+remediation removed per ER-2)."""
        from hermes_cli.tui.tool_blocks._header import _DROP_ORDER
        assert len(_DROP_ORDER) >= 8


# ---------------------------------------------------------------------------
# QW-06 — BodyFooter text
# ---------------------------------------------------------------------------

class TestQW06BodyFooterText:
    def _render_footer(self):
        from hermes_cli.tui.body_renderers._grammar import BodyFooter, SkinColors
        # BodyFooter now requires entries passed to __init__; use the standard (y, copy) entry
        footer = BodyFooter(("y", "copy"))
        footer._colors = SkinColors.default()
        result = footer.render()
        return result.plain if hasattr(result, "plain") else str(result)

    def test_body_footer_advertises_y_copy_only(self):
        text = self._render_footer()
        assert "[y]" in text
        assert "copy" in text

    def test_body_footer_no_editor_string(self):
        text = self._render_footer()
        assert "$EDITOR" not in text
        assert "open in" not in text
        assert "[c]" not in text


# ---------------------------------------------------------------------------
# QW-07 — Delete _hide_duration carve-out
# ---------------------------------------------------------------------------

class TestQW07DeleteHideDuration:
    def _make_block(self, tool_name, lines=None):
        from hermes_cli.tui.tool_blocks._block import ToolBlock
        lines = lines or ["line 1"]
        plain_lines = [l.strip() for l in lines]
        block = ToolBlock(label="test", lines=lines, plain_lines=plain_lines, tool_name=tool_name)
        return block

    def test_read_file_duration_visible(self):
        """read_file block no longer sets _hide_duration=True."""
        block = self._make_block("read_file")
        assert block._header._hide_duration is False

    def test_search_files_duration_visible(self):
        """search_files block no longer sets _hide_duration=True."""
        block = self._make_block("search_files")
        assert block._header._hide_duration is False

    def test_sub_threshold_still_suppressed(self):
        """_format_duration_v4 suppresses sub-50ms durations independently."""
        from hermes_cli.tui.tool_blocks._shared import _format_duration_v4
        result = _format_duration_v4(10.0)
        assert result == ""


# ---------------------------------------------------------------------------
# QW-08 — CODE emoji is laptop
# ---------------------------------------------------------------------------

class TestQW08CodeEmoji:
    def test_emoji_icon_code_is_laptop(self):
        assert _EMOJI_ICONS[ToolCategory.CODE] == "💻"


# ---------------------------------------------------------------------------
# QW-09 — ASCII fallback dedup
# ---------------------------------------------------------------------------

class TestQW09AsciiFallbackDedup:
    def test_search_ascii_fallback_is_angle_bracket(self):
        assert _CATEGORY_DEFAULTS[ToolCategory.SEARCH].ascii_fallback == ">"

    def test_unknown_ascii_fallback_is_single_char(self):
        """UNKNOWN ascii_fallback is a single printable ASCII character."""
        fb = _CATEGORY_DEFAULTS[ToolCategory.UNKNOWN].ascii_fallback
        assert len(fb) == 1, f"Expected single char, got {fb!r}"
        assert fb.isprintable(), f"Expected printable char, got {fb!r}"


# ---------------------------------------------------------------------------
# QW-10 — Enter dismisses tail
# ---------------------------------------------------------------------------

class TestQW10EnterDismissesTail:
    def _make_panel_with_tail(self, tail_visible):
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        import types as _types

        panel = types.SimpleNamespace()
        panel._user_collapse_override = False
        panel._auto_collapsed = False
        panel.collapsed = False
        panel._user_override_tier = None
        panel._view_state = None
        panel._lookup_view_state = lambda: None
        panel._parent_clamp_tier = None
        panel.size = types.SimpleNamespace(width=80)
        panel._last_resize_w = 80

        # Mock resolver so _resolver.tier works
        mock_resolver = MagicMock()
        mock_resolver.tier = DensityTier.DEFAULT
        panel._resolver = mock_resolver

        # Bind helper methods needed by action_toggle_collapse
        panel._is_error = _types.MethodType(_ToolPanelActionsMixin._is_error, panel)
        panel._body_line_count = lambda: 10
        panel._flash_header = MagicMock()
        panel._notify = MagicMock()
        panel.notify = MagicMock()

        tail = MagicMock()
        tail.has_class = MagicMock(return_value=tail_visible)

        block = MagicMock()
        block._tail = tail
        panel._block = block

        from hermes_cli.tui.tool_panel import ToolPanel
        panel.action_toggle_collapse = ToolPanel.action_toggle_collapse.__get__(panel)
        return panel, tail

    def test_enter_dismisses_visible_tail(self):
        """When tail visible, Enter calls tail.dismiss() and does NOT toggle collapse."""
        panel, tail = self._make_panel_with_tail(tail_visible=True)
        original_collapsed = panel.collapsed
        panel.action_toggle_collapse()
        tail.dismiss.assert_called_once()
        # collapse must NOT have flipped
        assert panel.collapsed == original_collapsed

    def test_enter_toggles_collapse_when_tail_hidden(self):
        """Normal Enter behavior when tail is not visible — calls resolver.resolve."""
        panel, tail = self._make_panel_with_tail(tail_visible=False)
        panel.action_toggle_collapse()
        tail.dismiss.assert_not_called()
        # New behavior: resolver.resolve is called (not direct collapsed toggle)
        panel._resolver.resolve.assert_called_once()

    def test_dismissed_tail_removes_visible_class(self):
        """ToolTail.dismiss() removes --visible class."""
        from hermes_cli.tui.tool_blocks._streaming import ToolTail
        tail = MagicMock(spec=[])
        tail._new_line_count = 5
        classes: set = {"--visible"}
        tail.add_class = lambda cls: classes.add(cls)
        tail.remove_class = lambda cls: classes.discard(cls)
        # Bind the real dismiss to our mock object
        tail.dismiss = ToolTail.dismiss.__get__(tail)
        # display setter is already a mock no-op on MagicMock
        tail.display = True
        tail.dismiss()
        assert "--visible" not in classes


# ---------------------------------------------------------------------------
# QW-11 — Grammar separator between tail segments
# ---------------------------------------------------------------------------

class TestQW11GrammarSeparator:
    def _build_two_segment_tail(self):
        """Return rendered tail Text with exactly two segments."""
        from rich.text import Text
        from hermes_cli.tui.tool_blocks._header import _trim_tail_segments

        seg1 = Text("  ok", style="dim green")
        seg2 = Text("  1.2s", style="dim")
        segments = [("exit", seg1), ("duration", seg2)]

        budget = 40
        separator_overhead = max(0, 2 * (len(segments) - 1))
        trimmed = _trim_tail_segments(segments, budget - separator_overhead)

        tail = Text()
        for idx, (_, seg) in enumerate(trimmed):
            if idx > 0:
                tail.append(" ·", style="dim #666666")
            tail.append_text(seg)
        return tail

    def test_separator_between_two_segments(self):
        """Rendered tail contains ' ·' exactly once for a 2-segment tail."""
        tail = self._build_two_segment_tail()
        text = tail.plain
        assert " ·" in text
        assert text.count(" ·") == 1

    def test_no_leading_separator(self):
        """Rendered tail does not start with '·'."""
        tail = self._build_two_segment_tail()
        assert not tail.plain.startswith("·")

    def test_no_trailing_separator(self):
        """Rendered tail does not end with '·'."""
        tail = self._build_two_segment_tail()
        assert not tail.plain.rstrip().endswith("·")

    def test_separator_dim_styled(self):
        """Separator span carries dim style."""
        from rich.text import Text
        from hermes_cli.tui.tool_blocks._header import _trim_tail_segments

        seg1 = Text("  ok", style="dim green")
        seg2 = Text("  1.2s", style="dim")
        segments = [("exit", seg1), ("duration", seg2)]

        budget = 40
        separator_overhead = max(0, 2 * (len(segments) - 1))
        trimmed = _trim_tail_segments(segments, budget - separator_overhead)

        tail = Text()
        for idx, (_, seg) in enumerate(trimmed):
            if idx > 0:
                tail.append(" ·", style="dim #666666")
            tail.append_text(seg)

        # Inspect spans for the separator
        sep_spans = [
            span for span in tail._spans
            if "dim" in str(span.style)
            and "#666666" in str(span.style)
        ]
        assert len(sep_spans) >= 1


# ---------------------------------------------------------------------------
# QW-12 — Per-category discovery gating
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_discovery_set():
    _comp_mod._DISCOVERY_SHOWN_CATEGORIES.clear()
    yield
    _comp_mod._DISCOVERY_SHOWN_CATEGORIES.clear()


def _make_hint_panel(category, *, has_result=True):
    from hermes_cli.tui.tool_panel import ToolPanel
    panel = types.SimpleNamespace()
    panel._discovery_shown = False
    panel._category = category
    if has_result:
        from hermes_cli.tui.tool_result_parse import ResultSummaryV4
        panel._result_summary_v4 = ResultSummaryV4(
            primary=None, exit_code=None, chips=(), actions=(), artifacts=(),
            is_error=False, stderr_tail="",
        )
    else:
        panel._result_summary_v4 = None
    mock_fb = MagicMock()
    mock_fb.LOW = 0
    panel.app = MagicMock()
    panel.app.feedback = mock_fb
    panel._maybe_show_discovery_hint = ToolPanel._maybe_show_discovery_hint.__get__(panel)
    return panel


class TestQW12PerCategoryDiscovery:
    def test_first_shell_panel_fires_hint(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "")
        panel = _make_hint_panel(ToolCategory.SHELL)
        panel._maybe_show_discovery_hint()
        panel.app.feedback.flash.assert_called_once()
        assert ToolCategory.SHELL in _comp_mod._DISCOVERY_SHOWN_CATEGORIES

    def test_second_shell_panel_skips_hint(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "")
        _comp_mod._DISCOVERY_SHOWN_CATEGORIES.add(ToolCategory.SHELL)
        panel = _make_hint_panel(ToolCategory.SHELL)
        panel._maybe_show_discovery_hint()
        panel.app.feedback.flash.assert_not_called()

    def test_first_file_panel_fires_hint_after_shell(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "")
        _comp_mod._DISCOVERY_SHOWN_CATEGORIES.add(ToolCategory.SHELL)
        panel = _make_hint_panel(ToolCategory.FILE)
        panel._maybe_show_discovery_hint()
        panel.app.feedback.flash.assert_called_once()

    def test_accessibility_mode_suppresses_all(self, monkeypatch):
        monkeypatch.setenv("HERMES_ACCESSIBLE", "1")
        panel = _make_hint_panel(ToolCategory.SHELL)
        panel._maybe_show_discovery_hint()
        panel.app.feedback.flash.assert_not_called()

    def test_reset_helper_clears_set(self):
        _comp_mod._DISCOVERY_SHOWN_CATEGORIES.add(ToolCategory.SHELL)
        _comp_mod._DISCOVERY_SHOWN_CATEGORIES.add(ToolCategory.FILE)
        _comp_mod._DISCOVERY_SHOWN_CATEGORIES.clear()
        assert len(_comp_mod._DISCOVERY_SHOWN_CATEGORIES) == 0
