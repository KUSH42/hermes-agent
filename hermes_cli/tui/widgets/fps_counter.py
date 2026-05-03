"""FPSCounter — floating HUD for event-loop FPS + avg-ms."""
from __future__ import annotations

from rich.text import Text
from textual.app import RenderResult
from textual.reactive import reactive
from textual.widget import Widget


class FPSCounter(Widget):
    """Floating FPS / avg-ms HUD.

    Displays the event-loop timer delivery rate (target: 10 fps) and average
    milliseconds per tick.  Values come from :class:`~hermes_cli.tui.perf.FrameRateProbe`
    via two reactives that ``HermesApp._tick_fps`` sets every 0.1 s.

    Toggle with **F8** or set ``display.fps_hud: true`` in your Hermes config to start visible.

    Visual layout::

        ┌──────────────────┐  ← docked top, overlay layer (no layout reflow)
        │  10.0fps  9.8ms  │
        └──────────────────┘

    Structural CSS is in ``DEFAULT_CSS``; visual CSS is in ``hermes.tcss``.
    The widget stays ``display: none`` until the ``--visible`` class is added.
    """

    DEFAULT_CSS = """
    FPSCounter {
        layer: overlay;
        dock: top;
        width: 18;
        height: 1;
        display: none;
    }
    FPSCounter.--visible {
        display: block;
    }
    """

    fps: reactive[float] = reactive(0.0, repaint=True)
    avg_ms: reactive[float] = reactive(0.0, repaint=True)

    def render(self) -> RenderResult:
        # fps here is the event-loop timer delivery rate (target: 10 Hz).
        # Display as Hz so it's not confused with screen render FPS.
        # avg_ms is the mean interval between probe ticks (~100ms = healthy).
        t = Text()
        t.append(f"{self.fps:.1f}", style="bold")
        t.append("Hz ", style="dim")
        t.append(f"{self.avg_ms:.0f}ms", style="dim")
        return t
