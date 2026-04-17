"""BodyRenderer abstract base class — Phase C."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, TYPE_CHECKING

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload
    from textual.widget import Widget


class BodyRenderer(ABC):
    kind: ClassVar["ResultKind"]
    supports_streaming: ClassVar[bool] = False  # only ShellOutputRenderer = True

    def __init__(self, payload: "ToolPayload", cls_result: "ClassificationResult") -> None:
        self.payload = payload
        self.cls_result = cls_result

    @classmethod
    @abstractmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        ...

    @abstractmethod
    def build(self):
        """Returns Rich renderable. Called in worker for >200 lines."""
        ...

    def build_widget(self) -> "Widget":
        """Override for renderers needing custom Widget (e.g. VirtualSearchList).
        Default: wraps build() in CopyableRichLog."""
        from hermes_cli.tui.widgets import CopyableRichLog
        rl = CopyableRichLog(highlight=False, markup=False)
        rl.write(self.build())
        return rl

    def refresh_incremental(self, chunk: str) -> None:
        raise NotImplementedError
