"""TTEWidget — non-blocking Terminal Text Effects inside Textual."""
from __future__ import annotations

import logging
import time
from typing import Any

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static

_log = logging.getLogger(__name__)


class TTEWidget(Widget):
    """Renders a Terminal Text Effects animation inside Textual."""

    DEFAULT_CSS = """
    TTEWidget {
        height: auto;
        min-height: 0;
        display: none;
    }
    TTEWidget.active {
        display: block;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._done_event: "Any | None" = None

    def compose(self) -> ComposeResult:
        yield Static("", id="tte-frame")

    def play(
        self,
        effect_name: str,
        text: str,
        params: dict[str, object] | None = None,
        done_event: "Any | None" = None,
    ) -> None:
        """Start a TTE animation. Non-blocking."""
        self.stop()
        self._done_event = done_event
        self.add_class("active")
        self._run_animation(effect_name, text, params)

    def stop(self) -> None:
        """Stop current animation and hide widget."""
        self.remove_class("active")
        try:
            frame = self.query_one("#tte-frame", Static)
            frame.update("")
        except NoMatches:  # il-ex-1-exempt: swallow
            pass
        if self._done_event is not None:
            self._done_event.set()
            self._done_event = None

    @work(thread=True, exclusive=True)
    def _run_animation(
        self,
        effect_name: str,
        text: str,
        params: dict[str, object] | None = None,
    ) -> None:
        """Background worker — generates TTE frames and pushes to UI."""
        done_event = self._done_event  # capture once; avoids racing with play()/stop()
        try:
            from hermes_cli.tui.tte_runner import iter_frames
            from textual import constants as _tc

            _frame_interval = 1.0 / _tc.MAX_FPS
            _next_t = time.monotonic()
            for frame in iter_frames(effect_name, text, params=params):
                if not self.is_mounted:
                    return
                rich_text = Text.from_ansi(frame)
                self.app.call_from_thread(self._update_frame, rich_text)
                _next_t += _frame_interval
                _sleep = _next_t - time.monotonic()
                if _sleep > 0:
                    time.sleep(_sleep)
        except Exception:
            _log.debug("TTEWidget animation error", exc_info=True)
        finally:
            if self.is_mounted:
                self.app.call_from_thread(self.remove_class, "active")
            if done_event is not None:
                done_event.set()

    def _update_frame(self, rich_text: Text) -> None:
        """Update frame widget on event loop."""
        try:
            frame = self.query_one("#tte-frame", Static)
            frame.update(rich_text)
        except NoMatches:  # il-ex-1-exempt: swallow
            pass
