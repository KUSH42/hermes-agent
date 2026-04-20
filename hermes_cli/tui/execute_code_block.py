"""ExecuteCodeBlock — Python execute_code tool UX redesign.

Extends StreamingToolBlock with:
- Per-chunk streaming of code argument via PartialJSONCodeExtractor + CharacterPacer
- rich.Syntax finalization at tool_start
- Blinking cursor during code streaming
- Success/error flash on completion
- Always-on click-to-toggle (even during streaming)
- Right-aligned header with python nerd-font icon
"""
from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.tool_blocks import (
    OmissionBar,
    StreamingToolBlock,
    ToolBodyContainer,
    ToolHeader,
    ToolTail,
    _SPINNER_FRAMES,
    _VISIBLE_CAP,
    _first_link,
)

# Higher collapse threshold for ExecuteCodeBlock — generic COLLAPSE_THRESHOLD=3
# would collapse any non-trivial python script before the user sees its output.
_EXECUTE_COLLAPSE_THRESHOLD = 20
from hermes_cli.tui.widgets import CopyableRichLog


class CodeSection(Widget):
    """Section containing syntax-highlighted Python source code."""

    DEFAULT_CSS = "CodeSection { height: auto; }"

    def compose(self) -> ComposeResult:
        yield CopyableRichLog(markup=False, highlight=False, wrap=False)


class OutputSection(Widget):
    """Section containing stdout/stderr streaming output."""

    DEFAULT_CSS = "OutputSection { height: auto; display: none; }"

    def compose(self) -> ComposeResult:
        yield CopyableRichLog(markup=False, highlight=False, wrap=False)


class OutputSeparator(Widget):
    """Dim 'output' label shown between code and stdout sections."""

    DEFAULT_CSS = "OutputSeparator { height: 1; display: none; }"

    def compose(self) -> ComposeResult:
        yield Static("  ─── output", classes="output-sep-label")


class ExecuteCodeBody(ToolBodyContainer):
    """Two-section body: CodeSection + OutputSeparator + OutputSection.

    Overrides ToolBodyContainer.compose() entirely — the parent yields
    a single CopyableRichLog which is not useful here.
    """

    def compose(self) -> ComposeResult:
        yield CodeSection()
        yield OutputSeparator()
        yield OutputSection()


# State constants
_STATE_STREAMING = "streaming"
_STATE_FINALIZED = "finalized"
_STATE_COMPLETED = "completed"


