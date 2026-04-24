"""FallbackRenderer — plain text fallback for unclassified output."""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from hermes_cli.tui.body_renderers.base import BodyRenderer

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload


class FallbackRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = False

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        return True  # terminator — always matches

    def build(self):
        """Build CopyableRichLog-compatible output from raw text."""
        from rich.text import Text

        raw = self.payload.output_raw or ""
        result = Text()
        for line in raw.splitlines():
            result.append_text(Text.from_ansi(line))
            result.append("\n")
        return result


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    FallbackRenderer.kind = ResultKind.TEXT


_set_kind()
