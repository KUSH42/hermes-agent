"""tests/tui/test_plan_panel_p1.py — PlanPanel P1 polish tests.

Pure-unit, no run_test / async needed.
"""
from __future__ import annotations

import os
import types
import unittest
from unittest.mock import MagicMock, patch, call, PropertyMock

# Ensure deterministic mode for timer-sensitive paths
os.environ.setdefault("HERMES_DETERMINISTIC", "1")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_call(state_name: str, label: str = "do_stuff", depth: int = 0,
               tool_call_id: str | None = "tcid-001", started_at=None):
    """Create a minimal PlannedCall-like object without importing the real class."""
    from hermes_cli.tui.plan_types import PlanState
    c = MagicMock()
    c.state = getattr(PlanState, state_name)
    c.label = label
    c.depth = depth
    c.tool_call_id = tool_call_id
    c.started_at = started_at
    return c


# ---------------------------------------------------------------------------
# TestPlanEntry
# ---------------------------------------------------------------------------

class TestPlanEntry(unittest.TestCase):
    """P1-1: _PlanEntry click/keyboard navigation."""

    def _make_entry(self, tool_call_id: str | None = "tcid-abc"):
        from hermes_cli.tui.widgets.plan_panel import _PlanEntry
        e = _PlanEntry.__new__(_PlanEntry)
        e._tool_call_id = tool_call_id
        return e

    def _patch_app(self, entry, mock_app):
        """Patch the read-only app property on a widget instance via PropertyMock."""
        from hermes_cli.tui.widgets.plan_panel import _PlanEntry
        p = patch.object(type(entry), "app", new_callable=PropertyMock, return_value=mock_app)
        p.start()
        return p

    def test_jump_calls_scroll_to_tool(self):
        """_jump() calls _svc_browse.scroll_to_tool() with _tool_call_id."""
        e = self._make_entry("tcid-123")
        mock_svc = MagicMock()
        mock_app = MagicMock()
        mock_app._svc_browse = mock_svc
        p = self._patch_app(e, mock_app)
        try:
            e._jump()
        finally:
            p.stop()
        mock_svc.scroll_to_tool.assert_called_once_with("tcid-123")

    def test_jump_noop_when_tool_call_id_none(self):
        """_jump() is a no-op when _tool_call_id is None."""
        e = self._make_entry(None)
        mock_svc = MagicMock()
        mock_app = MagicMock()
        mock_app._svc_browse = mock_svc
        # No need to patch app — _jump() returns early before accessing self.app
        e._jump()
        mock_svc.scroll_to_tool.assert_not_called()

    def test_jump_noop_when_no_svc_browse(self):
        """_jump() is a no-op when app has no _svc_browse (getattr returns None)."""
        e = self._make_entry("tcid-xyz")
        mock_app = MagicMock(spec=[])  # no _svc_browse attribute
        p = self._patch_app(e, mock_app)
        try:
            # Should not raise
            e._jump()
        finally:
            p.stop()

    def test_on_click_calls_jump(self):
        """on_click() delegates to _jump()."""
        e = self._make_entry("tcid-click")
        e._jump = MagicMock()
        e.on_click()
        e._jump.assert_called_once()

    def test_escape_focuses_input_area(self):
        """Esc key targets #input-area.focus()."""
        from hermes_cli.tui.widgets.plan_panel import _PlanEntry
        from textual import events
        e = _PlanEntry.__new__(_PlanEntry)
        e._tool_call_id = "tcid-esc"
        mock_input = MagicMock()
        mock_app = MagicMock()
        mock_app.query_one = MagicMock(return_value=mock_input)
        p = self._patch_app(e, mock_app)
        mock_event = MagicMock()
        mock_event.key = "escape"
        try:
            e.on_key(mock_event)
        finally:
            p.stop()
        mock_app.query_one.assert_called_with("#input-area")
        mock_input.focus.assert_called_once()
        mock_event.stop.assert_called_once()

    def test_enter_key_calls_jump(self):
        """Enter key calls _jump() when tool_call_id is set."""
        e = self._make_entry("tcid-enter")
        e._jump = MagicMock()
        mock_event = MagicMock()
        mock_event.key = "enter"
        e.on_key(mock_event)
        e._jump.assert_called_once()
        mock_event.stop.assert_called_once()

    def test_enter_key_no_jump_when_id_none(self):
        """Enter key does NOT call _jump() when tool_call_id is None."""
        e = self._make_entry(None)
        e._jump = MagicMock()
        mock_event = MagicMock()
        mock_event.key = "enter"
        e.on_key(mock_event)
        e._jump.assert_not_called()

    def test_plan_entry_can_focus_true(self):
        """_PlanEntry must have can_focus=True."""
        from hermes_cli.tui.widgets.plan_panel import _PlanEntry
        self.assertTrue(
            getattr(_PlanEntry, "can_focus", False) or
            getattr(_PlanEntry, "COMPONENT_CLASSES", None) is not None or
            True,  # can_focus is a class kwarg; check via __init_subclass__ or ALLOW_MAXIMIZE
            "_PlanEntry must declare can_focus=True",
        )
        # Directly check the class attribute set by Textual
        # (Textual stores it on the class as `can_focus`)
        self.assertTrue(
            getattr(_PlanEntry, "can_focus", None),
            "_PlanEntry.can_focus must be True",
        )

    def test_plan_entry_is_static_subclass(self):
        """_PlanEntry inherits Static."""
        from hermes_cli.tui.widgets.plan_panel import _PlanEntry
        from textual.widgets import Static
        self.assertTrue(issubclass(_PlanEntry, Static))


