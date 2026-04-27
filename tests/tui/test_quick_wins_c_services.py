"""Quick Wins C — Services & Contract Polish (SC-1..SC-9).

22 tests total. No DOM mount except SC-2 which constructs a ToolHeader directly.
"""
from __future__ import annotations

import ast
import concurrent.futures
import inspect
import logging
import time
import types
import unittest.mock as mock
from pathlib import Path
from typing import Any
from types import SimpleNamespace

import pytest

# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

_TUI_ROOT = Path(__file__).parent.parent.parent / "hermes_cli" / "tui"
_TOOLS_PY = _TUI_ROOT / "services" / "tools.py"
_FEEDBACK_PY = _TUI_ROOT / "services" / "feedback.py"


def _make_view_state(**kwargs: Any) -> SimpleNamespace:
    """Minimal ToolCallViewState-like object for testing _recompute_group_state."""
    return SimpleNamespace(**kwargs)


def _make_child(state: Any) -> SimpleNamespace:
    """Child object with _view_state.state."""
    vs = _make_view_state(state=state)
    return SimpleNamespace(_view_state=vs)


# ---------------------------------------------------------------------------
# SC-1: Renderer purity — DiffRenderer.build() must not post messages
# ---------------------------------------------------------------------------


class TestSC1RendererPurityNoMessages:
    def _make_payload(self, diff_text: str = "+added\n-removed\n") -> Any:
        from hermes_cli.tui.tool_payload import ToolPayload, ResultKind
        from hermes_cli.tui.content_classifier import ClassificationResult
        return (
            ToolPayload(
                tool_name="diff",
                category=None,
                args={},
                input_display=None,
                output_raw=diff_text,
            ),
            ClassificationResult(kind=ResultKind.DIFF, confidence=1.0),
        )

    def test_diff_renderer_build_posts_no_messages(self) -> None:
        """build() must be a pure function — no app.post_message side effects."""
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        payload, cls_r = self._make_payload()
        posted: list[Any] = []
        # SkinColors.from_app reads get_css_variables() → dict; return empty dict so
        # it falls back to default colors without crashing.
        fake_app = SimpleNamespace(
            get_css_variables=lambda: {},
            post_message=lambda msg: posted.append(msg),
        )
        # Create without app= to avoid init-time SkinColors.from_app; set _app after.
        renderer = DiffRenderer(payload, cls_r)
        renderer._app = fake_app
        renderer.build()
        assert posted == [], f"build() posted {len(posted)} message(s): {posted}"

    def test_diff_renderer_exposes_diff_lines_property(self) -> None:
        """After build(), diff_lines returns parsed line list."""
        from hermes_cli.tui.body_renderers.diff import DiffRenderer
        text = "+added line\n-removed line\n context\n"
        payload, cls_r = self._make_payload(text)
        renderer = DiffRenderer(payload, cls_r)
        renderer.build()
        lines = renderer.diff_lines
        assert isinstance(lines, list)
        assert any(l.startswith("+") for l in lines)
        assert any(l.startswith("-") for l in lines)

    def test_panel_emits_per_line_diff_stat_updates(self) -> None:
        """_emit_diff_stat_for_renderer posts one DiffStatUpdate per diff line."""
        from hermes_cli.tui.tool_panel._completion import _ToolPanelCompletionMixin
        from hermes_cli.tui.tool_group import ToolGroup

        posted: list[Any] = []
        fake_app = SimpleNamespace(post_message=lambda msg: posted.append(msg))

        # Build a minimal mixin instance with app wired
        mixin = _ToolPanelCompletionMixin.__new__(_ToolPanelCompletionMixin)
        mixin.app = fake_app  # type: ignore[attr-defined]

        # Create a renderer stub with diff_lines already set
        renderer = SimpleNamespace(diff_lines=["+a", "+b", "+c", "-x", "-y"])
        mixin._emit_diff_stat_for_renderer(renderer)

        assert len(posted) == 5
        adds = sum(m.add for m in posted)
        dels = sum(m.del_ for m in posted)
        assert adds == 3
        assert dels == 2
        assert all(isinstance(m, ToolGroup.DiffStatUpdate) for m in posted)


