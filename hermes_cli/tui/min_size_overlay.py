"""Minimum-size floor overlay — shown when terminal is too small to render."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.resize_utils import THRESHOLD_MIN_HEIGHT, THRESHOLD_ULTRA_NARROW


class MinSizeBox(Widget):
    """Inner content box with the warning message."""

    DEFAULT_CSS = """
    MinSizeBox {
        width: auto;
        height: auto;
        min-width: 26;
        min-height: 4;
        border: round $warning;
        padding: 0 2;
        background: $surface;
    }
    """

    def __init__(self, w: int, h: int) -> None:
        super().__init__()
        self._w = w
        self._h = h

    def compose(self) -> ComposeResult:
        yield Static(
            f"⚠  Terminal too small ({self._w}×{self._h})",
            classes="min-size-warning",
        )
        yield Static(
            f"Resize to ≥{THRESHOLD_ULTRA_NARROW}×{THRESHOLD_MIN_HEIGHT}",
            classes="min-size-hint",
        )

    def update_size(self, w: int, h: int) -> None:
        self._w = w
        self._h = h
        try:
            self.query_one(".min-size-warning", Static).update(
                f"⚠  Terminal too small ({w}×{h})"
            )
        except Exception:
            pass


class MinSizeBackdrop(Widget):
    """Full-screen overlay shown when terminal falls below the minimum viable size.

    Mounts on Screen.overlay layer so it covers all content.  ``can_focus=False``
    so keyboard events pass through to the underlying app — the user can still
    resize back without being trapped.
    """

    can_focus = False
    ALLOW_MAXIMIZE = False

    DEFAULT_CSS = """
    MinSizeBackdrop {
        layer: overlay;
        width: 100%;
        height: 100%;
        background: $surface 70%;
        align: center middle;
    }
    """

    def __init__(self, w: int, h: int) -> None:
        super().__init__()
        self._box = MinSizeBox(w, h)

    def compose(self) -> ComposeResult:
        yield self._box

    def update_size(self, w: int, h: int) -> None:
        self._box.update_size(w, h)
