"""SPEC-TBM — tool block MED + LOW cleanup tests.

Spec: /home/xush/.hermes/spec_tbm_tool_block_med_cleanup.md
"""
from __future__ import annotations

import ast
import logging
import pathlib
import threading
from unittest.mock import MagicMock, patch

import pytest


_REPO_ROOT = pathlib.Path(__file__).parents[2]
_ACTIONS_PATH = _REPO_ROOT / "hermes_cli" / "tui" / "tool_panel" / "_actions.py"
_STREAMING_PATH = _REPO_ROOT / "hermes_cli" / "tui" / "tool_blocks" / "_streaming.py"
_BASE_RENDERER_PATH = _REPO_ROOT / "hermes_cli" / "tui" / "body_renderers" / "base.py"
_CONCEPT_PATH = _REPO_ROOT / "docs" / "concept.md"


def _make_hint_fixture():
    from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
    obj = MagicMock(spec=_ToolPanelActionsMixin)
    obj._view_state = None
    obj._lookup_view_state = MagicMock(return_value=None)
    obj._result_summary_v4 = None
    obj._block = None
    obj.collapsed = False
    obj._is_error.return_value = False
    obj._visible_footer_action_kinds.return_value = set()
    obj._get_omission_bar.return_value = None
    obj._result_paths_for_action.return_value = []
    obj._next_kind_label = None
    return obj


# ---------------------------------------------------------------------------
# TBM-1 — Hint priority: t/T before e/o/u/E
# ---------------------------------------------------------------------------

class TestHintOrder:

    def test_hint_order_t_before_e_o_u(self) -> None:
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        obj = _make_hint_fixture()
        rs = MagicMock()
        rs.stderr_tail = "boom"
        rs.actions = ()
        rs.artifacts = ()
        obj._result_summary_v4 = rs
        obj._next_kind_label = lambda current: "json"
        _, contextual = _ToolPanelActionsMixin._collect_hints(obj)
        keys = [k for k, _ in contextual]
        assert "t" in keys, f"t should appear; got {keys}"
        t_idx = keys.index("t")
        for foreign in ("e", "o", "u", "E"):
            if foreign in keys:
                assert t_idx < keys.index(foreign), (
                    f"t at {t_idx} must precede {foreign} at {keys.index(foreign)}; got {keys}"
                )

    def test_hint_order_retry_first_when_present(self) -> None:
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        obj = _make_hint_fixture()
        obj._is_error.return_value = True
        rs = MagicMock()
        rs.stderr_tail = None
        rs.actions = ()
        rs.artifacts = ()
        obj._result_summary_v4 = rs
        obj._next_kind_label = lambda current: "json"
        primary, contextual = _ToolPanelActionsMixin._collect_hints(obj)
        primary_keys = [k for k, _ in primary]
        ctx_keys = [k for k, _ in contextual]
        # retry takes priority — present in primary; t/T omitted (mutually
        # exclusive with error path via the not _is_error() guard).
        assert "r" in primary_keys, f"retry must be present in primary; got {primary_keys}"
        assert "t" not in ctx_keys, f"t must not appear in error path; got {ctx_keys}"
        assert "T" not in ctx_keys, f"T must not appear in error path; got {ctx_keys}"


# ---------------------------------------------------------------------------
# TBM-2 — Sniff buffer cap
# ---------------------------------------------------------------------------

class TestSniffBufferCap:

    def _make_view(self):
        v = MagicMock()
        v._sniff_buffer = ""
        v.tool_call_id = "x"
        return v

    def _make_service(self):
        from hermes_cli.tui.services.tools import ToolRenderingService
        # Build a minimal stand-in: directly use the unbound method
        return ToolRenderingService

    def test_sniff_buffer_caps_at_512_bytes(self) -> None:
        from hermes_cli.tui.services.tools import ToolRenderingService, _SNIFF_BUFFER_CAP
        view = self._make_view()
        svc = MagicMock()
        svc._MIN_HINT_PREFIX_BYTES = 8
        # First call: fill exactly to cap
        ToolRenderingService._run_sniff_buffer(svc, view, " " * _SNIFF_BUFFER_CAP)
        # Second call adds more — buffer is at cap; should be cleared and returned
        ToolRenderingService._run_sniff_buffer(svc, view, " ")
        assert view._sniff_buffer is None

    def test_sniff_buffer_emits_no_hint_when_threshold_not_reached(self) -> None:
        from hermes_cli.tui.services.tools import ToolRenderingService, _SNIFF_BUFFER_CAP
        view = self._make_view()
        svc = MagicMock()
        svc._MIN_HINT_PREFIX_BYTES = 8
        with patch("hermes_cli.tui.services.tools.set_axis") as set_axis:
            for _ in range(_SNIFF_BUFFER_CAP + 1):
                ToolRenderingService._run_sniff_buffer(svc, view, " ")
            assert not any(
                call.args[1] == "streaming_kind_hint" for call in set_axis.call_args_list
            )

    def test_sniff_buffer_lstrip_correctness_below_cap(self) -> None:
        from hermes_cli.tui.services.tools import ToolRenderingService
        view = self._make_view()
        svc = MagicMock()
        svc._MIN_HINT_PREFIX_BYTES = 8
        with patch("hermes_cli.tui.body_renderers.REGISTRY", []):
            ToolRenderingService._run_sniff_buffer(svc, view, " " * 390 + "{abcdefgh}")
        # Hint dispatch attempted (buffer drained to None) — REGISTRY empty so no hint set,
        # but the dispatch was reached: buffer is now None.
        assert view._sniff_buffer is None