class ExecuteCodeBlock(StreamingToolBlock):
    """StreamingToolBlock variant for execute_code with per-chunk code streaming.

    Lifecycle: GEN_START → GEN_STREAMING → TOOL_START → EXEC_STREAMING → COMPLETED
    """

    DEFAULT_CSS = "ExecuteCodeBlock { height: auto; }"
    _content_type: str = "tool"

    def __init__(self, initial_label: str = "python", **kwargs: Any) -> None:
        super().__init__(label=initial_label, tool_name="execute_code", **kwargs)
        self._code_state = _STATE_STREAMING
        self._line_scratch = ""
        self._code_lines: list[str] = []
        self._user_toggled = False
        self._cursor_visible = True
        self._cursor_timer = None
        self._label_set = False

        # Initialized post-mount with app reference
        self._pacer = None
        self._extractor = None

    def compose(self) -> ComposeResult:
        yield self._header
        yield ExecuteCodeBody()
        yield self._tail

    def on_mount(self) -> None:
        # StreamingToolBlock.on_mount also fires (Textual chains MRO handlers).
        # It sets _body = query_one(ToolBodyContainer) and _has_affordances = False.
        # We override both after the chained on_mount completes.
        # Since Textual dispatches most-derived first, then parent, the parent's
        # on_mount will run AFTER ours and overwrite our settings.
        # Fix: use call_after_refresh to apply our overrides last.
        self.call_after_refresh(self._apply_execute_mount_overrides)

        # Initialize extractor and pacer
        from hermes_cli.tui.partial_json import PartialJSONCodeExtractor
        from hermes_cli.tui.character_pacer import CharacterPacer
        self._extractor = PartialJSONCodeExtractor(field="code")

        cps = 0
        try:
            from hermes_cli.config import read_raw_config
            cps = int(read_raw_config().get("display", {}).get("execute_code_typewriter_cps", 0))
        except Exception:
            pass

        # Reduced-motion check
        try:
            css_vars = self.app.get_css_variables()
            if css_vars.get("reduced-motion", "0") not in ("0", "", None):
                cps = 0
        except Exception:
            pass

        self._pacer = CharacterPacer(
            cps=cps,
            on_reveal=self.append_code_chars,
            app=self.app,
        )

        # Mount cursor Static inside CodeSection
        try:
            code_section = self.query_one(CodeSection)
            code_section.mount(Static("", id="code-live-cursor"))
        except Exception:
            pass

        # Start cursor blink
        self._start_cursor()

    def _apply_execute_mount_overrides(self) -> None:
        """Runs after all MRO on_mount handlers. Overrides StreamingToolBlock defaults."""
        try:
            self._body = self.query_one(ExecuteCodeBody)
            self._body.add_class("expanded")
        except NoMatches:
            pass
        self._header._has_affordances = True
        self._header.collapsed = False
        self._header._compact_tail = True  # natural flow, non-dim duration

        # Pre-mount both omission bars on OutputSection so they exist in DOM
        # immediately; _refresh_omission_bars() hides them until cap is reached.
        try:
            output_section = self.query_one(OutputSection)
            rl = output_section.query_one(CopyableRichLog)
        except NoMatches:
            return
        top_bar = OmissionBar(
            parent_block=self, position="top",
            classes="--omission-bar-top",
        )
        bottom_bar = OmissionBar(
            parent_block=self, position="bottom",
            classes="--omission-bar-bottom",
        )
        self._omission_bar_top = top_bar
        self._omission_bar_top_mounted = True
        self._omission_bar_bottom = bottom_bar
        self._omission_bar_bottom_mounted = True
        output_section.mount(top_bar, before=rl)
        output_section.mount(bottom_bar)

    def _start_cursor(self) -> None:
        try:
            css_vars = self.app.get_css_variables()
            if css_vars.get("reduced-motion", "0") not in ("0", "", None):
                return
        except Exception:
            pass
        self._cursor_timer = self.set_interval(0.5, self._tick_cursor)

    def _tick_cursor(self) -> None:
        if self._code_state == _STATE_FINALIZED:
            return
        self._cursor_visible = not self._cursor_visible
        self._refresh_cursor()

    def _refresh_cursor(self) -> None:
        try:
            cursor_widget = self.query_one("#code-live-cursor", Static)
            if self._code_state == _STATE_FINALIZED:
                cursor_widget.display = False
                return
            cursor_char = "▏" if self._cursor_visible else " "
            cursor_widget.update(f"{self._line_scratch}{cursor_char}")
        except NoMatches:
            pass

    def feed_delta(self, delta: str) -> None:
        """Process a streaming JSON args chunk. Event-loop only."""
        if self._code_state == _STATE_FINALIZED:
            return
        if self._extractor is None:
            return
        decoded = self._extractor.feed(delta)
        if decoded and self._pacer is not None:
            self._pacer.feed(decoded)

    def append_code_chars(self, chars: str) -> None:
        """Receive decoded python chars from pacer. Event-loop only."""
        if self._code_state == _STATE_FINALIZED:
            return
        self._line_scratch += chars
        # Flush complete lines
        while '\n' in self._line_scratch:
            line, self._line_scratch = self._line_scratch.split('\n', 1)
            self._emit_code_line(line)
        self._refresh_cursor()

    def _emit_code_line(self, line: str) -> None:
        """Per-line Pygments highlight and write to CodeSection RichLog."""
        is_first_line = len(self._code_lines) == 0
        self._code_lines.append(line)

        # Update header label on first non-empty line (once only)
        if not self._label_set and line.strip():
            label = line.strip()[:60]
            self._header._label = label
            # Also build a syntax-highlighted Rich Text for the header
            self._header._label_rich = Text.from_ansi(self._highlight_line(line.strip()[:60]))
            self._label_set = True

        if is_first_line:
            # Line 0 shown in header — skip writing to body
            return

        # Lines 1+ go to CodeSection body
        highlighted = self._highlight_line(line)
        try:
            code_log = self.query_one(CodeSection).query_one(CopyableRichLog)
            code_log.write_with_source(Text.from_ansi(highlighted), line)
        except NoMatches:
            pass

    def _highlight_line(self, line: str) -> str:
        """Per-line Pygments highlight for Python code. Delegates to CodeRenderer."""
        theme = "monokai"
        try:
            css_vars = self.app.get_css_variables()
            theme = css_vars.get("preview-syntax-theme", theme)
        except Exception:
            pass
        from hermes_cli.tui.body_renderer import BodyRenderer
        from hermes_cli.tui.tool_category import ToolCategory
        renderer = BodyRenderer.for_category(ToolCategory.CODE)
        return renderer.highlight_line(line, theme)

    def finalize_code(self, code: str) -> None:
        """Replace streamed per-line render with canonical rich.Syntax. Event-loop only."""
        if self._code_state == _STATE_FINALIZED:
            return
        self._code_state = _STATE_FINALIZED

        # Stop cursor
        if self._cursor_timer is not None:
            try:
                self._cursor_timer.stop()
            except Exception:
                pass
            self._cursor_timer = None

        # Flush and stop pacer (canonical code supersedes streamed per-line output)
        if self._pacer is not None:
            self._pacer.flush()
            self._pacer.stop()

        # Hide cursor widget
        try:
            cursor_w = self.query_one("#code-live-cursor", Static)
            cursor_w.display = False
        except NoMatches:
            pass

        # Record canonical code lines for collapse threshold
        if code:
            self._code_lines = code.splitlines()

        # Update header label + rich label from canonical first line
        if code:
            first_line = self._code_lines[0].strip()[:60] if self._code_lines else ""
            if first_line:
                self._header._label = first_line
                self._header._label_rich = Text.from_ansi(self._highlight_line(first_line))

        # Clear CodeSection and write Syntax renderable for lines 1+
        try:
            code_section = self.query_one(CodeSection)
            code_log = code_section.query_one(CopyableRichLog)
            code_log.clear()

            if code and len(self._code_lines) > 1:
                try:
                    css_vars = self.app.get_css_variables()
                    theme = css_vars.get("preview-syntax-theme", "monokai")
                    bg = css_vars.get("app-bg", None)
                except Exception:
                    theme = "monokai"
                    bg = None
                from hermes_cli.tui.body_renderer import BodyRenderer
                from hermes_cli.tui.tool_category import ToolCategory
                renderer = BodyRenderer.for_category(ToolCategory.CODE)
                renderable = renderer.finalize_code(code, theme=theme, bg=bg)
                if renderable is not None:
                    code_log.write(renderable)
        except NoMatches:
            pass

        # Reveal OutputSeparator + OutputSection
        try:
            self.query_one(OutputSeparator).display = True
        except NoMatches:
            pass
        try:
            output_section = self.query_one(OutputSection)
            output_section.display = True
        except NoMatches:
            pass

    def _flush_pending(self) -> None:
        """Override: drain pending stdout lines to OutputSection's RichLog."""
        if not self._pending:
            return
        batch = self._pending
        self._pending = []

        try:
            output_section = self.query_one(OutputSection)
            output_log = output_section.query_one(CopyableRichLog)
        except NoMatches:
            return

        lines_written = 0
        for rich_or_raw, plain in batch:
            if self._visible_count < _VISIBLE_CAP:
                if isinstance(rich_or_raw, Text):
                    styled = rich_or_raw
                else:
                    styled = Text.from_ansi(rich_or_raw)
                output_log.write_with_source(styled, plain, link=_first_link(plain))
                self._visible_count += 1
                lines_written += 1

        if self._omission_bar_bottom_mounted:
            self._refresh_omission_bars()

        if lines_written:
            try:
                scrolled_up = getattr(self.app.query_one("#output-panel"), "_user_scrolled_up", False)
            except Exception:
                scrolled_up = False
            if scrolled_up:
                new_total = self._tail._new_line_count + lines_written
                try:
                    self._tail.update_count(new_total)
                except Exception:
                    pass

    def complete(self, duration: str, is_error: bool = False) -> None:
        """Override: add flash_success/flash_error, use code+output for collapse threshold."""
        if self._completed:
            return
        self._completed = True

        # Finalize code if not already done (safety net)
        if self._code_state != _STATE_FINALIZED:
            self.finalize_code("")

        # Stop timers
        try:
            self._render_timer.stop()
            self._spinner_timer.stop()
            self._duration_timer.stop()
        except Exception:
            pass

        self._header._pulse_stop()
        self._header.set_error(is_error)

        # Final stdout flush
        self._flush_pending()
        # Hide tail badge
        self._tail.dismiss()

        # Update header
        self._header._spinner_char = None
        self._header._duration = duration

        # Collapse based on code lines + output lines; suppress "NL" display
        total = len(self._code_lines) + self._total_received
        self._header._line_count = 0  # don't show line count in execute_code header

        if not self._user_toggled:
            if total > _EXECUTE_COLLAPSE_THRESHOLD:
                self._header._has_affordances = True
                self._header.collapsed = True
                self._body.remove_class("expanded")
            elif total == 0:
                self._body.styles.display = "none"
                self._header.collapsed = False
            else:
                self._header._has_affordances = total > 0
                self._header.collapsed = False
        else:
            # User toggled — respect their choice, update affordances
            self._header._has_affordances = total > 0

        self._header.refresh()

        # Flash success or error
        if is_error:
            self._header.flash_error()
        else:
            self._header.flash_success()

        self._code_state = _STATE_COMPLETED

    def toggle(self) -> None:
        """Override: track user-initiated toggles."""
        self._user_toggled = True
        super().toggle()

    def on_unmount(self) -> None:
        super().on_unmount()
        if self._pacer is not None:
            self._pacer.stop()
        if self._cursor_timer is not None:
            try:
                self._cursor_timer.stop()
            except Exception:
                pass

    def _get_output_log(self) -> CopyableRichLog:
        return self.query_one(OutputSection).query_one(CopyableRichLog)

    def reveal_lines(self, start: int, end: int) -> None:
        """Append output _all_plain[start:end] to OutputSection's RichLog."""
        log = self._get_output_log()
        for plain in self._all_plain[start:end]:
            log.write_with_source(Text(plain), plain)

    def collapse_to(self, new_end: int) -> None:
        """Clear OutputSection's RichLog and rewrite _all_plain[:new_end]."""
        log = self._get_output_log()
        log.clear()
        for plain in self._all_plain[:new_end]:
            log.write_with_source(Text(plain), plain)

    def copy_content(self) -> str:
        """Concatenate code + output plain text with blank-line separator."""
        code_text = "\n".join(self._code_lines)
        output_text = "\n".join(self._all_plain)
        if code_text and output_text:
            return code_text + "\n\n" + output_text
        return code_text or output_text
