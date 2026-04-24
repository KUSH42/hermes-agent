"""tests/tui/test_plan_panel_p0.py — PlanPanel P0 fixes regression tests.

Pure-unit, no run_test / async needed.
"""
from __future__ import annotations

import os
import types
import unittest
from unittest.mock import MagicMock, patch

# Ensure deterministic mode for timer-sensitive paths
os.environ.setdefault("HERMES_DETERMINISTIC", "1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_call(state_name: str, label: str = "do_stuff", depth: int = 0,
               started_at=None, ended_at=None):
    """Create a minimal PlannedCall-like object without importing the real class."""
    from hermes_cli.tui.plan_types import PlanState
    c = MagicMock()
    c.state = getattr(PlanState, state_name)
    c.label = label
    c.depth = depth
    c.started_at = started_at
    c.ended_at = ended_at
    return c


# ---------------------------------------------------------------------------
# TestDeletedDoneSection
# ---------------------------------------------------------------------------

class TestDeletedDoneSection(unittest.TestCase):
    """P0-1: _DoneSection must not exist anywhere in plan_panel."""

    def test_done_section_class_not_defined(self):
        import hermes_cli.tui.widgets.plan_panel as pp
        self.assertFalse(
            hasattr(pp, "_DoneSection"),
            "_DoneSection class must be deleted from plan_panel.py",
        )

    def test_rebuild_done_method_not_defined(self):
        from hermes_cli.tui.widgets.plan_panel import PlanPanel
        self.assertFalse(
            hasattr(PlanPanel, "_rebuild_done"),
            "_rebuild_done method must be deleted from PlanPanel",
        )

    def test_compose_does_not_yield_done_section(self):
        """compose() generator should not produce a _DoneSection widget."""
        import hermes_cli.tui.widgets.plan_panel as pp
        if hasattr(pp, "_DoneSection"):
            self.fail("_DoneSection still exists")
        # Verify by inspecting the source (compile-time check already passes)
        import inspect
        src = inspect.getsource(pp.PlanPanel.compose)
        self.assertNotIn("_DoneSection", src)

    def test_rebuild_does_not_call_rebuild_done(self):
        """_rebuild() source must not reference _rebuild_done."""
        import inspect
        from hermes_cli.tui.widgets.plan_panel import PlanPanel
        src = inspect.getsource(PlanPanel._rebuild)
        self.assertNotIn("_rebuild_done", src)

    def test_on_collapse_changed_excludes_done_section(self):
        """_on_collapse_changed source must not reference _DoneSection."""
        import inspect
        from hermes_cli.tui.widgets.plan_panel import PlanPanel
        src = inspect.getsource(PlanPanel._on_collapse_changed)
        self.assertNotIn("_DoneSection", src)


# ---------------------------------------------------------------------------
# TestDefaultCollapsed
# ---------------------------------------------------------------------------

class TestDefaultCollapsed(unittest.TestCase):
    """P0-2: _collapsed reactive must default to True."""

    def test_collapsed_reactive_default_is_true(self):
        from hermes_cli.tui.widgets.plan_panel import PlanPanel
        # reactive default is stored as the first arg to reactive()
        # Access via the class-level reactive descriptor's default
        default = PlanPanel._collapsed._default  # type: ignore[attr-defined]
        self.assertTrue(default, "_collapsed reactive default must be True")

    def test_on_mount_syncs_collapsed_state(self):
        """on_mount must call _on_collapse_changed after _rebuild."""
        import inspect
        from hermes_cli.tui.widgets.plan_panel import PlanPanel
        src = inspect.getsource(PlanPanel.on_mount)
        self.assertIn("_on_collapse_changed", src)
        self.assertIn("plan_panel_collapsed", src)


# ---------------------------------------------------------------------------
# TestNowSectionTick
# ---------------------------------------------------------------------------

