"""Rendering widget classes for the Hermes TUI.

Contains: CopyableRichLog, CopyableBlock, CodeBlockFooter, LiveLineWidget,
StreamingCodeBlock, _fade_rule, TitledRule, PlainRule.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult, RenderResult
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.selection import Selection
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import RichLog, Static

from hermes_cli.tui.animation import AnimationClock, PulseMixin, lerp_color
from .utils import (
    _ANSI_RE,
    _ANSI_SEQ_RE,
    _PRENUMBERED_LINE_RE,
    _apply_span_style,
    _boost_layout_caches,
    _cursor_blink_enabled,
    _format_elapsed_compact,
    _prewrap_code_line,
    _skin_branding,
    _skin_color,
    _strip_ansi,
    _typewriter_burst_threshold,
    _typewriter_cursor_enabled,
    _typewriter_delay_s,
    _typewriter_enabled,
)

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp


class CopyableRichLog(RichLog, can_focus=False):
    """RichLog that stores plain text for clipboard operations.

    ``can_focus=False`` prevents Textual's focus machinery from calling
    ``Screen.scroll_to_center`` → ``scroll_to_widget`` → ``OutputPanel.
    scroll_to_region`` when this widget is clicked, which would scroll the
    output to y=0 (scroll-to-top regression).

    Text selection still works: in Textual 8.x selection is gated on
    ``ALLOW_SELECT`` / ``allow_select()`` (default True), not on ``can_focus``.
    Mouse events (MouseDown/Move/Up) are delivered by cursor position, not
    focus, so drag-to-select is unaffected.

    Overrides ``overflow-y: scroll`` from RichLog.DEFAULT_CSS to ``hidden``
    so that mouse-scroll events are NOT stopped here and can bubble up to
    the parent OutputPanel (the intended scroll container).  Without this,
    Textual's ``_on_mouse_scroll_up`` sees ``allow_vertical_scroll=True``
    on CopyableRichLog, calls ``event.stop()``, and OutputPanel never scrolls.
    Note: the ``MessagePanel RichLog`` CSS rule doesn't help here because
    Textual matches on ``_css_type_name`` ("CopyableRichLog"), not on the
    base-class name "RichLog".
    """

    DEFAULT_CSS = """
    CopyableRichLog {
        height: auto;
        overflow-y: hidden;
        overflow-x: hidden;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        _boost_layout_caches(self)
        self._plain_lines: list[str] = []

    def render_line(self, y: int) -> Strip:
        """Override to add offset metadata and selection highlighting.

        RichLog.render_line() returns strips without ``style.meta["offset"]``,
        so ``Compositor.get_widget_and_offset_at()`` always returns offset
        ``None`` — Textual's selection system can't track position within the
        widget and drag-to-select silently fails.

        RichLog._render_line() also does not paint the ``screen--selection``
        highlight (unlike ``Log._render_line_strip``).  We apply the selection
        style here so the visual highlight matches the tracked region.

        Selection is applied before ``apply_offsets`` so the final strip
        carries both correct metadata and the correct background color.
        """
        scroll_x, scroll_y = self.scroll_offset
        content_y = scroll_y + y
        line = self._render_line(content_y, scroll_x, self.scrollable_content_region.width)
        strip = line.apply_style(self.rich_style)

        selection = self.text_selection
        if selection is not None:
            span = selection.get_span(content_y)
            if span is not None:
                start_x, end_x = span
                try:
                    sel_style = self.screen.get_component_rich_style("screen--selection")
                    strip = _apply_span_style(strip, start_x, end_x, sel_style)
                except Exception:
                    pass

        return strip.apply_offsets(scroll_x, content_y)

    def write(  # type: ignore[override]
        self,
        content: Any,
        width: "int | None" = None,
        expand: bool = True,
        shrink: bool = True,
        scroll_end: "bool | None" = None,
        animate: bool = False,
    ) -> "CopyableRichLog":
        """Override to use the full widget width regardless of layout timing.

        RichLog.write(expand=True) computes: max(scrollable_content_region.width, 0).
        When the first streaming token arrives before layout completes,
        scrollable_content_region.width is 0, collapsing text to ~1-14 chars.
        Fix: resolve the target width here and pass it explicitly, falling back
        to self.size.width (post-layout) or app.width - scrollbar (pre-layout).
        """
        if width is None:
            region_w = self.scrollable_content_region.width
            if region_w > 0:
                width = region_w
            elif self.size.width > 0:
                # Post-layout: widget size accounts for parent scrollbar + margins
                width = self.size.width
            else:
                # Pre-layout fallback: subtract OutputPanel scrollbar (1 col)
                # AND CopyableBlock margins (2 left + 2 right = 4).  Without
                # the margin deduction, text wraps 4 cols too wide and the
                # rightmost characters spill under the scrollbar / outside
                # the viewport.
                try:
                    width = max(self.app.size.width - 5, 20)
                except Exception:
                    width = 80
        return super().write(  # type: ignore[return-value]
            content,
            width=width,
            expand=False,  # width already resolved above
            shrink=False,  # don't shrink the explicit width
            scroll_end=scroll_end,
            animate=animate,
        )

    def write_with_source(self, styled: Text, plain: str, **kwargs: Any) -> "CopyableRichLog":
        """Write styled text to display, store plain text for copy."""
        self._plain_lines.append(plain)
        try:
            from hermes_cli.tui.osc8 import inject_osc8, _osc8_supported
            if _osc8_supported():
                import io as _io
                from rich.console import Console as _Console
                buf = _io.StringIO()
                _Console(file=buf, force_terminal=True, width=10000, highlight=False).print(styled, end="")
                ansi_str = buf.getvalue().rstrip("\n")
                return self.write(Text.from_ansi(inject_osc8(ansi_str, _enabled=True)), **kwargs)
        except Exception:
            pass
        return self.write(styled, **kwargs)

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        """Return plain text for the selected region.

        Prefers ``self.lines`` (visual strips) so that selection ``y`` indices
        — which are visual-line indices — align exactly with the text passed to
        ``Selection.extract``.  Segment text is plain (Rich renders ANSI to
        Style objects, not escape codes).

        Falls back to ``_plain_lines`` when ``self.lines`` is empty (e.g. in
        tests where the widget is not mounted and writes are still deferred).
        """
        if self.lines:
            text = "\n".join("".join(seg.text for seg in line) for line in self.lines)
        elif self._plain_lines:
            text = "\n".join(self._plain_lines)
        else:
            return None
        return selection.extract(text), "\n"

    def copy_content(self) -> str:
        """Plain text for clipboard — no ANSI, no markup."""
        return "\n".join(self._plain_lines)

    def clear(self) -> "CopyableRichLog":
        self._plain_lines.clear()
        return super().clear()


class CopyableBlock(Widget):
    """Wraps CopyableRichLog with a hover-reveal copy button."""

    DEFAULT_CSS = "CopyableBlock { height: auto; margin: 0 2; }"
    _content_type: str = "prose"

    def __init__(self, _log_id: str | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        log_kwargs: dict[str, Any] = {"markup": False, "highlight": False, "wrap": True}
        if _log_id:
            log_kwargs["id"] = _log_id
        self._log = CopyableRichLog(**log_kwargs)

    def compose(self) -> ComposeResult:
        yield self._log
        # Copy button is lazy-mounted on first hover to avoid layout interference
        # with sibling RichLog deferred renders.  See on_click for implementation.

    @property
    def log(self) -> "CopyableRichLog":
        return self._log

    def on_click(self, event: Any) -> None:
        if getattr(event.widget, "id", None) == "copy-btn":
            text = self.log.copy_content()
            try:
                self.app._copy_text_with_hint(text)
            except Exception:
                pass
            event.prevent_default()

    def on_mouse_enter(self, _event: Any) -> None:
        """Lazily mount the copy button on first hover."""
        try:
            self.query_one("#copy-btn")
        except NoMatches:
            self.mount(Static("⎘", id="copy-btn"))


class CodeBlockFooter(Widget):
    """Dedicated footer row with distinct click targets for code actions."""

    DEFAULT_CSS = """
    CodeBlockFooter {
        height: 1;
        margin-top: 0;
        margin-left: 1;
        background: transparent;
        layout: horizontal;
    }
    CodeBlockFooter > Static {
        width: auto;
        color: $text-muted;
        background: transparent;
    }
    CodeBlockFooter > .sep {
        color: $text-muted;
    }
    CodeBlockFooter > .action:hover {
        color: $accent;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._copy = Static("", id="code-copy-action", classes="action")
        self._sep = Static("", classes="sep")
        self._toggle = Static("", id="code-toggle-action", classes="action")

    def compose(self) -> ComposeResult:
        yield self._copy
        yield self._sep
        yield self._toggle

    def set_actions(self, *, copy_label: str, toggle_label: str | None) -> None:
        self._copy.update(copy_label)
        if toggle_label:
            self._sep.update("  ·  ")
            self._toggle.update(toggle_label)
            self._sep.styles.display = "block"
            self._toggle.styles.display = "block"
        else:
            self._sep.update("")
            self._toggle.update("")
            self._sep.styles.display = "none"
            self._toggle.styles.display = "none"

    def on_click(self, event: Any) -> None:
        """Route clicks on footer actions to the parent StreamingCodeBlock."""
        if getattr(event, "button", 1) != 1:
            return
        parent = self.parent
        if parent is None:
            return
        target_id = getattr(getattr(event, "widget", None), "id", None)
        if target_id == "code-copy-action":
            try:
                self.app._copy_code_block(parent)  # type: ignore[attr-defined]
            except Exception:
                pass
            event.prevent_default()
            return
        if target_id == "code-toggle-action":
            try:
                if parent.can_toggle():
                    parent.toggle_collapsed()
                    event.prevent_default()
            except Exception:
                pass


class LiveLineWidget(Widget):
    """Renders the current in-progress streaming chunk before it is committed.

    Accumulates text via :meth:`append` (direct) or :meth:`feed` (typewriter).
    When a newline arrives, all complete lines are committed to the parent
    OutputPanel's RichLog and only the trailing partial line remains in the buffer.

    Typewriter animation is opt-in via config (``terminal.typewriter.enabled``).
    When disabled, :meth:`feed` falls through to :meth:`append` with zero overhead.
    """

    DEFAULT_CSS = "LiveLineWidget { height: auto; }"

    _buf: reactive[str] = reactive("", repaint=True)
    _animating: reactive[bool] = reactive(False, repaint=True)

    def on_mount(self) -> None:
        self._tw_enabled: bool = _typewriter_enabled()
        self._tw_delay: float = _typewriter_delay_s()
        self._tw_burst: int = _typewriter_burst_threshold()
        self._tw_cursor: bool = _typewriter_cursor_enabled()
        if self._tw_enabled:
            self._char_queue: asyncio.Queue[str] = asyncio.Queue()
            self._drain_chars()
        # Non-typewriter blink state — initialized here (not __init__) to avoid
        # event-loop resource issues on Python ≤ 3.9.
        self._blink_visible: bool = True
        self._blink_timer: object | None = None
        self._blink_enabled: bool = _cursor_blink_enabled()

    def on_unmount(self) -> None:
        self._animating = False
        # Cancel blink timer if active
        if getattr(self, "_blink_timer", None) is not None:
            self._blink_timer.stop()
            self._blink_timer = None

    def render(self) -> RenderResult:
        if not self._buf and not self._animating:
            return Text("")
        t = Text.from_ansi(self._buf) if self._buf else Text("")
        # Typewriter cursor (existing path — typewriter on):
        if self._animating and getattr(self, "_tw_cursor", True):
            t.append("▌", style="blink")
        # Non-typewriter blink (only when typewriter is off and blink timer active):
        elif (
            not getattr(self, "_tw_enabled", False)
            and getattr(self, "_blink_timer", None) is not None
            and getattr(self, "_blink_visible", True)
        ):
            t.append("▌", style="dim")
        return t

    def _commit_lines(self) -> None:
        """Commit all complete lines in _buf to the current MessagePanel's RichLog."""
        if "\n" not in self._buf:
            return
        lines = self._buf.split("\n")
        try:
            from hermes_cli.tui.widgets import OutputPanel
            panel = self.app.query_one(OutputPanel)
            msg = panel.current_message
            if msg is None:
                msg = panel.new_message()
            rl = msg.current_prose_log()
            msg.show_response_rule()
            for committed in lines[:-1]:
                engine = getattr(msg, "_response_engine", None)
                if engine is not None:
                    engine.process_line(committed)  # engine routes to prose log or code block
                else:
                    plain = _strip_ansi(committed)
                    if isinstance(rl, CopyableRichLog):
                        rl.write_with_source(Text.from_ansi(committed), plain)
                    else:
                        rl.write(Text.from_ansi(committed))
            if rl._deferred_renders:
                self.call_after_refresh(msg.refresh, layout=True)
        except NoMatches:
            pass
        self._buf = lines[-1]

    def append(self, chunk: str) -> None:
        """Append *chunk* directly; commit complete lines to the MessagePanel's RichLog."""
        self._buf += chunk
        if "\n" in self._buf:
            self._commit_lines()

    def _toggle_blink(self) -> None:
        """Blink timer callback — plain def required (no await)."""
        self._blink_visible = not self._blink_visible
        self.refresh()

    def feed(self, chunk: str) -> None:
        """Enqueue *chunk* for typewriter animation (falls through to append when disabled).

        ANSI escape sequences are enqueued as atomic items so _buf never contains
        a partial escape code between render frames.  Must be called from the event loop.
        """
        if not getattr(self, "_tw_enabled", False):
            # Non-typewriter path: start blink timer on first chunk (if enabled)
            if (
                getattr(self, "_blink_timer", None) is None
                and getattr(self, "_blink_enabled", True)
            ):
                clock: AnimationClock | None = getattr(
                    getattr(self, "app", None), "_anim_clock", None
                )
                if clock is not None:
                    self._blink_timer = clock.subscribe(8, self._toggle_blink)
                else:
                    self._blink_timer = self.set_interval(0.5, self._toggle_blink)
            self.append(chunk)
            return
        pos = 0
        for m in _ANSI_SEQ_RE.finditer(chunk):
            for ch in chunk[pos:m.start()]:
                self._char_queue.put_nowait(ch)
            self._char_queue.put_nowait(m.group(0))
            pos = m.end()
        for ch in chunk[pos:]:
            self._char_queue.put_nowait(ch)

    @work(exclusive=False)
    async def _drain_chars(self) -> None:
        """Long-running drainer — started once in on_mount(), exits on unmount.

        Burst compensation batch-drains when the queue is deep, avoiding O(N)
        asyncio.sleep calls for fast model output.
        """
        delay = self._tw_delay
        burst = self._tw_burst
        try:
            while self.is_mounted:
                try:
                    char = await asyncio.wait_for(
                        self._char_queue.get(), timeout=0.5
                    )
                except asyncio.TimeoutError:
                    continue

                self._animating = True
                self._buf += char
                if "\n" in self._buf:
                    self._commit_lines()

                qsize = self._char_queue.qsize()
                if qsize >= burst:
                    for _ in range(min(qsize, burst * 2)):
                        try:
                            c = self._char_queue.get_nowait()
                            self._buf += c
                            if "\n" in self._buf:
                                self._commit_lines()
                        except asyncio.QueueEmpty:
                            break
                    await asyncio.sleep(0)
                else:
                    await asyncio.sleep(delay)

                if self._char_queue.empty():
                    self._animating = False
        finally:
            self._animating = False

    def flush(self) -> None:
        """Synchronously drain all pending chars from _char_queue.

        Called from OutputPanel.flush_live() on the event loop when the None
        sentinel arrives.  Safe because asyncio is single-threaded.
        Also stops the non-typewriter blink timer.
        """
        # Stop non-typewriter blink timer
        if getattr(self, "_blink_timer", None) is not None:
            self._blink_timer.stop()
            self._blink_timer = None
        self._blink_visible = True  # reset to visible for next turn

        if not getattr(self, "_tw_enabled", False) or not hasattr(self, "_char_queue"):
            return
        while True:
            try:
                char = self._char_queue.get_nowait()
                self._buf += char
                if "\n" in self._buf:
                    self._commit_lines()
            except asyncio.QueueEmpty:
                break
        self._animating = False


class StreamingCodeBlock(Widget):
    """Fenced code block widget: streams per-line Pygments highlight, then
    finalizes to full rich.Syntax on fence close.

    States
    ------
    STREAMING → COMPLETE (fence closed — call_after_refresh(_finalize_syntax))
    STREAMING → FLUSHED  (turn ended before fence closed — content preserved)
    """

    DEFAULT_CSS = """
    StreamingCodeBlock {
        height: auto;
        layout: vertical;
        margin-left: 2;
        margin-top: 1;
        margin-bottom: 1;
    }
    StreamingCodeBlock.--copy-flash {
        border: tall $accent;
    }
    """
    _content_type: str = "code"

    def __init__(
        self,
        lang: str = "",
        pygments_theme: str = "monokai",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        _boost_layout_caches(self)
        self._lang = lang
        self._pygments_theme = pygments_theme
        self._state: "Literal['STREAMING', 'COMPLETE', 'FLUSHED']" = "STREAMING"
        self._code_lines: list[str] = []
        self._resolved_lang: str | None = None
        self._log = CopyableRichLog(markup=False)
        self._collapsed = False
        self._copy_flash = False
        self._controls_text_plain = ""

    def compose(self) -> ComposeResult:
        yield self._log

    # ------------------------------------------------------------------
    # Streaming phase
    # ------------------------------------------------------------------

    def append_line(self, line: str) -> None:
        """Called by ResponseFlowEngine for each code line during streaming."""
        plain_line = _strip_ansi(line)
        self._code_lines.append(plain_line)
        highlighted = self._highlight_line(plain_line, self._lang)
        # Pre-wrap long lines with continuation indent matching source indentation
        for wrapped_line in _prewrap_code_line(highlighted, source_line=plain_line):
            self._log.write_with_source(
                Text.from_ansi(wrapped_line),
                _strip_ansi(wrapped_line),
            )

    def _highlight_line(self, line: str, lang: str) -> str:
        """Per-line Pygments highlight — loses multi-line string context but
        gives correct token highlighting for 90%+ of code."""
        try:
            from pygments import highlight  # type: ignore[import-untyped]
            from pygments.lexers import TextLexer, get_lexer_by_name  # type: ignore[import-untyped]
            from pygments.formatters import TerminalTrueColorFormatter  # type: ignore[import-untyped]
            try:
                lexer = get_lexer_by_name(lang, stripall=False) if lang else TextLexer()
            except Exception:
                lexer = TextLexer()  # unknown language name → plain text
            return highlight(line, lexer, TerminalTrueColorFormatter(style=self._pygments_theme)).rstrip("\n")
        except Exception:
            return line  # safe fallback — plain text

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    def complete(self, skin_vars: dict[str, str]) -> None:
        """Fence closed — replace per-line content with full rich.Syntax block."""
        if self._state != "STREAMING":
            return
        self._state = "COMPLETE"
        self._pygments_theme = skin_vars.get("preview-syntax-theme", self._pygments_theme)
        self.add_class("--complete")
        self.call_after_refresh(self._finalize_syntax, dict(skin_vars))

    def _render_syntax(self, skin_vars: dict[str, str] | None = None) -> None:
        """Render code as rich.Syntax with line numbers. Shared by COMPLETE and FLUSHED."""
        from rich.syntax import Syntax
        from hermes_cli.tui.response_flow import _detect_lang
        vars = skin_vars or (self.app.get_css_variables() if self.app else {})
        code = "\n".join(self._display_code_lines())
        lang = self._resolved_lang or self._lang or _detect_lang(code)
        self._resolved_lang = lang
        self._pygments_theme = vars.get("preview-syntax-theme", self._pygments_theme)
        syntax = Syntax(
            code,
            lexer=lang,
            theme=self._pygments_theme,
            line_numbers=True,
            word_wrap=False,
            indent_guides=False,
            background_color=vars.get("app-bg", "#1e1e1e"),
        )
        self._log.clear()
        if not self._collapsed:
            self._log.write_with_source(syntax, code)  # type: ignore[arg-type]
        self._update_controls()
        self.refresh(layout=True)

    def _finalize_syntax(self, skin_vars: dict[str, str]) -> None:
        """COMPLETE path — delegates to shared _render_syntax."""
        self._render_syntax(skin_vars)

    # ------------------------------------------------------------------
    # Partial fence (turn ended before fence closed)
    # ------------------------------------------------------------------

    def flush(self) -> None:
        """Turn ended before fence closed. Finalize with rich.Syntax same as COMPLETE."""
        if self._state != "STREAMING":
            return
        self._state = "FLUSHED"
        self.add_class("--flushed")
        self.add_class("--complete")
        self._render_flushed_content()

    def copy_content(self) -> str:
        """Plain text of the code block for clipboard operations."""
        return "\n".join(self._display_code_lines())

    def refresh_skin(self, css_vars: dict[str, str]) -> None:
        """Refresh theme-dependent rendering without remounting the widget."""
        self._pygments_theme = css_vars.get("preview-syntax-theme", self._pygments_theme)
        if self._state in ("COMPLETE", "FLUSHED"):
            self._render_syntax(css_vars)

    def toggle_collapsed(self) -> None:
        """Collapse/expand code body after the block is complete/flushed."""
        if self._state == "STREAMING" or not self.can_toggle():
            return
        self._collapsed = not self._collapsed
        self._render_syntax()

    def can_toggle(self) -> bool:
        """Only completed multi-line code blocks get a collapse affordance."""
        return self._state != "STREAMING" and len(self._code_lines) > 1

    def flash_copy(self) -> None:
        """Flash copy confirmation via border highlight."""
        self.add_class("--copy-flash")
        self._copy_flash = True
        self.set_timer(1.5, self._end_copy_flash)

    def _end_copy_flash(self) -> None:
        self.remove_class("--copy-flash")
        self._copy_flash = False

    def _update_controls(self) -> None:
        """Update _controls_text_plain for backward compat (tests)."""
        if self.can_toggle():
            t = Text(" ")
            t.append("expand" if self._collapsed else "collapse", style="dim")
            self._controls_text_plain = t.plain
        else:
            self._controls_text_plain = ""

    def on_click(self, event: Any) -> None:
        """Left click toggles expand/collapse on finalized blocks."""
        if getattr(event, "button", 1) != 1:
            return
        if self.can_toggle():
            self.toggle_collapsed()
            event.prevent_default()

    def _render_flushed_content(self) -> None:
        """FLUSHED path — delegates to shared _render_syntax (same visual as COMPLETE)."""
        self._render_syntax()

    def _display_code_lines(self) -> list[str]:
        """Normalize code lines for display/copy, stripping duplicate model-added gutters."""
        nonempty = [line for line in self._code_lines if line.strip()]
        if not nonempty:
            return list(self._code_lines)
        matches = [_PRENUMBERED_LINE_RE.match(line) for line in nonempty]
        threshold = 1 if len(nonempty) == 1 else max(2, (len(nonempty) * 3 + 4) // 5)
        if sum(1 for m in matches if m) < threshold:
            return list(self._code_lines)
        numbers = [int(m.group(1)) for m in matches if m]
        if len(numbers) >= threshold:
            expected = list(range(numbers[0], numbers[0] + len(numbers)))
            sequential_hits = sum(1 for a, b in zip(numbers, expected) if a == b)
            if sequential_hits < threshold:
                return list(self._code_lines)
        stripped_lines: list[str] = []
        for line in self._code_lines:
            m = _PRENUMBERED_LINE_RE.match(line)
            stripped_lines.append(m.group(2) if m else line)
        return stripped_lines


# ---------------------------------------------------------------------------
# Titled rule helpers + classes
# ---------------------------------------------------------------------------

def _fade_rule(count: int, start_hex: str, end_hex: str) -> Text:
    """Build a run of ``─`` chars that fade from *start_hex* to *end_hex*.

    Uses Rich's ``blend_rgb`` for interpolation — no extra dependencies.
    """
    from rich.color import Color, blend_rgb

    if count <= 0:
        return Text()
    c_start = Color.parse(start_hex).get_truecolor()
    c_end = Color.parse(end_hex).get_truecolor()
    t = Text()
    for i in range(count):
        factor = i / max(count - 1, 1)
        c = blend_rgb(c_start, c_end, factor)
        t.append("─", style=f"rgb({c.red},{c.green},{c.blue})")
    return t


class TitledRule(PulseMixin, Widget):
    """Horizontal rule with an embedded title and fading rule chars.

    Pass ``show_state=True`` on the input-rule instance to get a right-side
    state glyph (``⟳`` amber when agent/command is running, hidden when idle).
    """

    DEFAULT_CSS = """
    TitledRule {
        height: 1;
    }
    """

    title_text: reactive[str] = reactive("Hermes")
    progress: reactive[float] = reactive(0.0, repaint=True)

    def __init__(
        self,
        title: str | None = None,
        fade_start: str | None = None,
        fade_end: str | None = None,
        accent: str | None = None,
        title_color: str | None = None,
        show_state: bool = False,
        created_at: "Any | None" = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.title_text = title or _skin_branding("response_label", "⚕ Hermes")
        self._fade_start = fade_start or _skin_color("rule_start", "#555555")
        self._fade_end = fade_end or _skin_color("rule_end", "#2A2A2A")
        self._accent = accent or _skin_color("banner_title", "#FFD700")
        self._title_color = title_color or _skin_color("banner_title", "#FFD700")
        self._show_state = show_state
        self._created_at = created_at  # datetime | None — shown as HH:MM when set
        self._glyph_error: bool = False
        self._response_tok_s: float | None = None
        self._response_elapsed_s: float | None = None
        self._response_streaming: bool = False

    def on_mount(self) -> None:
        if self._show_state:
            self.watch(self.app, "agent_running", self._on_state_change)
            self.watch(self.app, "command_running", self._on_state_change)

    def _on_state_change(self, _value: object = None) -> None:
        running = (
            getattr(self.app, "agent_running", False)
            or getattr(self.app, "command_running", False)
        )
        if running and getattr(self.app, "_animations_enabled", True):
            self._pulse_start()
        else:
            self._pulse_stop()
        self.refresh()

    def set_error(self, is_error: bool) -> None:
        """Set error state — hard red glyph, no animation."""
        self._glyph_error = is_error
        if is_error:
            self._pulse_stop()
        self.refresh()

    def set_response_metrics(
        self,
        *,
        tok_s: float | None = None,
        elapsed_s: float | None = None,
        streaming: bool = False,
    ) -> None:
        """Update per-response header metrics shown left of timestamp."""
        self._response_tok_s = tok_s if tok_s and tok_s > 0 else None
        if elapsed_s is not None:
            self._response_elapsed_s = elapsed_s
        self._response_streaming = streaming
        self.refresh()

    def _response_metrics_text(self) -> str:
        if self._show_state:
            return ""
        parts: list[str] = []
        if self._response_tok_s is not None:
            parts.append(f"{self._response_tok_s:.0f} tok/s")
        elif self._response_streaming:
            parts.append("… tok/s")
        if self._response_elapsed_s is not None:
            parts.append(_format_elapsed_compact(self._response_elapsed_s))
        return " · ".join(parts)

    def _live_colors(self) -> tuple[str, str, str, str]:
        """Read rule colours from CSS variables for hot-reload support.

        Returns (fade_start, fade_end, accent, title_color). Falls back to
        the instance variables set at construction time so pre-mount renders
        (e.g. during test setup) are safe.
        """
        try:
            v = self.app.get_css_variables()
            # rule-bg-color is the foreground colour the gradient fades *to* —
            # it should match the app background so the rule "disappears" at the
            # right edge.  Fall through to app-bg if rule-bg-color is not
            # explicitly overridden in the skin.
            fade_end = v.get("rule-bg-color") or v.get("app-bg", self._fade_end)
            return (
                v.get("rule-dim-color",        self._fade_start),
                fade_end,
                v.get("rule-accent-color",     self._accent),
                v.get("rule-accent-color",     self._title_color),
            )
        except Exception:
            return self._fade_start, self._fade_end, self._accent, self._title_color

    def render(self) -> RenderResult:
        if self.progress >= 0.5:
            return self._render_progress_bar()
        return self._render_normal()

    def _render_normal(self) -> RenderResult:
        fade_start, fade_end, accent, title_color = self._live_colors()
        w = self.size.width
        title = self.title_text
        # Split title into leading spaces + accent char (first non-space) + rest.
        # Some skins intentionally prefix response_label with a space, e.g.
        # " ⟁ Matrix". split(" ", 1) would treat the glyph as normal text and
        # lose the dedicated brand-glyph-color path entirely.
        leading = len(title) - len(title.lstrip(" "))
        if leading < len(title):
            accent_index = leading
            prefix = title[:accent_index]
            accent_char = title[accent_index]
            rest = title[accent_index + 1 :]
        else:
            prefix = ""
            accent_char = ""
            rest = ""

        # Determine glyph color: error → hard red; running → pulse; idle → brand-glyph-color
        # brand-glyph-color gives skins a dedicated var for the ⟁/⚕ glyph,
        # independent of the title text color and the pulse active color.
        try:
            v = self.app.get_css_variables()
            glyph_idle = v.get("brand-glyph-color", v.get("primary-darken-3", _skin_color("banner_dim", "#2d4a6e")))
            glyph_active = v.get("primary", _skin_color("banner_title", "#5f87d7"))
            glyph_err = v.get("status-error-color", "#EF5350")
        except Exception:
            glyph_idle = _skin_color("banner_title", "#FFD700")
            glyph_active = _skin_color("banner_title", "#5f87d7")
            glyph_err = "#EF5350"

        if self._glyph_error:
            glyph_color = glyph_err
        elif self._pulse_t > 0:
            glyph_color = lerp_color(glyph_idle, glyph_active, self._pulse_t)
        else:
            glyph_color = glyph_idle

        # Right-side state glyph — only on instances with show_state=True,
        # only visible when the agent is running.
        state_suffix = Text()
        if self._show_state and not self._glyph_error:
            running = (
                getattr(self.app, "agent_running", False)
                or getattr(self.app, "command_running", False)
            )
            if running:
                warn_color = v.get("status-warn-color", "#FFA726")
                state_suffix = Text(" ⟳", style=warn_color)

        # Right-side timestamp — HH:MM when created_at is set (response rules only)
        ts_text = ""
        if self._created_at is not None and not self._show_state:
            try:
                ts_text = self._created_at.strftime("%H:%M")
            except Exception:
                ts_text = ""
        metrics_text = self._response_metrics_text()
        # Compute fill width: total minus every rendered segment.
        # render appends: f" {metrics}" and f" · {ts}" directly after the fill.
        fill = w - len(f"{title} ")
        fill -= state_suffix.cell_len
        if metrics_text:
            fill -= 1 + len(metrics_text)          # leading " "
        if ts_text:
            fill -= 3 + len(ts_text)               # leading " · "
        right = max(0, fill)
        t = Text()
        # Title: preserve leading spaces, accent char gets dynamic glyph color,
        # remainder stays in title_color.
        if prefix:
            t.append(prefix, style=f"{title_color}")
        t.append(accent_char, style=f"bold {glyph_color}")
        t.append(f"{rest} ", style=f"{title_color}")
        # Right fill: fade out (start → end), then optional timestamp + state glyph
        t.append_text(_fade_rule(right, fade_start, fade_end))
        if metrics_text:
            t.append(f" {metrics_text}", style="dim")
        if ts_text:
            t.append(f" · {ts_text}", style="dim")
        t.append_text(state_suffix)
        return t

    def _render_progress_bar(self) -> RenderResult:
        fade_start, fade_end, accent, _title_color = self._live_colors()
        width = max(1, self.size.width)
        filled = int(width * self.progress)
        if self.progress >= 0.9:
            bar_color = _skin_color("error_color", "#E06C75")
        elif self.progress >= 0.75:
            bar_color = _skin_color("warning_color", "#FFA726")
        else:
            bar_color = _skin_color("caution_color", "#FFBF00")
        empty_color = fade_start  # use live-reloaded dim colour
        t = Text()
        t.append("━" * filled, style=bar_color)
        t.append("─" * (width - filled), style=empty_color)
        return t


class PlainRule(Widget):
    """Plain horizontal rule that fades out."""

    DEFAULT_CSS = """
    PlainRule {
        height: 1;
    }
    """

    def __init__(
        self,
        fade_start: str | None = None,
        fade_end: str | None = None,
        max_width: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._fade_start = fade_start or _skin_color("rule_start", "#555555")
        self._fade_end = fade_end or _skin_color("rule_end", "#2A2A2A")
        self._max_width = max_width

    def render(self) -> RenderResult:
        w = self.size.width
        if self._max_width:
            w = min(w, self._max_width)
        fade_start = self._fade_start
        fade_end = self._fade_end
        try:
            v = self.app.get_css_variables()
            fade_start = v.get("rule-dim-color", fade_start)
            # Same fallback chain as TitledRule: rule-bg-color → app-bg → default
            fade_end = v.get("rule-bg-color") or v.get("app-bg", fade_end)
        except Exception:
            pass
        return _fade_rule(w, fade_start, fade_end)
