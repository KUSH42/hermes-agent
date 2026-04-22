"""Tool block mounting, streaming, reasoning, plan-call tracking service extracted from _app_tool_rendering.py."""
from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field as _field
from typing import TYPE_CHECKING, Any

from textual.css.query import NoMatches

from hermes_cli.tool_icons import get_display_name
from .base import AppService

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp

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


class ToolRenderingService(AppService):
    """Tool block mounting, streaming, reasoning, plan-call tracking."""

    def __init__(self, app: "HermesApp") -> None:
        super().__init__(app)
        self._streaming_map: dict = {}
        self._turn_tool_calls: dict = {}
        self._agent_stack: list = []
        self._subagent_panels: dict = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_output_panel(self) -> "Any | None":
        """Return OutputPanel, cached after first successful lookup."""
        cached = getattr(self.app, "_cached_output_panel", None)
        if cached is not None and cached.is_mounted:
            return cached
        from hermes_cli.tui.widgets import OutputPanel
        try:
            panel = self.app.query_one(OutputPanel)
            self.app._cached_output_panel = panel
            return panel
        except NoMatches:
            return None

    # ------------------------------------------------------------------
    # Reasoning
    # ------------------------------------------------------------------

    def current_message_panel(self) -> "Any | None":
        """Return the current MessagePanel, or None."""
        output = self._get_output_panel()
        if output is None:
            return None
        return output.current_message

    def open_reasoning(self, title: str = "Reasoning") -> None:
        """Open the reasoning panel. Safe to call from any thread via call_from_thread."""
        msg = self.current_message_panel()
        if msg is not None:
            msg.open_thinking_block(title)
        try:
            from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO
            self.app.query_one(_DO).signal("reasoning")
        except Exception:
            pass

    def append_reasoning(self, delta: str) -> None:
        """Append reasoning delta. Safe to call from any thread via call_from_thread."""
        msg = self.current_message_panel()
        if msg is not None:
            msg.append_thinking(delta)

    def close_reasoning(self) -> None:
        """Close the reasoning panel. Safe to call from any thread via call_from_thread."""
        msg = self.current_message_panel()
        if msg is not None:
            msg.close_thinking_block()
        if self.app.agent_running:
            try:
                from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO
                self.app.query_one(_DO).signal("thinking")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # ToolBlock mounting
    # ------------------------------------------------------------------

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
        """Mount a ToolBlock into OutputPanel before the live-output duo."""
        if not lines:
            return
        output = self._get_output_panel()
        if output is None:
            return
        msg = output.current_message or output.new_message()
        msg.mount_tool_block(
            label,
            lines,
            plain_lines,
            tool_name=tool_name,
            rerender_fn=rerender_fn,
            header_stats=header_stats,
            parent_id=parent_id,
        )
        msg.refresh(layout=True)
        self.app._browse_total += 1
        if not output._user_scrolled_up:
            self.app.call_after_refresh(output.scroll_end, animate=False)

    # ------------------------------------------------------------------
    # StreamingToolBlock lifecycle
    # ------------------------------------------------------------------

    def open_gen_block(self, tool_name: str) -> "Any | None":
        """Open a StreamingToolBlock at gen_start time. Event-loop only."""
        output = self._get_output_panel()
        if output is None:
            return None
        msg = output.current_message or output.new_message()
        block = msg.open_streaming_tool_block(label=get_display_name(tool_name), tool_name=tool_name)
        self.app._browse_total += 1
        if not output._user_scrolled_up:
            self.app.call_after_refresh(output.scroll_end, animate=False)
        return block

    def open_execute_code_block(self, idx: int) -> "Any | None":
        """Open an ExecuteCodeBlock at gen_start time. Event-loop only."""
        output = self._get_output_panel()
        if output is None:
            return None
        try:
            from hermes_cli.tui.execute_code_block import ExecuteCodeBlock
            from hermes_cli.tui.tool_panel import ToolPanel as _ToolPanel
            msg = output.current_message or output.new_message()
            block = ExecuteCodeBlock(initial_label="python")
            panel = _ToolPanel(block, tool_name="execute_code")
            msg._mount_nonprose_block(panel)
            self.app._browse_total += 1
            if not output._user_scrolled_up:
                self.app.call_after_refresh(output.scroll_end, animate=False)
            return block
        except Exception as e:
            logger.warning("open_execute_code_block failed for idx=%d: %s", idx, e)
            return None

    def open_write_file_block(self, idx: int, path: str) -> "Any | None":
        """Open a WriteFileBlock at gen_start time. Event-loop only."""
        output = self._get_output_panel()
        if output is None:
            return None
        try:
            from hermes_cli.tui.write_file_block import WriteFileBlock
            from hermes_cli.tui.tool_panel import ToolPanel as _ToolPanel
            msg = output.current_message or output.new_message()
            block = WriteFileBlock(path=path)
            panel = _ToolPanel(block, tool_name="write_file")
            msg._mount_nonprose_block(panel)
            msg._last_file_tool_block = block
            self.app._browse_total += 1
            if not output._user_scrolled_up:
                self.app.call_after_refresh(output.scroll_end, animate=False)
            return block
        except Exception as e:
            logger.warning("open_write_file_block failed idx=%d: %s", idx, e)
            return None

    def open_streaming_tool_block(
        self,
        tool_call_id: str,
        label: str,
        tool_name: "str | None" = None,
    ) -> None:
        """Mount a StreamingToolBlock into OutputPanel before the live-output duo."""
        output = self._get_output_panel()
        if output is None:
            return
        try:
            msg = output.current_message or output.new_message()
            base_panel_id = f"tool-{tool_call_id}"
            try:
                self.app.query_one(f"#{base_panel_id}")
                panel_id: "str | None" = None
            except Exception:
                panel_id = base_panel_id
            _turn_count = getattr(self.app, "_current_turn_tool_count", 0) + 1
            self.app._current_turn_tool_count = _turn_count
            _is_first = (_turn_count == 1)

            # Stack inference — assign parent
            parent_tool_call_id: "str | None" = getattr(self.app, "_explicit_parent_map", {}).pop(tool_call_id, None)
            if parent_tool_call_id is None and self._agent_stack:
                parent_tool_call_id = self._agent_stack[-1]

            # Depth computation
            from hermes_cli.tui.tool_category import classify_tool, ToolCategory
            try:
                cat_enum = classify_tool(tool_name or "")
                cat = cat_enum.value
            except Exception:
                cat_enum = None
                cat = "unknown"

            parent_rec = self._turn_tool_calls.get(parent_tool_call_id) if parent_tool_call_id else None
            computed_depth = (parent_rec.depth + 1) if parent_rec else 0
            depth = min(computed_depth, 3)

            # Push AFTER parent assignment so tool is not its own parent
            if cat_enum is ToolCategory.AGENT:
                self._agent_stack.append(tool_call_id)

            # Update parent's children list
            if parent_rec is not None:
                parent_rec.children.append(tool_call_id)

            now = _time.monotonic()
            if self.app._turn_start_monotonic is None:
                self.app._turn_start_monotonic = now
            rec = _ToolCallRecord(
                tool_call_id=tool_call_id,
                parent_tool_call_id=parent_tool_call_id,
                label=label,
                tool_name=tool_name,
                category=cat,
                depth=depth,
                start_s=round(now - self.app._turn_start_monotonic, 4),
                dur_ms=None,
                is_error=False,
                error_kind=None,
                mcp_server=None,
            )
            self._turn_tool_calls[tool_call_id] = rec

            # Depth warning if capped
            if computed_depth > 3 and parent_tool_call_id is not None:
                ancestor_panel = getattr(msg, "_subagent_panels", {}).get(parent_tool_call_id)
                if ancestor_panel is not None:
                    try:
                        from textual.widgets import Static as _Static
                        ancestor_panel._body.mount(
                            _Static("… further nesting suppressed (depth limit reached)", classes="--depth-warning")
                        )
                    except Exception:
                        pass

            block = msg.open_streaming_tool_block(
                label=label, tool_name=tool_name, panel_id=panel_id,
                is_first_in_turn=_is_first,
                parent_tool_call_id=parent_tool_call_id,
                depth=depth,
                tool_call_id=tool_call_id,
            )
            self.app._active_streaming_blocks[tool_call_id] = block
            self.app._streaming_tool_count = len(self.app._active_streaming_blocks)
            self.app._active_tool_name = tool_name or ""
            try:
                from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO
                self.app.query_one(_DO).signal("tool")
            except Exception:
                pass
            self.app._update_anim_hint()
            msg.refresh(layout=True)
            self.app._browse_total += 1
            if not output._user_scrolled_up:
                self.app.call_after_refresh(output.scroll_end, animate=False)
        except NoMatches:
            pass

    def append_streaming_line(self, tool_call_id: str, line: str) -> None:
        """Append a line to the named streaming block. Event-loop only."""
        block = self.app._active_streaming_blocks.get(tool_call_id)
        if block is None:
            return
        block.append_line(line)
        panel = self._get_output_panel()
        if panel is not None and not panel._user_scrolled_up:
            self.app.call_after_refresh(panel.scroll_end, animate=False)

    def close_streaming_tool_block(
        self,
        tool_call_id: str,
        duration: str,
        is_error: bool = False,
        summary: "Any | None" = None,
        result_lines: "list[str] | None" = None,
    ) -> None:
        """Transition streaming block to COMPLETED state. Event-loop only."""
        block = self.app._active_streaming_blocks.pop(tool_call_id, None)
        if block is None:
            return
        self.app._streaming_tool_count = len(self.app._active_streaming_blocks)
        if result_lines:
            for _line in result_lines:
                block.append_line(_line)
        block.complete(duration, is_error=is_error)
        if summary is not None:
            panel = getattr(block, "_tool_panel", None)
            if panel is not None:
                panel.set_result_summary_v4(summary)
        if tool_call_id in self._agent_stack:
            self._agent_stack.remove(tool_call_id)
        self.app._active_tool_name = ""
        self.app._update_anim_hint()
        rec = self._turn_tool_calls.get(tool_call_id)
        if rec is not None:
            try:
                ds = str(duration)
                if ds.endswith("ms"):
                    rec.dur_ms = int(float(ds[:-2]))
                elif ds.endswith("s"):
                    rec.dur_ms = int(float(ds[:-1]) * 1000)
            except Exception:
                pass
            rec.is_error = is_error
        panel = self._get_output_panel()
        if panel is not None and not panel._user_scrolled_up:
            self.app.call_after_refresh(panel.scroll_end, animate=False)
        try:
            from hermes_cli.tui.drawille_overlay import DrawilleOverlay
            ov = self.app.query_one(DrawilleOverlay)
            ov.signal("error" if is_error else "thinking")
        except Exception:
            pass

    def close_streaming_tool_block_with_diff(
        self,
        tool_call_id: str,
        duration: str,
        is_error: bool,
        diff_lines: list[str],
        header_stats: object,
        summary: "Any | None" = None,
    ) -> None:
        """Inject diff into a streaming block's body then complete it. Event-loop only."""
        block = self.app._active_streaming_blocks.pop(tool_call_id, None)
        if block is None:
            return
        self.app._streaming_tool_count = len(self.app._active_streaming_blocks)
        block.inject_diff(diff_lines, header_stats)
        block.complete(duration, is_error=is_error)
        if summary is not None:
            panel = getattr(block, "_tool_panel", None)
            if panel is not None:
                panel.set_result_summary_v4(summary)
        if tool_call_id in self._agent_stack:
            self._agent_stack.remove(tool_call_id)
        rec = self._turn_tool_calls.get(tool_call_id)
        if rec is not None:
            try:
                ds = str(duration)
                if ds.endswith("ms"):
                    rec.dur_ms = int(float(ds[:-2]))
                elif ds.endswith("s"):
                    rec.dur_ms = int(float(ds[:-1]) * 1000)
            except Exception:
                pass
            rec.is_error = is_error
        panel = self._get_output_panel()
        if panel is not None and not panel._user_scrolled_up:
            self.app.call_after_refresh(panel.scroll_end, animate=False)
        try:
            from hermes_cli.tui.drawille_overlay import DrawilleOverlay
            ov = self.app.query_one(DrawilleOverlay)
            ov.signal("error" if is_error else "thinking")
        except Exception:
            pass

    def remove_streaming_tool_block(self, tool_call_id: str) -> None:
        """Remove a streaming block from the DOM entirely. Event-loop only."""
        block = self.app._active_streaming_blocks.pop(tool_call_id, None)
        if block is None:
            return
        self.app._streaming_tool_count = len(self.app._active_streaming_blocks)
        try:
            from hermes_cli.tui.tool_panel import ToolPanel as _TP
            body_pane = block.parent
            tool_panel = body_pane.parent if body_pane is not None else None
            if isinstance(tool_panel, _TP):
                tool_panel.remove()
            else:
                block.remove()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # PlanPanel mutations — event-loop only
    # ------------------------------------------------------------------

    def set_plan_batch(self, batch: "list[tuple[str, str, str, dict]]") -> None:
        """Seed planned_calls from a new tool batch."""
        from hermes_cli.tui.plan_types import PlannedCall, PlanState
        current: list = list(getattr(self.app, "planned_calls", []))
        kept = [c for c in current if c.state in (PlanState.DONE, PlanState.ERROR, PlanState.CANCELLED, PlanState.SKIPPED)]
        new_entries = []
        for tool_call_id, tool_name, label, args in batch:
            try:
                import json as _json
                raw = _json.dumps(args, ensure_ascii=False)
                preview = raw[:60] + ("…" if len(raw) > 60 else "")
            except Exception:
                preview = ""
            try:
                from hermes_cli.tui.tool_category import classify_tool
                cat = classify_tool(tool_name).value
            except Exception:
                cat = "unknown"
            new_entries.append(PlannedCall(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                label=label,
                category=cat,
                args_preview=preview,
                state=PlanState.PENDING,
                started_at=None,
                ended_at=None,
                parent_tool_call_id=None,
                depth=0,
            ))
        self.app.planned_calls = kept + new_entries

    def mark_plan_running(self, tool_call_id: str) -> None:
        """Transition a PENDING PlannedCall to RUNNING. Event-loop only."""
        from hermes_cli.tui.plan_types import PlanState
        items = list(getattr(self.app, "planned_calls", []))
        for i, call in enumerate(items):
            if call.tool_call_id == tool_call_id and call.state == PlanState.PENDING:
                items[i] = call.as_running()
                break
        self.app.planned_calls = items

    def mark_plan_done(self, tool_call_id: str, is_error: bool, dur_ms: int) -> None:
        """Transition a RUNNING PlannedCall to DONE or ERROR. Event-loop only."""
        from hermes_cli.tui.plan_types import PlanState
        items = list(getattr(self.app, "planned_calls", []))
        for i, call in enumerate(items):
            if call.tool_call_id == tool_call_id and call.state == PlanState.RUNNING:
                items[i] = call.as_done(is_error=is_error)
                break
        self.app.planned_calls = items

    def current_turn_tool_calls(self) -> list[dict]:
        """Return a list of per-turn tool call records (P7 /tools overlay).

        Thread-safe: builds a fresh list of dicts from _ToolCallRecord values.
        """
        return [
            {
                "tool_call_id": r.tool_call_id,
                "parent_tool_call_id": r.parent_tool_call_id,
                "name": r.tool_name or r.label,
                "category": r.category,
                "depth": r.depth,
                "children": list(r.children),
                "start_s": r.start_s,
                "dur_ms": r.dur_ms,
                "is_error": r.is_error,
                "error_kind": r.error_kind,
                "mcp_server": r.mcp_server,
            }
            for r in self._turn_tool_calls.values()
        ]

    def get_reasoning_panel(self) -> "Any | None":
        """Return the active ReasoningPanel, or None."""
        msg = self.current_message_panel()
        if msg is None:
            return None
        return getattr(msg, "_reasoning_panel", None)