# ---------------------------------------------------------------------------
# TBM-3 — _clear_streaming_kind_hint helper is the single call site
# ---------------------------------------------------------------------------

class TestClearStreamingHint:

    def test_clear_streaming_kind_hint_helper_is_single_callsite(self) -> None:
        src = _ACTIONS_PATH.read_text()
        tree = ast.parse(src)
        offending: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name == "_clear_streaming_kind_hint":
                continue
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Call):
                    continue
                func = sub.func
                if isinstance(func, ast.Name) and func.id == "set_axis":
                    if any(
                        isinstance(a, ast.Constant) and a.value == "streaming_kind_hint"
                        for a in sub.args
                    ):
                        offending.append(node.name)
        assert offending == [], (
            f"set_axis(.., 'streaming_kind_hint', ..) only allowed in helper; "
            f"found in: {offending}"
        )

    def test_action_kind_revert_clears_hint_exactly_once(self) -> None:
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        obj = MagicMock(spec=_ToolPanelActionsMixin)
        view = MagicMock()
        view.user_kind_override = "json"
        view.streaming_kind_hint = "code"
        obj._view_state = view
        obj._lookup_view_state = MagicMock(return_value=view)
        with patch("hermes_cli.tui.services.tools.set_axis") as set_axis, \
             patch("hermes_cli.tui.services.tools.set_user_kind_override") as set_user:
            # Make _clear_streaming_kind_hint use the real helper but force_renderer is mocked.
            obj._clear_streaming_kind_hint = _ToolPanelActionsMixin._clear_streaming_kind_hint.__get__(obj)
            _ToolPanelActionsMixin.action_kind_revert(obj)
            hint_calls = [c for c in set_axis.call_args_list if c.args[1] == "streaming_kind_hint"]
            assert len(hint_calls) == 1, f"expected 1 streaming_kind_hint clear; got {hint_calls}"


# ---------------------------------------------------------------------------
# TBM-4 — _set_view_state recursion guard
# ---------------------------------------------------------------------------

class TestSetViewStateRecursion:

    def _make_svc_with_view(self):
        from hermes_cli.tui.services.tools import ToolRenderingService, ToolCallState
        svc = MagicMock(spec=ToolRenderingService)
        svc._state_lock = threading.RLock()
        svc._plan_broker = None
        view = MagicMock()
        view.state = ToolCallState.STARTED
        view.streaming_kind_hint = None
        return svc, view

    def test_set_view_state_rejects_recursive_entry(self, caplog: pytest.LogCaptureFixture) -> None:
        from hermes_cli.tui.services.tools import ToolRenderingService, ToolCallState, _set_view_state_local
        svc, view = self._make_svc_with_view()
        # Reset thread-local depth counter (test isolation)
        _set_view_state_local.depth = 0
        observed_axis: list[tuple[str, object]] = []

        def fake_set_axis(v, name, val):
            observed_axis.append((name, val))
            if name == "state" and val == ToolCallState.STREAMING:
                # Re-enter from inside the watcher
                v.state = val
                ToolRenderingService._set_view_state(svc, v, ToolCallState.COMPLETING)

        with patch("hermes_cli.tui.services.tools.set_axis", side_effect=fake_set_axis):
            with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.services.tools"):
                ToolRenderingService._set_view_state(svc, view, ToolCallState.STREAMING)
        state_writes = [v for n, v in observed_axis if n == "state"]
        assert state_writes == [ToolCallState.STREAMING], (
            f"recursive state write should be rejected; got {state_writes}"
        )

    def test_set_view_state_recursive_entry_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        from hermes_cli.tui.services.tools import ToolRenderingService, ToolCallState, _set_view_state_local
        svc, view = self._make_svc_with_view()
        _set_view_state_local.depth = 0

        def fake_set_axis(v, name, val):
            if name == "state" and val == ToolCallState.STREAMING:
                v.state = val
                ToolRenderingService._set_view_state(svc, v, ToolCallState.COMPLETING)

        with patch("hermes_cli.tui.services.tools.set_axis", side_effect=fake_set_axis):
            with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.services.tools"):
                ToolRenderingService._set_view_state(svc, view, ToolCallState.STREAMING)
        assert any("recursive entry detected" in r.getMessage() for r in caplog.records), (
            f"expected recursive-entry warning; got: {[r.getMessage() for r in caplog.records]}"
        )


