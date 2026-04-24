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
        # SM-HIGH-02: buffered arg deltas keyed by gen_index
        self._pending_gen_arg_deltas: "dict[int, list[tuple[str, str]]]" = {}

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
        # SM-MED-01: capture panel back-reference from block
        view.panel = getattr(block, "_tool_panel", None) if block is not None else None
        self._tool_views_by_gen_index[gen_index] = view

        # SM-HIGH-02: drain any buffered arg deltas that arrived before the view
        self._drain_gen_arg_deltas(gen_index, view)

    def append_generation_args_delta(
        self,
        gen_index: int,
        tool_name: str,
        delta: str,
        accumulated: str,
    ) -> None:
        """SM-HIGH-02: Apply or buffer a generation arg delta. Event-loop only.

        If the view exists and has a block, applies the delta immediately.
        Otherwise buffers (delta, accumulated) for drain when the view opens.
        """
        view = self._tool_views_by_gen_index.get(gen_index)
        if view is not None and view.block is not None:
            self._apply_gen_arg_delta(view.block, tool_name, delta, accumulated)
        else:
            self._pending_gen_arg_deltas.setdefault(gen_index, []).append((delta, accumulated))

    def _apply_gen_arg_delta(
        self,
        block: "Any",
        tool_name: str,
        delta: str,
        accumulated: str,
    ) -> None:
        """Apply one arg delta to a block. No-op if block has no feed_delta."""
        if not hasattr(block, "feed_delta"):
            return
        try:
            block.feed_delta(delta)
        except Exception:
            logger.debug("feed_delta failed for %s", tool_name, exc_info=True)
        if tool_name in ("write_file", "create_file", "str_replace_editor"):
            if hasattr(block, "update_progress"):
                try:
                    written = len(accumulated.encode("utf-8", errors="replace"))
                    total = 0
                    try:
                        import json as _json
                        parsed = _json.loads(accumulated)
                        if isinstance(parsed, dict):
                            total = int(parsed.get("total_size") or parsed.get("bytes_written") or 0)
                    except Exception:
                        pass
                    block.update_progress(written, total)
                except Exception:
                    logger.debug("update_progress failed for %s", tool_name, exc_info=True)

    def _drain_gen_arg_deltas(self, gen_index: int, view: "ToolCallViewState") -> None:
        """SM-HIGH-02: Drain buffered deltas for gen_index into view.block."""
        buffered = self._pending_gen_arg_deltas.pop(gen_index, None)
        if not buffered or view.block is None:
            return
        for delta, accumulated in buffered:
            self._apply_gen_arg_delta(view.block, view.tool_name, delta, accumulated)

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

            # SM-MED-01: populate view.panel from block back-ref now that ID is known
            if view.panel is None and view.block is not None:
                view.panel = getattr(view.block, "_tool_panel", None)
            if view.panel is not None and hasattr(view.panel, "_plan_tool_call_id"):
                view.panel._plan_tool_call_id = tool_call_id

            # Wire args (SM-03)
            self._wire_args(view, args_clean)

            # SM-HIGH-02: discard any stale buffered deltas for the adopted gen slot
            if view.gen_index is not None:
                self._pending_gen_arg_deltas.pop(view.gen_index, None)

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
                # SM-MED-01: capture panel back-ref from block
                panel = getattr(block, "_tool_panel", None) if block is not None else None

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

        If `duration` is supplied, it takes precedence over the inferred value
        from the block's start time (SM-HIGH-01: CLI passes its own timer).
        """
        view = self._tool_views_by_id.get(tool_call_id)

        # Idempotent if already terminal (or unknown — still complete plan)
        _terminal = (ToolCallState.DONE, ToolCallState.ERROR,
                     ToolCallState.CANCELLED, ToolCallState.REMOVED)
        if view is not None and view.state in _terminal:
            return

        if view is not None:
            view.state = ToolCallState.COMPLETING

        # Compute duration string for UI display
        import time as _t
        if duration is not None:
            # Caller supplied duration (e.g. CLI's _stream_start_times timer)
            pass
        else:
            duration = ""
            block = self.app._active_streaming_blocks.get(tool_call_id)
            if block is not None:
                started = getattr(block, "_stream_started_at", None)
                if started is not None:
                    elapsed_ms = (_t.monotonic() - started) * 1000.0
                    if elapsed_ms >= 1000:
                        duration = f"{elapsed_ms/1000:.1f}s"
                    else:
                        duration = f"{elapsed_ms:.0f}ms"

        # Close the streaming block
        if diff_lines is not None:
            self.close_streaming_tool_block_with_diff(
                tool_call_id, duration, is_error, diff_lines, header_stats, summary
            )
        else:
            self.close_streaming_tool_block(
                tool_call_id, duration, is_error, summary, result_lines
            )

        # SM-05: always mark plan done regardless of tool_progress mode
        dur_ms = 0
        try:
            if duration.endswith("ms"):
                dur_ms = int(float(duration[:-2]))
            elif duration.endswith("s"):
                dur_ms = int(float(duration[:-1]) * 1000)
        except Exception:
            pass
        self.mark_plan_done(tool_call_id, is_error=is_error, dur_ms=dur_ms)

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
            view = self._tool_views_by_id.pop(tool_call_id, None)
        if view is None and gen_index is not None:
            view = self._tool_views_by_gen_index.pop(gen_index, None)

        if view is None:
            logger.warning("cancel_tool_call: no record for tool_call_id=%s gen_index=%s",
                           tool_call_id, gen_index)
            return

        _terminal = (ToolCallState.DONE, ToolCallState.ERROR,
                     ToolCallState.CANCELLED, ToolCallState.REMOVED)
        if view.state in _terminal:
            return

        view.state = ToolCallState.CANCELLED

        # Remove from active streaming blocks
        if view.tool_call_id:
            self.app._active_streaming_blocks.pop(view.tool_call_id, None)
            self.app._streaming_tool_count = len(self.app._active_streaming_blocks)

        # Remove visual block if present
        if view.block is not None:
            try:
                view.block.remove()
            except Exception:
                pass

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
