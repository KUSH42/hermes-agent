"""plan_types.py — Data model for PlanPanel (R1).

PlannedCall is immutable; state transitions replace the dataclass instance
inside a new list assigned to app.planned_calls (Textual reactive equality
requires a new list object to fire watchers).

Import from here, not from _app_tool_rendering.py, to avoid circular imports.
"""
from __future__ import annotations

import time as _time
from dataclasses import dataclass
from enum import auto
from typing import Optional

try:
    from enum import StrEnum
except ImportError:
    # Python < 3.11 fallback
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        pass


class PlanState(StrEnum):
    """State of a planned tool call."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class PlannedCall:
    """Immutable snapshot of a planned tool call.

    State transitions are done by replacing the instance in the list and
    re-assigning app.planned_calls.
    """

    tool_call_id: str
    tool_name: str
    label: str
    category: str
    args_preview: str                       # <= 60 chars
    state: PlanState
    started_at: Optional[float]             # monotonic; None while PENDING
    ended_at: Optional[float]               # monotonic; None until DONE/ERROR
    parent_tool_call_id: Optional[str]      # Phase 4 nesting; Phase 1 always None
    depth: int                              # 0 = top-level; Phase 1 always 0

    def as_running(self) -> "PlannedCall":
        """Return a new instance in RUNNING state."""
        return PlannedCall(
            tool_call_id=self.tool_call_id,
            tool_name=self.tool_name,
            label=self.label,
            category=self.category,
            args_preview=self.args_preview,
            state=PlanState.RUNNING,
            started_at=_time.monotonic(),
            ended_at=self.ended_at,
            parent_tool_call_id=self.parent_tool_call_id,
            depth=self.depth,
        )

    def as_done(self, is_error: bool = False) -> "PlannedCall":
        """Return a new instance in DONE or ERROR state."""
        return PlannedCall(
            tool_call_id=self.tool_call_id,
            tool_name=self.tool_name,
            label=self.label,
            category=self.category,
            args_preview=self.args_preview,
            state=PlanState.ERROR if is_error else PlanState.DONE,
            started_at=self.started_at,
            ended_at=_time.monotonic(),
            parent_tool_call_id=self.parent_tool_call_id,
            depth=self.depth,
        )
