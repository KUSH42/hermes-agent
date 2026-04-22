"""_ToolRenderingMixin — tool block mounting / streaming lifecycle for HermesApp.

Phase 2: all logic lives in ToolRenderingService; methods here are 1-line adapters.
"""
from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field as _field
from typing import Any

from textual.css.query import NoMatches

from hermes_cli.tool_icons import get_display_name

logger = logging.getLogger(__name__)


@dataclass
class _ToolCallRecord:
    tool_call_id: str
    parent_tool_call_id: str | None
    label: str
    tool_name: str | None
    category: str
    depth: int
    start_s: float
    dur_ms: int | None
    is_error: bool
    error_kind: str | None
    mcp_server: str | None
    children: list = _field(default_factory=list)


class _ToolRenderingMixin:
    """Tool block mounting and streaming lifecycle methods.

    Extracted from HermesApp to reduce file size.  Self is always a HermesApp
    instance at runtime — all attribute access on self is valid.

    Phase 2: all logic delegated to self._svc_tools (ToolRenderingService).
    """

    def _get_output_panel(self) -> "Any | None":
        return self._svc_tools._get_output_panel()  # type: ignore[attr-defined]  # DEPRECATED

    # --- Reasoning ---

    def _current_message_panel(self) -> "Any | None":
        return self._svc_tools.current_message_panel()  # type: ignore[attr-defined]  # DEPRECATED

    def open_reasoning(self, title: str = "Reasoning") -> None:
        return self._svc_tools.open_reasoning(title)  # type: ignore[attr-defined]

    def append_reasoning(self, delta: str) -> None:
        return self._svc_tools.append_reasoning(delta)  # type: ignore[attr-defined]

    def close_reasoning(self) -> None:
        return self._svc_tools.close_reasoning()  # type: ignore[attr-defined]

    # --- ToolBlock mounting ---

    def mount_tool_block(
        self,
        label: str,
        lines: list[str],
        plain_lines: list[str],
        rerender_fn: Any = None,
        header_stats: Any = None,
        tool_name: "str | None" = None,
        parent_id: "str | None" = None,
    ) -> None:
        return self._svc_tools.mount_tool_block(  # type: ignore[attr-defined]
            label, lines, plain_lines,
            rerender_fn=rerender_fn, header_stats=header_stats,
            tool_name=tool_name, parent_id=parent_id,
        )

    # --- StreamingToolBlock lifecycle ---

    def _open_gen_block(self, tool_name: str) -> "Any | None":
        return self._svc_tools.open_gen_block(tool_name)  # type: ignore[attr-defined]  # DEPRECATED

    def _open_execute_code_block(self, idx: int) -> "Any | None":
        return self._svc_tools.open_execute_code_block(idx)  # type: ignore[attr-defined]  # DEPRECATED

    def _open_write_file_block(self, idx: int, path: str) -> "Any | None":
        return self._svc_tools.open_write_file_block(idx, path)  # type: ignore[attr-defined]  # DEPRECATED

    def open_streaming_tool_block(self, tool_call_id: str, label: str, tool_name: "str | None" = None) -> None:
        return self._svc_tools.open_streaming_tool_block(tool_call_id, label, tool_name=tool_name)  # type: ignore[attr-defined]

    def append_streaming_line(self, tool_call_id: str, line: str) -> None:
        return self._svc_tools.append_streaming_line(tool_call_id, line)  # type: ignore[attr-defined]

    def close_streaming_tool_block(
        self,
        tool_call_id: str,
        duration: str,
        is_error: bool = False,
        summary: "Any | None" = None,
        result_lines: "list[str] | None" = None,
    ) -> None:
        return self._svc_tools.close_streaming_tool_block(  # type: ignore[attr-defined]
            tool_call_id, duration, is_error=is_error, summary=summary, result_lines=result_lines
        )

    def close_streaming_tool_block_with_diff(
        self,
        tool_call_id: str,
        duration: str,
        is_error: bool,
        diff_lines: list[str],
        header_stats: object,
        summary: "Any | None" = None,
    ) -> None:
        return self._svc_tools.close_streaming_tool_block_with_diff(  # type: ignore[attr-defined]
            tool_call_id, duration, is_error, diff_lines, header_stats, summary=summary
        )

    def remove_streaming_tool_block(self, tool_call_id: str) -> None:
        return self._svc_tools.remove_streaming_tool_block(tool_call_id)  # type: ignore[attr-defined]

    # --- PlanPanel (R1) mutations ---

    def set_plan_batch(self, batch: "list[tuple[str, str, str, dict]]") -> None:
        return self._svc_tools.set_plan_batch(batch)  # type: ignore[attr-defined]

    def mark_plan_running(self, tool_call_id: str) -> None:
        return self._svc_tools.mark_plan_running(tool_call_id)  # type: ignore[attr-defined]

    def mark_plan_done(self, tool_call_id: str, is_error: bool, dur_ms: int) -> None:
        return self._svc_tools.mark_plan_done(tool_call_id, is_error, dur_ms)  # type: ignore[attr-defined]

    def current_turn_tool_calls(self) -> list[dict]:
        return self._svc_tools.current_turn_tool_calls()  # type: ignore[attr-defined]
