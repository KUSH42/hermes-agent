"""StartupBannerWidget — lightweight inline startup banner host inside OutputPanel."""
from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.binding import Binding
from textual.widgets import Static

from ._events import STARTUP_BANNER_READY, STARTUP_TTE_SKIP  # noqa: F401 — re-exported by __init__


class StartupBannerWidget(Static):
    """Lightweight inline startup banner host inside OutputPanel.

    Used for startup TTE frames so animation doesn't go through
    ``CopyableRichLog.clear()+write()`` on every frame.
    """

    # TTE frames use fully-explicit ANSI colors; link scanning on every render
    # clones every Segment in every Strip (O(lines × spans)) at 60fps, driving
    # Python Gen-2 GC at ~1Hz.  There are no interactive links in animation frames.
    auto_links = False

    DEFAULT_CSS = """
    StartupBannerWidget {
        height: auto;
        width: 100%;
        overflow-x: hidden;
        margin: 1 0 0 0;
        text-wrap: nowrap;
        background: $app-bg;
    }
    """

    BINDINGS = [
        Binding("escape", "skip_tte", "Skip", show=False),
        Binding("s", "skip_tte", "Skip", show=False),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(Text(""), **kwargs)
        self._frame_count: int = 0

    def on_mount(self) -> None:
        STARTUP_BANNER_READY.set()

    def on_unmount(self) -> None:
        # Clear so a hot-reload or second App instance waits correctly.
        STARTUP_BANNER_READY.clear()
        STARTUP_TTE_SKIP.clear()

    def action_skip_tte(self) -> None:
        STARTUP_TTE_SKIP.set()
        self.refresh()

    def set_frame(self, rich_text: Text) -> None:
        # Always layout=True: animation frames are the same size as each other
        # but the final static banner is taller. Without layout=True on the final
        # frame, height:auto stays locked to the first animation frame's height,
        # making max_scroll_y=0 so scroll_end is a no-op.
        self._frame_count += 1
        self.update(rich_text, layout=True)