class TestNowSectionTick(unittest.TestCase):
    """P0-3 + B-3: _NowSection tick rewrite."""

    def _make_now_section(self):
        from hermes_cli.tui.widgets.plan_panel import _NowSection
        ns = _NowSection.__new__(_NowSection)
        ns._base_text = ""
        ns._elapsed_s = 0
        ns._timer_handle = None
        ns._start_monotonic = 0.0
        return ns

    def test_base_text_class_attribute_exists(self):
        from hermes_cli.tui.widgets.plan_panel import _NowSection
        self.assertIn("_base_text", _NowSection.__dict__)
        self.assertEqual(_NowSection._base_text, "")

    def test_clear_resets_base_text(self):
        ns = self._make_now_section()
        ns._base_text = "● read_file"
        # Stub query_one to avoid NoMatches
        ns.query_one = MagicMock(return_value=MagicMock())
        ns._stop_timer = MagicMock()
        ns.clear()
        self.assertEqual(ns._base_text, "")

    def test_update_now_line_elapsed_lt_3_no_suffix(self):
        """elapsed < 3 → no [Xs] suffix."""
        ns = self._make_now_section()
        ns._base_text = "● read_file"
        captured = []
        mock_static = MagicMock()
        mock_static.update = lambda txt: captured.append(txt)
        ns.query_one = MagicMock(return_value=mock_static)
        ns._update_now_line(2)
        self.assertEqual(captured, ["● read_file"])

    def test_update_now_line_elapsed_ge_3_has_suffix(self):
        """elapsed >= 3 → [Xs] suffix appended."""
        ns = self._make_now_section()
        ns._base_text = "● read_file"
        captured = []
        mock_static = MagicMock()
        mock_static.update = lambda txt: captured.append(txt)
        ns.query_one = MagicMock(return_value=mock_static)
        ns._update_now_line(5)
        self.assertEqual(captured, ["● read_file  [5s]"])

    def test_update_now_line_elapsed_exactly_3(self):
        """Boundary: elapsed == 3 → shows suffix."""
        ns = self._make_now_section()
        ns._base_text = "● tool"
        captured = []
        mock_static = MagicMock()
        mock_static.update = lambda txt: captured.append(txt)
        ns.query_one = MagicMock(return_value=mock_static)
        ns._update_now_line(3)
        self.assertIn("[3s]", captured[0])

    def test_update_now_line_never_string_parses(self):
        """_update_now_line source must not use rfind or 'in text' string parse."""
        import inspect
        from hermes_cli.tui.widgets.plan_panel import _NowSection
        src = inspect.getsource(_NowSection._update_now_line)
        self.assertNotIn("rfind", src)
        self.assertNotIn('"  ["', src)
        self.assertNotIn("'  ['", src)

    def test_tick_uses_update_now_line(self):
        """_tick must call _update_now_line (not string-parse static)."""
        import inspect
        from hermes_cli.tui.widgets.plan_panel import _NowSection
        src = inspect.getsource(_NowSection._tick)
        self.assertIn("_update_now_line", src)
        self.assertNotIn("rfind", src)

    def test_ensure_timer_uses_2_second_interval(self):
        """_ensure_timer must use 2.0s interval."""
        import inspect
        from hermes_cli.tui.widgets.plan_panel import _NowSection
        src = inspect.getsource(_NowSection._ensure_timer)
        self.assertIn("2.0", src)
        self.assertNotIn("1.0", src)

    def test_no_if_false_dead_branch(self):
        """Dead 'if False:' branch must be removed."""
        import inspect
        from hermes_cli.tui.widgets.plan_panel import _NowSection
        src = inspect.getsource(_NowSection)
        self.assertNotIn("if False:", src)


# ---------------------------------------------------------------------------
# TestErrorCountInChip
# ---------------------------------------------------------------------------