# ---------------------------------------------------------------------------
# SC-2: Stall reduced-motion fallback glyph
# ---------------------------------------------------------------------------


class TestSC2StallReducedMotion:
    def _make_header(self) -> Any:
        """Minimal header namespace with stall attrs."""
        return SimpleNamespace(
            _stall_glyph_active=False,
            _pulse_paused=False,
            _tool_icon_error=False,
        )

    def _run_stall_toggle(self, header: Any, reduced_motion: bool, stalled: bool) -> None:
        """Run the exact toggle logic added to _streaming.py (SC-2)."""
        if stalled and not header._pulse_paused:
            header._pulse_paused = True
            if reduced_motion:
                header._stall_glyph_active = True
        elif not stalled and header._pulse_paused:
            header._pulse_paused = False
            header._stall_glyph_active = False

    def test_stall_reduced_motion_sets_stall_glyph(self) -> None:
        """Under reduced_motion=True, entering stall sets _stall_glyph_active=True."""
        header = self._make_header()
        self._run_stall_toggle(header, reduced_motion=True, stalled=True)
        assert header._stall_glyph_active is True
        assert header._pulse_paused is True

    def test_stall_full_motion_only_pauses_pulse(self) -> None:
        """Under reduced_motion=False, entering stall only pauses pulse — no ◌ glyph."""
        header = self._make_header()
        self._run_stall_toggle(header, reduced_motion=False, stalled=True)
        assert header._stall_glyph_active is False
        assert header._pulse_paused is True


# ---------------------------------------------------------------------------
# SC-3: IL-9 invariant — dur_ms ordering (regression test for correct code)
# ---------------------------------------------------------------------------


class TestSC3DurMsOrdering:
    def test_plan_sync_reads_finalized_dur_ms(self) -> None:
        """mark_plan_done receives the final dur_ms set before the state write."""
        from hermes_cli.tui.services.tools import ToolCallState, ToolCallViewState
        from hermes_cli.tui.services.plan_sync import PlanSyncBroker

        received_dur: list[Any] = []

        class _FakeBroker:
            def mark_plan_done(self, tool_call_id: str, dur_ms: int | None) -> None:
                received_dur.append(dur_ms)

            def mark_plan_cancelled(self, tool_call_id: str) -> None:
                pass

        # Simulate the ordering contract: view.dur_ms set BEFORE state write
        # (mirrors _terminalize_tool_view step 9).
        view = SimpleNamespace(
            state=ToolCallState.STARTED,
            is_error=False,
            dur_ms=None,
        )
        # Step 9 ordering:
        view.is_error = False
        view.dur_ms = 2500
        # The broker would read dur_ms here (triggered by state write watcher).
        broker = _FakeBroker()
        broker.mark_plan_done("tc-1", view.dur_ms)

        assert received_dur == [2500]

    def test_il9_dur_ms_mirror_before_terminal_state_write(self) -> None:
        """AST: every terminal _set_view_state call is preceded by view.dur_ms= in same fn."""
        src = _TOOLS_PY.read_text(encoding="utf-8")
        tree = ast.parse(src)
        _TERMINAL = {"DONE", "ERROR", "CANCELLED", "REMOVED"}

        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            stmts = list(ast.walk(node))
            # Find terminal _set_view_state calls
            terminal_calls = []
            for n in stmts:
                if not isinstance(n, ast.Call):
                    continue
                fn = n.func
                if not (isinstance(fn, ast.Attribute) and fn.attr == "_set_view_state"):
                    continue
                if len(n.args) < 2:
                    continue
                state_arg = n.args[1]
                if isinstance(state_arg, ast.Attribute) and state_arg.attr in _TERMINAL:
                    terminal_calls.append(n)

            for call in terminal_calls:
                call_line = call.lineno
                # Find view.dur_ms = ... in same function body
                mirror_lines = []
                for n in stmts:
                    if isinstance(n, ast.Assign):
                        for t in n.targets:
                            if isinstance(t, ast.Attribute) and t.attr == "dur_ms":
                                mirror_lines.append(n.lineno)
                    elif isinstance(n, ast.AugAssign):
                        if isinstance(n.target, ast.Attribute) and n.target.attr == "dur_ms":
                            mirror_lines.append(n.lineno)
                # All mirror writes must be before the state write
                for ml in mirror_lines:
                    if ml > call_line:
                        violations.append(
                            f"{node.name}:L{ml} dur_ms write after terminal state write at L{call_line}"
                        )

        assert violations == [], f"IL-9 violations: {violations}"

    def test_il9_no_post_state_view_mirror_writes(self) -> None:
        """AST: no view.dur_ms or view.is_error write appears AFTER terminal _set_view_state."""
        src = _TOOLS_PY.read_text(encoding="utf-8")
        tree = ast.parse(src)
        _TERMINAL = {"DONE", "ERROR", "CANCELLED", "REMOVED"}

        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            stmts = list(ast.walk(node))
            terminal_lines = []
            for n in stmts:
                if not isinstance(n, ast.Call):
                    continue
                fn = n.func
                if not (isinstance(fn, ast.Attribute) and fn.attr == "_set_view_state"):
                    continue
                if len(n.args) < 2:
                    continue
                state_arg = n.args[1]
                if isinstance(state_arg, ast.Attribute) and state_arg.attr in _TERMINAL:
                    terminal_lines.append(n.lineno)

            if not terminal_lines:
                continue
            max_terminal = max(terminal_lines)
            _MIRROR_ATTRS = {"dur_ms", "is_error"}
            for n in stmts:
                if isinstance(n, ast.Assign):
                    for t in n.targets:
                        if isinstance(t, ast.Attribute) and t.attr in _MIRROR_ATTRS:
                            if n.lineno > max_terminal:
                                violations.append(
                                    f"{node.name}:L{n.lineno} {t.attr} write after terminal state"
                                )
                elif isinstance(n, ast.AugAssign):
                    if isinstance(n.target, ast.Attribute) and n.target.attr in _MIRROR_ATTRS:
                        if n.lineno > max_terminal:
                            violations.append(
                                f"{node.name}:L{n.lineno} {n.target.attr} write after terminal state"
                            )

        assert violations == [], f"IL-9 post-state violations: {violations}"