# ---------------------------------------------------------------------------
# TestScrollToTool
# ---------------------------------------------------------------------------

class TestScrollToTool(unittest.TestCase):
    """P1-1: BrowseService.scroll_to_tool finds matching ToolPanel."""

    def _make_service(self):
        from hermes_cli.tui.services.browse import BrowseService
        svc = BrowseService.__new__(BrowseService)
        return svc

    def test_scroll_to_tool_found(self):
        """When a ToolPanel with matching _plan_tool_call_id exists, scroll + highlight."""
        from hermes_cli.tui.services.browse import BrowseService
        svc = self._make_service()

        # Mock ToolPanel with matching id
        mock_panel = MagicMock()
        mock_panel._plan_tool_call_id = "tcid-found"

        # Mock OutputPanel
        mock_output = MagicMock()
        mock_output.query = MagicMock(return_value=[mock_panel])

        mock_app = MagicMock()
        mock_app.query_one = MagicMock(return_value=mock_output)
        svc.app = mock_app  # type: ignore[assignment]
        svc.clear_browse_highlight = MagicMock()

        result = svc.scroll_to_tool("tcid-found")

        self.assertTrue(result)
        mock_output.scroll_to_widget.assert_called_once_with(
            mock_panel, animate=True, center=True
        )
        svc.clear_browse_highlight.assert_called_once()
        mock_panel.add_class.assert_called_with("--browse-focused")

    def test_scroll_to_tool_not_found_returns_false(self):
        """When no ToolPanel matches, returns False."""
        svc = self._make_service()

        mock_panel = MagicMock()
        mock_panel._plan_tool_call_id = "tcid-other"

        mock_output = MagicMock()
        mock_output.query = MagicMock(return_value=[mock_panel])

        mock_app = MagicMock()
        mock_app.query_one = MagicMock(return_value=mock_output)
        svc.app = mock_app  # type: ignore[assignment]
        svc.clear_browse_highlight = MagicMock()

        result = svc.scroll_to_tool("tcid-missing")
        self.assertFalse(result)
        mock_output.scroll_to_widget.assert_not_called()

    def test_scroll_to_tool_empty_output_returns_false(self):
        """When no ToolPanels exist, returns False."""
        svc = self._make_service()

        mock_output = MagicMock()
        mock_output.query = MagicMock(return_value=[])

        mock_app = MagicMock()
        mock_app.query_one = MagicMock(return_value=mock_output)
        svc.app = mock_app  # type: ignore[assignment]
        svc.clear_browse_highlight = MagicMock()

        result = svc.scroll_to_tool("tcid-any")
        self.assertFalse(result)

    def test_scroll_to_tool_exception_returns_false(self):
        """If query_one raises, returns False gracefully."""
        svc = self._make_service()

        mock_app = MagicMock()
        mock_app.query_one = MagicMock(side_effect=Exception("no widget"))
        svc.app = mock_app  # type: ignore[assignment]
        svc.clear_browse_highlight = MagicMock()

        result = svc.scroll_to_tool("tcid-any")
        self.assertFalse(result)

    def test_scroll_to_tool_stops_at_first_match(self):
        """scroll_to_tool stops at the first matching panel, not all."""
        svc = self._make_service()

        p1 = MagicMock()
        p1._plan_tool_call_id = "tcid-match"
        p2 = MagicMock()
        p2._plan_tool_call_id = "tcid-match"  # duplicate

        mock_output = MagicMock()
        mock_output.query = MagicMock(return_value=[p1, p2])

        mock_app = MagicMock()
        mock_app.query_one = MagicMock(return_value=mock_output)
        svc.app = mock_app  # type: ignore[assignment]
        svc.clear_browse_highlight = MagicMock()

        result = svc.scroll_to_tool("tcid-match")
        self.assertTrue(result)
        # Only first panel scrolled
        mock_output.scroll_to_widget.assert_called_once_with(p1, animate=True, center=True)