class TestErrorCountInChip(unittest.TestCase):
    """P0-4 (updated for P1-2): _rebuild_header splits done vs errors;
    update_header delegates to chip segments."""

    def _make_header(self):
        from hermes_cli.tui.widgets.plan_panel import _PlanPanelHeader
        h = _PlanPanelHeader.__new__(_PlanPanelHeader)
        return h

    def _make_chip_segments(self):
        """Return a dict of mock segments keyed by id."""
        from unittest.mock import MagicMock
        segs = {}
        for seg_id in ("plan-header-label", "plan-chip-title", "chip-running",
                       "chip-done", "chip-errors", "chip-cost", "plan-f9-badge"):
            m = MagicMock()
            m.display = True
            m.update = MagicMock()
            segs[seg_id] = m
        return segs

    def _query_one_factory(self, segs):
        """Return a query_one side-effect that dispatches on id selector."""
        def _query_one(selector, *args):
            if selector.startswith("#"):
                key = selector[1:]
                if key in segs:
                    return segs[key]
            # Return a generic mock for unknown selectors
            return MagicMock()
        return _query_one

    def test_update_header_signature_has_errors_param(self):
        import inspect
        from hermes_cli.tui.widgets.plan_panel import _PlanPanelHeader
        sig = inspect.signature(_PlanPanelHeader.update_header)
        self.assertIn("errors", sig.parameters)
        self.assertIn("cost_usd", sig.parameters)

    def test_update_header_collapsed_shows_chip_title(self):
        """When collapsed=True, #plan-chip-title receives text with 'Plan ▸'."""
        from hermes_cli.tui.widgets.plan_panel import _PlanPanelHeader
        h = self._make_header()
        segs = self._make_chip_segments()
        h.query_one = MagicMock(side_effect=self._query_one_factory(segs))
        h.update_header(collapsed=True, running=0, pending=2, done=7, errors=0)
        title_calls = segs["plan-chip-title"].update.call_args_list
        self.assertTrue(len(title_calls) > 0, "#plan-chip-title.update() must be called")
        title_text = title_calls[0][0][0]
        self.assertIn("Plan", title_text)
        self.assertIn("▸", title_text)

    def test_update_header_collapsed_errors_uses_richtext(self):
        """When errors > 0 in chip mode, #chip-errors receives a RichText."""
        from hermes_cli.tui.widgets.plan_panel import _PlanPanelHeader
        from rich.text import Text as RichText
        h = self._make_header()
        segs = self._make_chip_segments()
        # chip-errors needs display to be settable
        segs["chip-errors"].display = False
        h.query_one = MagicMock(side_effect=self._query_one_factory(segs))
        h.update_header(collapsed=True, running=0, pending=2, done=7, errors=2)
        error_calls = segs["chip-errors"].update.call_args_list
        self.assertTrue(len(error_calls) > 0, "#chip-errors.update() must be called")
        arg = error_calls[0][0][0]
        self.assertIsInstance(arg, RichText, f"Expected RichText, got {type(arg)}")

    def test_update_header_collapsed_error_richtext_bold_red(self):
        """RichText passed to #chip-errors must contain bold red span over '✗'."""
        from hermes_cli.tui.widgets.plan_panel import _PlanPanelHeader
        from rich.text import Text as RichText
        h = self._make_header()
        segs = self._make_chip_segments()
        h.query_one = MagicMock(side_effect=self._query_one_factory(segs))
        h.update_header(collapsed=True, running=0, pending=0, done=0, errors=2)
        error_calls = segs["chip-errors"].update.call_args_list
        self.assertTrue(len(error_calls) > 0)
        label = error_calls[0][0][0]
        self.assertIsInstance(label, RichText)
        target_found = False
        for start, end, style in label._spans:  # type: ignore[attr-defined]
            span_text = label.plain[start:end]
            if "✗" in span_text:
                if hasattr(style, "bold") and style.bold and str(style.color) in ("red", "bright_red"):
                    target_found = True
                    break
                if isinstance(style, str) and "bold" in style and "red" in style:
                    target_found = True
                    break
        self.assertTrue(target_found, f"No bold+red span for '✗' in {label!r}")

    def test_update_header_expanded_shows_full_label(self):
        """When collapsed=False, #plan-header-label receives 'Plan ▾'."""
        from hermes_cli.tui.widgets.plan_panel import _PlanPanelHeader
        h = self._make_header()
        segs = self._make_chip_segments()
        h.query_one = MagicMock(side_effect=self._query_one_factory(segs))
        h.update_header(collapsed=False, running=1, pending=2, done=7, errors=0)
        label_calls = segs["plan-header-label"].update.call_args_list
        self.assertTrue(len(label_calls) > 0, "#plan-header-label.update() must be called")
        label_text = label_calls[0][0][0]
        self.assertIn("Plan", label_text)
        self.assertIn("▾", label_text)

    def test_rebuild_header_splits_done_and_errors(self):
        """_rebuild_header source must use separate done/errors counts."""
        import inspect
        from hermes_cli.tui.widgets.plan_panel import PlanPanel
        src = inspect.getsource(PlanPanel._rebuild_header)
        self.assertIn("PlanState.DONE", src)
        self.assertIn("PlanState.ERROR", src)
        # Both must appear as separate conditions, not combined with 'in (...)'
        # at the same line — we check that errors is counted separately
        self.assertIn("errors", src)


# ---------------------------------------------------------------------------
# TestBudgetVisibility
# ---------------------------------------------------------------------------

