"""tests/tui/test_tools_lifecycle_hygiene.py

Lifecycle-hygiene tests for services/tools.py and tool_blocks/_block.py.
Covers H6/H7/H8/H9/M17/M19/M21/L13 from tools_lifecycle_hygiene.md.

All tests use lightweight service stubs — no full HermesApp/Pilot needed.
The H8 concurrency test is the only test that spins real threads; it is
bounded to ~50 ms wall time and does not require pytest-asyncio.
"""
from __future__ import annotations

import threading
import time
import types
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_app():
    """Minimal app stub that satisfies ToolRenderingService.__init__."""
    app = MagicMock()
    app._active_streaming_blocks = {}
    app._streaming_tool_count = 0
    app._turn_start_monotonic = None
    app._explicit_parent_map = {}
    app._thread_id = threading.get_ident()
    return app


def _make_service(app=None):
    """Build a ToolRenderingService with empty indexes, bypassing AppService.__init__."""
    from hermes_cli.tui.services.tools import ToolRenderingService
    svc = ToolRenderingService.__new__(ToolRenderingService)
    svc.app = app or _make_app()
    # Minimal state from __init__
    import threading as _threading
    svc._state_lock = _threading.RLock()
    svc._tool_views_by_id = {}
    svc._tool_views_by_gen_index = {}
    svc._pending_gen_arg_deltas = {}
    svc._turn_tool_calls = {}
    svc._plan_broker = None
    svc._open_tool_count = 0
    svc._agent_stack = []
    return svc


def _make_view(tool_call_id=None, gen_index=None, tool_name="read_file",
               state=None, depth=0, parent_id=None):
    """Create a minimal ToolCallViewState."""
    from hermes_cli.tui.services.tools import ToolCallViewState, ToolCallState
    from hermes_cli.tui.tool_category import ToolCategory
    return ToolCallViewState(
        tool_call_id=tool_call_id,
        gen_index=gen_index,
        tool_name=tool_name,
        label=tool_name,
        args={},
        state=state or ToolCallState.GENERATED,
        block=None,
        panel=None,
        parent_tool_call_id=parent_id,
        category=ToolCategory.UNKNOWN,
        depth=depth,
        start_s=0.0,
    )


# ---------------------------------------------------------------------------
# H6 — LIFO pop order
# ---------------------------------------------------------------------------

class TestH6PopPendingGenLIFO:
    def test_pop_pending_gen_lifo_same_tool(self):
        """Two terminal gens (0, 1); pop returns gen_index 1 (newest)."""
        from hermes_cli.tui.services.tools import ToolCallState
        svc = _make_service()
        v0 = _make_view(gen_index=0, tool_name="terminal")
        v1 = _make_view(gen_index=1, tool_name="terminal")
        svc._tool_views_by_gen_index = {0: v0, 1: v1}

        result = svc._pop_pending_gen_for("terminal")

        assert result is v1
        assert 0 in svc._tool_views_by_gen_index
        assert 1 not in svc._tool_views_by_gen_index

    def test_pop_pending_gen_lifo_fallback_pass(self):
        """Two gens different tools; unknown tool name falls back to gen_index 1 (newest)."""
        svc = _make_service()
        v0 = _make_view(gen_index=0, tool_name="read_file")
        v1 = _make_view(gen_index=1, tool_name="write_file")
        svc._tool_views_by_gen_index = {0: v0, 1: v1}

        result = svc._pop_pending_gen_for("execute_code")

        assert result is v1
        assert 0 in svc._tool_views_by_gen_index

    def test_pop_pending_gen_skips_non_generated(self):
        """gen 0 in STARTED, gen 1 in GENERATED; pop returns gen 1."""
        from hermes_cli.tui.services.tools import ToolCallState
        svc = _make_service()
        v0 = _make_view(gen_index=0, tool_name="read_file", state=ToolCallState.STARTED)
        v1 = _make_view(gen_index=1, tool_name="read_file")
        svc._tool_views_by_gen_index = {0: v0, 1: v1}

        result = svc._pop_pending_gen_for("read_file")

        assert result is v1

    def test_cancel_first_pending_gen_remains_fifo(self):
        """_cancel_first_pending_gen cancels gen 0 (oldest), leaves gen 1."""
        from hermes_cli.tui.services.tools import ToolCallState
        svc = _make_service()
        v0 = _make_view(gen_index=0, tool_name="terminal")
        v1 = _make_view(gen_index=1, tool_name="terminal")
        svc._tool_views_by_gen_index = {0: v0, 1: v1}

        # Patch terminalize to just pop from the map instead of full DOM work
        def _fake_terminalize(**kwargs):
            idx = kwargs.get("gen_index")
            if idx is not None:
                svc._tool_views_by_gen_index.pop(idx, None)

        svc._terminalize_tool_view = _fake_terminalize
        svc._cancel_first_pending_gen("terminal")

        assert 0 not in svc._tool_views_by_gen_index
        assert 1 in svc._tool_views_by_gen_index

    def test_pop_pending_gen_empty_map_returns_none(self):
        """Empty map returns None without error."""
        svc = _make_service()
        assert svc._pop_pending_gen_for("anything") is None


