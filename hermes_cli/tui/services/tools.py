"""Tool block mounting, streaming, reasoning, plan-call tracking service extracted from _app_tool_rendering.py."""
from __future__ import annotations

import logging
import threading
import time as _time
from dataclasses import dataclass, field as _field
from enum import Enum
from typing import TYPE_CHECKING, Any

from textual.css.query import NoMatches

from hermes_cli.tool_icons import get_display_name
from .base import AppService

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SM-01: Tool-call unified state machine model
# ---------------------------------------------------------------------------

class ToolCallState(str, Enum):
    """Lifecycle states for a single tool call."""
    PENDING    = "pending"     # allocated but not yet materialised by the service
    GENERATED  = "generated"   # model is still generating tool args
    STARTED    = "started"     # tool handler has started
    STREAMING  = "streaming"   # output body is receiving lines
    COMPLETING = "completing"  # result parsing / diff merge in progress
    DONE       = "done"
    ERROR      = "error"
    CANCELLED  = "cancelled"
    REMOVED    = "removed"


_TERMINAL_STATES = frozenset({
    ToolCallState.DONE,
    ToolCallState.ERROR,
    ToolCallState.CANCELLED,
    ToolCallState.REMOVED,
})


@dataclass
class ToolCallViewState:
    """Per-tool-call view state owned by ToolRenderingService."""
    tool_call_id: "str | None"
    gen_index: "int | None"
    tool_name: str
    label: str
    args: "dict[str, Any]"
    state: ToolCallState
    block: "Any | None"
    panel: "Any | None"
    parent_tool_call_id: "str | None"
    category: str
    depth: int
    start_s: float
    started_at: float = _field(default_factory=_time.monotonic)


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
        self._open_tool_count: int = 0  # A1: tracks concurrent open tool blocks
        # SM-01: unified tool-call state machine indexes
        self._tool_views_by_id: dict = {}
        self._tool_views_by_gen_index: dict = {}
        self._tool_views_history_by_id: dict = {}
        self._pending_gen_arg_deltas: dict = {}
        self._state_lock = threading.RLock()

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
            from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay as _DO
            self.app.query_one(_DO).signal("reasoning")
        except Exception:  # il-ex-1-exempt: overlay absent during startup; signal is optional
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
                from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay as _DO
                self.app.query_one(_DO).signal("thinking")
            except Exception:  # il-ex-1-exempt: overlay absent during startup; signal is optional
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
        is_error: bool = False,
    ) -> "Widget | None":
        """Mount a ToolBlock into OutputPanel before the live-output duo."""
        if not lines:
            return None
        output = self._get_output_panel()
        if output is None:
            return None
        msg = output.current_message or output.new_message()
        result = msg.mount_tool_block(
            label,
            lines,
            plain_lines,
            tool_name=tool_name,
            rerender_fn=rerender_fn,
            header_stats=header_stats,
            parent_id=parent_id,
            is_error=is_error,
        )
        msg.refresh(layout=True)
        self.app._browse_total += 1
        if not output._user_scrolled_up:
            self.app.call_after_refresh(output.scroll_end, animate=False)
        return result

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
            logger.warning("open_execute_code_block failed for idx=%d", idx, exc_info=True)
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
            logger.warning("open_write_file_block failed idx=%d", idx, exc_info=True)
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
            except Exception:  # il-ex-1-exempt: NoMatches expected when panel not yet mounted; fallback to base_panel_id
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
            except Exception:  # il-ex-1-exempt: classify_tool unavailable; fallback to "unknown" is correct
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
                    except Exception:  # il-ex-1-exempt: best-effort depth warning; ancestor panel may not be mounted
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
                panel = getattr(block, "_tool_panel", None)
                if panel is not None:
                    panel.add_class("--streaming")
            except Exception:  # il-ex-1-exempt: best-effort class addition; panel may not be attached
                pass
            # A1: increment open tool count and set TOOL_EXEC phase
            self._open_tool_count += 1
            from hermes_cli.tui.agent_phase import Phase as _Phase
            self.app.status_phase = _Phase.TOOL_EXEC
            try:
                from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay as _DO
                self.app.query_one(_DO).signal("tool")
            except Exception:  # il-ex-1-exempt: overlay absent during startup; signal is optional
                pass
            self.app._svc_commands.update_anim_hint()
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
        # A1: decrement open tool count; revert phase when last tool closes
        self._open_tool_count = max(0, self._open_tool_count - 1)
        if self._open_tool_count == 0:
            from hermes_cli.tui.agent_phase import Phase as _Phase
            if getattr(self.app, "agent_running", False):
                self.app.status_phase = _Phase.REASONING
            else:
                self.app.status_phase = _Phase.IDLE
        self.app._svc_commands.update_anim_hint()
        rec = self._turn_tool_calls.get(tool_call_id)
        if rec is not None:
            try:
                ds = str(duration)
                if ds.endswith("ms"):
                    rec.dur_ms = int(float(ds[:-2]))
                elif ds.endswith("s"):
                    rec.dur_ms = int(float(ds[:-1]) * 1000)
            except Exception:  # il-ex-1-exempt: malformed duration string; dur_ms stays at current value
                pass
            rec.is_error = is_error
        panel = self._get_output_panel()
        if panel is not None and not panel._user_scrolled_up:
            self.app.call_after_refresh(panel.scroll_end, animate=False)
        try:
            from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay
            ov = self.app.query_one(DrawbrailleOverlay)
            ov.signal("error" if is_error else "thinking")
        except Exception:  # il-ex-1-exempt: overlay absent; signal is optional
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
        # A1: decrement open tool count; revert phase when last tool closes
        self._open_tool_count = max(0, self._open_tool_count - 1)
        if self._open_tool_count == 0:
            from hermes_cli.tui.agent_phase import Phase as _Phase
            if getattr(self.app, "agent_running", False):
                self.app.status_phase = _Phase.REASONING
            else:
                self.app.status_phase = _Phase.IDLE
        rec = self._turn_tool_calls.get(tool_call_id)
        if rec is not None:
            try:
                ds = str(duration)
                if ds.endswith("ms"):
                    rec.dur_ms = int(float(ds[:-2]))
                elif ds.endswith("s"):
                    rec.dur_ms = int(float(ds[:-1]) * 1000)
            except Exception:  # il-ex-1-exempt: malformed duration string; dur_ms stays at current value
                pass
            rec.is_error = is_error
        panel = self._get_output_panel()
        if panel is not None and not panel._user_scrolled_up:
            self.app.call_after_refresh(panel.scroll_end, animate=False)
        try:
            from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay
            ov = self.app.query_one(DrawbrailleOverlay)
            ov.signal("error" if is_error else "thinking")
        except Exception:  # il-ex-1-exempt: overlay absent; signal is optional
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
        except Exception:  # il-ex-1-exempt: block may already be removed; removal failure is safe to skip
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
            except Exception:  # il-ex-1-exempt: args serialization failure; preview stays empty
                preview = ""
            try:
                from hermes_cli.tui.tool_category import classify_tool
                cat = classify_tool(tool_name).value
            except Exception:  # il-ex-1-exempt: classify_tool unavailable; fallback to "unknown" is correct
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
        """Transition a RUNNING or PENDING PlannedCall to DONE or ERROR. Event-loop only."""
        from hermes_cli.tui.plan_types import PlanState
        items = list(getattr(self.app, "planned_calls", []))
        for i, call in enumerate(items):
            if call.tool_call_id == tool_call_id and call.state in (PlanState.RUNNING, PlanState.PENDING):
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

    # ------------------------------------------------------------------
    # SM-01..SM-06: Unified tool-call state machine
    # ------------------------------------------------------------------

    def _panel_for_block(self, block: "Any") -> "Any | None":
        """Return the ToolPanel for a block — check _tool_panel attr first, then parent."""
        panel = getattr(block, "_tool_panel", None)
        if panel is not None:
            return panel
        parent = getattr(block, "parent", None)
        if parent is None:
            return None
        # Check parent looks like a ToolPanel (best-effort; avoids hard import)
        if type(parent).__name__ == "ToolPanel":
            return parent
        return None

    def append_tool_output(self, tool_call_id: str, line: str) -> None:
        """Append a line to a streaming block; transition STARTED→STREAMING on first call."""
        view = self._tool_views_by_id.get(tool_call_id)
        if view is not None and view.state in _TERMINAL_STATES:
            return
        if view is not None and view.state == ToolCallState.STARTED:
            view.state = ToolCallState.STREAMING
        self.append_streaming_line(tool_call_id, line)

    def _make_view_category(self, tool_name: str) -> str:
        try:
            from hermes_cli.tui.tool_category import classify_tool
            return classify_tool(tool_name).value
        except Exception:  # il-ex-1-exempt: classify_tool unavailable at startup; fallback to "unknown" is correct
            return "unknown"

    def _compute_parent_depth(self, tool_call_id: str) -> "tuple[str | None, int]":
        parent_id: "str | None" = getattr(self.app, "_explicit_parent_map", {}).pop(tool_call_id, None)
        if parent_id is None and self._agent_stack:
            parent_id = self._agent_stack[-1]
        parent_rec = self._turn_tool_calls.get(parent_id) if parent_id else None
        depth = min((parent_rec.depth + 1) if parent_rec else 0, 3)
        return parent_id, depth

    def _wire_args(self, view: "ToolCallViewState", args: "dict[str, Any]") -> None:
        args_copy = dict(args)
        view.args = args_copy
        if view.block is not None and hasattr(view.block, "_tool_input"):
            view.block._tool_input = args_copy
        if view.panel is not None:
            try:
                view.panel.set_tool_args(args_copy)
            except Exception:  # il-ex-1-exempt: best-effort panel update; panel may not be fully mounted
                pass

    def _pop_pending_gen_for(self, tool_name: str) -> "ToolCallViewState | None":
        for gen_index, view in list(self._tool_views_by_gen_index.items()):
            if view.tool_name == tool_name and view.state == ToolCallState.GENERATED:
                del self._tool_views_by_gen_index[gen_index]
                return view
        return None

    def open_tool_generation(self, gen_index: int, tool_name: str) -> None:
        """Open a gen-phase block and register a GENERATED view. Event-loop only."""
        if tool_name == "execute_code":
            block = self.open_execute_code_block(gen_index)
        elif tool_name in ("write_file", "create_file"):
            block = self.open_write_file_block(gen_index, "")
        else:
            block = self.open_gen_block(tool_name)

        now = _time.monotonic()
        turn_start = getattr(self.app, "_turn_start_monotonic", now) or now
        view = ToolCallViewState(
            tool_call_id=None,
            gen_index=gen_index,
            tool_name=tool_name,
            label=get_display_name(tool_name),
            args={},
            state=ToolCallState.GENERATED,
            block=block,
            panel=getattr(block, "_tool_panel", None) if block else None,
            parent_tool_call_id=None,
            category=self._make_view_category(tool_name),
            depth=0,
            start_s=round(now - turn_start, 4),
        )
        self._tool_views_by_gen_index[gen_index] = view

        # Drain any deltas buffered before this generation opened
        pending = self._pending_gen_arg_deltas.pop(gen_index, [])
        for delta, accumulated in pending:
            if block is not None:
                if hasattr(block, "feed_delta"):
                    block.feed_delta(delta)
                if tool_name == "write_file" and hasattr(block, "update_progress"):
                    written = len(accumulated.encode("utf-8", errors="replace"))
                    block.update_progress(written, written)

    def append_generation_args_delta(
        self, gen_index: int, tool_name: str, delta: str, accumulated: str
    ) -> None:
        """Feed a generation-args delta to the block, or buffer if gen not yet open."""
        view = self._tool_views_by_gen_index.get(gen_index)
        if view is None:
            self._pending_gen_arg_deltas.setdefault(gen_index, []).append((delta, accumulated))
            return
        block = view.block
        if block is not None:
            if hasattr(block, "feed_delta"):
                block.feed_delta(delta)
            if tool_name == "write_file" and hasattr(block, "update_progress"):
                written = len(accumulated.encode("utf-8", errors="replace"))
                block.update_progress(written, written)

    def _create_write_fallback(
        self, tool_call_id: str, tool_name: str, args: "dict[str, Any]"
    ) -> "tuple[Any, Any]":
        """Create WriteFileBlock + ToolPanel fallback when no gen block exists."""
        path = args.get("path", "")
        output = self._get_output_panel()
        try:
            from hermes_cli.tui.write_file_block import WriteFileBlock
            from hermes_cli.tui.tool_panel import ToolPanel as _ToolPanel
            block = WriteFileBlock(path=path)
            panel = _ToolPanel(block, tool_name=tool_name)
            panel._plan_tool_call_id = tool_call_id
            if output is not None:
                msg = output.current_message or output.new_message()
                msg._mount_nonprose_block(panel)
            self.app._active_streaming_blocks[tool_call_id] = block
            self.app._streaming_tool_count = len(self.app._active_streaming_blocks)
            self._open_tool_count += 1
            from hermes_cli.tui.agent_phase import Phase as _Phase
            self.app.status_phase = _Phase.TOOL_EXEC
            return block, panel
        except Exception:  # il-ex-1-exempt: failure surfaced via logger.warning above
            logger.warning("_create_write_fallback failed for %s", tool_call_id, exc_info=True)
            return None, None

    def start_tool_call(self, tool_call_id: str, tool_name: str, args: "dict[str, Any]") -> None:
        """Adopt a GENERATED view or open a new block; transition to STARTED. Event-loop only."""
        # Preemption: existing live view for same id → archive it
        existing = self._tool_views_by_id.get(tool_call_id)
        if existing is not None:
            self._terminalize_tool_view(
                tool_call_id,
                terminal_state=ToolCallState.REMOVED,
                is_error=False,
                mark_plan=False,
                remove_visual=False,
                delete_view=False,
                view=existing,
            )

        label = get_display_name(tool_name)
        parent_id, depth = self._compute_parent_depth(tool_call_id)
        category = self._make_view_category(tool_name)

        now = _time.monotonic()
        turn_start = getattr(self.app, "_turn_start_monotonic", now) or now
        start_s = round(now - turn_start, 4)

        gen_view = self._pop_pending_gen_for(tool_name)

        if gen_view is not None:
            # Adopt gen view: assign id, clear gen_index, update metadata
            gen_view.tool_call_id = tool_call_id
            gen_view.gen_index = None  # H7: cleared on adoption
            gen_view.state = ToolCallState.STARTED
            gen_view.parent_tool_call_id = parent_id
            gen_view.depth = depth
            gen_view.category = category
            gen_view.start_s = start_s

            block = gen_view.block
            self.app._active_streaming_blocks[tool_call_id] = block
            self.app._streaming_tool_count = len(self.app._active_streaming_blocks)

            if tool_name in ("write_file", "create_file", "str_replace_editor"):
                path = args.get("path", "")
                if block is not None and hasattr(block, "set_final_path"):
                    block.set_final_path(path)

            self._open_tool_count += 1
            from hermes_cli.tui.agent_phase import Phase as _Phase
            self.app.status_phase = _Phase.TOOL_EXEC

            # Register in turn records for current_turn_tool_calls()
            rec = _ToolCallRecord(
                tool_call_id=tool_call_id,
                parent_tool_call_id=parent_id,
                label=label,
                tool_name=tool_name,
                category=category,
                depth=depth,
                start_s=start_s,
                dur_ms=None,
                is_error=False,
                error_kind=None,
                mcp_server=None,
            )
            self._turn_tool_calls[tool_call_id] = rec

            view = gen_view
        else:
            # No gen block — create block now
            if tool_name in ("write_file", "create_file", "str_replace_editor"):
                block, panel = self._create_write_fallback(tool_call_id, tool_name, args)
            else:
                self.open_streaming_tool_block(tool_call_id, label, tool_name=tool_name)
                block = self.app._active_streaming_blocks.get(tool_call_id)
                panel = getattr(block, "_tool_panel", None) if block else None

            view = ToolCallViewState(
                tool_call_id=tool_call_id,
                gen_index=None,
                tool_name=tool_name,
                label=label,
                args={},
                state=ToolCallState.STARTED,
                block=block,
                panel=panel,
                parent_tool_call_id=parent_id,
                category=category,
                depth=depth,
                start_s=start_s,
            )

        # Wire args (copies into view.args, block._tool_input, panel.set_tool_args)
        self._wire_args(view, args)

        # Propagate plan id to panel if present
        if view.panel is not None and hasattr(view.panel, "_plan_tool_call_id"):
            view.panel._plan_tool_call_id = tool_call_id

        self._tool_views_by_id[tool_call_id] = view
        self.mark_plan_running(tool_call_id)

    def complete_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        args: "dict[str, Any]",
        raw_result: str,
        *,
        is_error: bool,
        summary: "Any | None",
        diff_lines: "list[str] | None" = None,
        header_stats: "Any | None" = None,
        result_lines: "list[str] | None" = None,
        duration: "str | None" = None,
    ) -> None:
        """Transition a tool call to DONE/ERROR; close its block. Event-loop only."""
        view = self._tool_views_by_id.get(tool_call_id)
        if view is None:
            self.mark_plan_done(tool_call_id, is_error=is_error, dur_ms=0)
            return

        # Compute duration from block start time
        block = self.app._active_streaming_blocks.get(tool_call_id)
        dur_ms = 0
        if block is not None:
            started_at = getattr(block, "_stream_started_at", None)
            if started_at is not None:
                try:
                    dur_ms = max(0, int((_time.monotonic() - float(started_at)) * 1000))
                except Exception:  # il-ex-1-exempt: malformed start timestamp; dur_ms=0 fallback is correct
                    pass
        dur_str = duration or f"{dur_ms}ms"

        terminal_state = ToolCallState.ERROR if is_error else ToolCallState.DONE

        if diff_lines is not None:
            self.close_streaming_tool_block_with_diff(
                tool_call_id, dur_str, is_error, diff_lines, header_stats, summary=summary
            )
        else:
            self.close_streaming_tool_block(
                tool_call_id, dur_str, is_error=is_error, summary=summary,
                result_lines=result_lines,
            )

        self._terminalize_tool_view(
            tool_call_id,
            terminal_state=terminal_state,
            is_error=is_error,
            mark_plan=True,
            remove_visual=False,
            delete_view=False,
            view=view,
            dur_ms=dur_ms,
        )

    def cancel_tool_call(
        self,
        tool_call_id: "str | None" = None,
        gen_index: "int | None" = None,
    ) -> None:
        """Cancel a GENERATED (by gen_index) or live (by tool_call_id) view."""
        if gen_index is not None:
            self._tool_views_by_gen_index.pop(gen_index, None)
        if tool_call_id is not None:
            view = self._tool_views_by_id.get(tool_call_id)
            if view is not None:
                self._terminalize_tool_view(
                    tool_call_id,
                    terminal_state=ToolCallState.CANCELLED,
                    is_error=False,
                    mark_plan=False,
                    remove_visual=False,
                    delete_view=False,
                    view=view,
                )

    def _terminalize_tool_view(
        self,
        tool_call_id: str,
        *,
        terminal_state: "ToolCallState",
        is_error: bool,
        mark_plan: bool,
        remove_visual: bool,
        delete_view: bool,
        view: "ToolCallViewState",
        dur_ms: int = 0,
    ) -> None:
        """Move view to terminal state, archive to history, optionally mark plan done."""
        view.state = terminal_state
        self._tool_views_by_id.pop(tool_call_id, None)

        hist = self._tool_views_history_by_id.setdefault(tool_call_id, [])
        hist.append(view)
        if len(hist) > 10:
            del hist[0]

        if mark_plan:
            self.mark_plan_done(tool_call_id, is_error=is_error, dur_ms=dur_ms)

    def live_by_id(self, tool_call_id: str) -> "ToolCallViewState | None":
        """Return the live (non-terminal) view for tool_call_id, or None."""
        return self._tool_views_by_id.get(tool_call_id)

    def history_by_id(self, tool_call_id: str) -> "list[ToolCallViewState]":
        """Return a copy of the terminal-state history list for tool_call_id."""
        return list(self._tool_views_history_by_id.get(tool_call_id, []))
