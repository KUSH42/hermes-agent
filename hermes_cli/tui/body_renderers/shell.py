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

    def __init__(self, payload: "ToolPayload", cls_result: "ClassificationResult") -> None:
        super().__init__(payload, cls_result)
        self._log_widget: "CopyableRichLog | None" = None

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        return True  # always renderable; selection handled by pick_renderer

    def build(self):
        """Build Rich renderable from shell output, stripping CWD tokens."""
        from rich.text import Text
        from hermes_cli.tui.cwd_strip import strip_cwd

        raw = self.payload.output_raw or ""
        cleaned, cwd = strip_cwd(raw)

        result = Text()
        for line in cleaned.splitlines():
            result.append_text(Text.from_ansi(line))
            result.append("\n")

        if cwd is not None:
            from rich.text import Text as RichText
            cwd_line = RichText(f"cwd: {cwd}", style="dim")
            result.append_text(cwd_line)
            result.append("\n")

        return result

    def build_widget(self):
        """Create a CopyableRichLog, populate it, and store a ref for streaming."""
        from hermes_cli.tui.widgets import CopyableRichLog
        from rich.text import Text
        from hermes_cli.tui.cwd_strip import strip_cwd

        rl = CopyableRichLog(highlight=False, markup=False)
        self._log_widget = rl

        raw = self.payload.output_raw or ""
        cleaned, cwd = strip_cwd(raw)

        for line in cleaned.splitlines():
            rl.write(Text.from_ansi(line))

        if cwd is not None:
            cwd_line = Text(f"cwd: {cwd}", style="dim")
            rl.write(cwd_line)

        return rl

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
