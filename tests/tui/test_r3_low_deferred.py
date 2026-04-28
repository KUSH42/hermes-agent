"""Tests for R3-LOW deferred fixes.

LOW-1: duplicate is_error→collapsed=False writers removed from _post_complete_tidy
LOW-2: per-tier drop order in trim_tail_for_tier / _trim_tail_segments
"""
from __future__ import annotations

import types
import unittest.mock as mock

from rich.text import Text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_summary(is_error: bool) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        is_error=is_error,
        primary=None,
        error_kind=None,
        chips=None,
        stderr_tail="",
        actions=None,
        artifacts=None,
        exit_code=0 if not is_error else 1,
    )


def _seg(name: str, text: str) -> tuple[str, Text]:
    return (name, Text(text))


# ---------------------------------------------------------------------------
# LOW-1: Duplicate collapse writers
# ---------------------------------------------------------------------------

class TestDuplicateCollapseWriters:
    """LOW-1: set_result_summary owns collapsed=False for errors; _post_complete_tidy must not write it."""

    def _make_panel(self):
        """Minimal stub satisfying _ToolPanelCompletionMixin without Textual."""
        from hermes_cli.tui.tool_panel._completion import _ToolPanelCompletionMixin

        panel = mock.MagicMock(spec_set=[])
        # Install mixin methods directly
        panel.__class__ = type("_TestPanel", (_ToolPanelCompletionMixin, mock.MagicMock), {})
        return panel

    def test_error_summary_only_one_collapse_write(self):
        """set_result_summary(error) writes collapsed=False exactly once; no second write after."""
        from hermes_cli.tui.tool_panel._completion import _ToolPanelCompletionMixin

        writes: list[bool] = []

        class _FakePanel(_ToolPanelCompletionMixin):
            _result_summary_v4 = None
            _completed_at = None
            _start_time = 0.0
            _block = None
            _footer_pane = None
            _tool_name = "test_tool"
            _category = None
            _tool_args = None
            _view_state = None
            _body_pane = None
            _discovery_shown = False
            _user_collapse_override = False
            _user_override_tier = None
            _resolver = mock.MagicMock()
            _saved_visible_start = None
            _header_remediation_hint = None

            def _lookup_view_state(self):
                return None

            def _body_line_count(self):
                return 0

            def _update_kind_from_classifier(self, lc):
                pass

            def _schedule_age_ticks(self):
                pass

            def _has_footer_content(self):
                return False

            def add_class(self, *a, **kw):
                pass

            def remove_class(self, *a, **kw):
                pass

            class Completed:
                pass

            def post_message(self, *a, **kw):
                pass

            def call_after_refresh(self, fn, *args):
                # Run synchronously for testing
                fn(*args)

            # Track collapsed setter calls
            @property
            def collapsed(self):
                return self._collapsed

            @collapsed.setter
            def collapsed(self, value):
                writes.append(value)
                self._collapsed = value

            _collapsed = True

        panel = _FakePanel()
        summary = _make_summary(is_error=True)

        panel.set_result_summary(summary)

        false_writes = [v for v in writes if v is False]
        assert len(false_writes) == 1, (
            f"Expected exactly 1 collapsed=False write, got {len(false_writes)}: {writes}"
        )

    def test_post_complete_tidy_does_not_write_collapsed(self):
        """_post_complete_tidy(error_summary) must not write collapsed at all."""
        from hermes_cli.tui.tool_panel._completion import _ToolPanelCompletionMixin

        writes: list[bool] = []

        class _FakePanel(_ToolPanelCompletionMixin):
            _result_summary_v4 = None
            _user_collapse_override = False
            _footer_pane = None

            def remove_class(self, *a, **kw):
                pass

            def _apply_complete_auto_collapse(self):
                pass

            def _maybe_activate_mini(self, s):
                pass

            @property
            def collapsed(self):
                return self._collapsed

            @collapsed.setter
            def collapsed(self, value):
                writes.append(value)
                self._collapsed = value

            _collapsed = True

        panel = _FakePanel()
        summary = _make_summary(is_error=True)

        # Simulate: set_result_summary already ran and wrote collapsed=False
        panel._collapsed = False
        writes.clear()

        panel._post_complete_tidy(summary)

        assert not writes, (
            f"_post_complete_tidy must not write collapsed for error path, but got: {writes}"
        )


