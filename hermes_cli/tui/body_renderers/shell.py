"""ShellOutputRenderer — ANSI-aware shell output renderer with CWD stripping."""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from hermes_cli.tui.body_renderers.base import BodyRenderer

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload
    from hermes_cli.tui.widgets import CopyableRichLog


class ShellOutputRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = True
    truncation_bias: ClassVar = "tail"
    kind_icon: ClassVar[str] = "$"

    def __init__(self, payload: "ToolPayload", cls_result: "ClassificationResult", **kwargs) -> None:
        super().__init__(payload, cls_result, **kwargs)
        self._log_widget: "CopyableRichLog | None" = None

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        return True  # always renderable; selection handled by pick_renderer

    def _build_body(self, cleaned: str) -> "object":
        """Build body renderable from pre-stripped shell output (no cwd rule)."""
        from rich.text import Text
        from rich.style import Style as _Style
        from hermes_cli.tui.body_renderers._grammar import build_rule, glyph

        result = Text()

        for line in cleaned.splitlines():
            result.append_text(Text.from_ansi(line))
            result.append("\n")

        # Exit code rule (non-zero or non-None shows rule; zero skipped)
        exit_code = getattr(self.payload, "exit_code", None)
        if exit_code is not None and exit_code != 0:
            error_color = self.colors.error if self.colors else "#E06C75"
            exit_line = Text()
            exit_line.append(glyph("──") + " ", style=_Style(color=error_color))
            exit_line.append(f"exit {exit_code}", style=_Style(color=error_color))
            exit_line.append(" " + glyph("──"), style=_Style(color=error_color))
            result.append_text(exit_line)
            result.append("\n")

        # Stderr lines with "! " gutter
        stderr_raw = getattr(self.payload, "stderr_raw", None)
        if stderr_raw:
            error_color = self.colors.error if self.colors else "#E06C75"
            for line in stderr_raw.splitlines():
                stderr_line = Text()
                stderr_line.append("! ", style=_Style(color=error_color))
                stderr_line.append(line)
                result.append_text(stderr_line)
                result.append("\n")

        return result

    def build(self):
        """Build Rich renderable from shell output, stripping CWD tokens."""
        from rich.text import Text
        from hermes_cli.tui.cwd_strip import strip_cwd
        from hermes_cli.tui.body_renderers._grammar import build_rule

        raw = self.payload.output_raw or ""
        cleaned, cwd = strip_cwd(raw)

        result = Text()

        # Emit leading CWD rule only when header breadcrumb does not already show it
        header_has_cwd = getattr(self.payload, "header_has_cwd", False)
        if cwd is not None and not header_has_cwd:
            cwd_rule = build_rule(f"cwd: {cwd}", colors=self.colors)
            result.append_text(cwd_rule)
            result.append("\n")

        result.append_text(self._build_body(cleaned))
        return result

    def build_widget(self, density=None, clamp_rows=None):
        from hermes_cli.tui.cwd_strip import strip_cwd
        from hermes_cli.tui.body_renderers._grammar import build_path_header, BodyFooter
        from hermes_cli.tui.body_renderers._frame import BodyFrame

        raw = self.payload.output_raw or ""
        cleaned, cwd = strip_cwd(raw)

        header_has_cwd = getattr(self.payload, "header_has_cwd", False)
        header = (
            build_path_header(cwd, colors=self.colors)
            if cwd and not header_has_cwd else None
        )
        return BodyFrame(
            header=header,
            body=self._build_body(cleaned),
            footer=BodyFooter(("y", "copy")),
            density=density,
        )

    def refresh_incremental(self, chunk: str) -> None:
        """Append a new chunk to the live log widget."""
        if self._log_widget is None:
            return
        from rich.text import Text
        self._log_widget.write(Text.from_ansi(chunk))


# Set kind after import to avoid circular import issues
def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    ShellOutputRenderer.kind = ResultKind.TEXT


_set_kind()
