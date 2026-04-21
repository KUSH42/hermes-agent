"""_ToolRenderingMixin — tool block mounting / streaming lifecycle for HermesApp."""
from __future__ import annotations

import logging
from typing import Any

from textual.css.query import NoMatches

from hermes_cli.tool_icons import get_display_name

logger = logging.getLogger(__name__)


class _ToolRenderingMixin:
    """Tool block mounting and streaming lifecycle methods.

    Extracted from HermesApp to reduce file size.  Self is always a HermesApp
    instance at runtime — all attribute access on self is valid.
    """

    def _get_output_panel(self) -> "Any | None":
        """Return OutputPanel, cached after first successful lookup."""
        cached = getattr(self, "_cached_output_panel", None)
        if cached is not None and cached.is_mounted:
            return cached
        from hermes_cli.tui.widgets import OutputPanel
        try:
            panel = self.query_one(OutputPanel)  # type: ignore[attr-defined]
            self._cached_output_panel = panel  # type: ignore[attr-defined]
            return panel
        except NoMatches:
            return None

    # --- Reasoning ---

    def _current_message_panel(self) -> "Any | None":
        """Return the current MessagePanel, or None."""
        output = self._get_output_panel()
        if output is None:
            return None
        return output.current_message

    def open_reasoning(self, title: str = "Reasoning") -> None:
        """Open the reasoning panel. Safe to call from any thread via call_from_thread."""
        msg = self._current_message_panel()
        if msg is not None:
            msg.open_thinking_block(title)
        try:
            from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO
            self.query_one(_DO).signal("reasoning")  # type: ignore[attr-defined]
        except Exception:
            pass

    def append_reasoning(self, delta: str) -> None:
        """Append reasoning delta. Safe to call from any thread via call_from_thread."""
        msg = self._current_message_panel()
        if msg is not None:
            msg.append_thinking(delta)

    def close_reasoning(self) -> None:
        """Close the reasoning panel. Safe to call from any thread via call_from_thread."""
        msg = self._current_message_panel()
        if msg is not None:
            msg.close_thinking_block()
        if self.agent_running:  # type: ignore[attr-defined]
            try:
                from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO
                self.query_one(_DO).signal("thinking")  # type: ignore[attr-defined]
            except Exception:
                pass

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
        self._browse_total += 1  # type: ignore[attr-defined]
        if not output._user_scrolled_up:
            self.call_after_refresh(output.scroll_end, animate=False)  # type: ignore[attr-defined]

    # --- StreamingToolBlock lifecycle ---

    def _open_gen_block(self, tool_name: str) -> "Any | None":
        """Open a StreamingToolBlock at gen_start time. Event-loop only."""
        output = self._get_output_panel()
        if output is None:
            return None
        msg = output.current_message or output.new_message()
        block = msg.open_streaming_tool_block(label=get_display_name(tool_name), tool_name=tool_name)
        self._browse_total += 1  # type: ignore[attr-defined]
        if not output._user_scrolled_up:
            self.call_after_refresh(output.scroll_end, animate=False)  # type: ignore[attr-defined]
        return block

    def _open_execute_code_block(self, idx: int) -> "Any | None":
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
            self._browse_total += 1  # type: ignore[attr-defined]
            if not output._user_scrolled_up:
                self.call_after_refresh(output.scroll_end, animate=False)  # type: ignore[attr-defined]
            return block
        except Exception as e:
            logger.warning("_open_execute_code_block failed for idx=%d: %s", idx, e)
            return None

    def _open_write_file_block(self, idx: int, path: str) -> "Any | None":
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
            self._browse_total += 1  # type: ignore[attr-defined]
            if not output._user_scrolled_up:
                self.call_after_refresh(output.scroll_end, animate=False)  # type: ignore[attr-defined]
            return block
        except Exception as e:
            logger.warning("_open_write_file_block failed idx=%d: %s", idx, e)
            return None

    def open_streaming_tool_block(self, tool_call_id: str, label: str, tool_name: "str | None" = None) -> None:
        """Mount a StreamingToolBlock into OutputPanel before the live-output duo."""
        import time as _time
        output = self._get_output_panel()
        if output is None:
            return
        try:
            msg = output.current_message or output.new_message()
            base_panel_id = f"tool-{tool_call_id}"
            try:
                self.query_one(f"#{base_panel_id}")  # type: ignore[attr-defined]
                panel_id: "str | None" = None
            except Exception:
                panel_id = base_panel_id
            _turn_count = getattr(self, "_current_turn_tool_count", 0) + 1
            self._current_turn_tool_count = _turn_count  # type: ignore[attr-defined]
            _is_first = (_turn_count == 1)
            block = msg.open_streaming_tool_block(
                label=label, tool_name=tool_name, panel_id=panel_id,
                is_first_in_turn=_is_first,
            )
            self._active_streaming_blocks[tool_call_id] = block  # type: ignore[attr-defined]
            self._streaming_tool_count = len(self._active_streaming_blocks)  # type: ignore[attr-defined]
            self._active_tool_name = tool_name or ""  # type: ignore[attr-defined]
            try:
                from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO
                self.query_one(_DO).signal("tool")  # type: ignore[attr-defined]
            except Exception:
                pass
            self._update_anim_hint()  # type: ignore[attr-defined]
            now = _time.monotonic()
            if self._turn_start_monotonic is None:  # type: ignore[attr-defined]
                self._turn_start_monotonic = now  # type: ignore[attr-defined]
            try:
                from hermes_cli.tui.tool_category import classify_tool
                cat = classify_tool(tool_name or "").value
            except Exception:
                cat = "unknown"
            self._turn_tool_calls.append({  # type: ignore[attr-defined]
                "tool_call_id": tool_call_id,
                "name": tool_name or label,
                "category": cat,
                "start_s": round(now - self._turn_start_monotonic, 4),  # type: ignore[attr-defined]
                "dur_ms": None,
                "is_error": False,
                "error_kind": None,
                "args": {},
                "primary_result": "",
                "mcp_server": None,
            })
            msg.refresh(layout=True)
            self._browse_total += 1  # type: ignore[attr-defined]
            if not output._user_scrolled_up:
                self.call_after_refresh(output.scroll_end, animate=False)  # type: ignore[attr-defined]
        except NoMatches:
            pass

    def append_streaming_line(self, tool_call_id: str, line: str) -> None:
        """Append a line to the named streaming block. Event-loop only."""
        block = self._active_streaming_blocks.get(tool_call_id)  # type: ignore[attr-defined]
        if block is None:
            return
        block.append_line(line)
        panel = self._get_output_panel()
        if panel is not None and not panel._user_scrolled_up:
            self.call_after_refresh(panel.scroll_end, animate=False)  # type: ignore[attr-defined]

    def close_streaming_tool_block(
        self,
        tool_call_id: str,
        duration: str,
        is_error: bool = False,
        summary: "Any | None" = None,
        result_lines: "list[str] | None" = None,
    ) -> None:
        """Transition streaming block to COMPLETED state. Event-loop only."""
        from hermes_cli.tui.widgets import OutputPanel
        block = self._active_streaming_blocks.pop(tool_call_id, None)  # type: ignore[attr-defined]
        if block is None:
            return
        self._streaming_tool_count = len(self._active_streaming_blocks)  # type: ignore[attr-defined]
        if result_lines:
            for _line in result_lines:
                block.append_line(_line)
        block.complete(duration, is_error=is_error)
        if summary is not None:
            panel = getattr(block, "_tool_panel", None)
            if panel is not None:
                panel.set_result_summary_v4(summary)
        self._active_tool_name = ""  # type: ignore[attr-defined]
        self._update_anim_hint()  # type: ignore[attr-defined]
        for entry in self._turn_tool_calls:  # type: ignore[attr-defined]
            if entry["tool_call_id"] == tool_call_id:
                try:
                    ds = str(duration)
                    if ds.endswith("ms"):
                        entry["dur_ms"] = int(float(ds[:-2]))
                    elif ds.endswith("s"):
                        entry["dur_ms"] = int(float(ds[:-1]) * 1000)
                except Exception:
                    pass
                entry["is_error"] = is_error
                break
        panel = self._get_output_panel()
        if panel is not None and not panel._user_scrolled_up:
            self.call_after_refresh(panel.scroll_end, animate=False)  # type: ignore[attr-defined]
        try:
            from hermes_cli.tui.drawille_overlay import DrawilleOverlay
            ov = self.query_one(DrawilleOverlay)  # type: ignore[attr-defined]
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
        block = self._active_streaming_blocks.pop(tool_call_id, None)  # type: ignore[attr-defined]
        if block is None:
            return
        self._streaming_tool_count = len(self._active_streaming_blocks)  # type: ignore[attr-defined]
        block.inject_diff(diff_lines, header_stats)
        block.complete(duration, is_error=is_error)
        if summary is not None:
            panel = getattr(block, "_tool_panel", None)
            if panel is not None:
                panel.set_result_summary_v4(summary)
        for entry in self._turn_tool_calls:  # type: ignore[attr-defined]
            if entry["tool_call_id"] == tool_call_id:
                try:
                    ds = str(duration)
                    if ds.endswith("ms"):
                        entry["dur_ms"] = int(float(ds[:-2]))
                    elif ds.endswith("s"):
                        entry["dur_ms"] = int(float(ds[:-1]) * 1000)
                except Exception:
                    pass
                entry["is_error"] = is_error
                break
        panel = self._get_output_panel()
        if panel is not None and not panel._user_scrolled_up:
            self.call_after_refresh(panel.scroll_end, animate=False)  # type: ignore[attr-defined]
        try:
            from hermes_cli.tui.drawille_overlay import DrawilleOverlay
            ov = self.query_one(DrawilleOverlay)  # type: ignore[attr-defined]
            ov.signal("error" if is_error else "thinking")
        except Exception:
            pass

    def remove_streaming_tool_block(self, tool_call_id: str) -> None:
        """Remove a streaming block from the DOM entirely. Event-loop only."""
        block = self._active_streaming_blocks.pop(tool_call_id, None)  # type: ignore[attr-defined]
        if block is None:
            return
        self._streaming_tool_count = len(self._active_streaming_blocks)  # type: ignore[attr-defined]
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

    def current_turn_tool_calls(self) -> list[dict]:
        """Return a shallow copy of per-turn tool call records (P7 /tools overlay).

        Thread-safe: returns list(self._turn_tool_calls) — a shallow copy.
        Dicts inside are fresh snapshots; caller must not mutate them.
        """
        return list(self._turn_tool_calls)  # type: ignore[attr-defined]
