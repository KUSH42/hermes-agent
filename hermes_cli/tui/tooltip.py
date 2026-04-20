"""Tooltip widget and TooltipMixin for hover hints in the Hermes TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widget import Widget

if TYPE_CHECKING:
    pass


class Tooltip(Widget):
    """Ephemeral hover tooltip, mounted on the screen tooltip layer."""

    DEFAULT_CSS = """
    Tooltip {
        layer: tooltip;
        position: absolute;
        background: $surface;
        border: tall $accent 40%;
        padding: 0 1;
        width: auto;
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(self, text: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._text = text

    def render(self) -> str:
        return self._text


class TooltipMixin:
    """Mixin for Widget subclasses that want a hover tooltip after a short delay.

    Usage::

        class MyWidget(TooltipMixin, Widget):
            _tooltip_text = "Hover hint"
    """

    _tooltip_text: str = ""
    _tooltip_timer: Any = None
    _tooltip_widget: "Tooltip | None" = None
    _TOOLTIP_DELAY: float = 0.5

    def on_mouse_enter(self, _event: Any) -> None:
        if not self._tooltip_text:
            return
        if self._tooltip_timer is not None:
            self._tooltip_timer.stop()
        self._tooltip_timer = self.set_timer(  # type: ignore[attr-defined]
            self._TOOLTIP_DELAY, self._show_tooltip
        )

    def on_mouse_leave(self, _event: Any) -> None:
        if self._tooltip_timer is not None:
            self._tooltip_timer.stop()
            self._tooltip_timer = None
        self._dismiss_tooltip()

    def _show_tooltip(self) -> None:
        self._tooltip_timer = None
        if self._tooltip_widget is not None and self._tooltip_widget.is_mounted:
            return
        try:
            t = Tooltip(self._tooltip_text)
            self.app.screen.mount(t)  # type: ignore[attr-defined]
            region = self.content_region  # type: ignore[attr-defined]
            app_w = self.app.size.width  # type: ignore[attr-defined]
            app_h = self.app.size.height  # type: ignore[attr-defined]
            est_w = len(self._tooltip_text) + 4  # +4 for border + padding
            x = min(region.x, max(0, app_w - est_w - 1))
            y = min(region.y + region.height, app_h - 2)
            t.styles.offset = (x, y)
            self._tooltip_widget = t
        except Exception:
            pass

    def _dismiss_tooltip(self) -> None:
        if self._tooltip_widget is not None and self._tooltip_widget.is_mounted:
            self._tooltip_widget.remove()
        self._tooltip_widget = None
