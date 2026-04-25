"""Tool block mounting, streaming, reasoning, plan-call tracking service extracted from _app_tool_rendering.py."""
from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass, field as _field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Literal

from textual.css.query import NoMatches

from hermes_cli.tool_icons import get_display_name
from hermes_cli.tui.tool_panel.density import DensityTier
from .base import AppService

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp
    from hermes_cli.tui.tool_payload import ClassificationResult

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
    started_at: float = _field(default_factory=_time.monotonic)
    dur_ms: "int | None" = None
    is_error: bool = False
    error_kind: "str | None" = None
    children: "list[str]" = _field(default_factory=list)
    # AXIS-2: KIND axis — stamped once at COMPLETING by the classifier.
    kind: "ClassificationResult | None" = None
    # AXIS-2: DENSITY axis — Move 1 replaces this mirror with the resolver.
    density: DensityTier = _field(default=DensityTier.DEFAULT)
    # AXIS-3: per-instance watcher list.
    _watchers: "list[_AxisWatcher]" = _field(default_factory=list, repr=False, compare=False)


# ---------------------------------------------------------------------------
# AXIS-3: Observer hook
# ---------------------------------------------------------------------------

AxisName = Literal["state", "kind", "density"]
_AxisWatcher = Callable[["ToolCallViewState", AxisName, Any, Any], None]


def add_axis_watcher(view: "ToolCallViewState", watcher: "_AxisWatcher") -> None:
    """Register a watcher. Called as watcher(view, axis, old, new) after each set_axis."""
    view._watchers.append(watcher)


def remove_axis_watcher(view: "ToolCallViewState", watcher: "_AxisWatcher") -> None:
    """Best-effort remove; silent if absent."""
    try:
        view._watchers.remove(watcher)
    except ValueError:
        pass  # already gone — safe


def set_axis(view: "ToolCallViewState", axis: "AxisName", value: Any) -> None:
    """Single mutation entry point that fires watchers.

    Direct field assignment still works (existing call sites unchanged); only
    callers that want change notifications must route through set_axis.
    """
    old = getattr(view, axis)
    if old == value:
        return
    setattr(view, axis, value)
    for w in list(view._watchers):
        try:
            w(view, axis, old, value)
        except Exception:
            logger.exception("axis watcher failed (axis=%s); continuing", axis)


