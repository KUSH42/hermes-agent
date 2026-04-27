"""ChildPanel — compact-mode ToolPanel for children of SubAgentPanel."""
from __future__ import annotations

import time as _time
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from ._core import ToolPanel
from ._footer import BodyPane, FooterPane


class ChildPanel(ToolPanel):
    BINDINGS = [
        *ToolPanel.BINDINGS,
        Binding("alt+c", "toggle_compact", show=False, priority=True),
        Binding("enter", "toggle_collapse", show=False, priority=True),
    ]

    def __init__(self, block: Any, tool_name: str = "", depth: int = 1,
                 parent_subagent: Any = None, **kwargs: Any) -> None:
        super().__init__(block, tool_name=tool_name, **kwargs)
        self._compact_mode: bool = True
        self._user_touched_compact: bool = False
        self._depth: int = depth
        self._parent_subagent: Any = parent_subagent
        self._start_time: float = _time.monotonic()
        self.add_class("--compact")
        if depth >= 1:
            self.add_class(f"--depth-{min(depth, 3)}")

    def compose(self) -> ComposeResult:
        self._body_pane = BodyPane(self._block, category=self._category)
        self._footer_pane = FooterPane()
        self._hint_row = Static("", classes="--focus-hint")
        yield self._body_pane
        yield self._footer_pane
        yield self._hint_row

    def on_mount(self) -> None:
        super().on_mount()
        header = getattr(self._block, "_header", None)
        if header is not None:
            header._is_child = True
            header.refresh()
        from hermes_cli.tui.sub_agent_panel import SubAgentPanel
        if isinstance(self._parent_subagent, SubAgentPanel):
            self.watch(self._parent_subagent, "density_tier", self._on_parent_density_change)
            self._on_parent_density_change(self._parent_subagent.density_tier)

    @property
    def _tool_header(self) -> Any:
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
        self._user_touched_compact = True
        self.set_compact(not self._compact_mode)

    def _on_parent_density_change(self, tier: "Any") -> None:
        from hermes_cli.tui.tool_panel.density import DensityTier
        clamp = tier if tier != DensityTier.DEFAULT else None
        self._parent_clamp_tier = clamp
        if self._result_summary_v4 is not None:  # type: ignore[attr-defined]
            self._apply_complete_auto_collapse()  # type: ignore[attr-defined]
        else:
            if clamp is not None:
                self.set_compact(True)
            else:
                self.set_compact(False)

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
        if getattr(summary, "is_error", False) and self._compact_mode and not self._user_touched_compact:
            self.set_compact(False)

    def set_result_summary_v4(self, summary: Any) -> None:
        self.set_result_summary(summary)
