"""Message display classes for the Hermes TUI.

Contains: MessagePanel, ThinkingWidget, _EchoBullet, UserMessagePanel, ReasoningPanel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult, RenderResult
from textual.css.query import NoMatches
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.animation import PulseMixin, lerp_color
from .renderers import (
    CopyableBlock,
    CopyableRichLog,
    PlainRule,
    TitledRule,
)
from .utils import _boost_layout_caches

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp


class ThinkingWidget(Widget):
    """Animated placeholder shown while agent is thinking.

    Lines 0-1: drawille helix animation (height 3 braille, 2 terminal rows).
    Line 2: "Thinking..." with animated dots cycling at 250ms.
    """

    DEFAULT_CSS = """
ThinkingWidget { height: 0; display: none; }
ThinkingWidget.--active { height: 3; display: block; }
"""

    _shimmer_timer: object | None = None
    _dot_phase: int = 0
    _helix_frames: tuple[str, ...] = ()
    _helix_idx: int = 0
    _last_helix_w: int = 0

    _THINKING_DOTS = ("Thinking.  ", "Thinking.. ", "Thinking...")

    def activate(self) -> None:
        if self._shimmer_timer is not None:
            return
        self.add_class("--active")
        self._build_helix_if_needed()
        self._shimmer_timer = self.set_interval(0.25, self._tick_shimmer)

    def deactivate(self) -> None:
        if self._shimmer_timer is not None:
            self._shimmer_timer.stop()
            self._shimmer_timer = None
        self.remove_class("--active")

    def _tick_shimmer(self) -> None:
        """Advance dot animation phase and helix frame."""
        self._dot_phase = (self._dot_phase + 1) % 3
        if self._helix_frames:
            self._helix_idx = (self._helix_idx + 1) % len(self._helix_frames)
        self.refresh()

    def _build_helix_if_needed(self) -> None:
        """Build drawille helix frames if width changed."""
        try:
            from hermes_cli.tui.app import _drawille
        except ImportError:
            return
        if _drawille is None:
            return
        widget_w = self.size.width or 40
        # 2-cell indent on right before scrollbar
        canvas_w = max(4, widget_w - 2)
        if canvas_w == self._last_helix_w and self._helix_frames:
            return
        self._last_helix_w = canvas_w
        self._helix_frames = self._build_helix_frames(_drawille, canvas_w)
        self._helix_idx = 0

    @staticmethod
    def _build_helix_frames(drawille_mod, width_cells: int) -> tuple[str, ...]:
        """Precompute drawille frames for a 3-strand helix, height 3 (12 dot rows)."""
        import math
        width_points = max(2, width_cells * 2)
        amplitude = 2.5
        midpoint = 6.0
        frame_count = 24
        frames: list[str] = []

        for frame_idx in range(frame_count):
            canvas = drawille_mod.Canvas()
            phase = (frame_idx / frame_count) * (2 * math.pi)
            for strand_idx in range(3):
                strand_phase = phase + (strand_idx * 2 * math.pi / 3)
                for x in range(width_points):
                    theta = strand_phase + (x * 0.42)
                    y = midpoint + (math.sin(theta) * amplitude)
                    canvas.set(x, int(round(max(0.0, min(11.0, y)))))
            rendered = canvas.frame()
            lines = rendered.splitlines() if rendered else []
            # Take first 3 terminal lines (12 dot rows / 4 dots per braille row)
            block = "\n".join(lines[:3]) if lines else ""
            # Pad each line to width_cells
            padded_lines = []
            for line in lines[:3]:
                padded_lines.append(line.ljust(width_cells)[:width_cells])
            while len(padded_lines) < 3:
                padded_lines.append(" " * width_cells)
            frames.append("\n".join(padded_lines))
        return tuple(frames)

    def render_line(self, y: int) -> Strip:
        width = self.size.width or 40
        # Lines 0-1: drawille helix animation (3 braille rows = 2 terminal lines shown)
        if y < 2 and self._helix_frames:
            self._build_helix_if_needed()
            frame = self._helix_frames[self._helix_idx % len(self._helix_frames)]
            frame_lines = frame.splitlines()
            line_idx = y if y < len(frame_lines) else 0
            raw = frame_lines[line_idx] if line_idx < len(frame_lines) else ""
            text = Text(raw, style="dim", no_wrap=True, overflow="ellipsis")
            segments = [
                Segment(seg.text, seg.style or Style(), seg.control)
                for seg in text.render(self.app.console)
            ]
            return Strip(segments, text.cell_len).extend_cell_length(width).crop(0, width)
        # Line 2 (or fallback): animated dots text
        if y == 2 or (y == 0 and not self._helix_frames):
            dots = self._THINKING_DOTS[self._dot_phase % 3]
            text = Text(f" {dots}", style="italic dim", no_wrap=True, overflow="ellipsis")
            segments = [
                Segment(seg.text, seg.style or Style(), seg.control)
                for seg in text.render(self.app.console)
            ]
            return Strip(segments, text.cell_len).extend_cell_length(width).crop(0, width)
        return Strip.blank(width)


class ReasoningPanel(Widget):
    """Collapsible reasoning display with left gutter marker.

    Hidden by default via CSS ``display: none``. Toggled visible via the
    ``visible`` CSS class when reasoning output arrives. Each committed
    line is rendered in dim italic text, with the gutter supplied by CSS.

    After ``close_box()`` is called, clicking anywhere on the panel toggles
    the body between expanded and collapsed states.
    """

    DEFAULT_CSS = """
    ReasoningPanel {
        display: none;
        height: auto;
        margin: 0 2;
    }
    ReasoningPanel.visible {
        display: block;
    }
    ReasoningPanel #reasoning-collapsed {
        background: $primary 5%;
        padding: 0 1;
        height: 1;
        display: none;
    }
    ReasoningPanel.--closeable.--collapsed #reasoning-collapsed {
        display: block;
    }
    ReasoningPanel.--closeable:hover {
        background: $accent 5%;
    }
    """
    _content_type: str = "reasoning"

    def __init__(self, **kwargs: Any) -> None:
        from hermes_cli.tui.widgets.prose import InlineProseLog
        self._reasoning_log = InlineProseLog(markup=False, highlight=False, wrap=True, id="reasoning-log")
        self._live_line = Static("", id="reasoning-live")
        self._collapsed_stub = Static("", id="reasoning-collapsed")
        super().__init__(**kwargs)
        _boost_layout_caches(self)
        self._live_buf = ""
        self._plain_lines: list[str] = []
        self._is_closed: bool = False
        self._body_collapsed: bool = False
        self._reasoning_engine = None  # set in on_mount when MARKDOWN_ENABLED

    def on_mount(self) -> None:
        from hermes_cli.tui.response_flow import MARKDOWN_ENABLED, ReasoningFlowEngine
        if MARKDOWN_ENABLED:
            engine = ReasoningFlowEngine(panel=self)
            engine._skin_vars = self.app.get_css_variables()
            engine._pygments_theme = engine._skin_vars.get("preview-syntax-theme", "monokai")
            self._reasoning_engine = engine

    def compose(self) -> ComposeResult:
        yield self._collapsed_stub
        yield self._reasoning_log
        yield self._live_line

    def _gutter_line(self, content: str) -> Text:
        """Build a dim italic line for the reasoning log.

        The left gutter marker is rendered as a CSS ``border-left: vkey`` on
        the whole ``ReasoningPanel``, so it appears on every visual row of a
        wrapped line — not just the first row (which was the bug with the old
        text-prepended ``▌`` approach).
        """
        return Text(content, style="dim italic")

    def _update_collapsed_stub(self) -> None:
        """Rebuild the one-line collapsed summary (I1: bold glyph + primary tint)."""
        n = len(self._plain_lines)
        try:
            k = self.app.get_css_variables().get("primary", "#5f87d7")
        except Exception:
            k = "#5f87d7"
        t = Text()
        t.append("▸ ", style=f"bold {k}")
        t.append(f"Reasoning collapsed · {n}L · ", style="dim")
        t.append("click to expand", style=f"dim {k}")
        self._collapsed_stub.update(t)

    def _sync_collapsed_state(self) -> None:
        self._reasoning_log.styles.display = "none" if self._body_collapsed else "block"
        self.set_class(self._body_collapsed, "--collapsed")
        if self._body_collapsed:
            self._update_collapsed_stub()

    def on_click(self, event: Any | None = None) -> None:
        """Toggle body visibility after streaming completes."""
        if not self._is_closed:
            return
        if event is not None and getattr(event, "button", 1) != 1:
            return
        if event is not None:
            event.prevent_default()
        self._body_collapsed = not self._body_collapsed
        self._sync_collapsed_state()

    def open_box(self, title: str) -> None:
        """Show the reasoning panel."""
        self._live_buf = ""
        # Only clear the log if no content committed yet.
        # Guard prevents wiping content when open_box fires after early deltas (race).
        if not self._plain_lines:
            self._reasoning_log.clear()
        self._plain_lines.clear()
        self._is_closed = False
        self._body_collapsed = False
        self._live_line.styles.display = "none"
        self._live_line.update("")
        self.remove_class("--closeable")
        self.remove_class("--collapsed")
        self._sync_collapsed_state()
        self.add_class("visible")
        if self._reasoning_engine is not None:
            from agent.rich_output import StreamingBlockBuffer
            self._reasoning_engine._block_buf = StreamingBlockBuffer()
            self._reasoning_engine._state = "NORMAL"
            self._reasoning_engine._active_block = None
            self._reasoning_engine._pending_source_line = None
            self._reasoning_engine._pending_code_intro = False
            self._reasoning_engine._list_cont_indent = ""
            self._reasoning_engine._fence_char = "`"
            self._reasoning_engine._fence_depth = 3
        # Force a layout refresh so the RichLog receives a Resize event and
        # sets _size_known=True, enabling deferred writes to be committed.
        self.call_after_refresh(self.refresh, layout=True)

    def append_delta(self, text: str) -> None:
        """Append a reasoning text delta, streaming character-by-character.

        Buffers partial lines and commits on newlines so the RichLog
        shows complete lines while still updating in real-time.
        Each committed line gets dim italic styling (via engine or gutter fallback).
        """
        self._live_buf += text
        while "\n" in self._live_buf:
            line, self._live_buf = self._live_buf.split("\n", 1)
            if self._reasoning_engine is not None:
                self._reasoning_engine.process_line(line)
            else:
                self._reasoning_log.write(self._gutter_line(line), expand=True)
                self._plain_lines.append(line)
        if self._reasoning_log._deferred_renders:
            self.call_after_refresh(self.refresh, layout=True)
        if self._live_buf:
            self._live_line.update(self._gutter_line(self._live_buf))
            self._live_line.styles.display = "block"
        else:
            self._live_line.styles.display = "none"
            self._live_line.update("")
        self.refresh(layout=True)

    def close_box(self) -> None:
        """Flush remaining buffer and activate collapse affordance."""
        buf = self._live_buf
        if buf:
            if self._reasoning_engine is not None:
                self._reasoning_engine.process_line(buf)
                self._reasoning_engine.flush()
            else:
                self._reasoning_log.write(self._gutter_line(buf), expand=True)
                self._plain_lines.append(buf)
            self._live_buf = ""
        elif self._reasoning_engine is not None:
            self._reasoning_engine.flush()
        if self._reasoning_log._deferred_renders:
            self.call_after_refresh(self.refresh, layout=True)
        self._live_line.styles.display = "none"
        self._live_line.update("")
        self._is_closed = True
        # Defensive: finalization must never drop the panel from the transcript,
        # even if a concurrent class toggle/race stripped visibility earlier.
        self.add_class("visible")
        self.add_class("--closeable")
        self._sync_collapsed_state()
        # Don't remove "visible" — reasoning stays shown as part of the
        # message so it isn't lost when tool output or the next response
        # pushes new content into the same MessagePanel.


class MessagePanel(Widget):
    """Owns all assistant-turn content blocks for one message."""

    DEFAULT_CSS = """
    MessagePanel {
        height: auto;
    }
    MessagePanel RichLog {
        height: auto;
        overflow-y: hidden;
        overflow-x: hidden;
    }
    MessagePanel TitledRule {
        display: none;
    }
    MessagePanel TitledRule.visible {
        display: block;
    }
    """

    _msg_counter: int = 0

    def __init__(self, user_text: str = "", show_header: bool = True, **kwargs: Any) -> None:
        import datetime as _dt
        MessagePanel._msg_counter += 1
        self._msg_id = MessagePanel._msg_counter
        self._show_header = show_header
        self._created_at = _dt.datetime.now()
        self._response_rule = TitledRule(
            id=f"response-rule-{self._msg_id}",
            created_at=self._created_at,
        )
        self._response_block = CopyableBlock(
            id=f"response-block-{self._msg_id}",
            _log_id=f"response-{self._msg_id}",
        )
        self._prose_blocks: list[CopyableBlock] = [self._response_block]
        self._thinking_blocks: list[ReasoningPanel] = []
        self._active_thinking_block: ReasoningPanel | None = None
        self._active_prose_block: CopyableBlock = self._response_block
        self._user_text: str = user_text
        self._response_engine: "Any | None" = None   # ResponseFlowEngine, set in on_mount
        self._carry_pending: "str | None" = None    # setext line migrated from prev panel
        self._carry_partial: "str | None" = None    # partial chunk (no \n) migrated from prev engine
        self._last_file_tool_block: "Any | None" = None   # tracks most-recent file-tool STB for diff connector
        self._adj_anchors: dict = {}
        self._subagent_panels: dict[str, Any] = {}
        self._child_buffer: dict[str, list] = {}
        self._flush_scheduled: set[str] = set()
        self._raw_text: str = ""
        super().__init__(**kwargs)
        _boost_layout_caches(self, box_model_maxsize=256, arrangement_maxsize=32)

    def _finish_fade(self) -> None:
        """Stub kept for API compatibility — fade handled by CSS transition on --entering class."""

    def compose(self) -> ComposeResult:
        yield self._response_rule
        yield self._response_block

    def show_response_rule(self) -> None:
        """Show the response title rule (called when first content arrives)."""
        if not self._show_header:
            return
        self._response_rule.add_class("visible")
        # Trigger a metrics refresh so header shows tok/s immediately
        try:
            self.app._refresh_live_response_metrics()
        except Exception:
            pass

    def set_response_metrics(
        self,
        *,
        tok_s: float | None = None,
        elapsed_s: float | None = None,
        streaming: bool = False,
    ) -> None:
        """Update right-side response metrics on this turn's header."""
        self._response_rule.set_response_metrics(
            tok_s=tok_s,
            elapsed_s=elapsed_s,
            streaming=streaming,
        )

    @property
    def reasoning(self) -> ReasoningPanel:
        if self._active_thinking_block is not None:
            return self._active_thinking_block
        if self._thinking_blocks:
            return self._thinking_blocks[-1]
        rp = ReasoningPanel(id=f"reasoning-{self._msg_id}-1")
        self._thinking_blocks.append(rp)
        self._mount_nonprose_block(rp)
        return rp

    def on_mount(self) -> None:
        """Lazy engine init — panel.app is guaranteed available at mount time."""
        for block in self._thinking_blocks:
            if block.parent is None:
                self._mount_nonprose_block(block)
        from hermes_cli.tui.response_flow import MARKDOWN_ENABLED, ResponseFlowEngine
        self._response_engine = (
            ResponseFlowEngine(panel=self) if MARKDOWN_ENABLED else None
        )
        if self._response_engine is not None:
            if self._carry_pending is not None:
                try:
                    self._response_engine.process_line(self._carry_pending)
                except Exception:
                    pass
                self._carry_pending = None
            if self._carry_partial is not None:
                try:
                    self._response_engine.feed(self._carry_partial)
                except Exception:
                    pass
                self._carry_partial = None
        # Signal cli.py that the engine is ready — streaming may now start.
        try:
            ev = getattr(self.app, "_panel_ready_event", None)
            if ev is not None:
                self.app._panel_ready_event = None
                ev.set()
        except Exception:
            pass

    @property
    def response_log(self) -> CopyableRichLog:
        return self._response_block.log

    def current_prose_log(self) -> CopyableRichLog:
        return self.ensure_prose_block().log

    def _has_any_prose_content(self) -> bool:
        return any(block.log._plain_lines for block in self._prose_blocks)

    def _maybe_insert_type_gap(self, block: Widget) -> None:
        """Insert a spacer line if the previous sibling is a different content type."""
        if not self.children:
            return
        prev = self.children[-1]
        # Skip non-content children (TitledRule, hidden separators, etc.)
        prev_type = getattr(prev, "_content_type", None)
        if prev_type is None:
            return
        new_type = getattr(block, "_content_type", None)
        if new_type is None or new_type == prev_type:
            return
        spacer = Static("")
        spacer.styles.height = 1
        spacer.styles.min_height = 1
        self.mount(spacer)

    def _mount_nonprose_block(self, block: Widget, parent_tool_call_id: "str | None" = None) -> None:
        """Mount a non-prose block in timeline order.

        If parent_tool_call_id is set, mount as a child of the corresponding SubAgentPanel.
        """
        if not self.is_attached:
            return
        if parent_tool_call_id is not None:
            parent = self._subagent_panels.get(parent_tool_call_id)
            if parent is not None:
                parent.add_child_panel(block)
                return
            # Race: child arrives before parent — buffer
            self._child_buffer.setdefault(parent_tool_call_id, []).append(block)
            if parent_tool_call_id not in self._flush_scheduled:
                self._flush_scheduled.add(parent_tool_call_id)
                self.call_after_refresh(self._flush_child_buffer, parent_tool_call_id)
            return
        # Top-level path
        try:
            from hermes_cli.tui.tool_group import _maybe_start_group
            _maybe_start_group(self, block)
        except Exception:
            pass
        if (
            self._response_block.parent is self
            and self.children
            and self.children[-1] is self._response_block
            and not self._has_any_prose_content()
        ):
            # Bootstrap: mount before response_block, then add type gap
            # between the new block and response_block if types differ.
            self.mount(block, before=self._response_block)
            block_type = getattr(block, "_content_type", None)
            resp_type = getattr(self._response_block, "_content_type", None)
            if block_type and resp_type and block_type != resp_type:
                spacer = Static("")
                spacer.styles.height = 1
                spacer.styles.min_height = 1
                self.mount(spacer, before=self._response_block)
        else:
            self._maybe_insert_type_gap(block)
            self.mount(block)

    def _flush_child_buffer(self, parent_tool_call_id: str) -> None:
        self._flush_scheduled.discard(parent_tool_call_id)
        children = self._child_buffer.pop(parent_tool_call_id, [])
        parent = self._subagent_panels.get(parent_tool_call_id)
        if parent is None:
            for child in children:
                self._mount_nonprose_block(child, parent_tool_call_id=None)
            return
        for child in children:
            parent.add_child_panel(child)

    def ensure_prose_block(self) -> CopyableBlock:
        """Return the current prose destination, creating a trailing block if needed."""
        active = self._active_prose_block
        if active is self._response_block and active.parent is None:
            return active
        if active.parent is self and self.children and self.children[-1] is active:
            return active

        new_prose = CopyableBlock(
            id=f"prose-{self._msg_id}-{len(self._prose_blocks)}",
            _log_id=f"prose-log-{self._msg_id}-{len(self._prose_blocks)}",
        )
        self._maybe_insert_type_gap(new_prose)
        self.mount(new_prose)
        self._prose_blocks.append(new_prose)
        self._active_prose_block = new_prose
        return new_prose

    def open_thinking_block(self, title: str = "Reasoning") -> ReasoningPanel:
        """Open a new thinking block for this message."""
        if self._active_thinking_block is not None:
            self._active_thinking_block.close_box()
            self._active_thinking_block = None

        prev = self._thinking_blocks[-1] if self._thinking_blocks else None
        if (
            prev is not None
            and prev.parent is self
            and not prev._plain_lines
            and not prev._live_buf
            and not prev._reasoning_log.lines
        ):
            block = prev
        else:
            block = ReasoningPanel(
                id=f"reasoning-{self._msg_id}-{len(self._thinking_blocks) + 1}"
            )
            self._thinking_blocks.append(block)
            self._mount_nonprose_block(block)
        self._active_thinking_block = block
        block.open_box(title)
        return block

    def append_thinking(self, delta: str) -> None:
        if not delta:
            return
        block = self._active_thinking_block or self.open_thinking_block("Reasoning")
        block.append_delta(delta)

    def close_thinking_block(self) -> None:
        block = self._active_thinking_block
        if block is None:
            return
        block.close_box()
        self._active_thinking_block = None

    def mount_tool_block(
        self,
        label: str,
        lines: list[str],
        plain_lines: list[str],
        tool_name: str | None = None,
        rerender_fn=None,
        header_stats=None,
        parent_id: str | None = None,
    ) -> Widget | None:
        if not lines:
            return None
        from hermes_cli.tui.tool_blocks import ToolBlock as _ToolBlock
        from hermes_cli.tui.tool_panel import ToolPanel as _ToolPanel
        block = _ToolBlock(
            label,
            lines,
            plain_lines,
            tool_name=tool_name,
            rerender_fn=rerender_fn,
            header_stats=header_stats,
        )
        if label == "diff":
            block._header._compact_tail = True  # stats/toggle/timer inline after label
            block._header._is_child_diff = True
        panel = _ToolPanel(block, tool_name=tool_name)
        if label == "diff":
            panel.add_class("tool-panel--child-diff")
        self._mount_nonprose_block(panel)
        return block

    def open_streaming_tool_block(
        self,
        label: str,
        tool_name: "str | None" = None,
        panel_id: "str | None" = None,
        is_first_in_turn: bool = False,
        parent_tool_call_id: "str | None" = None,
        depth: int = 0,
        tool_call_id: "str | None" = None,
    ) -> Widget:
        from hermes_cli.tui.tool_blocks import StreamingToolBlock as _STB, _FILE_TOOL_NAMES
        from hermes_cli.tui.tool_panel import ToolPanel as _ToolPanel
        from hermes_cli.tui.tool_category import classify_tool, ToolCategory

        block = _STB(label=label, tool_name=tool_name)

        cat_enum = classify_tool(tool_name or "")

        if cat_enum == ToolCategory.AGENT:
            from hermes_cli.tui.sub_agent_panel import SubAgentPanel
            panel = SubAgentPanel(depth=depth)
            block._tool_panel = panel
            if tool_call_id:
                self._subagent_panels[tool_call_id] = panel
            self._mount_nonprose_block(panel, parent_tool_call_id=parent_tool_call_id)
        elif parent_tool_call_id is not None:
            from hermes_cli.tui.child_panel import ChildPanel
            parent_sap = self._subagent_panels.get(parent_tool_call_id)
            panel = ChildPanel(
                block,
                tool_name=tool_name,
                depth=depth,
                parent_subagent=parent_sap,
            )
            block._tool_panel = panel
            self._mount_nonprose_block(panel, parent_tool_call_id=parent_tool_call_id)
        else:
            panel = _ToolPanel(block, tool_name=tool_name)
            block._tool_panel = panel
            self._mount_nonprose_block(panel)


        if tool_name in _FILE_TOOL_NAMES:
            self._last_file_tool_block = block
        # Register adj anchor for adjacent-mount tracking
        if tool_name:
            self._adj_anchors[tool_name] = panel
        if panel_id:
            self._adj_anchors[panel_id] = panel
        # Bash syntax highlight on header label for shell-category tools
        if label:
            try:
                if cat_enum == ToolCategory.SHELL:
                    from pygments import highlight as _hl
                    from pygments.lexers import BashLexer
                    from pygments.formatters import TerminalTrueColorFormatter
                    from rich.text import Text as _Text
                    ansi = _hl(label, BashLexer(), TerminalTrueColorFormatter(style="monokai")).rstrip("\n")
                    block._header._label_rich = _Text.from_ansi(ansi)
            except Exception:
                pass
        return block

    def all_prose_text(self) -> str:
        """Plain text from all prose sections — for copy-all and history search."""
        parts = []
        for block in self._prose_blocks:
            text = block.log.copy_content()
            if text:
                parts.append(text)
        return "\n".join(parts)

    def record_raw(self, text: str) -> None:
        """Accumulate raw streamed text for this message."""
        if text:
            self._raw_text += text

    def raw_response_text(self) -> str:
        """Return the raw unprocessed text captured during streaming."""
        return self._raw_text

    def first_response_line(self) -> str:
        """First non-empty display line from any prose section — for history search preview."""
        for block in self._prose_blocks:
            for line in block.log._plain_lines:
                if line.strip():
                    return line
        return ""