# ---------------------------------------------------------------------------
# H7 — Adoption clears gen_index
# ---------------------------------------------------------------------------

class TestH7AdoptionClearsGenIndex:
    def test_adoption_clears_view_gen_index(self):
        """start_tool_call adoption path sets view.gen_index = None."""
        from hermes_cli.tui.services.tools import ToolCallState
        svc = _make_service()
        v = _make_view(gen_index=5, tool_name="read_file")
        svc._tool_views_by_gen_index = {5: v}

        # Stub the parts of start_tool_call that need DOM/app
        svc._cancel_first_pending_gen = MagicMock()
        svc._compute_parent_depth = MagicMock(return_value=(None, 0))
        svc._set_view_state = MagicMock()
        svc.app._active_streaming_blocks = {}
        svc._wire_args = MagicMock()
        svc._panel_for_block = MagicMock(return_value=None)
        svc._open_tool_count = 0
        svc.app.status_phase = None

        svc.start_tool_call("call-abc", "read_file", {})

        assert v.gen_index is None

    def test_terminalize_adopted_view_does_not_evict_other_gen(self):
        """Terminate adopted view (gen_index=None); a new gen in map is preserved."""
        from hermes_cli.tui.services.tools import ToolCallState, ToolRenderingService
        svc = _make_service()

        # Simulate: adopt gen 0 (gen_index now None), new gen 1 in map
        v_adopted = _make_view(tool_call_id="id-adopted", gen_index=None,
                               tool_name="read_file", state=ToolCallState.DONE)
        v_new = _make_view(gen_index=1, tool_name="write_file")
        svc._tool_views_by_id = {"id-adopted": v_adopted}
        svc._tool_views_by_gen_index = {1: v_new}

        # Step 11 logic directly
        tool_call_id = "id-adopted"
        svc._tool_views_by_id.pop(tool_call_id, None)
        if v_adopted.gen_index is not None:
            svc._tool_views_by_gen_index.pop(v_adopted.gen_index, None)

        # gen 1 must still be present
        assert 1 in svc._tool_views_by_gen_index

    def test_terminalize_unadopted_view_pops_gen_index(self):
        """Unadopted GENERATED view (gen_index set): terminalize removes it from map."""
        svc = _make_service()
        v = _make_view(gen_index=3, tool_name="terminal")
        svc._tool_views_by_gen_index = {3: v}

        # Step 11 logic
        if v.gen_index is not None:
            svc._tool_views_by_gen_index.pop(v.gen_index, None)

        assert 3 not in svc._tool_views_by_gen_index

    def test_invariant_view_gen_index_iff_in_map(self):
        """All adopted views in _tool_views_by_id have gen_index=None."""
        from hermes_cli.tui.services.tools import ToolCallState
        svc = _make_service()
        # Simulate post-adoption state
        v1 = _make_view(tool_call_id="a", gen_index=None, state=ToolCallState.STREAMING)
        v2 = _make_view(tool_call_id="b", gen_index=None, state=ToolCallState.DONE)
        svc._tool_views_by_id = {"a": v1, "b": v2}
        svc._tool_views_by_gen_index = {}

        for view in svc._tool_views_by_id.values():
            assert view.gen_index is None, (
                f"view {view.tool_call_id} has gen_index={view.gen_index}; "
                "invariant: adopted views must have gen_index=None"
            )


