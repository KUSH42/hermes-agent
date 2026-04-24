"""EmptyStateRenderer — renders empty/no-output state."""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from hermes_cli.tui.body_renderers.base import BodyRenderer

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload


def _get_empty_message(category) -> str:
    from hermes_cli.tui.tool_category import ToolCategory
    return {
        ToolCategory.SHELL:  "(no output)",
        ToolCategory.SEARCH: "No matches",
        ToolCategory.FILE:   "Empty file",
        ToolCategory.WEB:    "No content",
        ToolCategory.CODE:   "(no output)",
        ToolCategory.AGENT:  "(no result)",
        ToolCategory.MCP:    "(no result)",
    }.get(category, "(no output)")


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
        msg = _get_empty_message(getattr(self.payload, "category", None))
        return Text(msg, style="dim")

    def build_widget(self):
        """Return a Static widget for empty state."""
        from textual.widgets import Static
        msg = _get_empty_message(getattr(self.payload, "category", None))
        return Static(msg, classes="empty-state")


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    EmptyStateRenderer.kind = ResultKind.EMPTY


_set_kind()
