"""ChildPanel — compact-mode ToolPanel for children of SubAgentPanel."""
from __future__ import annotations

import time as _time
from typing import Any

from textual.binding import Binding

from hermes_cli.tui.tool_panel import ToolPanel


class ChildPanel(ToolPanel):
    BINDINGS = [
        *ToolPanel.BINDINGS,
        Binding("space", "toggle_compact", show=False, priority=True),
        Binding("enter", "toggle_collapse", show=False, priority=True),
    ]

    def __init__(self, block: Any, tool_name: str = "", depth: int = 1,
                 parent_subagent: Any = None, **kwargs: Any) -> None:
        super().__init__(block, tool_name=tool_name, **kwargs)
        self._compact_mode: bool = True
        self._depth: int = depth
        self._parent_subagent: Any = parent_subagent
        self._start_time: float = _time.monotonic()
        self.add_class("--compact")
        if depth >= 1:
            self.add_class(f"--depth-{min(depth, 3)}")

    @property
    def _tool_header(self) -> Any:
        """The inner ToolHeader — used by SubAgentPanel.add_child_panel."""
        return self._block._header

    def set_compact(self, value: bool) -> None:
        if value == self._compact_mode:
            return
        self._compact_mode = value
        if value:
            self.add_class("--compact")
        else:
            self.remove_class("--compact")

    def action_toggle_compact(self) -> None:
        self.set_compact(not self._compact_mode)

    def action_toggle_collapse(self) -> None:
        self.collapsed = not self.collapsed

    def watch_collapsed(self, old: Any, new: Any) -> None:
        from textual.css.query import NoMatches
        try:
            self.query_one(".tool-body-container").display = not new
        except NoMatches:
            pass

    def set_result_summary(self, summary: Any) -> None:
        super().set_result_summary(summary)
        dur_ms = int((_time.monotonic() - self._start_time) * 1000)
        if self._parent_subagent is not None:
            self._parent_subagent._notify_child_complete(
                getattr(self._block, "_tool_call_id", ""),
                getattr(summary, "is_error", False),
                dur_ms,
            )
        if getattr(summary, "is_error", False) and self._compact_mode:
            self.set_compact(False)

    def set_result_summary_v4(self, summary: Any) -> None:
        self.set_result_summary(summary)
