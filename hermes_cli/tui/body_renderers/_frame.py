"""BodyFrame — canonical body container: header + body + footer slots."""
from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
    from rich.console import RenderableType
    from hermes_cli.tui.body_renderers._grammar import BodyFooter
    from hermes_cli.tui.tool_panel.density import DensityTier

_TIER_CLASS: dict[str, str] = {
    "hero":    "body-frame--hero",
    "default": "body-frame--default",
    "compact": "body-frame--compact",
    "trace":   "body-frame--trace",
}


class BodyFrame(Widget):
    """Canonical body container: header slot + body slot + footer slot.

    header and footer are Rich renderables wrapped in Static children.
    body may be either a RenderableType (wrapped in Static) or a pre-built
    Widget (mounted directly) to accommodate renderers that produce complex
    Textual widget trees (DiffRenderer, SearchRenderer, JsonRenderer).
    """

    DEFAULT_CSS = """
BodyFrame {
    height: auto;
    width: 1fr;
}
BodyFrame > .body-frame--header { height: auto; }
BodyFrame > .body-frame--body   { height: auto; width: 1fr; }
BodyFrame > .body-frame--footer { height: 1; }
BodyFrame.body-frame--compact > BodyFooter { display: none; }
BodyFrame.body-frame--default { margin-bottom: 1; }
"""

    def __init__(
        self,
        header: "RenderableType | None",
        body: "RenderableType | Widget",
        footer: "BodyFooter | None",
        *,
        density: "DensityTier | None" = None,
        classes: str = "",
    ) -> None:
        tier_class = ""
        if density is not None:
            tier_class = _TIER_CLASS.get(str(density.value) if hasattr(density, "value") else str(density), "")
        super().__init__(classes=f"{classes} {tier_class}".strip())
        self._header = header
        self._body = body
        self._footer = footer
        self._density = density

    def compose(self) -> ComposeResult:
        if self._header is not None:
            yield Static(self._header, classes="body-frame--header")
        if isinstance(self._body, Widget):
            self._body.add_class("body-frame--body")
            yield self._body
        else:
            yield Static(self._body, classes="body-frame--body")
        if self._footer is not None:
            yield self._footer