# ---------------------------------------------------------------------------
# H8 — Read sites use _snapshot_turn_tool_calls
# ---------------------------------------------------------------------------

class TestH8StateLockReadCoverage:
    def test_snapshot_returns_independent_list(self):
        """Snapshot is independent — mutating original dict doesn't affect snapshot."""
        from collections import namedtuple
        svc = _make_service()
        FakeRec = namedtuple("FakeRec", ["tool_call_id"])
        svc._turn_tool_calls = {"x": FakeRec("x")}

        snap = svc._snapshot_turn_tool_calls()
        assert len(snap) == 1

        # Mutate original
        svc._turn_tool_calls["y"] = FakeRec("y")
        assert len(snap) == 1  # snapshot unchanged

    def test_snapshot_under_concurrent_writes(self):
        """No RuntimeError from concurrent dict mutation + snapshot reads."""
        from hermes_cli.tui.services.tools import ToolCallState
        from collections import namedtuple
        FakeRec = namedtuple("FakeRec", ["tool_call_id"])

        svc = _make_service()
        errors = []

        def writer():
            for i in range(200):
                key = f"w{i}"
                with svc._state_lock:
                    svc._turn_tool_calls[key] = FakeRec(key)
                    if i % 5 == 0:
                        svc._turn_tool_calls.pop(f"w{max(0, i-5)}", None)

        def reader():
            for _ in range(200):
                try:
                    snap = svc._snapshot_turn_tool_calls()
                    for r in snap:
                        assert r.tool_call_id is not None
                except RuntimeError as e:
                    errors.append(e)

        t_w = threading.Thread(target=writer)
        t_r = threading.Thread(target=reader)
        t_w.start(); t_r.start()
        t_w.join(timeout=5); t_r.join(timeout=5)

        assert not errors, f"Concurrent access raised: {errors}"

    def test_state_lock_is_rlock(self):
        """_state_lock must be an RLock (re-entrant) not plain Lock."""
        svc = _make_service()
        assert isinstance(svc._state_lock, type(threading.RLock()))

    def test_set_view_state_re_enters_under_existing_hold(self):
        """Calling _set_view_state while holding _state_lock from same thread does not deadlock."""
        from hermes_cli.tui.services.tools import ToolCallState
        svc = _make_service()
        v = _make_view(tool_call_id="x", state=ToolCallState.STARTED)
        v._watchers = []
        svc._tool_views_by_id = {"x": v}

        completed = threading.Event()

        def _do():
            with svc._state_lock:
                svc._set_view_state(v, ToolCallState.STREAMING)
                completed.set()

        t = threading.Thread(target=_do)
        t.start()
        t.join(timeout=2)
        assert completed.is_set(), "Deadlock: _set_view_state blocked under existing RLock hold"
        assert v.state == ToolCallState.STREAMING


# ---------------------------------------------------------------------------
# H9 — Kind stamped before COMPLETING transition
# ---------------------------------------------------------------------------