def _parse_duration_ms(s: "str | None") -> int:
    """Parse duration string like '1.2s', '450ms', '900us' into integer milliseconds.

    Returns 0 on parse failure / empty / None; never raises.
    """
    if not s:
        return 0
    try:
        s = s.strip()
        if s.endswith("µs") or s.endswith("us"):
            return max(0, int(float(s[:-2]) / 1000))
        if s.endswith("ms"):
            return max(0, int(float(s[:-2])))
        if s.endswith("s"):
            return max(0, int(float(s[:-1]) * 1000))
        return max(0, int(float(s)))
    except (ValueError, TypeError):
        logger.debug("could not parse duration %r", s)
        return 0


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
            logger.debug("DrawbrailleOverlay.signal('reasoning') failed", exc_info=True)

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
                logger.debug("DrawbrailleOverlay.signal('thinking') failed", exc_info=True)

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
                panel_id: "str | None" = None  # collision: caller will skip suffix
            except NoMatches:  # vocab-2: ID free → use base
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
            cat_enum = classify_tool(tool_name or "")
            cat = cat_enum.value

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
                        logger.debug("depth-warning _Static mount on ancestor panel failed", exc_info=True)

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
                logger.debug("panel.add_class('--streaming') failed", exc_info=True)
            # A1: increment open tool count and set TOOL_EXEC phase
            self._open_tool_count += 1
            from hermes_cli.tui.agent_phase import Phase as _Phase
            self.app.status_phase = _Phase.TOOL_EXEC
            try:
                from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay as _DO
                self.app.query_one(_DO).signal("tool")
            except Exception:
                logger.debug("DrawbrailleOverlay.signal('tool') failed", exc_info=True)
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
        # R2-HIGH-01: route counters/phase/active-name/agent-stack/record-update
        # through the unified helper. mark_plan=False — complete_tool_call calls
        # mark_plan_done explicitly after this method returns.
        self._terminalize_tool_view(
            tool_call_id,
            terminal_state=ToolCallState.ERROR if is_error else ToolCallState.DONE,
            is_error=is_error,
            mark_plan=False,
            remove_visual=False,
            delete_view=False,
            dur_ms=_parse_duration_ms(duration),
        )
        self.app._svc_commands.update_anim_hint()
        panel = self._get_output_panel()
        if panel is not None and not panel._user_scrolled_up:
            self.app.call_after_refresh(panel.scroll_end, animate=False)
        try:
            from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay
            ov = self.app.query_one(DrawbrailleOverlay)
            ov.signal("error" if is_error else "thinking")
        except Exception:
            logger.debug("draw overlay signal failed", exc_info=True)

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
        # R2-HIGH-01: unified cleanup; symmetric with non-diff path.
        self._terminalize_tool_view(
            tool_call_id,
            terminal_state=ToolCallState.ERROR if is_error else ToolCallState.DONE,
            is_error=is_error,
            mark_plan=False,
            remove_visual=False,
            delete_view=False,
            dur_ms=_parse_duration_ms(duration),
        )
        panel = self._get_output_panel()
        if panel is not None and not panel._user_scrolled_up:
            self.app.call_after_refresh(panel.scroll_end, animate=False)
        try:
            from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay
            ov = self.app.query_one(DrawbrailleOverlay)
            ov.signal("error" if is_error else "thinking")
        except Exception:
            logger.debug("draw overlay signal failed", exc_info=True)

    def remove_streaming_tool_block(self, tool_call_id: str) -> None:
        """Remove a streaming block from the DOM entirely. Event-loop only."""
        self._terminalize_tool_view(
            tool_call_id,
            terminal_state=ToolCallState.REMOVED,
            mark_plan=False,
            remove_visual=True,
            delete_view=True,
        )

    # ------------------------------------------------------------------
    # PlanPanel mutations — event-loop only
    # ------------------------------------------------------------------

    def set_plan_batch(self, batch: "list[tuple[str, str, str, dict]]") -> None:
        """Seed planned_calls from a new tool batch."""
        from hermes_cli.tui.plan_types import PlannedCall, PlanState
        current: list = list(getattr(self.app, "planned_calls", []))
        kept = [c for c in current if c.state in (PlanState.DONE, PlanState.ERROR, PlanState.CANCELLED, PlanState.SKIPPED)]
        new_entries = []
        import json as _json
        from hermes_cli.tui.tool_category import classify_tool
        for tool_call_id, tool_name, label, args in batch:
            try:
                raw = _json.dumps(args, ensure_ascii=False)
                preview = raw[:60] + ("…" if len(raw) > 60 else "")
            except (TypeError, ValueError):  # vocab-2: non-serializable args → empty preview
                preview = ""
            cat = classify_tool(tool_name).value
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
            if call.tool_call_id == tool_call_id:
                # R2-HIGH-01: cross-path cancel-vs-complete race — preserve a CANCELLED
                # or already-DONE row even when complete_tool_call arrives later.
                if call.state in (PlanState.DONE, PlanState.CANCELLED):
                    return
                if call.state in (PlanState.PENDING, PlanState.RUNNING):
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
    # R2-HIGH-01: unified terminal cleanup helper
    # ------------------------------------------------------------------

    def _terminalize_tool_view(
        self,
        tool_call_id: "str | None",
        *,
        terminal_state: ToolCallState,
        is_error: bool = False,
        mark_plan: bool = True,
        remove_visual: bool = False,
        delete_view: bool = False,
        dur_ms: "int | None" = None,
        view: "ToolCallViewState | None" = None,
        gen_index: "int | None" = None,
    ) -> "ToolCallViewState | None":
        """Single terminal cleanup path for remove / cancel / close.

        Resolves the view, captures `prev_state` BEFORE any mutation, then
        decrements counters / clears active fields / updates phase / writes
        the terminal state via the axis bus / removes the visual / pops
        index entries — in that order. See spec R2-HIGH-01.
        """
        # Step 1: resolve view
        if view is None and tool_call_id:
            view = self._tool_views_by_id.get(tool_call_id)
        if view is None and gen_index is not None:
            view = self._tool_views_by_gen_index.get(gen_index)

        if view is None and (
            not tool_call_id or tool_call_id not in self.app._active_streaming_blocks
        ):
            return None

        prev_state = view.state if view is not None else None

        _terminal = (ToolCallState.DONE, ToolCallState.ERROR,
                     ToolCallState.CANCELLED, ToolCallState.REMOVED)
        if view is not None and prev_state in _terminal:
            return view

        # Step 2: pop active streaming block + refresh count
        if tool_call_id:
            self.app._active_streaming_blocks.pop(tool_call_id, None)
            self.app._streaming_tool_count = len(self.app._active_streaming_blocks)

        # Step 3: decrement open tool count for non-terminal in-flight states
        _inflight = (ToolCallState.STARTED, ToolCallState.STREAMING,
                     ToolCallState.COMPLETING)
        if prev_state in _inflight:
            self._open_tool_count = max(0, self._open_tool_count - 1)

        # Step 4: remove from agent stack
        if tool_call_id and tool_call_id in self._agent_stack:
            try:
                self._agent_stack.remove(tool_call_id)
            except ValueError:
                pass  # already removed; concurrent cleanup — safe

        # Step 5: clear _active_tool_name only when this view owns it
        # OR when no tools remain open
        active_name = getattr(self.app, "_active_tool_name", "")
        if view is not None and active_name and active_name == view.tool_name:
            self.app._active_tool_name = ""
        elif self._open_tool_count == 0:
            self.app._active_tool_name = ""

        # Step 6: update status_phase
        if self._open_tool_count == 0:
            from hermes_cli.tui.agent_phase import Phase as _Phase
            if getattr(self.app, "agent_running", False):
                self.app.status_phase = _Phase.REASONING
            else:
                self.app.status_phase = _Phase.IDLE

        # Step 7: dispatch plan transition
        if mark_plan and tool_call_id:
            if terminal_state in (ToolCallState.DONE, ToolCallState.ERROR):
                self.mark_plan_done(tool_call_id, is_error=is_error, dur_ms=dur_ms or 0)
            elif terminal_state == ToolCallState.CANCELLED:
                self.mark_plan_cancelled(tool_call_id)
            # REMOVED: no plan mutation; visual-only cleanup

        # Step 8: update _ToolCallRecord
        if tool_call_id:
            rec = self._turn_tool_calls.get(tool_call_id)
            if rec is not None:
                rec.is_error = is_error
                if dur_ms is not None:
                    rec.dur_ms = dur_ms

        # Step 9: write terminal state via axis bus (fires watchers exactly once).
        # Mirror is_error onto the view BEFORE the state write so any watcher
        # reading view.is_error during the state-change callback sees the
        # terminal value, not the in-flight value (R3-AXIS-03).
        if view is not None:
            view.is_error = is_error
            set_axis(view, "state", terminal_state)

        # Step 10: remove visual
        if remove_visual and view is not None and view.block is not None:
            try:
                panel = self._panel_for_block(view.block)
                if panel is not None:
                    panel.remove()
                else:
                    view.block.remove()
            except Exception:
                logger.debug("terminalize visual remove failed", exc_info=True)

        # Step 11: pop view from index maps
        if tool_call_id:
            self._tool_views_by_id.pop(tool_call_id, None)
        if view is not None and view.gen_index is not None:
            self._tool_views_by_gen_index.pop(view.gen_index, None)

        # Step 12: optional _turn_tool_calls deletion
        if delete_view and tool_call_id:
            self._turn_tool_calls.pop(tool_call_id, None)

        return view

    # ------------------------------------------------------------------
    # SM-01/02/03/05/06: Unified state-machine lifecycle methods
    # ------------------------------------------------------------------

    _PANEL_CLASS_NAMES = frozenset({"ToolPanel", "ChildPanel", "SubAgentPanel"})

    def _panel_for_block(self, block: "Any | None") -> "Any | None":
        """TCL-MED-01: Return the enclosing panel for a block.

        Checks _tool_panel attr first, then walks block.parent and
        block.parent.parent for a ToolPanel/ChildPanel/SubAgentPanel.
        Returns None without logging if block is unmounted.
        """
        if block is None:
            return None
        attr = getattr(block, "_tool_panel", None)
        if attr is not None:
            return attr
        parent = getattr(block, "parent", None)
        if parent is None:
            return None
        if type(parent).__name__ in self._PANEL_CLASS_NAMES:
            return parent
        grandparent = getattr(parent, "parent", None)
        if grandparent is not None and type(grandparent).__name__ in self._PANEL_CLASS_NAMES:
            return grandparent
        return None

    def _make_view_category(self, tool_name: str) -> str:
        from hermes_cli.tui.tool_category import classify_tool
        return classify_tool(tool_name).value

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
                    logger.debug("header.refresh() post-arg-wire failed", exc_info=True)

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
        """Cancel the oldest GENERATED record for tool_name (e.g. background terminal).

        R3-AXIS-02: routes through _terminalize_tool_view so the GENERATED→
        CANCELLED transition fires axis watchers and visual-remove failures
        log instead of being silently swallowed. mark_plan=False because a
        GENERATED view never produced an active Plan row.
        """
        for gen_idx in sorted(self._tool_views_by_gen_index):
            v = self._tool_views_by_gen_index[gen_idx]
            if v.state == ToolCallState.GENERATED and v.tool_name == tool_name:
                self._terminalize_tool_view(
                    tool_call_id=v.tool_call_id,
                    terminal_state=ToolCallState.CANCELLED,
                    is_error=False,
                    mark_plan=False,
                    remove_visual=True,
                    delete_view=False,
                    view=v,
                    gen_index=gen_idx,
                )
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
        # TCL-MED-01: capture panel back-reference via helper (attr or parent walk)
        view.panel = self._panel_for_block(block)
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
                    import json as _json
                    try:
                        parsed = _json.loads(accumulated)
                    except _json.JSONDecodeError:  # vocab-2: partial JSON during stream → skip total
                        logger.debug("partial JSON during stream — skipping total update", exc_info=True)
                    else:
                        if isinstance(parsed, dict):
                            try:
                                total = int(parsed.get("total_size") or parsed.get("bytes_written") or 0)
                            except (TypeError, ValueError):  # vocab-2: non-numeric total → skip
                                logger.debug("non-numeric total in stream payload — skipping total update", exc_info=True)
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
            view.started_at = _time.monotonic()  # reset from gen-block creation time to actual tool start
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
            cat = _ct(tool_name).value
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

            # TCL-MED-01: populate view.panel via helper now that ID is known
            if view.panel is None and view.block is not None:
                view.panel = self._panel_for_block(view.block)
            if view.panel is not None and hasattr(view.panel, "_plan_tool_call_id"):
                view.panel._plan_tool_call_id = tool_call_id

            # R2-HIGH-02: backfill block + DOM panel id for adopted generated panels
            if view.block is not None:
                try:
                    view.block._tool_call_id = tool_call_id
                except AttributeError:
                    logger.debug("block %r does not accept _tool_call_id", type(view.block).__name__)

            if view.panel is not None:
                new_id = f"tool-{tool_call_id}"
                current_id = getattr(view.panel, "id", None)
                if current_id != new_id:
                    try:
                        existing = self.app.query(f"#{new_id}")
                        if not list(existing):
                            view.panel.id = new_id
                        else:
                            logger.debug("DOM id %s already present; keeping panel id=%s", new_id, current_id)
                    except Exception:
                        logger.debug("R2-HIGH-02 DOM id update failed", exc_info=True)

            # Wire args (SM-03)
            self._wire_args(view, args_clean)
            if view.panel is not None:
                try:
                    view.panel.refresh()
                except Exception:
                    logger.debug("panel.refresh after _wire_args failed", exc_info=True)

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
                # TCL-MED-01: capture panel back-ref via helper
                panel = self._panel_for_block(block)

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
        # classify_tool is total; hoist out of the outer try so the AST sweep
        # can verify no try/except Exception wraps it (R3-VOCAB-2 invariant).
        from hermes_cli.tui.tool_category import classify_tool as _ct
        cat = _ct(tool_name).value
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
        # R3-AXIS-01: route STARTED→STREAMING through the axis bus so watchers
        # see the most common state transition in the system. set_axis is a
        # no-op when old == new, so re-entry from STREAMING is safe.
        if view.state == ToolCallState.STARTED:
            set_axis(view, "state", ToolCallState.STREAMING)
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
            set_axis(view, "state", ToolCallState.COMPLETING)
            self._stamp_kind_on_completing(view, result_lines)

        # Compute duration string for UI display
        dur_ms_float: float = 0.0
        block = self.app._active_streaming_blocks.get(tool_call_id)
        if duration is not None:
            # Caller supplied duration (e.g. CLI's _stream_start_times timer)
            pass
        else:
            if view is not None:
                dur_ms_float = (_time.monotonic() - view.started_at) * 1000.0
                if dur_ms_float >= 1000:
                    duration = f"{dur_ms_float/1000:.1f}s"
                else:
                    duration = f"{dur_ms_float:.0f}ms"
            elif block is not None:
                started = getattr(block, "_stream_started_at", None)
                if started is not None:
                    elapsed_ms = (_time.monotonic() - started) * 1000.0
                    dur_ms_float = elapsed_ms
                    if elapsed_ms >= 1000:
                        duration = f"{elapsed_ms/1000:.1f}s"
                    else:
                        duration = f"{elapsed_ms:.0f}ms"
            if duration is None:
                duration = ""

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
        dur_ms_int = int(dur_ms_float)
        self.mark_plan_done(tool_call_id, is_error=is_error, dur_ms=dur_ms_int)

        # Record tool call latency into perf probe
        from hermes_cli.tui.perf import _tool_probe
        _tool_probe.record(tool_name, tool_call_id, dur_ms_float, is_error=is_error)

        # R3-AXIS-03: terminal write + index pop already done by
        # _terminalize_tool_view inside close_streaming_tool_block (Step 9 + Step 11).

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

        # Helper handles terminal-state short-circuit, counter decrement, plan
        # cancel, visual removal, and index pops in the correct order.
        self._terminalize_tool_view(
            view.tool_call_id if view.tool_call_id else None,
            terminal_state=ToolCallState.CANCELLED,
            is_error=False,
            mark_plan=True,
            remove_visual=True,
            delete_view=False,  # keep _turn_tool_calls record for /tools overlay history
            view=view,
            gen_index=gen_index if view.tool_call_id is None else None,
        )

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

    def _stamp_kind_on_completing(
        self,
        view: "ToolCallViewState",
        result_lines: "list[str] | None",
    ) -> None:
        """AXIS-4: classify once at COMPLETING and stamp onto view-state.

        Idempotent: only writes when view.kind is None. Exceptions are logged
        and swallowed — classifier failure must never break completion.
        """
        if view.kind is not None:
            return  # already stamped (defensive — shouldn't happen)
        try:
            from hermes_cli.tui.content_classifier import classify_content
            from hermes_cli.tui.tool_payload import ToolPayload
            output_raw = "\n".join(result_lines) if result_lines else ""
            payload = ToolPayload(
                tool_name=view.tool_name,
                category=view.category,
                args=view.args or {},
                input_display=None,
                output_raw=output_raw,
            )
            result = classify_content(payload)
        except Exception:
            logger.exception("AXIS-4: classifier failed during COMPLETING; leaving kind=None")
            return
        set_axis(view, "kind", result)
