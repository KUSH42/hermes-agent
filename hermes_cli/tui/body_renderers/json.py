"""JsonRenderer — pretty-printed JSON using rich.pretty.Pretty."""
from __future__ import annotations

import json
from typing import TYPE_CHECKING, ClassVar

from hermes_cli.tui.body_renderers.base import BodyRenderer

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload


class JsonRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = False

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        from hermes_cli.tui.tool_payload import ResultKind
        return cls_result.kind == ResultKind.JSON

    def build(self):
        """Build a rich.pretty.Pretty renderable. Falls back to Text on parse failure."""
        from rich.pretty import Pretty
        from rich.text import Text

        raw = self.payload.output_raw or ""
        try:
            data = json.loads(raw)
            return Pretty(data, indent_guides=True)
        except (json.JSONDecodeError, MemoryError, ValueError):
            return Text(raw)


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    JsonRenderer.kind = ResultKind.JSON


_set_kind()