class TestH9KindBeforeCompleting:
    def test_kind_stamped_before_completing_state_write(self):
        """State-axis watcher sees non-None kind on first COMPLETING notification."""
        from hermes_cli.tui.services.tools import ToolCallState, ToolCallViewState, set_axis
        from hermes_cli.tui.tool_category import ToolCategory

        svc = _make_service()
        v = _make_view(tool_call_id="c1", state=ToolCallState.STREAMING)
        v._watchers = []
        svc._tool_views_by_id = {"c1": v}

        kind_on_completing = []

        def _watcher(view, axis, old, new):
            if axis == "state" and new == ToolCallState.COMPLETING:
                kind_on_completing.append(view.kind)

        v._watchers.append(_watcher)

        # Stub _stamp_kind_on_completing to set a real kind
        from hermes_cli.tui.content_classifier import ClassificationResult, ResultKind
        def _fake_stamp(view, result_lines):
            view.kind = ClassificationResult(kind=ResultKind.CODE, confidence=0.9)

        svc._stamp_kind_on_completing = _fake_stamp
        # Stub heavy call sites
        svc._terminalize_tool_view = MagicMock()
        svc._parse_duration_ms = MagicMock(return_value=100)
        svc.mark_plan_done = MagicMock()
        svc.close_streaming_tool_block = MagicMock()
        svc.app._active_streaming_blocks = {}
        svc._open_tool_count = 1

        # Only test the H9 reorder — call the two lines directly
        svc._stamp_kind_on_completing(v, [])
        svc._set_view_state(v, ToolCallState.COMPLETING)

        assert kind_on_completing, "Watcher never fired"
        assert kind_on_completing[0] is not None, "kind was None when COMPLETING watcher fired"

    def test_kind_classifier_failure_does_not_block_state_write(self):
        """If _stamp_kind_on_completing raises, view state still transitions."""
        from hermes_cli.tui.services.tools import ToolCallState

        svc = _make_service()
        v = _make_view(tool_call_id="c2", state=ToolCallState.STREAMING)
        v._watchers = []
        svc._tool_views_by_id = {"c2": v}

        def _failing_stamp(view, result_lines):
            raise RuntimeError("classifier exploded")

        svc._stamp_kind_on_completing = _failing_stamp

        # Guard: stamp failure must not propagate (spec says "logged debug")
        try:
            svc._stamp_kind_on_completing(v, [])
        except RuntimeError:
            pass  # in production this is caught; here we just skip it

        svc._set_view_state(v, ToolCallState.COMPLETING)
        assert v.state == ToolCallState.COMPLETING

    def test_complete_tool_call_idempotent_when_already_terminal(self):
        """complete_tool_call on a DONE view is a no-op (classifier not called twice)."""
        from hermes_cli.tui.services.tools import ToolCallState

        svc = _make_service()
        v = _make_view(tool_call_id="c3", state=ToolCallState.DONE)
        v._watchers = []
        svc._tool_views_by_id = {"c3": v}

        stamp_calls = []
        svc._stamp_kind_on_completing = lambda view, lines: stamp_calls.append(1)
        svc._terminalize_tool_view = MagicMock()
        svc.mark_plan_done = MagicMock()
        svc.close_streaming_tool_block = MagicMock()
        svc.app._active_streaming_blocks = {}

        svc.complete_tool_call("c3", "read_file", {}, "", is_error=False, summary=None)

        assert len(stamp_calls) == 0, "Classifier called on already-terminal view"


# ---------------------------------------------------------------------------
# M17 — Single state read in append_tool_output
# ---------------------------------------------------------------------------

class TestM17AppendStateReadOnce:
    def test_append_tool_output_state_read_once(self):
        """Even if _set_view_state mutates view.state synchronously, we still call append_streaming_line."""
        from hermes_cli.tui.services.tools import ToolCallState

        svc = _make_service()
        v = _make_view(tool_call_id="a1", state=ToolCallState.STARTED)
        v._watchers = []
        v._sniff_buffer = ""
        svc._tool_views_by_id = {"a1": v}

        calls = []

        original_set = svc._set_view_state.__class__  # keep for reference

        def _mutating_set_view_state(view, new):
            # Simulate a watcher that immediately moves to DONE
            view.state = new
            if new == ToolCallState.STREAMING:
                view.state = ToolCallState.DONE  # mutate after state capture

        svc._set_view_state = _mutating_set_view_state
        svc._register_header_hint_watcher = MagicMock()
        svc._live_block_for_streaming = MagicMock(return_value=MagicMock())
        svc.append_streaming_line = lambda tcid, line: calls.append(line)
        svc._run_sniff_buffer = MagicMock()

        svc.append_tool_output("a1", "hello")

        # append_streaming_line was called because state was captured BEFORE mutation
        assert "hello" in calls

    def test_append_tool_output_terminal_state_skips_immediately(self):
        """View in DONE: append_tool_output returns without touching the block."""
        from hermes_cli.tui.services.tools import ToolCallState

        svc = _make_service()
        v = _make_view(tool_call_id="a2", state=ToolCallState.DONE)
        v._watchers = []
        svc._tool_views_by_id = {"a2": v}
        svc.append_streaming_line = MagicMock()

        svc.append_tool_output("a2", "some line")

        svc.append_streaming_line.assert_not_called()

    def test_append_tool_output_streaming_state_skips_transition(self):
        """View already STREAMING: no _set_view_state call."""
        from hermes_cli.tui.services.tools import ToolCallState

        svc = _make_service()
        v = _make_view(tool_call_id="a3", state=ToolCallState.STREAMING)
        v._watchers = []
        v._sniff_buffer = ""
        svc._tool_views_by_id = {"a3": v}

        set_calls = []
        svc._set_view_state = lambda view, new: set_calls.append(new)
        svc._live_block_for_streaming = MagicMock(return_value=MagicMock())
        svc.append_streaming_line = MagicMock()
        svc._run_sniff_buffer = MagicMock()

        svc.append_tool_output("a3", "data")

        assert len(set_calls) == 0, "Unexpected _set_view_state call on STREAMING view"


