"""PG-1: PlanSyncBroker — mirrors ToolCallViewState transitions to PlannedCall rows."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from hermes_cli.tui.services.tools import ToolCallState, ToolCallViewState

if TYPE_CHECKING:
    from hermes_cli.tui.services.tools import ToolRenderingService

_log = logging.getLogger(__name__)


class PlanSyncBroker:
    """Mirrors view-state transitions to plan-row state.

    Receives on_view_state() from _set_view_state (the single choke-point).
    Calls mark_plan_* on the service.  Idempotency is enforced by each
    mark_plan_* guard (PENDING/RUNNING checks).
    """

    def __init__(self, svc: "ToolRenderingService") -> None:
        self._svc = svc

    def on_view_state(
        self,
        view: ToolCallViewState,
        old: ToolCallState,
        new: ToolCallState,
    ) -> None:
        tid = view.tool_call_id
        if not tid:
            return
        match new:
            case ToolCallState.STARTED | ToolCallState.STREAMING:
                self._svc.mark_plan_running(tid)
            case ToolCallState.DONE:
                self._svc.mark_plan_done(tid, is_error=False, dur_ms=view.dur_ms or 0)
            case ToolCallState.ERROR:
                self._svc.mark_plan_done(tid, is_error=True, dur_ms=view.dur_ms or 0)
            case ToolCallState.CANCELLED:
                self._svc.mark_plan_cancelled(tid)
            case _:
                pass  # GENERATED, COMPLETING, REMOVED: no plan update