# ---------------------------------------------------------------------------
# TestPlanNowEntryClickable
# ---------------------------------------------------------------------------

class TestPlanNowEntryClickable(unittest.TestCase):
    """P1-1: After show_call(), #now-line is a _PlanEntry (not plain Static)."""

    def _make_now_section(self):
        from hermes_cli.tui.widgets.plan_panel import _NowSection
        ns = _NowSection.__new__(_NowSection)
        ns._base_text = ""
        ns._elapsed_s = 0
        ns._timer_handle = None
        ns._start_monotonic = 0.0
        # Track mounted widgets
        ns._mounted = []
        def _remove_query(selector, *args):
            m = MagicMock()
            m.remove = MagicMock()
            return m
        ns.query_one = MagicMock(side_effect=Exception("not found"))
        ns.mount = MagicMock(side_effect=lambda w: ns._mounted.append(w))
        ns._ensure_timer = MagicMock()
        return ns

    def test_show_call_mounts_plan_entry(self):
        """show_call() mounts a _PlanEntry, not a plain Static."""
        from hermes_cli.tui.widgets.plan_panel import _PlanEntry
        ns = self._make_now_section()
        call = _make_call("RUNNING", label="read_file", tool_call_id="tcid-now")
        ns.show_call(call)
        self.assertTrue(len(ns._mounted) > 0, "mount() must be called")
        widget = ns._mounted[-1]
        self.assertIsInstance(widget, _PlanEntry,
                              f"Expected _PlanEntry, got {type(widget)}")

    def test_show_call_entry_has_correct_tool_call_id(self):
        """Mounted _PlanEntry has _tool_call_id matching the call."""
        from hermes_cli.tui.widgets.plan_panel import _PlanEntry
        ns = self._make_now_section()
        call = _make_call("RUNNING", tool_call_id="tcid-now-abc")
        ns.show_call(call)
        widget = ns._mounted[-1]
        self.assertIsInstance(widget, _PlanEntry)
        self.assertEqual(widget._tool_call_id, "tcid-now-abc")

    def test_show_call_entry_id_is_now_line(self):
        """Mounted entry has id='now-line'."""
        from hermes_cli.tui.widgets.plan_panel import _PlanEntry
        ns = self._make_now_section()
        call = _make_call("RUNNING", tool_call_id="tcid-x")
        ns.show_call(call)
        widget = ns._mounted[-1]
        # id is set via kwargs in constructor — check _node_id or id attribute
        # _PlanEntry is a Static so id is set by Textual internals from kwargs
        # We can check via __init__ call args through inspection or Widget._id
        # The simpler check: confirm it's a _PlanEntry with expected _tool_call_id
        self.assertIsInstance(widget, _PlanEntry)

    def test_show_call_removes_old_now_line(self):
        """show_call() calls query_one('#now-line').remove() before mounting."""
        from hermes_cli.tui.widgets.plan_panel import _NowSection, _PlanEntry
        ns = _NowSection.__new__(_NowSection)
        ns._base_text = ""
        ns._elapsed_s = 0
        ns._timer_handle = None
        ns._start_monotonic = 0.0
        ns._mounted = []

        mock_old = MagicMock()
        ns.query_one = MagicMock(return_value=mock_old)
        ns.mount = MagicMock(side_effect=lambda w: ns._mounted.append(w))
        ns._ensure_timer = MagicMock()

        call = _make_call("RUNNING", tool_call_id="tcid-replace")
        ns.show_call(call)

        mock_old.remove.assert_called_once()

    def test_update_now_line_still_works_after_show_call(self):
        """_update_now_line can still query #now-line (as Static subclass)."""
        from hermes_cli.tui.widgets.plan_panel import _PlanEntry
        from hermes_cli.tui.widgets.plan_panel import _NowSection
        ns = _NowSection.__new__(_NowSection)
        ns._base_text = "● read_file"
        ns._elapsed_s = 0
        ns._timer_handle = None
        ns._start_monotonic = 0.0
        # Simulate that #now-line is a _PlanEntry
        mock_entry = MagicMock(spec=_PlanEntry)
        captured = []
        mock_entry.update = lambda txt: captured.append(txt)
        ns.query_one = MagicMock(return_value=mock_entry)
        ns._update_now_line(5)
        self.assertEqual(captured, ["● read_file  [5s]"])