class TestBudgetVisibility(unittest.TestCase):
    """P0-5 / A13: _BudgetSection gated on not-active + not-collapsed + non-zero budget."""

    def _make_panel(self, collapsed: bool = False, cost_usd: float = 1.5, tokens_in: int = 1000):
        """Create a minimal PlanPanel-like object for unit testing budget visibility."""
        import types
        from hermes_cli.tui.widgets.plan_panel import PlanPanel

        panel = types.SimpleNamespace()
        panel._collapsed = collapsed
        panel._active_hide_timer = None
        app = MagicMock()
        app.turn_cost_usd = cost_usd
        app.turn_tokens_in = tokens_in
        panel.app = app
        panel._refresh_budget_visibility = PlanPanel._refresh_budget_visibility.__get__(panel)
        return panel

    def test_refresh_budget_visibility_hides_during_active(self):
        panel = self._make_panel()
        mock_budget = MagicMock()
        panel.query_one = MagicMock(return_value=mock_budget)
        panel._refresh_budget_visibility(has_active=True, calls=[])
        mock_budget.set_class.assert_called_with(False, "--visible")

    def test_refresh_budget_visibility_hides_when_collapsed(self):
        panel = self._make_panel(collapsed=True)
        mock_budget = MagicMock()
        panel.query_one = MagicMock(return_value=mock_budget)
        panel._refresh_budget_visibility(has_active=False, calls=[])
        mock_budget.set_class.assert_called_with(False, "--visible")

    def test_refresh_budget_visibility_shows_after_turn(self):
        panel = self._make_panel(collapsed=False)
        mock_budget = MagicMock()
        panel.query_one = MagicMock(return_value=mock_budget)
        panel._refresh_budget_visibility(has_active=False, calls=[])
        mock_budget.set_class.assert_called_with(True, "--visible")

    def test_refresh_budget_no_timer_started(self):
        """A13: no 5s timer — budget visibility is synchronous gate only."""
        panel = self._make_panel()
        mock_budget = MagicMock()
        panel.query_one = MagicMock(return_value=mock_budget)
        panel.set_timer = MagicMock()
        panel._refresh_budget_visibility(has_active=False, calls=[])
        panel.set_timer.assert_not_called()

    def test_refresh_budget_hides_when_zero_budget(self):
        """A13: zero-budget panels stay hidden even when expanded+idle."""
        panel = self._make_panel(collapsed=False, cost_usd=0.0, tokens_in=0)
        mock_budget = MagicMock()
        panel.query_one = MagicMock(return_value=mock_budget)
        panel._refresh_budget_visibility(has_active=False, calls=[])
        mock_budget.set_class.assert_called_with(False, "--visible")

    def test_collapse_watcher_excludes_budget_section(self):
        """_on_collapse_changed must not toggle _BudgetSection visibility."""
        import inspect
        from hermes_cli.tui.widgets.plan_panel import PlanPanel
        src = inspect.getsource(PlanPanel._on_collapse_changed)
        self.assertNotIn("_BudgetSection", src)


# ---------------------------------------------------------------------------
# TestActiveDebounce
# ---------------------------------------------------------------------------