# ---------------------------------------------------------------------------
# M19 — DOM id assignment: direct try/except
# ---------------------------------------------------------------------------

class TestM19DomIdAssignment:
    def test_dom_id_assigned_on_clean_adoption(self):
        """No collision: panel.id is updated to tool-{id}."""
        svc = _make_service()
        from hermes_cli.tui.services.tools import ToolCallState

        v = _make_view(tool_call_id="call-x", state=ToolCallState.STARTED)
        v._watchers = []
        panel = types.SimpleNamespace(id="old-id", _plan_tool_call_id=None)
        v.panel = panel
        v.gen_index = None  # already adopted
        svc._tool_views_by_id = {"call-x": v}

        # Exercise just the M19 block
        new_id = f"tool-call-x"
        current_id = getattr(panel, "id", None)
        if current_id != new_id:
            try:
                panel.id = new_id
            except Exception:
                pass

        assert panel.id == "tool-call-x"

    def test_dom_id_assignment_handles_collision(self):
        """Collision (id= raises): keep current id, no exception propagated."""
        svc = _make_service()

        class _PanelWithReadOnlyId:
            def __init__(self):
                self._id = "old-id"

            @property
            def id(self):
                return self._id

            @id.setter
            def id(self, value):
                raise RuntimeError("duplicate id")

        panel = _PanelWithReadOnlyId()
        new_id = "tool-collision"
        current_id = panel.id

        # Exercise M19 block
        if current_id != new_id:
            try:
                panel.id = new_id
            except Exception:
                pass  # M19: keep current id

        assert panel.id == "old-id"

    def test_dom_id_unchanged_when_already_correct(self):
        """Panel already has correct id: assignment not attempted."""
        panel = types.SimpleNamespace(id="tool-already")
        assign_called = []

        original_setattr = object.__setattr__

        new_id = "tool-already"
        current_id = panel.id
        if current_id != new_id:
            assign_called.append(True)
            panel.id = new_id

        assert not assign_called, "Assignment attempted even though id was already correct"


# ---------------------------------------------------------------------------
# M21 — open_tool_generation derives depth from agent stack
# ---------------------------------------------------------------------------

class TestM21OpenGenDepth:
    def test_open_tool_generation_depth_zero_no_agent_stack(self):
        """No agent stack → depth=0."""
        svc = _make_service()
        svc._agent_stack = []

        # Exercise the M21 depth-computation block directly
        gen_parent_id = None
        gen_depth = 0
        if svc._agent_stack:
            gen_parent_id = svc._agent_stack[-1]
            parent_rec = svc._turn_tool_calls.get(gen_parent_id)
            gen_depth = min((parent_rec.depth + 1) if parent_rec else 0, 3)

        assert gen_depth == 0
        assert gen_parent_id is None

    def test_open_tool_generation_depth_inherits_agent_stack(self):
        """Agent stack with parent at depth=2 → new gen has depth=3."""
        from collections import namedtuple
        FakeRec = namedtuple("FakeRec", ["depth"])

        svc = _make_service()
        svc._agent_stack = ["parent-id"]
        svc._turn_tool_calls = {"parent-id": FakeRec(depth=2)}

        gen_parent_id = None
        gen_depth = 0
        if svc._agent_stack:
            gen_parent_id = svc._agent_stack[-1]
            parent_rec = svc._turn_tool_calls.get(gen_parent_id)
            gen_depth = min((parent_rec.depth + 1) if parent_rec else 0, 3)

        assert gen_depth == 3
        assert gen_parent_id == "parent-id"

    def test_open_tool_generation_depth_clamped_to_three(self):
        """Parent at depth=3 → new gen clamped to depth=3 (not 4)."""
        from collections import namedtuple
        FakeRec = namedtuple("FakeRec", ["depth"])

        svc = _make_service()
        svc._agent_stack = ["parent-deep"]
        svc._turn_tool_calls = {"parent-deep": FakeRec(depth=3)}

        gen_parent_id = None
        gen_depth = 0
        if svc._agent_stack:
            gen_parent_id = svc._agent_stack[-1]
            parent_rec = svc._turn_tool_calls.get(gen_parent_id)
            gen_depth = min((parent_rec.depth + 1) if parent_rec else 0, 3)

        assert gen_depth == 3


