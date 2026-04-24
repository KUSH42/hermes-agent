"""Tool block mounting, streaming, reasoning, plan-call tracking service extracted from _app_tool_rendering.py."""
from __future__ import annotations

import logging
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
    GENERATED  = "generated"   # model is still generating tool args
    STARTED    = "started"     # tool handler has started
    STREAMING  = "streaming"   # output body is receiving lines
    COMPLETING = "completing"  # result parsing / diff merge in progress
    DONE       = "done"
    ERROR      = "error"
    CANCELLED  = "cancelled"
    REMOVED    = "removed"


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
    dur_ms: "int | None" = None
    is_error: bool = False
    error_kind: "str | None" = None
    children: "list[str]" = _field(default_factory=list)


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

    # Tools whose gen-start block creation is intentionally deferred to tool-start
    # (we know the skill name only after the call starts).
    _SKILL_TOOL_NAMES: frozenset = frozenset({"skill_view", "skill_manage"})

    def __init__(self, app: "HermesApp") -> None:
        super().__init__(app)
        self._streaming_map: dict = {}
        self._turn_tool_calls: dict = {}
        self._agent_stack: list = []
        self._subagent_panels: dict = {}
        self._open_tool_count: int = 0  # A1: tracks concurrent open tool blocks
        # SM-01: unified state-machine indexes
        self._tool_views_by_id: "dict[str, ToolCallViewState]" = {}
        self._tool_views_by_gen_index: "dict[int, ToolCallViewState]" = {}

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
                from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay as _DO
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
                panel = getattr(block, "_tool_panel", None)
                if panel is not None:
                    panel.add_class("--streaming")
            except Exception:
                pass
            # A1: increment open tool count and set TOOL_EXEC phase
            self._open_tool_count += 1
            from hermes_cli.tui.agent_phase import Phase as _Phase
            self.app.status_phase = _Phase.TOOL_EXEC
            try:
                from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay as _DO
                self.app.query_one(_DO).signal("tool")
            except Exception:
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
        # Clear active tool name only when this tool owns it or no tools remain
        _tool_label = ""
        rec = self._turn_tool_calls.get(tool_call_id)
        if rec is not None:
            _tool_label = rec.tool_name or rec.label
        if self.app._active_tool_name == _tool_label or self._open_tool_count == 0:
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
            from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay
            ov = self.app.query_one(DrawbrailleOverlay)
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
        # Clear active tool name only when this tool owns it or no tools remain
        _rec_diff = self._turn_tool_calls.get(tool_call_id)
        _tool_label_diff = (_rec_diff.tool_name or _rec_diff.label) if _rec_diff is not None else ""
        if self.app._active_tool_name == _tool_label_diff or self._open_tool_count == 0:
            self.app._active_tool_name = ""
        # A1: decrement open tool count; revert phase when last tool closes
        self._open_tool_count = max(0, self._open_tool_count - 1)
        if self._open_tool_count == 0:
            from hermes_cli.tui.agent_phase import Phase as _Phase
            if getattr(self.app, "agent_running", False):
                self.app.status_phase = _Phase.REASONING
            else:
                self.app.status_phase = _Phase.IDLE
        if _rec_diff is not None:
            try:
                ds = str(duration)
                if ds.endswith("ms"):
                    _rec_diff.dur_ms = int(float(ds[:-2]))
                elif ds.endswith("s"):
                    _rec_diff.dur_ms = int(float(ds[:-1]) * 1000)
            except Exception:
                pass
            _rec_diff.is_error = is_error
        panel = self._get_output_panel()
        if panel is not None and not panel._user_scrolled_up:
            self.app.call_after_refresh(panel.scroll_end, animate=False)
        try:
            from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay
            ov = self.app.query_one(DrawbrailleOverlay)
            ov.signal("error" if is_error else "thinking")
        except Exception:
            pass

    def _terminalize_tool_view(
        self,
        tool_call_id: str,
        *,
        terminal_state: ToolCallState,
        is_error: bool = False,
        mark_plan: bool = True,
        remove_visual: bool = False,
        delete_view: bool = False,
        dur_ms: int | None = None,
    ) -> "ToolCallViewState | None":
        """TCS-HIGH-02: Shared terminal cleanup helper for remove, cancel, and completion.

        Handles _open_tool_count, _agent_stack, _active_tool_name, status_phase,
        PlanPanel, and view-state indexes in one place. Returns the view before
        mutation so callers can log it; returns None when no record exists.
        """
        view = self._tool_views_by_id.get(tool_call_id)

        # Pop active streaming block
        block = self.app._active_streaming_blocks.pop(tool_call_id, None)
        if block is not None:
            self.app._streaming_tool_count = len(self.app._active_streaming_blocks)

        # Decrement open count only for views that incremented it
        _was_active = view is not None and view.state in (ToolCallState.STARTED, ToolCallState.STREAMING)
        if _was_active:
            self._open_tool_count = max(0, self._open_tool_count - 1)

        # Remove from agent stack
        if tool_call_id in self._agent_stack:
            self._agent_stack.remove(tool_call_id)

        # Clear active tool name conditionally
        if view is not None:
            tool_label = view.tool_name or view.label
            if self.app._active_tool_name == tool_label or self._open_tool_count == 0:
                self.app._active_tool_name = ""

        # Update status phase
        if self._open_tool_count == 0:
            from hermes_cli.tui.agent_phase import Phase as _Phase
            if getattr(self.app, "agent_running", False):
                self.app.status_phase = _Phase.REASONING
            else:
                self.app.status_phase = _Phase.IDLE
        self.app._svc_commands.update_anim_hint()

        # Update turn record
        rec = self._turn_tool_calls.get(tool_call_id)
        if rec is not None:
            if dur_ms is not None:
                rec.dur_ms = dur_ms
            rec.is_error = is_error

        # Mark PlanPanel
        if mark_plan:
            if terminal_state == ToolCallState.CANCELLED:
                self.mark_plan_cancelled(tool_call_id)
            else:
                _dur = rec.dur_ms if rec is not None and rec.dur_ms is not None else (dur_ms or 0)
                self.mark_plan_done(tool_call_id, is_error=is_error, dur_ms=_dur)

        # Update view state and remove from active indexes
        if view is not None:
            view.state = terminal_state
            view.is_error = is_error
            self._tool_views_by_id.pop(tool_call_id, None)
            if view.gen_index is not None:
                self._tool_views_by_gen_index.pop(view.gen_index, None)
            if delete_view:
                self._turn_tool_calls.pop(tool_call_id, None)

        # Remove visual panel
        if remove_visual and block is not None:
            try:
                from hermes_cli.tui.tool_panel._core import ToolPanel as _TP
                from hermes_cli.tui.tool_panel._child import ChildPanel as _CP
                body_pane = block.parent
                panel = body_pane.parent if body_pane is not None else None
                if isinstance(panel, (_TP, _CP)):
                    panel.remove()
                else:
                    block.remove()
            except Exception:
                logger.debug("remove_visual failed for tool_call_id=%s", tool_call_id, exc_info=True)

        return view

    def remove_streaming_tool_block(self, tool_call_id: str) -> None:
        """Remove a streaming block from the DOM entirely. Event-loop only.

        Routes through _terminalize_tool_view so _open_tool_count, status_phase,
        and agent stack stay consistent.
        """
        view = self._tool_views_by_id.get(tool_call_id)
        # Only terminalize if we have an active view (patch dedup path)
        if view is not None:
            self._terminalize_tool_view(
                tool_call_id,
                terminal_state=ToolCallState.REMOVED,
                mark_plan=False,
                remove_visual=True,
            )
            return
        # Fallback: no state-machine record — just remove the block visually
        block = self.app._active_streaming_blocks.pop(tool_call_id, None)
        if block is None:
            return
        self.app._streaming_tool_count = len(self.app._active_streaming_blocks)
        try:
            from hermes_cli.tui.tool_panel._core import ToolPanel as _TP
            from hermes_cli.tui.tool_panel._child import ChildPanel as _CP
            body_pane = block.parent
            panel = body_pane.parent if body_pane is not None else None
            if isinstance(panel, (_TP, _CP)):
                panel.remove()
            else:
                block.remove()
        except Exception:
            logger.debug("remove_streaming_tool_block DOM remove failed", exc_info=True)

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
        """Transition a PENDING or RUNNING PlannedCall to DONE or ERROR. Event-loop only.

        Accepts PENDING in addition to RUNNING so that completion is idempotent
        even when the start callback was skipped or raced with completion (SM-05).
        """
        from hermes_cli.tui.plan_types import PlanState
        items = list(getattr(self.app, "planned_calls", []))
        for i, call in enumerate(items):
            if call.tool_call_id == tool_call_id and call.state in (PlanState.PENDING, PlanState.RUNNING):
                items[i] = call.as_done(is_error=is_error)
                break
        self.app.planned_calls = items

    def mark_plan_cancelled(self, tool_call_id: str) -> None:
        """Transition a PENDING or RUNNING PlannedCall to CANCELLED. Event-loop only."""
        from hermes_cli.tui.plan_types import PlanState
        items = list(getattr(self.app, "planned_calls", []))
        for i, call in enumerate(items):
            if call.tool_call_id == tool_call_id and call.state in (PlanState.PENDING, PlanState.RUNNING):
                items[i] = call.as_cancelled()
                break
        self.app.planned_calls = items

    # ------------------------------------------------------------------
    # SM-01/02/03/05/06: Unified state-machine lifecycle methods
    # ------------------------------------------------------------------

    def _make_view_category(self, tool_name: str) -> str:
        try:
            from hermes_cli.tui.tool_category import classify_tool
            return classify_tool(tool_name).value
        except Exception:
            return "unknown"

    def _wire_args(self, view: ToolCallViewState, args: "dict[str, Any]") -> None:
        """SM-03: attach invocation args to block and panel."""
        args_copy = dict(args or {})
        view.args = args_copy
        if view.block is not None and hasattr(view.block, "_tool_input"):
            view.block._tool_input = args_copy
        if view.panel is not None and hasattr(view.panel, "set_tool_args"):
            view.panel.set_tool_args(args_copy)
            header = getattr(view.block, "_header", None) if view.block is not None else None
            if header is not None:
                try:
                    header.refresh()
                except Exception:
                    pass

    def _pop_pending_gen_for(self, tool_name: str) -> "ToolCallViewState | None":
        """Pop the oldest GENERATED record matching tool_name, or any GENERATED if none match."""
        if not self._tool_views_by_gen_index:
            return None
        # First pass: match by tool_name
        for gen_idx in sorted(self._tool_views_by_gen_index):
            v = self._tool_views_by_gen_index[gen_idx]
            if v.state == ToolCallState.GENERATED and v.tool_name == tool_name:
                del self._tool_views_by_gen_index[gen_idx]
                return v
        # Second pass: any GENERATED (FIFO fallback — handles provider skipping gen-start)
        for gen_idx in sorted(self._tool_views_by_gen_index):
            v = self._tool_views_by_gen_index[gen_idx]
            if v.state == ToolCallState.GENERATED:
                del self._tool_views_by_gen_index[gen_idx]
                return v
        return None

    def _cancel_first_pending_gen(self, tool_name: str) -> None:
        """Cancel the oldest GENERATED record for tool_name (e.g. background terminal)."""
        for gen_idx in sorted(self._tool_views_by_gen_index):
            v = self._tool_views_by_gen_index[gen_idx]
            if v.state == ToolCallState.GENERATED and v.tool_name == tool_name:
                v.state = ToolCallState.CANCELLED
                del self._tool_views_by_gen_index[gen_idx]
                if v.block is not None:
                    try:
                        v.block.remove()
                    except Exception:
                        pass
                return

    def _compute_parent_depth(self, tool_call_id: str) -> "tuple[str | None, int]":
        """Return (parent_tool_call_id, depth) for a new tool call."""
        parent_id: "str | None" = getattr(self.app, "_explicit_parent_map", {}).pop(tool_call_id, None)
        if parent_id is None and self._agent_stack:
            parent_id = self._agent_stack[-1]
        parent_rec = self._turn_tool_calls.get(parent_id) if parent_id else None
        computed = (parent_rec.depth + 1) if parent_rec else 0
        return parent_id, min(computed, 3)

    def open_tool_generation(self, gen_index: int, tool_name: str) -> None:
        """SM-02: Create a GENERATED view state record and open the visual block.

        Called from the event loop via call_from_thread. Returns None — callers
        must not capture a block reference; all block access goes through the
        state machine.
        """
        cat = self._make_view_category(tool_name)
        now = _time.monotonic()
        turn_start = getattr(self.app, "_turn_start_monotonic", None) or now
        view = ToolCallViewState(
            tool_call_id=None,
            gen_index=gen_index,
            tool_name=tool_name,
            label=get_display_name(tool_name),
            args={},
            state=ToolCallState.GENERATED,
            block=None,
            panel=None,
            parent_tool_call_id=None,
            category=cat,
            depth=0,
            start_s=round(now - turn_start, 4),
        )

        # Route to appropriate block creator
        block: "Any | None" = None
        if tool_name == "execute_code":
            block = self.open_execute_code_block(gen_index)
        elif tool_name in ("write_file", "create_file"):
            block = self.open_write_file_block(gen_index, "")
        elif tool_name not in self._SKILL_TOOL_NAMES:
            block = self.open_gen_block(tool_name)
        # Skill tools intentionally get no gen block — deferred to start_tool_call

        view.block = block
        self._tool_views_by_gen_index[gen_index] = view

    def start_tool_call(
        self,
        tool_call_id: str,
        tool_name: str,
        args: "dict[str, Any] | None",
    ) -> None:
        """SM-02: Adopt a GENERATED record or create a new STARTED record.

        If a GENERATED record exists, adopts it (assigns tool_call_id, args,
        parent, depth) and transitions to STARTED.  If no GENERATED record
        exists, creates a new record directly in STARTED (non-streaming or
        provider paths that skip gen-start).

        All DOM creation and active-block indexing happens here; the CLI
        callback layer only forwards parsed provider events.
        """
        args_clean = dict(args or {})

        # Background terminal: cancel the pending gen block and skip start
        if tool_name == "terminal" and args_clean.get("background"):
            self._cancel_first_pending_gen("terminal")
            return

        parent_id, depth = self._compute_parent_depth(tool_call_id)
        now = _time.monotonic()
        turn_start = getattr(self.app, "_turn_start_monotonic", None) or now

        view = self._pop_pending_gen_for(tool_name)

        if view is not None:
            # ── Adopted path ──────────────────────────────────────────────
            view.tool_call_id = tool_call_id
            view.state = ToolCallState.STARTED
            view.parent_tool_call_id = parent_id
            view.depth = depth
            self._tool_views_by_id[tool_call_id] = view

            # Register the pre-created block in the active map
            if view.block is not None:
                self.app._active_streaming_blocks[tool_call_id] = view.block
                self.app._streaming_tool_count = len(self.app._active_streaming_blocks)

            # Handle tool-specific finalization on the adopted block
            if tool_name == "execute_code":
                code = args_clean.get("code", "")
                if not isinstance(code, str):
                    code = ""
                if view.block is not None and hasattr(view.block, "finalize_code"):
                    try:
                        self.app.call_after_refresh(lambda _b=view.block, _c=code: _b.finalize_code(_c))
                    except Exception:
                        logger.debug("finalize_code scheduling failed", exc_info=True)
            elif tool_name in ("write_file", "create_file"):
                path = args_clean.get("path", "")
                if not isinstance(path, str):
                    path = ""
                if view.block is not None and path and hasattr(view.block, "set_final_path"):
                    try:
                        view.block.set_final_path(path)
                    except Exception:
                        logger.debug("set_final_path failed", exc_info=True)

            # Update parent children list
            parent_rec = self._turn_tool_calls.get(parent_id) if parent_id else None
            if parent_rec is not None:
                parent_rec.children.append(tool_call_id)

            # Backward-compat _ToolCallRecord
            from hermes_cli.tui.tool_category import classify_tool as _ct
            try:
                cat = _ct(tool_name).value
            except Exception:
                cat = view.category
            rec = _ToolCallRecord(
                tool_call_id=tool_call_id,
                parent_tool_call_id=parent_id,
                label=view.label,
                tool_name=tool_name,
                category=cat,
                depth=depth,
                start_s=round(now - turn_start, 4),
                dur_ms=None,
                is_error=False,
                error_kind=None,
                mcp_server=None,
            )
            self._turn_tool_calls[tool_call_id] = rec

            # TCS-HIGH-03: Backfill panel identity onto adopted generated block
            if view.block is not None:
                # 1. Backfill tool_call_id onto the block itself
                if hasattr(view.block, "__dict__"):
                    view.block._tool_call_id = tool_call_id

                # 2. Resolve panel from block attribute or ancestor walk
                _adopted_panel = getattr(view.block, "_tool_panel", None)
                if _adopted_panel is None:
                    try:
                        from hermes_cli.tui.tool_panel._core import ToolPanel as _TP
                        from hermes_cli.tui.tool_panel._child import ChildPanel as _CP
                        _ancestor = view.block.parent
                        while _ancestor is not None:
                            if isinstance(_ancestor, (_TP, _CP)):
                                _adopted_panel = _ancestor
                                break
                            _ancestor = getattr(_ancestor, "parent", None)
                    except Exception:
                        logger.debug("panel ancestor walk failed for %s", tool_call_id, exc_info=True)

                # 3. Store panel on view
                view.panel = _adopted_panel

                # 4. Backfill panel identity
                if _adopted_panel is not None:
                    _adopted_panel._plan_tool_call_id = tool_call_id
                    _target_id = f"tool-{tool_call_id}"
                    try:
                        self.app.query(f"#{_target_id}")
                    except Exception:
                        try:
                            _adopted_panel.id = _target_id
                        except Exception:
                            logger.debug("panel ID backfill failed for %s", tool_call_id, exc_info=True)

            # Wire args (SM-03)
            self._wire_args(view, args_clean)

            # 5. Refresh panel so updated args/invocation copy are visible immediately
            if view.panel is not None:
                try:
                    view.panel.refresh()
                except Exception:
                    pass

            # A1: increment open tool count and set phase (gen-start didn't do this)
            self._open_tool_count += 1
            from hermes_cli.tui.agent_phase import Phase as _Phase
            self.app.status_phase = _Phase.TOOL_EXEC

        else:
            # ── Direct-start path (no GENERATED record) ───────────────────
            if tool_name in ("write_file", "create_file", "str_replace_editor"):
                # SM-06: create write-tool fallback block
                block, panel = self._create_write_fallback(tool_call_id, tool_name, args_clean)
            else:
                # For all other tools, use the existing method which handles
                # DOM mounting, record creation, phase, agent stack, etc.
                label = get_display_name(tool_name)
                self.open_streaming_tool_block(tool_call_id, label, tool_name=tool_name)
                block = self.app._active_streaming_blocks.get(tool_call_id)
                panel = None

            cat = self._make_view_category(tool_name)
            view = ToolCallViewState(
                tool_call_id=tool_call_id,
                gen_index=None,
                tool_name=tool_name,
                label=get_display_name(tool_name),
                args=args_clean,
                state=ToolCallState.STARTED,
                block=block,
                panel=panel,
                parent_tool_call_id=parent_id,
                category=cat,
                depth=depth,
                start_s=round(now - turn_start, 4),
            )
            self._tool_views_by_id[tool_call_id] = view
            # Wire args (SM-03) — for the existing open_streaming_tool_block path,
            # _wire_args also stores on the block.
            self._wire_args(view, args_clean)

        # PlanPanel: transition PENDING → RUNNING
        self.mark_plan_running(tool_call_id)

    def _create_write_fallback(
        self, tool_call_id: str, tool_name: str, args: "dict[str, Any]"
    ) -> "tuple[Any, Any]":
        """SM-06: Create a WriteFileBlock fallback when no gen block exists."""
        path = args.get("path", "")
        if not isinstance(path, str):
            path = ""
        output = self._get_output_panel()
        block: "Any | None" = None
        panel: "Any | None" = None
        try:
            from hermes_cli.tui.write_file_block import WriteFileBlock
            from hermes_cli.tui.tool_panel import ToolPanel as _ToolPanel
            block = WriteFileBlock(path=path)
            panel = _ToolPanel(block, tool_name=tool_name)
            panel._plan_tool_call_id = tool_call_id
            if output is not None:
                msg = output.current_message or output.new_message()
                msg._mount_nonprose_block(panel)
                self.app._browse_total += 1
                if not output._user_scrolled_up:
                    self.app.call_after_refresh(output.scroll_end, animate=False)
            self.app._active_streaming_blocks[tool_call_id] = block
            self.app._streaming_tool_count = len(self.app._active_streaming_blocks)
            # A1: count this as an open tool block
            self._open_tool_count += 1
            from hermes_cli.tui.agent_phase import Phase as _Phase
            self.app.status_phase = _Phase.TOOL_EXEC
            # Backward-compat record
            from hermes_cli.tui.tool_category import classify_tool as _ct
            try:
                cat = _ct(tool_name).value
            except Exception:
                cat = "file_tools"
            now = _time.monotonic()
            turn_start = getattr(self.app, "_turn_start_monotonic", None) or now
            rec = _ToolCallRecord(
                tool_call_id=tool_call_id,
                parent_tool_call_id=None,
                label=get_display_name(tool_name),
                tool_name=tool_name,
                category=cat,
                depth=0,
                start_s=round(now - turn_start, 4),
                dur_ms=None,
                is_error=False,
                error_kind=None,
                mcp_server=None,
            )
            self._turn_tool_calls[tool_call_id] = rec
        except Exception:
            logger.warning("_create_write_fallback failed for %s id=%s", tool_name, tool_call_id, exc_info=True)
        return block, panel

    def append_tool_output(self, tool_call_id: str, line: str) -> None:
        """SM-02: Transition STARTED→STREAMING on first call; append line to block.

        Idempotent on terminal states; logs warning for unknown IDs.
        """
        if not line:
            return
        view = self._tool_views_by_id.get(tool_call_id)
        if view is None:
            logger.warning("append_tool_output: unknown tool_call_id=%s", tool_call_id)
            return
        if view.state in (ToolCallState.DONE, ToolCallState.ERROR,
                          ToolCallState.CANCELLED, ToolCallState.REMOVED):
            return
        if view.state == ToolCallState.STARTED:
            view.state = ToolCallState.STREAMING
        self.append_streaming_line(tool_call_id, line)

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
        """SM-02: Complete a tool call. Idempotent on terminal states.

        Enters COMPLETING (transient), closes the streaming block, marks the
        PlanPanel done (SM-05: always, regardless of display.tool_progress),
        then exits to DONE or ERROR.

        When `duration` is supplied it overrides the inferred block duration.
        """
        view = self._tool_views_by_id.get(tool_call_id)

        # Idempotent if already terminal (or unknown — still complete plan)
        _terminal = (ToolCallState.DONE, ToolCallState.ERROR,
                     ToolCallState.CANCELLED, ToolCallState.REMOVED)
        if view is not None and view.state in _terminal:
            return

        # When view is absent the tool was already terminalized (e.g. via remove).
        # Skip block closure to avoid duplicate close; still mark plan done below.
        _view_absent = view is None

        if view is not None:
            view.state = ToolCallState.COMPLETING

        # Resolve duration — supplied arg takes precedence over block inference
        _duration: str = duration or ""
        if not _duration:
            import time as _t
            block = self.app._active_streaming_blocks.get(tool_call_id)
            if block is not None:
                started = getattr(block, "_stream_started_at", None)
                if started is not None:
                    elapsed_ms = (_t.monotonic() - started) * 1000.0
                    if elapsed_ms >= 1000:
                        _duration = f"{elapsed_ms/1000:.1f}s"
                    else:
                        _duration = f"{elapsed_ms:.0f}ms"

        # Close the streaming block only when view was present (not already terminalized)
        if not _view_absent:
            if diff_lines is not None:
                self.close_streaming_tool_block_with_diff(
                    tool_call_id, _duration, is_error, diff_lines, header_stats, summary
                )
            else:
                self.close_streaming_tool_block(
                    tool_call_id, _duration, is_error, summary, result_lines
                )

        # SM-05: always mark plan done regardless of tool_progress mode
        dur_ms = 0
        try:
            if _duration.endswith("ms"):
                dur_ms = int(float(_duration[:-2]))
            elif _duration.endswith("s"):
                dur_ms = int(float(_duration[:-1]) * 1000)
        except Exception:
            pass
        self.mark_plan_done(tool_call_id, is_error=is_error, dur_ms=dur_ms)

        # Update _turn_tool_calls even when block was absent
        rec = self._turn_tool_calls.get(tool_call_id)
        if rec is not None:
            if dur_ms:
                rec.dur_ms = dur_ms
            rec.is_error = is_error

        # Update view state to terminal
        if view is not None:
            view.state = ToolCallState.ERROR if is_error else ToolCallState.DONE
            view.is_error = is_error
            # Remove from active indexes but retain as immutable snapshot
            self._tool_views_by_id.pop(tool_call_id, None)
            # Note: we do NOT re-insert — snapshot is accessible via _turn_tool_calls

    def cancel_tool_call(
        self,
        tool_call_id: "str | None" = None,
        gen_index: "int | None" = None,
    ) -> None:
        """SM-02: Cancel a tool call (GENERATED, STARTED, or STREAMING).

        Lookup order: tool_call_id takes precedence over gen_index.
        Raises ValueError if both are None.
        No-op with warning if no matching record exists.
        """
        if tool_call_id is None and gen_index is None:
            raise ValueError("cancel_tool_call requires tool_call_id or gen_index")

        view: "ToolCallViewState | None" = None
        if tool_call_id is not None:
            view = self._tool_views_by_id.get(tool_call_id)
        if view is None and gen_index is not None:
            view = self._tool_views_by_gen_index.get(gen_index)

        if view is None:
            logger.warning("cancel_tool_call: no record for tool_call_id=%s gen_index=%s",
                           tool_call_id, gen_index)
            return

        _terminal = (ToolCallState.DONE, ToolCallState.ERROR,
                     ToolCallState.CANCELLED, ToolCallState.REMOVED)
        if view.state in _terminal:
            return

        # _terminalize_tool_view handles removal from both indexes
        self._terminalize_tool_view(
            view.tool_call_id or "",
            terminal_state=ToolCallState.CANCELLED,
            mark_plan=True,
            remove_visual=True,
        )
        # Also remove gen_index lookup if cancellation was via gen_index
        if gen_index is not None and gen_index in self._tool_views_by_gen_index:
            self._tool_views_by_gen_index.pop(gen_index, None)

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