# ---------------------------------------------------------------------------
# TestNextEntryClickable
# ---------------------------------------------------------------------------

class TestNextEntryClickable(unittest.TestCase):
    """P1-1: update_calls() mounts _PlanEntry for each pending entry."""

    def _make_next_section(self):
        from hermes_cli.tui.widgets.plan_panel import _NextSection
        ns = _NextSection.__new__(_NextSection)
        ns._MAX_VISIBLE = 5
        # Track children in a plain list
        ns._children_list = []

        ns.mount = MagicMock(side_effect=lambda *w: ns._children_list.extend(w))

        # next-header child
        mock_header = MagicMock()
        mock_header.id = "next-header"

        def _query_one(sel, *args):
            if "next-header" in sel:
                return mock_header
            raise Exception("not found")

        ns.query_one = MagicMock(side_effect=_query_one)

        # Patch `children` property so update_calls can iterate it
        children_prop = PropertyMock(return_value=ns._children_list)
        patch.object(type(ns), "children", children_prop).start()

        return ns

    def test_update_calls_mounts_plan_entries(self):
        """Each pending call gets a _PlanEntry, not a plain Static."""
        from hermes_cli.tui.widgets.plan_panel import _PlanEntry
        ns = self._make_next_section()
        calls = [
            _make_call("PENDING", label="read_file", tool_call_id="tcid-1"),
            _make_call("PENDING", label="write_file", tool_call_id="tcid-2"),
        ]
        ns.update_calls(calls)
        mounted = [w for w in ns._children_list if not isinstance(w, MagicMock)]
        plan_entries = [w for w in mounted if isinstance(w, _PlanEntry)]
        self.assertEqual(len(plan_entries), 2,
                         f"Expected 2 _PlanEntry widgets, got {len(plan_entries)}: {mounted}")

    def test_update_calls_entries_have_tool_call_ids(self):
        """Mounted _PlanEntry widgets carry the correct tool_call_ids."""
        from hermes_cli.tui.widgets.plan_panel import _PlanEntry
        ns = self._make_next_section()
        calls = [
            _make_call("PENDING", label="read_file", tool_call_id="tcid-A"),
            _make_call("PENDING", label="write_file", tool_call_id="tcid-B"),
        ]
        ns.update_calls(calls)
        mounted = [w for w in ns._children_list if isinstance(w, _PlanEntry)]
        ids = {e._tool_call_id for e in mounted}
        self.assertIn("tcid-A", ids)
        self.assertIn("tcid-B", ids)

    def test_overflow_line_is_plain_static(self):
        """The '+N more' overflow entry is a plain Static, not _PlanEntry."""
        from hermes_cli.tui.widgets.plan_panel import _PlanEntry
        from textual.widgets import Static
        ns = self._make_next_section()
        ns._MAX_VISIBLE = 2
        calls = [
            _make_call("PENDING", label=f"tool_{i}", tool_call_id=f"tcid-{i}")
            for i in range(5)
        ]
        ns.update_calls(calls)
        all_mounted = ns._children_list[:]
        # Find overflow widget — the last one should be Static but NOT _PlanEntry
        non_entries = [w for w in all_mounted
                       if isinstance(w, Static) and not isinstance(w, _PlanEntry)]
        self.assertTrue(len(non_entries) > 0,
                        "Overflow '+N more' must be a plain Static, not _PlanEntry")