# ---------------------------------------------------------------------------
# LOW-2: Per-tier drop order
# ---------------------------------------------------------------------------

class TestDropOrderTiers:
    """LOW-2: tier-keyed drop policies in _trim_tail_segments / trim_tail_for_tier."""

    def _import(self):
        from hermes_cli.tui.tool_blocks._header import (
            _trim_tail_segments,
            trim_tail_for_tier,
        )
        from hermes_cli.tui.tool_panel.density import DensityTier
        return _trim_tail_segments, trim_tail_for_tier, DensityTier

    def _segs(self, names: list[str], width: int = 10) -> list[tuple[str, Text]]:
        return [_seg(n, "x" * width) for n in names]

    def test_hero_tier_never_drops_hero_segment(self):
        _trim, trim, DT = self._import()
        # Extreme budget — forces everything to drop
        segs = self._segs(["flash", "chip", "linecount",
                            "duration", "diff", "hero", "chevron", "exit"])
        result = trim(segs, tail_budget=1, tier=DT.HERO)
        names = [n for n, _ in result]
        assert "hero" in names, f"HERO tier must never drop 'hero', got: {names}"

    def test_hero_tier_drops_flash_before_diff(self):
        _trim, trim, DT = self._import()
        # Budget that forces dropping flash but not diff (ER-2: remediation/stderrwarn removed)
        segs = self._segs(["flash", "diff", "hero"], width=10)
        # Total = 30; budget = 15 → need to drop 1 segment (10 chars)
        result = trim(segs, tail_budget=15, tier=DT.HERO)
        names = [n for n, _ in result]
        assert "flash" not in names, f"HERO should drop 'flash' first, got: {names}"
        assert "diff" in names or "hero" in names, f"Should keep diff/hero, got: {names}"

    def test_compact_tier_keeps_exit(self):
        """COMPACT tier always keeps 'exit' as the highest-priority segment."""
        _trim, trim, DT = self._import()
        segs = self._segs(["flash", "linecount", "diff",
                            "hero", "chevron", "duration", "chip", "exit"])
        # Very narrow budget — only 2 segments survive
        result = trim(segs, tail_budget=20, tier=DT.COMPACT)
        names = [n for n, _ in result]
        assert "exit" in names, f"COMPACT must keep 'exit', got: {names}"

    def test_compact_tier_drops_chip_before_exit(self):
        _trim, trim, DT = self._import()
        # Budget that removes chip but not exit (chip is first in COMPACT order)
        segs = self._segs(["chip", "exit"], width=10)
        # Total=20; budget=15 → drop 1 (chip is first in COMPACT order)
        result = trim(segs, tail_budget=15, tier=DT.COMPACT)
        names = [n for n, _ in result]
        assert "chip" not in names, f"COMPACT should drop 'chip' early, got: {names}"
        assert "exit" in names, f"COMPACT must keep 'exit', got: {names}"

    def test_default_tier_uses_default_order(self):
        _trim, trim, DT = self._import()
        # DEFAULT: chip dropped first, then linecount, then duration
        segs = self._segs(["chip", "linecount", "duration", "hero", "exit"], width=10)
        # Total=50; budget=35 → drop 1
        result = trim(segs, tail_budget=35, tier=DT.DEFAULT)
        names = [n for n, _ in result]
        assert "chip" not in names, f"DEFAULT should drop 'chip' first, got: {names}"
        assert "exit" in names, f"DEFAULT should keep 'exit', got: {names}"

    def test_default_tier_drops_hero_at_extreme_width(self):
        _trim, trim, DT = self._import()
        # Only hero+flash remain; DEFAULT should allow pre-loop special case to drop hero
        segs = self._segs(["hero", "flash"], width=10)
        result = trim(segs, tail_budget=1, tier=DT.DEFAULT)
        names = [n for n, _ in result]
        assert "hero" not in names, f"DEFAULT extreme width should drop 'hero', got: {names}"

    def test_trace_tier_drops_nothing(self):
        _trim, trim, DT = self._import()
        all_names = ["flash", "chip", "linecount",
                     "duration", "diff", "hero", "chevron", "exit"]
        segs = self._segs(all_names, width=10)
        # Arbitrarily narrow budget
        result = trim(segs, tail_budget=1, tier=DT.TRACE)
        names = [n for n, _ in result]
        assert names == all_names, f"TRACE must preserve all segments, got: {names}"
