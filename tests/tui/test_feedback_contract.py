"""FC-1..FC-4 — Feedback contract tests.

No Textual pilot. All tests use unit-level mocks.

Classes:
  TestFC1CopyActions      — 8 tests: empty-guard warning flashes on copy actions
  TestFC2CancellationRace — 6 tests: terminalize race debug log + panel flash
  TestFC3Preemption       — 4 tests: preempt debug log + would_flash helper
  TestFC4OtherActions     — 4 tests: retry success, open_url no-url, cycle_kind regression, meta-test
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_panel(
    copy_content: str = "",
    result_paths: list[str] | None = None,
    rs: Any = None,
    block_all_rich: Any = None,
    header_full_path: str | None = None,
    rs_is_error: bool = False,
) -> MagicMock:
    """Return a minimal ToolPanel mock wired up for _ToolPanelActionsMixin tests."""
    from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
    panel = MagicMock()
    panel.copy_content.return_value = copy_content
    panel._result_paths = result_paths or []
    panel._result_summary_v4 = rs
    panel._result_paths_for_action = _ToolPanelActionsMixin._result_paths_for_action.__get__(panel)

    # Restore real _flash_header so we can spy on it.
    flash_calls: list[tuple[str, ...]] = []

    def _flash(msg: str, tone: str = "success") -> None:
        flash_calls.append((msg, tone))

    panel._flash_header = _flash  # type: ignore[method-assign]
    panel._flash_calls = flash_calls  # type: ignore[attr-defined]

    # app stubs
    panel.app = MagicMock()
    panel.app._copy_text_with_hint = MagicMock()
    panel.app.notify = MagicMock()
    panel.app.feedback = MagicMock()
    panel.id = "test-panel-id"
    panel.is_mounted = True

    # block / header stubs
    block = MagicMock()
    block._all_rich = block_all_rich
    block._body = MagicMock()
    block._body.query_one.side_effect = Exception("no CopyableRichLog")
    header = MagicMock()
    header._full_path = header_full_path
    header._has_affordances = True
    block._header = header
    panel._block = block

    return panel


def _make_rs(
    *,
    stderr_tail: str = "",
    actions: list[Any] | None = None,
    artifacts: list[Any] | None = None,
    is_error: bool = False,
) -> MagicMock:
    rs = MagicMock()
    rs.stderr_tail = stderr_tail
    rs.actions = actions or []
    rs.artifacts = artifacts or []
    rs.is_error = is_error
    return rs


def _make_artifact(kind: str, path_or_url: str) -> MagicMock:
    a = MagicMock()
    a.kind = kind
    a.path_or_url = path_or_url
    return a


def _make_action(kind: str, payload: str = "") -> MagicMock:
    a = MagicMock()
    a.kind = kind
    a.payload = payload
    return a


# ---------------------------------------------------------------------------
# FC-1 — Copy empty-guard warning flashes
# ---------------------------------------------------------------------------


class TestFC1CopyActions:
    def test_copy_body_flashes_on_success(self) -> None:
        panel = _make_panel(copy_content="hello world")
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        _ToolPanelActionsMixin.action_copy_body(panel)  # type: ignore[arg-type]
        assert panel.app._copy_text_with_hint.called
        assert any("copied text" in msg for msg, _ in panel._flash_calls)

    def test_copy_body_flashes_nothing_when_empty(self) -> None:
        panel = _make_panel(copy_content="")
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        _ToolPanelActionsMixin.action_copy_body(panel)  # type: ignore[arg-type]
        assert not panel.app._copy_text_with_hint.called
        assert any("nothing to copy" in msg and tone == "warning"
                   for msg, tone in panel._flash_calls)

    def test_copy_err_flashes_on_success(self) -> None:
        rs = _make_rs(stderr_tail="some error text")
        panel = _make_panel(rs=rs)
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        _ToolPanelActionsMixin.action_copy_err(panel)  # type: ignore[arg-type]
        assert panel.app._copy_text_with_hint.called
        assert any("copied stderr" in msg for msg, _ in panel._flash_calls)

    def test_copy_err_flashes_nothing_when_no_payload(self) -> None:
        rs = _make_rs(stderr_tail="", actions=[])
        panel = _make_panel(rs=rs)
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        _ToolPanelActionsMixin.action_copy_err(panel)  # type: ignore[arg-type]
        assert not panel.app._copy_text_with_hint.called
        assert any("nothing to copy" in msg and tone == "warning"
                   for msg, tone in panel._flash_calls)

    def test_copy_paths_flashes_nothing_when_empty(self) -> None:
        rs = _make_rs(artifacts=[])
        panel = _make_panel(rs=rs, result_paths=[])
        panel._result_summary_v4 = rs
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        _ToolPanelActionsMixin.action_copy_paths(panel)  # type: ignore[arg-type]
        assert not panel.app._copy_text_with_hint.called
        assert any("nothing to copy" in msg and tone == "warning"
                   for msg, tone in panel._flash_calls)

    def test_copy_urls_flashes_nothing_when_empty(self) -> None:
        rs = _make_rs(artifacts=[_make_artifact("file", "/tmp/x.txt")])
        panel = _make_panel(rs=rs)
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        _ToolPanelActionsMixin.action_copy_urls(panel)  # type: ignore[arg-type]
        assert not panel.app._copy_text_with_hint.called
        assert any("nothing to copy" in msg and tone == "warning"
                   for msg, tone in panel._flash_calls)

    def test_copy_full_path_flashes_nothing_when_no_path(self) -> None:
        panel = _make_panel(header_full_path=None)
        panel._block._header._full_path = None
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        _ToolPanelActionsMixin.action_copy_full_path(panel)  # type: ignore[arg-type]
        assert not panel.app._copy_text_with_hint.called
        assert any("nothing to copy" in msg and tone == "warning"
                   for msg, tone in panel._flash_calls)

    def test_copy_html_flashes_nothing_when_no_rich(self) -> None:
        panel = _make_panel(block_all_rich=None)
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        _ToolPanelActionsMixin.action_copy_html(panel)  # type: ignore[arg-type]
        assert not panel.app._copy_text_with_hint.called
        assert any("nothing to copy" in msg and tone == "warning"
                   for msg, tone in panel._flash_calls)


# ---------------------------------------------------------------------------
# FC-2 — Cancellation race detection
# ---------------------------------------------------------------------------


class TestFC2CancellationRace:
    def _make_svc(self) -> Any:
        from hermes_cli.tui.services.tools import ToolRenderingService  # noqa: F401
        svc = MagicMock(spec=ToolRenderingService)
        svc._tool_views_by_id = {}
        svc._tool_views_by_gen_index = {}
        svc._open_tool_count = 0
        svc._agent_stack = []
        svc._turn_tool_calls = {}
        svc.app = MagicMock()
        svc.app._active_streaming_blocks = {}
        svc.app._streaming_tool_count = 0
        svc.app._active_tool_name = ""
        svc.app.agent_running = False
        svc.app.status_phase = None
        svc.app.planned_calls = []
        # Use real _panel_for_block so panel lookup works
        from hermes_cli.tui.services.tools import ToolRenderingService  # noqa: F401
        svc._panel_for_block = ToolRenderingService._panel_for_block.__get__(svc)
        svc._terminalize_tool_view = ToolRenderingService._terminalize_tool_view.__get__(svc)
        return svc

    def _make_terminal_view(self, state_value: str) -> MagicMock:
        from hermes_cli.tui.services.tools import ToolCallState
        view = MagicMock()
        view.state = ToolCallState(state_value)
        view.block = None
        view.gen_index = None
        view.tool_name = "test_tool"
        view.is_error = False
        return view

    def test_cancel_after_done_logs_debug(self) -> None:
        from hermes_cli.tui.services.tools import ToolCallState
        svc = self._make_svc()
        view = self._make_terminal_view("done")
        svc._tool_views_by_id["id1"] = view

        with patch("hermes_cli.tui.services.tools.logger") as mock_log:
            svc._terminalize_tool_view("id1", terminal_state=ToolCallState.CANCELLED)
            assert any(
                "terminalize race" in str(c) for c in mock_log.debug.call_args_list
            )

    def test_cancel_after_done_flashes_user(self) -> None:
        from hermes_cli.tui.services.tools import ToolCallState
        svc = self._make_svc()
        view = self._make_terminal_view("done")
        block = MagicMock()
        panel = MagicMock()
        panel.is_mounted = True
        panel._flash_header = MagicMock()
        block._tool_panel = panel
        view.block = block
        svc._tool_views_by_id["id1"] = view

        svc._terminalize_tool_view("id1", terminal_state=ToolCallState.CANCELLED)
        panel._flash_header.assert_called_once()
        msg, tone = panel._flash_header.call_args[0][0], panel._flash_header.call_args[1].get("tone", "")
        assert "cancel ignored" in msg
        assert "done" in msg
        assert tone == "warning"

    def test_cancel_after_error_flashes_user(self) -> None:
        from hermes_cli.tui.services.tools import ToolCallState
        svc = self._make_svc()
        view = self._make_terminal_view("error")
        block = MagicMock()
        panel = MagicMock()
        panel.is_mounted = True
        panel._flash_header = MagicMock()
        block._tool_panel = panel
        view.block = block
        svc._tool_views_by_id["id1"] = view

        svc._terminalize_tool_view("id1", terminal_state=ToolCallState.CANCELLED)
        panel._flash_header.assert_called_once()
        msg = panel._flash_header.call_args[0][0]
        assert "cancel ignored" in msg
        assert "error" in msg

    def test_done_after_cancelled_logs_no_flash(self) -> None:
        from hermes_cli.tui.services.tools import ToolCallState
        svc = self._make_svc()
        view = self._make_terminal_view("cancelled")
        block = MagicMock()
        panel = MagicMock()
        panel.is_mounted = True
        panel._flash_header = MagicMock()
        block._tool_panel = panel
        view.block = block
        svc._tool_views_by_id["id1"] = view

        with patch("hermes_cli.tui.services.tools.logger") as mock_log:
            svc._terminalize_tool_view("id1", terminal_state=ToolCallState.DONE)
            assert any("terminalize race" in str(c) for c in mock_log.debug.call_args_list)
        panel._flash_header.assert_not_called()

    def test_removed_state_logs_no_flash(self) -> None:
        from hermes_cli.tui.services.tools import ToolCallState
        svc = self._make_svc()
        view = self._make_terminal_view("removed")
        block = MagicMock()
        panel = MagicMock()
        panel.is_mounted = True
        panel._flash_header = MagicMock()
        block._tool_panel = panel
        view.block = block
        svc._tool_views_by_id["id1"] = view

        with patch("hermes_cli.tui.services.tools.logger") as mock_log:
            svc._terminalize_tool_view("id1", terminal_state=ToolCallState.CANCELLED)
            assert any("terminalize race" in str(c) for c in mock_log.debug.call_args_list)
        panel._flash_header.assert_not_called()

    def test_idempotent_recall_no_log(self) -> None:
        from hermes_cli.tui.services.tools import ToolCallState
        svc = self._make_svc()
        view = self._make_terminal_view("done")
        svc._tool_views_by_id["id1"] = view

        with patch("hermes_cli.tui.services.tools.logger") as mock_log:
            svc._terminalize_tool_view("id1", terminal_state=ToolCallState.DONE)
            assert all("terminalize race" not in str(c) for c in mock_log.debug.call_args_list)


# ---------------------------------------------------------------------------
# FC-3 — Flash preemption telemetry + would_flash
# ---------------------------------------------------------------------------


class _FakeCancelToken:
    def stop(self) -> None:
        pass


class _FakeScheduler:
    def after(self, delay: float, cb: Any) -> _FakeCancelToken:
        return _FakeCancelToken()


class _FakeAdapter:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def apply(self, state: Any) -> None:
        self.calls.append(state.message)

    def restore(self) -> None:
        pass


def _make_feedback_svc() -> Any:
    from hermes_cli.tui.services.feedback import FeedbackService
    svc = FeedbackService(_FakeScheduler())
    adapter = _FakeAdapter()
    svc.register_channel("ch1", adapter)
    return svc, adapter


class TestFC3Preemption:
    def test_preempted_flash_logs_debug(self) -> None:
        from hermes_cli.tui.services.feedback import CRITICAL, NORMAL
        svc, _ = _make_feedback_svc()
        svc.flash("ch1", "high message", priority=CRITICAL)

        with patch("hermes_cli.tui.services.feedback._log") as mock_log:
            svc.flash("ch1", "low message", priority=NORMAL)
            assert mock_log.debug.called
            args = str(mock_log.debug.call_args_list)
            assert "preempted" in args
            assert "low message" in args

    def test_would_flash_returns_true_when_channel_free(self) -> None:
        from hermes_cli.tui.services.feedback import NORMAL
        svc, _ = _make_feedback_svc()
        assert svc.would_flash("ch1", NORMAL) is True

    def test_would_flash_returns_false_when_busy_higher_priority(self) -> None:
        from hermes_cli.tui.services.feedback import CRITICAL, NORMAL
        svc, _ = _make_feedback_svc()
        svc.flash("ch1", "high", priority=CRITICAL)
        assert svc.would_flash("ch1", NORMAL) is False

    def test_bell_on_preempt_disabled_by_default(self) -> None:
        """Default config must not ring bell on preempt."""
        from hermes_cli.config import DEFAULT_CONFIG
        display = DEFAULT_CONFIG.get("display", {})
        feedback_cfg = display.get("feedback", {})
        assert feedback_cfg.get("bell_on_preempt", None) is False


# ---------------------------------------------------------------------------
# FC-4 — Partial flash gaps: retry success, open_url no-url, regression
# ---------------------------------------------------------------------------


class TestFC4OtherActions:
    def test_retry_success_flashes_confirmation(self) -> None:
        rs = _make_rs(is_error=True)
        panel = _make_panel(rs=rs)
        panel._result_summary_v4 = rs
        panel.app._svc_commands = MagicMock()
        panel.app._svc_commands.initiate_retry.return_value = None

        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        _ToolPanelActionsMixin.action_retry(panel)  # type: ignore[arg-type]

        assert any("retrying" in msg for msg, _ in panel._flash_calls)

    def test_open_url_no_url_found_flashes_warning(self) -> None:
        rs = _make_rs(actions=[], artifacts=[_make_artifact("file", "/tmp/x.txt")])
        panel = _make_panel(rs=rs)
        panel._result_summary_v4 = rs

        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        _ToolPanelActionsMixin.action_open_url(panel)  # type: ignore[arg-type]

        assert any("no URL" in msg and tone == "warning"
                   for msg, tone in panel._flash_calls)

    def test_cycle_kind_flash_regression(self) -> None:
        """action_cycle_kind must flash with 'render as:' prefix — regression guard."""
        panel = _make_panel()
        from hermes_cli.tui.services.tools import ToolCallState
        from hermes_cli.tui.tool_payload import ResultKind

        view = MagicMock()
        view.state = ToolCallState.DONE
        view.user_kind_override = None
        view.kind = None
        view.density = MagicMock()
        panel._view_state = view
        panel._lookup_view_state = MagicMock(return_value=view)
        panel.force_renderer = MagicMock()

        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin
        _ToolPanelActionsMixin.action_cycle_kind(panel)  # type: ignore[arg-type]

        assert any("render as:" in msg for msg, _ in panel._flash_calls)

    def test_meta_state_mutating_actions_flash(self) -> None:
        """Every action_* method in _ToolPanelActionsMixin must contain a flash call
        unless it is in the explicit exclusion set."""
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin

        _ACCEPTED_FEEDBACK_CALLS = {
            "_flash_header", "_flash_hint", "notify", "flash_success",
        }
        _NO_FLASH_ACTIONS = {
            "action_scroll_body_down", "action_scroll_body_up",
            "action_scroll_body_page_down", "action_scroll_body_page_up",
            "action_scroll_body_top", "action_scroll_body_bottom",
            "action_show_help",
            "action_dismiss_error_banner",
            "action_show_context_menu",
            "action_omission_expand",
            "action_omission_collapse",
            "action_expand_lines",
            "action_expand_all_lines",
        }

        violations: list[str] = []
        for name, method in inspect.getmembers(_ToolPanelActionsMixin, predicate=inspect.isfunction):
            if not name.startswith("action_"):
                continue
            if name in _NO_FLASH_ACTIONS:
                continue
            src = inspect.getsource(method)
            tree = ast.parse(textwrap.dedent(src))
            # Collect all Name and Attribute calls in the AST
            call_names: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute):
                        call_names.add(node.func.attr)
                    elif isinstance(node.func, ast.Name):
                        call_names.add(node.func.id)
            if not call_names.intersection(_ACCEPTED_FEEDBACK_CALLS):
                violations.append(name)

        assert not violations, (
            f"action_* methods missing a feedback call: {violations}"
        )