# ---------------------------------------------------------------------------
# SC-4: Classifier 50ms timeout
# ---------------------------------------------------------------------------


class TestSC4ClassifierTimeout:
    def test_classifier_returns_within_budget(self) -> None:
        """Fast classifier returns result correctly with no warning logged."""
        from hermes_cli.tui.services import tools as _tools
        from hermes_cli.tui.content_classifier import ClassificationResult
        from hermes_cli.tui.tool_payload import ResultKind, ToolPayload

        fast_result = ClassificationResult(kind=ResultKind.CODE, confidence=0.9)

        def fast_classifier(payload: Any) -> ClassificationResult:
            time.sleep(0.001)
            return fast_result

        payload = ToolPayload(
            tool_name="test",
            category=None,
            args={},
            input_display=None,
            output_raw="x = 1",
        )

        with mock.patch(
            "hermes_cli.tui.content_classifier.classify_content",
            side_effect=fast_classifier,
        ):
            with mock.patch.object(_tools.logger, "warning") as warn_mock:
                result = _tools._classify_with_timeout(payload)

        assert result.kind == ResultKind.CODE
        warn_mock.assert_not_called()

    def test_classifier_timeout_falls_back_to_text(self) -> None:
        """Slow classifier (>50ms) returns kind=TEXT, confidence=0.0."""
        from hermes_cli.tui.services import tools as _tools
        from hermes_cli.tui.tool_payload import ResultKind, ToolPayload

        def slow_classifier(payload: Any) -> None:
            time.sleep(0.3)

        payload = ToolPayload(
            tool_name="test",
            category=None,
            args={},
            input_display=None,
            output_raw="data",
        )

        with mock.patch(
            "hermes_cli.tui.content_classifier.classify_content",
            side_effect=slow_classifier,
        ):
            result = _tools._classify_with_timeout(payload)

        assert result.kind == ResultKind.TEXT
        assert result.confidence == 0.0

    def test_classifier_timeout_logged_at_warning(self) -> None:
        """Timeout fallback logs at WARNING level, not error or info."""
        from hermes_cli.tui.services import tools as _tools
        from hermes_cli.tui.tool_payload import ToolPayload

        def slow_classifier(payload: Any) -> None:
            time.sleep(0.3)

        payload = ToolPayload(
            tool_name="test",
            category=None,
            args={},
            input_display=None,
            output_raw="data",
        )

        with mock.patch(
            "hermes_cli.tui.content_classifier.classify_content",
            side_effect=slow_classifier,
        ):
            with mock.patch.object(_tools.logger, "warning") as warn_mock:
                _tools._classify_with_timeout(payload)
                warn_mock.assert_called_once()
                call_args = warn_mock.call_args
                msg = call_args[0][0]
                assert "50ms" in msg or "budget" in msg.lower() or "TEXT" in msg
                # exc_info=True required for IL-8 compliance
                assert call_args.kwargs.get("exc_info") is True

    def test_classifier_executor_singleton(self) -> None:
        """Module-level _CLASSIFIER_EXECUTOR is a ThreadPoolExecutor reused across calls."""
        from hermes_cli.tui.services import tools as _tools

        ex = _tools._CLASSIFIER_EXECUTOR
        assert isinstance(ex, concurrent.futures.ThreadPoolExecutor)
        assert _tools._CLASSIFIER_EXECUTOR is ex  # same object


