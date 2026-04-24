"""EmptyStateRenderer — renders empty/no-output state."""
from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from hermes_cli.tui.body_renderers.base import BodyRenderer

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload


def _get_empty_message(category) -> str:
    from hermes_cli.tui.tool_category import ToolCategory
    return {
        ToolCategory.SHELL:  "No output",
        ToolCategory.SEARCH: "No matches",
        ToolCategory.FILE:   "Empty file",
        ToolCategory.WEB:    "No content",
        ToolCategory.CODE:   "No output",
        ToolCategory.AGENT:  "No result",
        ToolCategory.MCP:    "No result",
    }.get(category, "No output")


class EmptyStateRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = False

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        from hermes_cli.tui.tool_payload import ResultKind
        return cls_result.kind == ResultKind.EMPTY

    def _build_message(self) -> str:
        category = getattr(self.payload, "category", None)
        msg = _get_empty_message(category)

        exit_code = getattr(self.payload, "exit_code", None)
        started_at = getattr(self.payload, "started_at", 0.0) or 0.0
        finished_at = getattr(self.payload, "finished_at", None)

        elapsed: float | None = None
        if finished_at is not None and started_at is not None:
            elapsed = finished_at - started_at

        suffix_parts = []
        if elapsed is not None:
            suffix_parts.append(f"{elapsed:.2f}s")
        if exit_code is not None:
            suffix_parts.append(f"exit {exit_code}")

        if suffix_parts:
            return f"{msg} · {' · '.join(suffix_parts)}"
        return msg

    def build(self):
        """Return dim Text indicating no output."""
        from rich.text import Text
        msg = self._build_message()
        return Text(msg, style="dim")

    def build_widget(self):
        """Return a Static widget for empty state."""
        from textual.widgets import Static
        msg = self._build_message()
        return Static(msg, classes="empty-state")


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    EmptyStateRenderer.kind = ResultKind.EMPTY


_set_kind()
