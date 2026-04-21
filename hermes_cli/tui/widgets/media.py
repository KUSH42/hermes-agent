"""Inline media player widgets for the Hermes TUI.

Contains: SeekBar, InlineMediaWidget.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.tooltip import TooltipMixin
from .renderers import InlineThumbnail

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp


class SeekBar(TooltipMixin, Widget):
    """Horizontal seek bar — click to seek, ←→ for ±5s, space to pause/resume."""

    can_focus = True

    DEFAULT_CSS = """
    SeekBar { height: 1; }
    """

    BINDINGS = [
        Binding("left",  "seek_back",    "−5s",  show=False),
        Binding("right", "seek_forward", "+5s",  show=False),
        Binding("space", "play_pause",   "Play", show=False),
    ]

    position: reactive[float] = reactive(0.0)
    duration: reactive[float] = reactive(0.0)
    playing:  reactive[bool]  = reactive(False)

    _ICON_COLS = 2
    _TIME_COLS = 14

    _tooltip_text = "Click to seek"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.on_seek:       "Callable[[float], None] | None" = None
        self.on_play_pause: "Callable[[], None] | None" = None

    def render(self) -> Text:
        icon = "⏸ " if self.playing else "▶ "
        pos_s = int(self.position)
        dur_s = int(self.duration)
        pos_str = f"{pos_s // 60}:{pos_s % 60:02d}"
        dur_str = f"{dur_s // 60}:{dur_s % 60:02d}"
        time_str = f" {pos_str} / {dur_str}"
        time_str = time_str.rjust(self._TIME_COLS)

        width = self.size.width
        bar_cols = width - self._ICON_COLS - self._TIME_COLS
        t = Text(no_wrap=True, overflow="crop")
        t.append(icon)
        if bar_cols >= 1 and self.duration > 0:
            filled = int((self.position / self.duration) * bar_cols)
            filled = max(0, min(filled, bar_cols))
            bar = "━" * filled + "╸" + "━" * (bar_cols - filled - 1) if filled < bar_cols else "━" * bar_cols
            t.append(bar)
        t.append(time_str)
        return t

    def on_click(self, event: Any) -> None:
        bar_x    = event.x - self._ICON_COLS
        bar_cols = self.size.width - self._ICON_COLS - self._TIME_COLS
        if bar_cols > 0 and self.duration > 0 and 0 <= bar_x < bar_cols:
            pos = (bar_x / bar_cols) * self.duration
            if self.on_seek:
                self.on_seek(pos)

    def action_seek_back(self) -> None:
        if self.on_seek:
            self.on_seek(max(0.0, self.position - 5.0))

    def action_seek_forward(self) -> None:
        if self.on_seek and self.duration > 0:
            self.on_seek(min(self.duration, self.position + 5.0))

    def action_play_pause(self) -> None:
        if self.on_play_pause:
            self.on_play_pause()


# ── InlineMediaWidget ──────────────────────────────────────────────────────────

class InlineMediaWidget(Widget):
    """Inline audio/video player. Mounts in output pane when media URL detected."""

    class PlaybackEnded(Message):
        pass

    can_focus = True

    BINDINGS = [
        Binding("enter", "play_pause", "Play/Pause", show=False),
    ]

    DEFAULT_CSS = """
    InlineMediaWidget {
        height: auto;
        margin: 0 0 1 2;
        padding: 0;
    }
    """

    state:    reactive[str]   = reactive("idle")
    title:    reactive[str]   = reactive("")
    position: reactive[float] = reactive(0.0)
    duration: reactive[float] = reactive(0.0)

    def __init__(self, url: str, kind: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._url  = url
        self._kind = kind   # "audio" | "video" | "youtube"
        from hermes_cli.tui.media_player import _inline_media_config
        self._cfg  = _inline_media_config()
        self._ctrl:   "Any | None" = None
        self._poller: "Any | None" = None
        self._show_timeline = self._cfg.show_timeline

    def compose(self) -> ComposeResult:
        yield Static("", id="media-controls")
        yield SeekBar(id="media-seekbar")

    def on_mount(self) -> None:
        from hermes_cli.tui.media_player import _short_url
        self.state = "loading"
        sb = self.query_one("#media-seekbar", SeekBar)
        self._seekbar = sb
        sb.display = False
        if self._show_timeline and self._cfg.timeline_auto_s == 0:
            sb.display = True
        sb.on_seek       = lambda pos: self._ctrl.seek(pos) if self._ctrl else None
        sb.on_play_pause = self.action_play_pause
        ctrl_label = self.query_one("#media-controls", Static)
        ctrl_label.update(f"◉ {_short_url(self._url)}  [loading…]")
        self._prepare()

    def on_resize(self, event: Any) -> None:
        if hasattr(self, "_seekbar"):
            self._seekbar.refresh()

    @work(thread=True)
    def _prepare(self) -> None:
        from hermes_cli.tui.media_player import (
            MpvController,
            _resolve_youtube_url,
            _fetch_youtube_thumbnail,
            _extract_video_thumbnail,
        )
        cfg = self._cfg
        resolved_url: str | None = None
        if self._kind == "youtube":
            resolved_url = _resolve_youtube_url(self._url)
        ctrl = MpvController(
            url=self._url, kind=self._kind, cfg=cfg, resolved_url=resolved_url
        )
        thumb_path: str | None = None
        if self._kind == "youtube" and cfg.video_thumbs:
            thumb_path = _fetch_youtube_thumbnail(self._url)
        elif self._kind == "video" and cfg.video_thumbs:
            thumb_path = _extract_video_thumbnail(self._url)
        self.app.call_from_thread(self._on_ready, ctrl, thumb_path)

    def _on_ready(self, ctrl: Any, thumb_path: "str | None") -> None:
        if not self.is_mounted:
            return
        from hermes_cli.tui.media_player import _short_url
        self._ctrl = ctrl
        if thumb_path:
            try:
                self.mount(InlineThumbnail(thumb_path), before="#media-controls")
            except Exception:
                pass
        self.state = "idle"
        try:
            ctrl_label = self.query_one("#media-controls", Static)
            ctrl_label.update(f"◉ {_short_url(self._url)}")
        except Exception:
            pass

    def action_play_pause(self) -> None:
        if self.state == "idle":
            self._start_playback()
        elif self.state == "playing":
            if self._ctrl:
                self._ctrl.pause()
            self.state = "paused"
            sb = self.query_one("#media-seekbar", SeekBar)
            sb.playing = False
        elif self.state == "paused":
            if self._ctrl:
                self._ctrl.resume()
            self.state = "playing"
            sb = self.query_one("#media-seekbar", SeekBar)
            sb.playing = True

    def _start_playback(self) -> None:
        if self._ctrl is None:
            return
        app = self.app
        if getattr(app, "_active_media_count", 0) >= self._cfg.max_concurrent:
            self._set_error("max players active")
            return
        self._ctrl.start()
        from hermes_cli.tui.media_player import MpvPoller
        self._poller = MpvPoller(
            self._ctrl,
            on_tick=lambda pos, dur: app.call_from_thread(self._on_tick, pos, dur),
            on_end=lambda: app.call_from_thread(self._on_end),
        )
        self._poller.start()
        app._active_media_count = getattr(app, "_active_media_count", 0) + 1
        self.state = "playing"

    def _on_tick(self, pos: float, dur: float) -> None:
        self.position = pos
        self.duration = dur
        try:
            sb = self.query_one("#media-seekbar", SeekBar)
            sb.position = pos
            sb.duration = dur
            sb.playing = (self.state == "playing")
            if self._show_timeline and not sb.display:
                if self._cfg.timeline_auto_s == 0 or dur > self._cfg.timeline_auto_s:
                    sb.display = True
        except Exception:
            pass

    def _on_end(self) -> None:
        self.state = "stopped"
        app = self.app
        app._active_media_count = max(0, getattr(app, "_active_media_count", 0) - 1)
        self.post_message(self.PlaybackEnded())

    def _set_error(self, msg: str) -> None:
        self.state = "error"
        self.title = msg

    def on_unmount(self) -> None:
        if self._poller:
            self._poller.stop()
        if self._ctrl:
            self._ctrl.stop()