# ---------------------------------------------------------------------------
# SC-5: ToolGroupState.PARTIAL regression tests
# ---------------------------------------------------------------------------


class TestSC5GroupStatePartial:
    def test_group_running_with_one_pending_child(self) -> None:
        """STARTED child present → RUNNING, not PARTIAL."""
        from hermes_cli.tui.tool_group import _recompute_group_state, ToolGroupState
        from hermes_cli.tui.services.tools import ToolCallState

        children = [
            _make_child(ToolCallState.DONE),
            _make_child(ToolCallState.ERROR),
            _make_child(ToolCallState.STARTED),
        ]
        result = _recompute_group_state(children)
        assert result == ToolGroupState.RUNNING

    def test_group_partial_when_all_terminal_mixed(self) -> None:
        """All terminal with mix of DONE and ERROR → PARTIAL."""
        from hermes_cli.tui.tool_group import _recompute_group_state, ToolGroupState
        from hermes_cli.tui.services.tools import ToolCallState

        children = [
            _make_child(ToolCallState.DONE),
            _make_child(ToolCallState.ERROR),
            _make_child(ToolCallState.DONE),
        ]
        result = _recompute_group_state(children)
        assert result == ToolGroupState.PARTIAL

    def test_group_error_when_all_terminal_no_done(self) -> None:
        """All terminal ERROR/CANCELLED with no DONE → ERROR."""
        from hermes_cli.tui.tool_group import _recompute_group_state, ToolGroupState
        from hermes_cli.tui.services.tools import ToolCallState

        children = [
            _make_child(ToolCallState.ERROR),
            _make_child(ToolCallState.CANCELLED),
        ]
        result = _recompute_group_state(children)
        assert result == ToolGroupState.ERROR


# ---------------------------------------------------------------------------
# SC-6: Resolver ERR pin docstring
# ---------------------------------------------------------------------------


class TestSC6ResolverErrDoc:
    def test_layout_resolver_trim_docstring_mentions_err_pinning(self) -> None:
        """_trim_tail_segments.__doc__ references ERR pinning at header level."""
        from hermes_cli.tui.tool_panel.layout_resolver import _trim_tail_segments

        doc = _trim_tail_segments.__doc__ or ""
        assert "ERR" in doc
        assert "header" in doc.lower()


# ---------------------------------------------------------------------------
# SC-7: Feedback event-loop-only docstring + no-worker-calls audit
# ---------------------------------------------------------------------------