class _EchoBullet(PulseMixin, Widget):
    """Single-line user message display with a pulsing ❯ chevron.

    Pulses from mount until the FIRST agent turn that follows this message
    completes.  Subsequent turns leave the bullet static (one-shot guard).
    """

    DEFAULT_CSS = "_EchoBullet { height: 1; }"

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._message = message
        self._bullet_peak: str = "#FFBF00"
        self._bullet_dim: str = "#6e6e6e"
        self._turn_started: bool = False
        self._turn_complete: bool = False
        self._watcher_registered: bool = False

    def on_mount(self) -> None:
        try:
            v = self.app.get_css_variables()
            self._bullet_peak = (
                v.get("user-echo-bullet-color") or v.get("rule-accent-color", "#FFBF00")
            )
            self._bullet_dim = v.get("running-indicator-dim-color", "#6e6e6e")
        except Exception:
            pass
        self.watch(self.app, "agent_running", self._on_agent_running, init=False)
        self._watcher_registered = True
        # Check current state explicitly — avoids init=True timing issues
        # where the watcher fires before _turn_started is meaningful.
        try:
            if getattr(self.app, "agent_running", False):
                self._turn_started = True
                if getattr(self.app, "_animations_enabled", True):
                    self._pulse_start()
        except Exception:
            pass

    def on_unmount(self) -> None:
        """Explicit cleanup — ensure pulse stops even if MRO or watcher is disrupted."""
        self._pulse_stop()

    def _on_agent_running(self, running: bool) -> None:
        if self._turn_complete:
            return
        if running:
            if not self._turn_started:
                self._turn_started = True
                if getattr(self.app, "_animations_enabled", True):
                    self._pulse_start()
        elif self._turn_started:
            self._pulse_stop()
            self._turn_complete = True

    def render(self) -> RenderResult:
        if self._pulse_timer is not None:
            color = lerp_color(self._bullet_dim, self._bullet_peak, self._pulse_t)
        else:
            color = self._bullet_peak
        t = Text()
        t.append("❯ ", style=f"bold {color}")
        msg = self._message
        if "\n" in msg:
            first_line = msg.split("\n")[0]
            line_count = msg.count("\n") + 1
            t.append(first_line, style="bold")
            t.append(f" (+{line_count - 1} lines)", style="dim")
        else:
            t.append(msg, style="bold")
        return t

    def get_text(self) -> Text:
        return self.render()  # type: ignore[return-value]


class UserMessagePanel(Widget):
    """Displays the user's submitted message framed by short fade rulers.

    Mounted into OutputPanel when the user sends a message, before the new
    MessagePanel.
    """

    DEFAULT_CSS = """
    UserMessagePanel {
        height: auto;
        margin: 1 0 0 0;
        padding: 0 1;
    }
    """

    _ECHO_RULE_WIDTH = 30

    def __init__(self, message: str, images: int = 0, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._message = message
        self._images = images

    def compose(self) -> ComposeResult:
        yield PlainRule(max_width=self._ECHO_RULE_WIDTH, id="echo-rule-top")
        yield _EchoBullet(self._message, id="echo-text")
        if self._images:
            yield Static(self._format_images(), id="echo-images")

    def _format_images(self) -> Text:
        n = self._images
        return Text(f"  📎 {n} image{'s' if n > 1 else ''} attached", style="dim")
