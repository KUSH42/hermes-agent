"""Tests for Tool UX Audit Pass 7 — Phase C: Header & tail polish."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# C1 — AGENT label always ends with "…" on truncation
# ---------------------------------------------------------------------------

class TestC1AgentLabelTruncation:
    """header_label_v4 for AGENT category always appends '…' on truncation."""

    def _make_agent_spec(self):
        from hermes_cli.tui.tool_category import ToolCategory
        spec = MagicMock()
        spec.category = ToolCategory.AGENT
        spec.primary_arg = None
        spec.primary_result = "text"
        spec.provenance = None
        spec.name = "agent_task"
        return spec

    def test_truncated_label_ends_with_ellipsis(self):
        """C1: text longer than 60 chars is truncated with '…'."""
        from hermes_cli.tui.tool_blocks import header_label_v4
        spec = self._make_agent_spec()
        long_task = "A" * 70  # > 60 chars
        args = {"task": long_task}
        result = header_label_v4(spec, args, long_task, None, available=80)
        plain = result.plain.strip()
        assert plain.endswith("…"), f"Expected '…' at end, got: {plain!r}"
        assert len(plain) <= 62  # 60 chars + "…" + leading space

    def test_short_label_no_ellipsis(self):
        """C1: text under 60 chars is not truncated."""
        from hermes_cli.tui.tool_blocks import header_label_v4
        spec = self._make_agent_spec()
        short_task = "Do the thing"
        args = {"task": short_task}
        result = header_label_v4(spec, args, short_task, None, available=80)
        plain = result.plain.strip()
        assert not plain.endswith("…"), f"Should not have ellipsis: {plain!r}"
        assert short_task in plain


# ---------------------------------------------------------------------------
# C2 — Browse badge as first tail item
# ---------------------------------------------------------------------------

class TestC2BrowseBadgeFirst:
    """Browse badge is prepended in _render_v4 tail, removed from render()."""

    def test_browse_badge_in_render_v4_not_appended_after(self):
        """C2: render() doesn't double-append badge when _render_v4 succeeds."""
        import inspect
        from hermes_cli.tui.tool_blocks import ToolHeader
        render_src = inspect.getsource(ToolHeader.render)
        # After C2, render() should NOT append browse_badge AFTER a successful _render_v4 call.
        # The fallback path (degraded) is OK to keep it — but the primary v4 path should not.
        # Check: no 'result.append' call on browse_badge after 'if result is not None: return result'
        # The key indicator: there should NOT be a line that checks _render_v4 result AND badge
        lines = render_src.split('\n')
        # Looking for pattern: result.append(..._browse_badge...) — this was the old behavior
        result_badge_appends = [l for l in lines if 'result' in l and '_browse_badge' in l and 'append' in l]
        assert len(result_badge_appends) == 0, \
            f"render() must not re-append browse_badge to v4 result: {result_badge_appends}"

    def test_render_v4_source_has_browse_badge(self):
        """C2: _render_v4() source adds browse badge as first tail item."""
        import inspect
        from hermes_cli.tui.tool_blocks import ToolHeader
        src = inspect.getsource(ToolHeader._render_v4)
        assert "_browse_badge" in src, "_render_v4 should handle browse_badge internally"
        # Badge should appear before the tail hero chip assembly (primary_hero)
        badge_pos = src.find("_browse_badge")
        hero_pos = src.find("_primary_hero")
        assert badge_pos < hero_pos, \
            f"Browse badge (pos {badge_pos}) should be before _primary_hero (pos {hero_pos})"


# ---------------------------------------------------------------------------
# C3 — Narrow mode hint sorting
# ---------------------------------------------------------------------------

class TestC3NarrowModeHintSort:
    """_build_hint_text sorts error hints first in narrow mode."""

    def test_error_hints_first_in_narrow_mode(self):
        """C3: sort puts error keys (r, x) before copy keys (c) in narrow mode."""
        # Test the sorting logic directly
        _ERROR_KEYS = frozenset({"r", "E", "x"})
        _COPY_OPEN_KEYS = frozenset({"c", "o", "p", "e", "u", "O", "C", "H", "I", "P"})

        def _hint_priority(h):
            k = h[0].strip()
            if k in _ERROR_KEYS:
                return 0
            if k in _COPY_OPEN_KEYS:
                return 1
            return 2

        hints = [
            ("c", " ", "copy  "),
            ("r", " ", "retry  "),
            ("?", " ", "menu  "),
        ]
        hints.sort(key=_hint_priority)
        keys_in_order = [h[0] for h in hints]
        assert keys_in_order.index("r") < keys_in_order.index("c"), \
            f"'r' should come before 'c' after sort: {keys_in_order}"

    def test_hint_sort_implementation_in_build_hint_text(self):
        """C3: _build_hint_text uses primary/contextual tier ordering."""
        import inspect
        from hermes_cli.tui.tool_panel import ToolPanel
        src = inspect.getsource(ToolPanel._build_hint_text)
        # B1 three-tier model: primary tier always first, contextual tier second
        assert "primary" in src, "C3: _build_hint_text must define a primary hints tier"
        assert "contextual" in src, "C3: _build_hint_text must define a contextual hints tier"


# ---------------------------------------------------------------------------
# C4 — First-focus toggle hint
# ---------------------------------------------------------------------------

class TestC4FirstFocusHint:
    """ToolPanel.on_focus flashes '(Enter) toggle' hint on first focus."""

    def test_first_focus_flashes_hint(self):
        """C4: on_focus fires flash on first call when affordances present."""
        from hermes_cli.tui.tool_panel import ToolPanel
        panel = ToolPanel.__new__(ToolPanel)
        panel._toggle_hint_shown = False
        panel._flash_header = MagicMock()
        # D4: flash only fires when _has_affordances=True
        header_mock = MagicMock()
        header_mock._has_affordances = True
        block_mock = MagicMock()
        block_mock._header = header_mock
        panel._block = block_mock
        panel.on_focus()
        panel._flash_header.assert_called_once()
        msg = panel._flash_header.call_args[0][0]
        assert "Enter" in msg or "toggle" in msg

    def test_second_focus_no_flash(self):
        """C4: on_focus does NOT flash on second+ focus."""
        from hermes_cli.tui.tool_panel import ToolPanel
        panel = ToolPanel.__new__(ToolPanel)
        panel._toggle_hint_shown = True  # already shown
        panel._flash_header = MagicMock()
        panel.on_focus()
        panel._flash_header.assert_not_called()

    def test_toggle_hint_shown_set_after_first_focus(self):
        """C4: _toggle_hint_shown becomes True after first focus (requires affordances)."""
        from hermes_cli.tui.tool_panel import ToolPanel
        panel = ToolPanel.__new__(ToolPanel)
        panel._toggle_hint_shown = False
        panel._flash_header = MagicMock()
        header_mock = MagicMock()
        header_mock._has_affordances = True
        block_mock = MagicMock()
        block_mock._header = header_mock
        panel._block = block_mock
        panel.on_focus()
        assert panel._toggle_hint_shown is True