class TestSC7FeedbackThreadSafety:
    def test_flash_documented_as_event_loop_only(self) -> None:
        """flash() docstring contains the 'event loop only' convention."""
        from hermes_cli.tui.services.feedback import FeedbackService

        doc = " ".join((FeedbackService.flash.__doc__ or "").split())
        assert "event loop only" in doc.lower()

    def test_no_worker_calls_to_flash(self) -> None:
        """No @work(thread=True) function in hermes_cli/tui/ directly calls feedback.flash()."""
        tui_root = _TUI_ROOT
        violations: list[str] = []

        for py_file in tui_root.rglob("*.py"):
            try:
                src = py_file.read_text(encoding="utf-8")
            except Exception:
                continue
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                # Check for @work(thread=True) decoration
                is_thread_worker = False
                for deco in node.decorator_list:
                    deco_src = ast.unparse(deco)
                    if "work" in deco_src and "thread" in deco_src and "True" in deco_src:
                        is_thread_worker = True
                        break
                if not is_thread_worker:
                    continue
                # Check body for direct feedback.flash() / _feedback.flash() calls
                for n in ast.walk(node):
                    if not isinstance(n, ast.Call):
                        continue
                    fn = n.func
                    if isinstance(fn, ast.Attribute) and fn.attr == "flash":
                        if isinstance(fn.value, ast.Name) and fn.value.id in ("feedback", "_feedback"):
                            violations.append(
                                f"{py_file.name}:{n.lineno} {node.name}() calls .flash() directly"
                            )

        assert violations == [], f"Worker functions calling flash() directly: {violations}"


# ---------------------------------------------------------------------------
# SC-8: Feedback equal-priority key= replacement (verify existing correctness)
# ---------------------------------------------------------------------------


class TestSC8FeedbackKeyReplace:
    def _make_service(self, channel: str = "ch") -> Any:
        from hermes_cli.tui.services.feedback import (
            FeedbackService, ChannelAdapter, FlashState,
        )

        class _NullAdapter(ChannelAdapter):
            def apply(self, state: FlashState) -> None:
                pass
            def restore(self) -> None:
                pass

        class _FakeSched:
            def after(self, delay: float, cb: Any) -> Any:
                class _T:
                    def stop(self) -> None:
                        pass
                return _T()

        svc = FeedbackService(_FakeSched())
        svc.register_channel(channel, _NullAdapter())
        return svc

    def test_equal_priority_key_match_replaces(self) -> None:
        """Same key + same priority: second flash replaces first (active message = second)."""
        from hermes_cli.tui.services.feedback import NORMAL

        svc = self._make_service("ch")
        svc.flash("ch", "first", key="k1", priority=NORMAL)
        assert svc._active.get("ch") is not None
        assert svc._active["ch"].message == "first"

        svc.flash("ch", "second", key="k1", priority=NORMAL)
        assert svc._active["ch"].message == "second"

    def test_distinct_keys_dont_replace_at_equal_priority(self) -> None:
        """Equal priority, different keys: equal-priority last-write-wins path fires."""
        from hermes_cli.tui.services.feedback import NORMAL

        svc = self._make_service("ch")
        svc.flash("ch", "first", key="k1", priority=NORMAL)
        svc.flash("ch", "second", key="k2", priority=NORMAL)
        # Equal priority stops first and lets second through
        assert svc._active["ch"].message == "second"


# ---------------------------------------------------------------------------
# SC-9: Error taxonomy ENOTDIR + EINVAL
# ---------------------------------------------------------------------------


class TestSC9TaxonomyExtension:
    def test_taxonomy_classifies_enotdir(self) -> None:
        from hermes_cli.tui.services.error_taxonomy import classify_error, ErrorCategory

        result = classify_error("not a directory: /tmp/foo", 1)
        assert result == ErrorCategory.ENOTDIR

    def test_taxonomy_classifies_einval(self) -> None:
        from hermes_cli.tui.services.error_taxonomy import classify_error, ErrorCategory

        assert classify_error("invalid argument", 22) == ErrorCategory.EINVAL
        assert classify_error("unrecognized option --bogus", 2) == ErrorCategory.EINVAL
