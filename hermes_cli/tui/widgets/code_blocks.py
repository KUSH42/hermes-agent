"""Code block widgets for the Hermes TUI.

Contains: CodeBlockFooter, StreamingCodeBlock.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from .renderers import CopyableRichLog
from .utils import (
    _PRENUMBERED_LINE_RE,
    _boost_layout_caches,
    _prewrap_code_line,
    _strip_ansi,
)

if TYPE_CHECKING:
    pass


def _strip_bold(style_str: str) -> str:
    """Remove bold, italic, and underline modifiers from a Pygments style string."""
    return re.sub(r'\b(bold|italic|underline)\b\s*', '', style_str).strip()


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
    CodeBlockFooter.--flash-copy > #code-copy-action {
        color: $success;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._copy = Static("", id="code-copy-action", classes="action")
        self._sep = Static("", classes="sep")
        self._toggle = Static("", id="code-toggle-action", classes="action")
        self._copy_original: str = ""

    def compose(self) -> ComposeResult:
        yield self._copy
        yield self._sep
        yield self._toggle

    def on_mount(self) -> None:
        # RX1 Phase B: register code-footer channel with FeedbackService
        try:
            from hermes_cli.tui.services.feedback import CodeFooterAdapter
            self.app.feedback.register_channel(
                f"code-footer::{self.id}",
                CodeFooterAdapter(self),
            )
        except Exception:
            pass

    def on_unmount(self) -> None:
        # RX1 Phase B: deregister code-footer channel
        try:
            self.app.feedback.deregister_channel(f"code-footer::{self.id}")
        except Exception:
            pass

    def set_actions(self, *, copy_label: str, toggle_label: str | None) -> None:
        self._copy_original = copy_label
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

    def flash_copy(self, flash_label: str = "✓ Copied", duration: float = 1.5) -> None:
        """Briefly swap the copy label to a success indicator.

        Routes through FeedbackService (RX1 Phase B).
        """
        try:
            self.app.feedback.flash(
                f"code-footer::{self.id}",
                flash_label,
                duration=duration,
                key="copy",
            )
        except Exception:
            pass

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
    _tooltip_text: str = "Click to expand/collapse  ·  double-click to copy"

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
        self._partial_line: str = ""
        self._collapsed = False
        self._controls_text_plain = ""
        self._complete_skin_vars: dict[str, str] = {}

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
        self.clear_partial()
        if self._state != "STREAMING":
            return
        self._state = "COMPLETE"
        self._pygments_theme = skin_vars.get("preview-syntax-theme", self._pygments_theme)
        self._complete_skin_vars = dict(skin_vars)
        self.add_class("--complete")
        app = getattr(self, "app", None)
        if self._lang == "mermaid" and getattr(app, "_mermaid_enabled", False):
            self._try_render_mermaid_async()
        else:
            self.call_after_refresh(self._finalize_syntax, dict(skin_vars))
        # Browse streaming→ready flash
        try:
            _mounted = self.is_mounted
        except Exception:
            _mounted = False
        if (
            _mounted
            and getattr(app, "browse_mode", False)
            and getattr(app, "_browse_markers_enabled", True)
            and getattr(app, "_browse_streaming_flash", True)
        ):
            self.add_class("--browse-newly-anchored")
            try:
                self.set_timer(0.6, lambda: self.remove_class("--browse-newly-anchored"))
            except Exception:
                pass

    def _try_render_mermaid_async(self) -> None:
        """Dispatch mermaid rendering via safe_run (io_boundary).

        On success: mounts an InlineImage sibling after this block.
        On failure (mmdc absent, render error): falls back to _render_syntax().
        """
        from hermes_cli.tui.math_renderer import _build_mermaid_cmd
        from hermes_cli.tui.io_boundary import safe_run

        code = "\n".join(self._display_code_lines())
        result = _build_mermaid_cmd(code)
        if result is None:
            self._on_mermaid_rendered(None)
            return

        cmd, mmd_tmp, png_tmp = result

        def _cleanup_tmps(m: "object", p: "object") -> None:
            try:
                m.unlink(missing_ok=True)  # type: ignore[union-attr]
            except Exception:
                pass
            try:
                p.unlink(missing_ok=True)  # type: ignore[union-attr]
            except Exception:
                pass

        safe_run(
            self,
            cmd,
            timeout=30,
            on_success=lambda out, err, rc: (
                self._on_mermaid_rendered(png_tmp),
                mmd_tmp.unlink(missing_ok=True),
            ),
            on_error=lambda exc, err: (
                self._on_mermaid_rendered(None),
                _cleanup_tmps(mmd_tmp, png_tmp),
            ),
            on_timeout=lambda elapsed: (
                self._on_mermaid_rendered(None),
                _cleanup_tmps(mmd_tmp, png_tmp),
            ),
        )

    def _on_mermaid_rendered(self, path: "Any") -> None:
        """Called on the event-loop thread with the rendered PNG path (or None)."""
        if path is None:
            # mmdc unavailable or render failed — show syntax-highlighted source
            self._render_syntax(self._complete_skin_vars or None)
            return
        try:
            from hermes_cli.tui.widgets.inline_media import InlineImage
            max_rows = getattr(getattr(self, "app", None), "_math_max_rows", 24)
            img_widget = InlineImage(image=path, max_rows=max_rows)
            self.parent.mount(img_widget, after=self)
        except Exception:
            self._render_syntax(self._complete_skin_vars or None)

    def _render_syntax(self, skin_vars: dict[str, str] | None = None) -> None:
        """Render code as rich.Syntax with line numbers. Shared by COMPLETE and FLUSHED."""
        from rich.syntax import Syntax
        from hermes_cli.tui.response_flow import _detect_lang
        vars = skin_vars or (self.app.get_css_variables() if self.app else {})
        code = "\n".join(self._display_code_lines())
        lang = getattr(self, "_resolved_lang", None) or getattr(self, "_lang", "") or _detect_lang(code)
        self._resolved_lang = lang
        self._pygments_theme = vars.get("preview-syntax-theme", getattr(self, "_pygments_theme", "monokai"))
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

    def feed_partial(self, fragment: str) -> None:
        """Show a partial (sub-line) fragment with a cursor indicator."""
        self._partial_line = fragment
        pd = getattr(self, "_partial_display", None)
        if pd is not None:
            pd.styles.display = "block"
            t = Text(fragment)
            t.append("▌", style="dim")
            pd.update(t)

    def clear_partial(self) -> None:
        """Clear the partial fragment display."""
        if not getattr(self, "_partial_line", ""):
            return
        self._partial_line = ""
        pd = getattr(self, "_partial_display", None)
        if pd is not None:
            pd.update("")

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
        self._syntax_bold = css_vars.get("preview-syntax-bold", "true") != "false"
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
        self.set_timer(1.5, lambda: self.remove_class("--copy-flash"))

    def _update_controls(self) -> None:
        """Update _controls_text_plain for backward compat (tests)."""
        if self.can_toggle():
            t = Text(" ")
            t.append("expand" if self._collapsed else "collapse", style="dim")
            self._controls_text_plain = t.plain
        else:
            self._controls_text_plain = ""

    def on_click(self, event: Any) -> None:
        """Left single-click toggles; double-click copies code."""
        if getattr(event, "button", 1) != 1:
            return
        if getattr(event, "chain", 1) == 2:
            # E1: double-click copies code (only when finalized, not streaming)
            if getattr(self, "_state", "STREAMING") != "STREAMING":
                code = "\n".join(self._display_code_lines())
                try:
                    self.app._copy_text_with_hint(code)
                except Exception:
                    pass
                event.prevent_default()
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