class TestActiveDebounce(unittest.TestCase):
    """P0-6: --active class removal is debounced by 3s."""

    def _make_panel(self):
        import types
        from hermes_cli.tui.widgets.plan_panel import PlanPanel
        p = types.SimpleNamespace()
        p._collapsed = False
        p._budget_hide_timer = None
        p._active_hide_timer = None
        p._do_hide_active = PlanPanel._do_hide_active.__get__(p)
        p._on_planned_calls_changed = PlanPanel._on_planned_calls_changed.__get__(p)
        return p

    def test_do_hide_active_removes_classes(self):
        panel = self._make_panel()
        panel.remove_class = MagicMock()
        mock_app = MagicMock()
        panel.app = mock_app  # type: ignore[assignment]
        panel._do_hide_active()
        panel.remove_class.assert_called_with("--active")
        mock_app.remove_class.assert_called_with("plan-active")
        self.assertIsNone(panel._active_hide_timer)

    def test_do_hide_active_is_class_method(self):
        """_do_hide_active must be defined on PlanPanel directly (not nested)."""
        from hermes_cli.tui.widgets.plan_panel import PlanPanel
        self.assertTrue(
            callable(getattr(PlanPanel, "_do_hide_active", None)),
            "_do_hide_active must be a class-level method on PlanPanel",
        )

    def test_has_any_true_cancels_pending_timer(self):
        """When calls arrive again, any pending hide timer is cancelled."""
        from hermes_cli.tui.widgets.plan_panel import PlanPanel
        panel = self._make_panel()
        mock_timer = MagicMock()
        panel._active_hide_timer = mock_timer
        panel.add_class = MagicMock()
        panel.remove_class = MagicMock()
        panel.set_timer = MagicMock(return_value=MagicMock())
        panel.query_one = MagicMock(side_effect=Exception("no widget"))
        # Patch app
        mock_app = MagicMock()
        panel.app = mock_app  # type: ignore[assignment]
        # Simulate has_any=True path via _on_planned_calls_changed
        from hermes_cli.tui.plan_types import PlanState
        call = _make_call("PENDING")
        panel._rebuild = MagicMock()
        panel._refresh_budget_visibility = MagicMock()
        panel._on_planned_calls_changed([call])
        mock_timer.stop.assert_called_once()
        self.assertIsNone(panel._active_hide_timer)

    def test_has_any_false_sets_3s_timer(self):
        """When calls list is empty, a 3s hide timer is started."""
        from hermes_cli.tui.widgets.plan_panel import PlanPanel
        panel = self._make_panel()
        panel.add_class = MagicMock()
        panel.remove_class = MagicMock()
        mock_timer = MagicMock()
        panel.set_timer = MagicMock(return_value=mock_timer)
        panel.query_one = MagicMock(side_effect=Exception("no widget"))
        mock_app = MagicMock()
        panel.app = mock_app  # type: ignore[assignment]
        panel._rebuild = MagicMock()
        panel._refresh_budget_visibility = MagicMock()
        panel._on_planned_calls_changed([])
        panel.set_timer.assert_called_once()
        args = panel.set_timer.call_args
        self.assertEqual(args[0][0], 3.0)


# ---------------------------------------------------------------------------
# TestDeadExpandedReactive
# ---------------------------------------------------------------------------

class TestDeadExpandedReactive(unittest.TestCase):
    """B-1: _NextSection must not have _expanded reactive."""

    def test_next_section_no_expanded_attribute(self):
        from hermes_cli.tui.widgets.plan_panel import _NextSection
        self.assertFalse(
            "_expanded" in _NextSection.__dict__,
            "_NextSection must not have a class-level _expanded attribute",
        )

    def test_next_section_update_calls_uses_max_visible(self):
        """update_calls must always use _MAX_VISIBLE, not _expanded."""
        import inspect
        from hermes_cli.tui.widgets.plan_panel import _NextSection
        src = inspect.getsource(_NextSection.update_calls)
        self.assertNotIn("_expanded", src)
        self.assertIn("_MAX_VISIBLE", src)


# ---------------------------------------------------------------------------
# TestPlanNowFgColor
# ---------------------------------------------------------------------------

class TestPlanNowFgColor(unittest.TestCase):
    """B-2: plan-now-fg must not collide with accent-interactive (#00bcd4)."""

    def test_plan_now_fg_not_accent_color(self):
        from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS
        plan_now = COMPONENT_VAR_DEFAULTS.get("plan-now-fg", "")
        # Unwrap VarSpec if present
        if not isinstance(plan_now, str):
            plan_now = str(plan_now)
        self.assertNotEqual(
            plan_now.lower(), "#00bcd4",
            "plan-now-fg must not be #00bcd4 (collides with accent-interactive)",
        )

    def test_plan_now_fg_is_amber(self):
        from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS
        plan_now = COMPONENT_VAR_DEFAULTS.get("plan-now-fg", "")
        if not isinstance(plan_now, str):
            plan_now = str(plan_now)
        self.assertEqual(
            plan_now.lower(), "#ffb454",
            f"plan-now-fg must be #ffb454 (warm amber), got {plan_now!r}",
        )

    def test_plan_pending_fg_updated(self):
        from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS
        pending = COMPONENT_VAR_DEFAULTS.get("plan-pending-fg", "")
        if not isinstance(pending, str):
            pending = str(pending)
        self.assertEqual(
            pending.lower(), "#888888",
            f"plan-pending-fg must be #888888, got {pending!r}",
        )


if __name__ == "__main__":
    unittest.main()