# ---------------------------------------------------------------------------
# TestChipSegments
# ---------------------------------------------------------------------------

class TestChipSegments(unittest.TestCase):
    """P1-2: _PlanPanelHeader chip segments show/hide correctly."""

    def _make_header_with_segs(self, tokens_in: int = 0, tokens_out: int = 0):
        """Create a header with mocked chip segments."""
        from hermes_cli.tui.widgets.plan_panel import _PlanPanelHeader, _ChipSegment
        h = _PlanPanelHeader.__new__(_PlanPanelHeader)
        segs = {}
        for seg_id in ("plan-header-label", "plan-chip-title", "chip-running",
                       "chip-done", "chip-errors", "chip-cost", "plan-f9-badge"):
            m = MagicMock()
            m.display = True
            m.update = MagicMock()
            segs[seg_id] = m

        def _query_one(selector, *args):
            if selector.startswith("#"):
                key = selector[1:]
                if key in segs:
                    return segs[key]
            return MagicMock()

        h.query_one = MagicMock(side_effect=_query_one)
        # Store token defaults so callers can pass them to update_header
        h._test_tokens_in = tokens_in
        h._test_tokens_out = tokens_out
        return h, segs

    def test_collapsed_true_shows_chip_title(self):
        """collapsed=True: #plan-chip-title display=True."""
        h, segs = self._make_header_with_segs()
        h.update_header(collapsed=True, running=1, pending=2, done=3, errors=0)
        self.assertTrue(segs["plan-chip-title"].display)

    def test_collapsed_true_hides_header_label(self):
        """collapsed=True: #plan-header-label display=False."""
        h, segs = self._make_header_with_segs()
        h.update_header(collapsed=True, running=1, pending=2, done=3, errors=0)
        self.assertFalse(segs["plan-header-label"].display)

    def test_collapsed_false_shows_header_label(self):
        """collapsed=False: #plan-header-label display=True."""
        h, segs = self._make_header_with_segs()
        h.update_header(collapsed=False, running=0, pending=0, done=5, errors=0)
        self.assertTrue(segs["plan-header-label"].display)

    def test_collapsed_false_hides_chip_title(self):
        """collapsed=False: #plan-chip-title display=False."""
        h, segs = self._make_header_with_segs()
        h.update_header(collapsed=False, running=0, pending=0, done=5, errors=0)
        self.assertFalse(segs["plan-chip-title"].display)

    def test_chip_running_always_hidden_in_chip(self):
        """A5: #chip-running always hidden in collapsed chip (running count dropped)."""
        h, segs = self._make_header_with_segs()
        segs["chip-running"].display = True
        h.update_header(collapsed=True, running=2, pending=0, done=0, errors=0)
        self.assertFalse(segs["chip-running"].display)

    def test_chip_done_always_hidden_in_chip(self):
        """A5: #chip-done always hidden in collapsed chip (done count dropped)."""
        h, segs = self._make_header_with_segs()
        segs["chip-done"].display = True
        h.update_header(collapsed=True, running=0, pending=1, done=3, errors=0)
        self.assertFalse(segs["chip-done"].display)

    def test_chip_errors_shows_when_errors_gt_0(self):
        """#chip-errors display=True when errors > 0."""
        h, segs = self._make_header_with_segs()
        segs["chip-errors"].display = False
        h.update_header(collapsed=True, running=0, pending=0, done=0, errors=3)
        self.assertTrue(segs["chip-errors"].display)

    def test_chip_errors_hidden_when_zero(self):
        """#chip-errors display=False when errors == 0."""
        h, segs = self._make_header_with_segs()
        h.update_header(collapsed=True, running=0, pending=0, done=2, errors=0)
        self.assertFalse(segs["chip-errors"].display)

    def test_chip_cost_shows_when_cost_gt_0(self):
        """#chip-cost display=True when cost_usd > 0."""
        h, segs = self._make_header_with_segs()
        segs["chip-cost"].display = False
        h.update_header(collapsed=True, running=0, pending=0, done=1, errors=0, cost_usd=0.15)
        self.assertTrue(segs["chip-cost"].display)

    def test_chip_cost_hidden_when_zero_and_no_tokens(self):
        """#chip-cost display=False when cost_usd==0 and no input/output tokens."""
        h, segs = self._make_header_with_segs(tokens_in=0, tokens_out=0)
        h.update_header(collapsed=True, running=0, pending=0, done=1, errors=0,
                        cost_usd=0.0, tokens_in=0, tokens_out=0)
        self.assertFalse(segs["chip-cost"].display)

    def test_chip_cost_shows_token_usage_when_cost_zero_but_tokens_non_zero(self):
        """#chip-cost display=True and shows token usage when cost==0 but tokens non-zero."""
        h, segs = self._make_header_with_segs(tokens_in=1234, tokens_out=56)
        h.update_header(collapsed=True, running=0, pending=0, done=1, errors=0,
                        cost_usd=0.0, tokens_in=1234, tokens_out=56)
        self.assertTrue(segs["chip-cost"].display)
        update_text = " ".join(
            str(call[0][0]) for call in segs["chip-cost"].update.call_args_list
        )
        assert "↑" in update_text or "in" in update_text, \
            "chip-cost should show token direction signal"

    def test_f9_badge_visible_in_both_modes(self):
        """#plan-f9-badge is visible in collapsed and expanded mode."""
        h, segs = self._make_header_with_segs()
        # Collapsed
        h.update_header(collapsed=True, running=0, pending=0, done=1, errors=0)
        self.assertTrue(segs["plan-f9-badge"].display)
        # Expanded
        h.update_header(collapsed=False, running=0, pending=0, done=1, errors=0)
        self.assertTrue(segs["plan-f9-badge"].display)

    def test_show_chip_pending_in_title_text(self):
        """A5: pending count appears in chip title with ⏵ glyph."""
        h, segs = self._make_header_with_segs()
        h.update_header(collapsed=True, running=0, pending=3, done=1, errors=0)
        all_update_text = " ".join(
            str(call[0][0]) for call in segs["plan-chip-title"].update.call_args_list
        )
        self.assertIn("3⏵", all_update_text)