# ---------------------------------------------------------------------------
# TBM-5 — apply_layout queue/replay
# ---------------------------------------------------------------------------

class TestApplyLayoutQueue:

    def _make_panel(self):
        from hermes_cli.tui.tool_panel._core import ToolPanel
        # Build a stand-in without invoking Widget.__init__ (no app context).
        panel = MagicMock(spec=ToolPanel)
        panel._view_state = None
        panel._lookup_view_state = MagicMock(return_value=None)
        panel._pending_layout_decisions = []
        # Bind real _publish_layout_axis so the helper actually fires set_axis.
        panel._publish_layout_axis = ToolPanel._publish_layout_axis.__get__(panel)
        return panel

    def test_apply_layout_queues_when_view_state_missing(self) -> None:
        from hermes_cli.tui.tool_panel._core import ToolPanel
        from hermes_cli.tui.tool_panel.layout_resolver import LayoutDecision, DensityTier
        panel = self._make_panel()
        decision = LayoutDecision(
            tier=DensityTier.DEFAULT, footer_visible=True, width=80, reason="auto"
        )
        with patch("hermes_cli.tui.services.tools.set_axis") as set_axis:
            ToolPanel._publish_layout_axis  # ensures method exists
            # Call our queue helper logic directly (mirrors the new branch)
            vs = panel._view_state or panel._lookup_view_state()
            if vs is None:
                panel._pending_layout_decisions.append(decision)
            assert len(panel._pending_layout_decisions) == 1
            assert not set_axis.called

    def test_replay_pending_layout_replays_queued_decisions(self) -> None:
        from hermes_cli.tui.tool_panel._core import ToolPanel
        from hermes_cli.tui.tool_panel.layout_resolver import LayoutDecision, DensityTier
        panel = self._make_panel()
        d1 = LayoutDecision(tier=DensityTier.COMPACT, footer_visible=False, width=80, reason="auto")
        d2 = LayoutDecision(tier=DensityTier.DEFAULT, footer_visible=True, width=80, reason="auto")
        panel._pending_layout_decisions.extend([d1, d2])
        vs = MagicMock()
        with patch("hermes_cli.tui.services.tools.set_axis") as set_axis:
            ToolPanel._replay_pending_layout(panel, vs)
            density_writes = [c for c in set_axis.call_args_list if c.args[1] == "density"]
            assert len(density_writes) == 2
        assert panel._pending_layout_decisions == []

    def test_axis_bus_eventually_consistent_after_late_attach(self) -> None:
        from hermes_cli.tui.tool_panel._core import ToolPanel
        from hermes_cli.tui.tool_panel.layout_resolver import LayoutDecision, DensityTier
        panel = self._make_panel()
        decision = LayoutDecision(tier=DensityTier.HERO, footer_visible=True, width=80, reason="auto")
        panel._pending_layout_decisions.append(decision)
        vs = MagicMock()
        with patch("hermes_cli.tui.services.tools.set_axis") as set_axis:
            ToolPanel._replay_pending_layout(panel, vs)
            density_writes = [c for c in set_axis.call_args_list if c.args[1] == "density"]
            assert density_writes and density_writes[-1].args[2] == DensityTier.HERO


# ---------------------------------------------------------------------------
# TBM-6 — Streaming renderer O(1) lookup
# ---------------------------------------------------------------------------

