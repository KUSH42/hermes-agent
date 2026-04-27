"""BodyRenderer abstract base class — Phase C."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, TYPE_CHECKING

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload
    from textual.widget import Widget
    from hermes_cli.tui.body_renderers._grammar import SkinColors
    from hermes_cli.tui.services.tools import ToolCallState
    from hermes_cli.tui.tool_panel.density import DensityTier
    from hermes_cli.tui.tool_panel.layout_resolver import LayoutDecision
    from rich.console import ConsoleRenderable
    from rich.text import Text


class BodyRenderer(ABC):
    kind: ClassVar["ResultKind"]
    supports_streaming: ClassVar[bool] = False  # only ShellOutputRenderer = True
    footer_entries: ClassVar[tuple] = (("y", "copy"),)

    # Phases at which this renderer is willing to be picked. Subclasses may
    # override to narrow further; empty frozenset means {COMPLETING, DONE}.
    accepted_phases: ClassVar[frozenset["ToolCallState"]] = frozenset()

    @classmethod
    def accepts(cls, phase: "ToolCallState", density: "DensityTier") -> bool:
        """Return True iff this renderer is willing to render at (phase, density).

        Default policy: accept any phase in {COMPLETING, DONE} at any density.
        Override accepted_phases to widen; override accepts() to add density logic.
        """
        from hermes_cli.tui.services.tools import ToolCallState
        allowed = cls.accepted_phases or frozenset({ToolCallState.COMPLETING, ToolCallState.DONE})
        return phase in allowed

    def __init__(
        self,
        payload: "ToolPayload | None" = None,
        cls_result: "ClassificationResult | None" = None,
        *,
        app=None,
        decision: "LayoutDecision | None" = None,
    ) -> None:
        self.payload = payload  # type: ignore[assignment]
        self.cls_result = cls_result  # type: ignore[assignment]
        self._app = app
        self._decision = decision
        self._colors: "SkinColors | None" = None

    @property
    def colors(self) -> "SkinColors":
        if self._colors is None:
            from hermes_cli.tui.body_renderers._grammar import SkinColors
            self._colors = SkinColors.from_app(self._app) if self._app else SkinColors.default()
        return self._colors

    def decision_or_default(
        self,
        *,
        phase: "ToolCallState",
        density: "DensityTier",
        width: int,
    ) -> "LayoutDecision":
        """Return the stored decision, or synthesise one from explicit args."""
        if self._decision is not None:
            return self._decision
        from hermes_cli.tui.tool_panel.layout_resolver import LayoutDecision, DensityTier as _DT
        return LayoutDecision(
            tier=density,
            footer_visible=(density != _DT.COMPACT),
            width=width,
            reason="initial",
        )

    @classmethod
    @abstractmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        ...

    @abstractmethod
    def build(self):
        """Returns Rich renderable. Called in worker for >200 lines."""
        ...

    def _user_forced_caption_renderable(self) -> "Text | None":
        """Return caption Text if this render was manually forced by the user, else None."""
        if not getattr(self.cls_result, "_user_forced", False):
            return None
        from hermes_cli.tui.body_renderers._grammar import user_forced_caption
        return user_forced_caption(self.cls_result.kind)

    def build_widget(self, density: "DensityTier | None" = None) -> "Widget":
        """Override for renderers needing custom Widget (e.g. VirtualSearchList).
        Default: wraps build() in CopyableRichLog."""
        from hermes_cli.tui.widgets import CopyableRichLog
        rl = CopyableRichLog(highlight=False, markup=False)
        caption = self._user_forced_caption_renderable()
        if caption is not None:
            rl.write(caption)
        rl.write(self.build())
        return rl

    def refresh_incremental(self, chunk: str) -> None:
        raise NotImplementedError

    # ----- streaming protocol (R-2B-1) -----

    def render_stream_line(self, raw: str, plain: str) -> "ConsoleRenderable":
        """Per-line streaming render. Override in renderers that accept STREAMING."""
        raise NotImplementedError(
            f"{type(self).__name__} did not opt into STREAMING; "
            "registry should not have selected it."
        )

    def finalize(
        self, all_plain: list[str], **kwargs: object
    ) -> "ConsoleRenderable | None":
        """Optional post-stream replacement. Default: no swap."""
        return None

    def preview(self, all_plain: list[str], max_lines: int) -> "ConsoleRenderable":
        """Lightweight preview (footer / collapsed body). Default: dim tail."""
        from rich.text import Text
        tail = all_plain[-max_lines:] if all_plain else []
        return Text("\n".join(tail), style="dim")

    def extract_sidecar(self, tool_call: object, all_plain: list[str]) -> None:
        """Optional post-finalize hook to mutate ToolCall fields."""
        return None

    @classmethod
    def streaming_kind_hint(cls, first_chunk: str) -> "ResultKind | None":
        """Return a ResultKind if the first chunk is a strong signal for this renderer's kind.

        Called once per block at sniff-threshold crossing or COMPLETING (whichever first).
        Must be O(1) on chunk length — input is pre-truncated to 256 bytes by the service.
        Must not raise (service wraps in try/except; raises are logged and treated as None).
        Must be deterministic. Default: None (no hint).
        """
        return None