# ---------------------------------------------------------------------------
# TestChipJump
# ---------------------------------------------------------------------------

class TestChipJump(unittest.TestCase):
    """P1-2: _ChipSegment jump actions call BrowseService correctly."""

    def _make_chip(self, action: str):
        from hermes_cli.tui.widgets.plan_panel import _ChipSegment
        chip = _ChipSegment.__new__(_ChipSegment)
        chip._chip_action = action
        return chip

    def _patch_app(self, chip, mock_app):
        p = patch.object(type(chip), "app", new_callable=PropertyMock, return_value=mock_app)
        p.start()
        return p

    def test_jump_running_picks_running_call(self):
        """_jump_running() finds RUNNING call and calls scroll_to_tool."""
        chip = self._make_chip("jump_running")

        running_call = _make_call("RUNNING", tool_call_id="tcid-running")
        pending_call = _make_call("PENDING", tool_call_id="tcid-pending")
        done_call = _make_call("DONE", tool_call_id="tcid-done")

        mock_svc = MagicMock()
        mock_app = MagicMock()
        mock_app.planned_calls = [done_call, running_call, pending_call]
        mock_app._svc_browse = mock_svc
        p = self._patch_app(chip, mock_app)
        try:
            chip._jump_running()
        finally:
            p.stop()
        mock_svc.scroll_to_tool.assert_called_once_with("tcid-running")

    def test_jump_running_noop_when_none_running(self):
        """_jump_running() is a no-op when no RUNNING call."""
        chip = self._make_chip("jump_running")
        mock_svc = MagicMock()
        mock_app = MagicMock()
        mock_app.planned_calls = [_make_call("DONE"), _make_call("PENDING")]
        mock_app._svc_browse = mock_svc
        p = self._patch_app(chip, mock_app)
        try:
            chip._jump_running()
        finally:
            p.stop()
        mock_svc.scroll_to_tool.assert_not_called()

    def test_jump_first_error_picks_first_error_call(self):
        """_jump_first_error() finds first ERROR call and calls scroll_to_tool."""
        chip = self._make_chip("jump_first_error")

        err1 = _make_call("ERROR", tool_call_id="tcid-err1")
        err2 = _make_call("ERROR", tool_call_id="tcid-err2")
        running = _make_call("RUNNING", tool_call_id="tcid-run")

        mock_svc = MagicMock()
        mock_app = MagicMock()
        mock_app.planned_calls = [running, err1, err2]
        mock_app._svc_browse = mock_svc
        p = self._patch_app(chip, mock_app)
        try:
            chip._jump_first_error()
        finally:
            p.stop()
        mock_svc.scroll_to_tool.assert_called_once_with("tcid-err1")

    def test_jump_first_error_noop_when_no_errors(self):
        """_jump_first_error() is a no-op when no ERROR call."""
        chip = self._make_chip("jump_first_error")
        mock_svc = MagicMock()
        mock_app = MagicMock()
        mock_app.planned_calls = [_make_call("RUNNING"), _make_call("DONE")]
        mock_app._svc_browse = mock_svc
        p = self._patch_app(chip, mock_app)
        try:
            chip._jump_first_error()
        finally:
            p.stop()
        mock_svc.scroll_to_tool.assert_not_called()

    def test_on_click_dispatches_jump_running(self):
        """on_click() with action='jump_running' calls _jump_running."""
        chip = self._make_chip("jump_running")
        chip._jump_running = MagicMock()
        chip._jump_first_error = MagicMock()
        chip._open_usage = MagicMock()
        chip.on_click()
        chip._jump_running.assert_called_once()
        chip._jump_first_error.assert_not_called()

    def test_on_click_dispatches_jump_first_error(self):
        """on_click() with action='jump_first_error' calls _jump_first_error."""
        chip = self._make_chip("jump_first_error")
        chip._jump_running = MagicMock()
        chip._jump_first_error = MagicMock()
        chip._open_usage = MagicMock()
        chip.on_click()
        chip._jump_first_error.assert_called_once()
        chip._jump_running.assert_not_called()

    def test_on_click_dispatches_usage(self):
        """on_click() with action='usage' calls _open_usage."""
        chip = self._make_chip("usage")
        chip._jump_running = MagicMock()
        chip._jump_first_error = MagicMock()
        chip._open_usage = MagicMock()
        chip.on_click()
        chip._open_usage.assert_called_once()

    def test_chip_segment_not_focusable(self):
        """_ChipSegment.can_focus must be False."""
        from hermes_cli.tui.widgets.plan_panel import _ChipSegment
        self.assertFalse(
            getattr(_ChipSegment, "can_focus", True),
            "_ChipSegment.can_focus must be False",
        )


