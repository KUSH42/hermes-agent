"""FallbackRenderer — plain text fallback for unclassified output."""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from hermes_cli.tui.body_renderers.base import BodyRenderer

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload


class FallbackRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = False
    truncation_bias: ClassVar = "tail"
    kind_icon: ClassVar[str] = "⬜"

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        return True  # terminator — always matches

    def _should_show_footer(self) -> bool:
        from hermes_cli.tui.tool_payload import ResultKind
        return (
            self.cls_result.confidence < 0.5
            or self.cls_result.kind == ResultKind.TEXT
        )

    def build(self):
        """Build CopyableRichLog-compatible output from raw text."""
        from rich.text import Text

        raw = self.payload.output_raw or ""
        result = Text()
        for line in raw.splitlines():
            result.append_text(Text.from_ansi(line))
            result.append("\n")

        return result

    def build_widget(self, density=None, clamp_rows=None):
        """Wrap the plain-text body in a BodyFrame with the unclassified rule
        on the header (concept §161 normalisation — rule moves out of body)."""
        from hermes_cli.tui.body_renderers._grammar import build_rule
        from hermes_cli.tui.body_renderers._frame import BodyFrame
        from hermes_cli.tui.widgets import CopyableRichLog
        rl = CopyableRichLog(highlight=False, markup=True)
        rl.write(self.build())
        header = (
            build_rule("unclassified · plain text", colors=self.colors)
            if self._should_show_footer() else None
        )
        return BodyFrame(
            header=header,
            body=rl,
            footer=None,
            density=density,
        )


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    FallbackRenderer.kind = ResultKind.TEXT


_set_kind()