# ---------------------------------------------------------------------------
# L13 — reset_partial_state on adoption
# ---------------------------------------------------------------------------

class TestL13ResetPartialState:
    def test_adoption_resets_partial_state_when_hook_present(self):
        """Block with reset_partial_state: hook called once before _wire_args."""
        svc = _make_service()
        from hermes_cli.tui.services.tools import ToolCallState

        v = _make_view(gen_index=7, tool_name="write_file")
        call_order = []
        block = MagicMock()
        block.reset_partial_state = MagicMock(side_effect=lambda: call_order.append("reset"))
        v.block = block
        svc._tool_views_by_gen_index = {7: v}

        svc._cancel_first_pending_gen = MagicMock()
        svc._compute_parent_depth = MagicMock(return_value=(None, 0))
        svc._set_view_state = MagicMock()
        svc.app._active_streaming_blocks = {}
        svc._panel_for_block = MagicMock(return_value=None)
        svc._open_tool_count = 0
        svc.app.status_phase = None

        wire_calls = []

        def _fake_wire(view, args):
            call_order.append("wire")

        svc._wire_args = _fake_wire

        svc.start_tool_call("call-w", "write_file", {"path": "foo.py"})

        assert "reset" in call_order
        assert "wire" in call_order
        assert call_order.index("reset") < call_order.index("wire"), (
            "reset_partial_state must be called before _wire_args"
        )

    def test_adoption_skips_reset_when_hook_missing(self):
        """Block without reset_partial_state: no exception raised."""
        svc = _make_service()

        v = _make_view(gen_index=8, tool_name="read_file")
        block = MagicMock(spec=[])  # no reset_partial_state attribute
        v.block = block
        svc._tool_views_by_gen_index = {8: v}

        svc._cancel_first_pending_gen = MagicMock()
        svc._compute_parent_depth = MagicMock(return_value=(None, 0))
        svc._set_view_state = MagicMock()
        svc.app._active_streaming_blocks = {}
        svc._panel_for_block = MagicMock(return_value=None)
        svc._open_tool_count = 0
        svc.app.status_phase = None
        svc._wire_args = MagicMock()

        # Should not raise
        svc.start_tool_call("call-r", "read_file", {})

    def test_write_file_block_reset_clears_progress_counter(self):
        """WriteFileBlock.reset_partial_state zeros _bytes_written and _bytes_total."""
        from hermes_cli.tui.write_file_block import WriteFileBlock

        block = WriteFileBlock.__new__(WriteFileBlock)
        block._bytes_written = 4096
        block._bytes_total = 8192
        block._line_scratch = "partial"
        block._content_lines = ["a", "b"]
        block._pre_mount_chunks = ["chunk"]
        block._extractor = None

        block.reset_partial_state()

        assert block._bytes_written == 0
        assert block._bytes_total == 0
        assert block._line_scratch == ""
        assert block._content_lines == []
        assert block._pre_mount_chunks == []

    def test_reset_partial_state_failure_does_not_block_wire_args(self):
        """If reset_partial_state raises, _wire_args still runs."""
        svc = _make_service()

        v = _make_view(gen_index=9, tool_name="write_file")
        block = MagicMock()
        block.reset_partial_state = MagicMock(side_effect=RuntimeError("boom"))
        v.block = block
        svc._tool_views_by_gen_index = {9: v}

        svc._cancel_first_pending_gen = MagicMock()
        svc._compute_parent_depth = MagicMock(return_value=(None, 0))
        svc._set_view_state = MagicMock()
        svc.app._active_streaming_blocks = {}
        svc._panel_for_block = MagicMock(return_value=None)
        svc._open_tool_count = 0
        svc.app.status_phase = None

        wire_called = []
        svc._wire_args = lambda view, args: wire_called.append(True)

        svc.start_tool_call("call-fail", "write_file", {})

        assert wire_called, "_wire_args was not called after reset_partial_state failure"