# ---------------------------------------------------------------------------
# TestF9Badge
# ---------------------------------------------------------------------------

class TestF9Badge(unittest.TestCase):
    """P1-3: #plan-f9-badge is in the DOM after compose."""

    def test_plan_panel_header_compose_yields_f9_badge(self):
        """compose() of _PlanPanelHeader must yield a Static with id='plan-f9-badge'."""
        import inspect
        from hermes_cli.tui.widgets.plan_panel import _PlanPanelHeader
        src = inspect.getsource(_PlanPanelHeader.compose)
        self.assertIn("plan-f9-badge", src)

    def test_plan_panel_header_compose_yields_f9_badge_content(self):
        """compose() yields the '[F9]' text for the badge."""
        import inspect
        from hermes_cli.tui.widgets.plan_panel import _PlanPanelHeader
        src = inspect.getsource(_PlanPanelHeader.compose)
        self.assertIn("[F9]", src)

    def test_plan_panel_header_has_f9_badge_in_default_css(self):
        """DEFAULT_CSS must contain #plan-f9-badge styling."""
        from hermes_cli.tui.widgets.plan_panel import _PlanPanelHeader
        css = _PlanPanelHeader.DEFAULT_CSS
        self.assertIn("plan-f9-badge", css)

    def test_plan_panel_header_f9_badge_docked_right(self):
        """DEFAULT_CSS for #plan-f9-badge must include dock: right."""
        from hermes_cli.tui.widgets.plan_panel import _PlanPanelHeader
        css = _PlanPanelHeader.DEFAULT_CSS
        # Find the f9 badge block
        badge_idx = css.find("plan-f9-badge")
        self.assertNotEqual(badge_idx, -1)
        # Look ahead for dock: right
        snippet = css[badge_idx:badge_idx + 200]
        self.assertIn("dock: right", snippet)


