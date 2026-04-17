"""EmptyStateRenderer — renders empty/no-output state."""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from hermes_cli.tui.body_renderers.base import BodyRenderer

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload


class EmptyStateRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = False

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        from hermes_cli.tui.tool_payload import ResultKind
        return cls_result.kind == ResultKind.EMPTY

    def build(self):
        """Return dim Text indicating no output."""
        from rich.text import Text
        return Text("(no output)", style="dim")

    def build_widget(self):
        """Return a Static widget for empty state."""
        from textual.widgets import Static
        return Static("(no output)", classes="empty-state")


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    EmptyStateRenderer.kind = ResultKind.EMPTY


_set_kind()