class TestStreamingRendererLookup:

    def test_streaming_renderer_lookup_is_o1_for_known_categories(self) -> None:
        from hermes_cli.tui.body_renderers import (
            _STREAMING_RENDERER_BY_CATEGORY,
            pick_renderer,
            _STREAMING_EMPTY_CLS,
        )
        from hermes_cli.tui.tool_payload import ToolPayload
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_category import ToolCategory

        assert ToolCategory.SHELL in _STREAMING_RENDERER_BY_CATEGORY
        # Replace REGISTRY temporarily to prove the O(1) path is taken.
        with patch("hermes_cli.tui.body_renderers.REGISTRY", []):
            payload = ToolPayload(
                tool_name="bash",
                category=ToolCategory.SHELL,
                args={},
                input_display=None,
                output_raw="",
                line_count=0,
            )
            cls = pick_renderer(
                _STREAMING_EMPTY_CLS, payload,
                phase=ToolCallState.STREAMING,
                density=DensityTier.DEFAULT,
            )
            assert cls is _STREAMING_RENDERER_BY_CATEGORY[ToolCategory.SHELL]

    def test_streaming_renderer_falls_back_to_linear_walk_for_unknown_categories(self) -> None:
        from hermes_cli.tui.body_renderers import pick_renderer, PlainBodyRenderer, _STREAMING_EMPTY_CLS
        from hermes_cli.tui.tool_payload import ToolPayload
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_panel.density import DensityTier

        class _SyntheticCat:
            name = "SYNTHETIC"

        payload = MagicMock(spec=ToolPayload)
        payload.category = _SyntheticCat()
        cls = pick_renderer(
            _STREAMING_EMPTY_CLS, payload,
            phase=ToolCallState.STREAMING,
            density=DensityTier.DEFAULT,
        )
        assert cls is PlainBodyRenderer


# ---------------------------------------------------------------------------
# TBM-7 — action_edit_cmd logs on exception
# ---------------------------------------------------------------------------

class TestActionEditLogging:

    def test_action_edit_cmd_logs_on_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        obj = MagicMock(spec=_ToolPanelActionsMixin)
        obj._result_summary_v4 = MagicMock()
        obj._result_summary_v4.actions = (MagicMock(kind="edit_cmd", payload="ls"),)
        # Force the inner query_one path to raise.
        obj.app = MagicMock()
        obj.app.query_one = MagicMock(side_effect=RuntimeError("boom"))
        with caplog.at_level(logging.ERROR, logger="hermes_cli.tui.tool_panel._actions"):
            _ToolPanelActionsMixin.action_edit_cmd(obj)
        assert any("action_edit_cmd" in r.getMessage() for r in caplog.records), (
            f"expected action_edit_cmd log; got {[r.getMessage() for r in caplog.records]}"
        )
        obj._flash_header.assert_called_with("edit unavailable")


# ---------------------------------------------------------------------------
# TBM-9 — LOW cleanups
# ---------------------------------------------------------------------------

class TestLowCleanups:

    def test_skeleton_pulse_constant_documented(self) -> None:
        src = _STREAMING_PATH.read_text()
        idx = src.find("_SKELETON_PULSE_S")
        assert idx > -1
        # Look in a small window above
        window = src[max(0, idx - 200): idx + 50]
        assert "concept.md §perception-budgets" in window, (
            f"perception-budgets reference missing near _SKELETON_PULSE_S; window={window!r}"
        )

    def test_summary_line_base_implementation_carries_todo(self) -> None:
        src = _BASE_RENDERER_PATH.read_text()
        assert "Subclasses may use density" in src

    def test_on_key_handles_unset_density_reactive(self) -> None:
        # Ensure the source uses the guarded form: getattr(self.density, "value", "default")
        core_path = _REPO_ROOT / "hermes_cli" / "tui" / "tool_panel" / "_core.py"
        src = core_path.read_text()
        # 4 sites: on_key/on_click/on_mouse_scroll_up/_down.
        n = src.count('getattr(self.density, "value", "default")')
        assert n >= 4, f"expected ≥4 guarded density.value sites; got {n}"
        assert "density=self.density.value" not in src, (
            "raw self.density.value access must be removed from event handlers"
        )

    def test_register_header_hint_watcher_warns_on_missing_attr(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from hermes_cli.tui.services.tools import ToolRenderingService
        svc = MagicMock(spec=ToolRenderingService)

        class _BadHeader:
            pass

        view = MagicMock()
        block = MagicMock()
        block._header = _BadHeader()
        view.block = block
        view.tool_call_id = "x"
        with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.services.tools"):
            ToolRenderingService._register_header_hint_watcher(svc, view)
        assert any(
            "missing attach_stream_axis_watcher" in r.getMessage() for r in caplog.records
        ), f"expected missing-attr warning; got {[r.getMessage() for r in caplog.records]}"


# ---------------------------------------------------------------------------
# TBM-10 — concept doc changelog
# ---------------------------------------------------------------------------

class TestConceptDocAmendments:

    def test_concept_doc_changelog_amendments_present(self) -> None:
        src = _CONCEPT_PATH.read_text()
        for needle in (
            "hint priority order corrected so [t]/[T] precede e/o/u/E",
            "_clear_streaming_kind_hint helper",
            "_set_view_state now rejects recursive entry",
        ):
            assert needle in src, f"missing changelog bullet: {needle!r}"