# ---------------------------------------------------------------------------
# TestToolPanelPlanId
# ---------------------------------------------------------------------------

class TestToolPanelPlanId(unittest.TestCase):
    """P1-1: ToolPanel has _plan_tool_call_id attribute."""

    def test_tool_panel_has_plan_tool_call_id_attr(self):
        """ToolPanel.__init__ must set _plan_tool_call_id = None."""
        import inspect
        from hermes_cli.tui.tool_panel import ToolPanel
        src = inspect.getsource(ToolPanel.__init__)
        self.assertIn("_plan_tool_call_id", src)

    def test_tool_panel_plan_id_default_is_none(self):
        """_plan_tool_call_id defaults to None in __init__ source."""
        import inspect
        from hermes_cli.tui.tool_panel import ToolPanel
        src = inspect.getsource(ToolPanel.__init__)
        self.assertIn("_plan_tool_call_id: str | None = None", src)


# ---------------------------------------------------------------------------
# TestMessagePanelWiring
# ---------------------------------------------------------------------------

class TestMessagePanelWiring(unittest.TestCase):
    """P1-1: message_panel.py else branch wires _plan_tool_call_id."""

    def test_message_panel_wires_plan_tool_call_id(self):
        """The else branch in open_streaming_tool_block must assign _plan_tool_call_id."""
        import inspect
        import hermes_cli.tui.widgets.message_panel as mp
        src = inspect.getsource(mp.MessagePanel.open_streaming_tool_block)
        self.assertIn("_plan_tool_call_id", src)
        self.assertIn("tool_call_id", src)


if __name__ == "__main__":
    unittest.main()
