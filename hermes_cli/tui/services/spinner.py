"""Spinner tick, hint phase, FPS HUD service extracted from _app_spinner.py."""
from __future__ import annotations

import logging
import math
import time as _time
from typing import TYPE_CHECKING, Any

from textual.css.query import NoMatches
from textual.content import Content
from textual.widgets import Static
from wcwidth import wcswidth

_log = logging.getLogger(__name__)

from hermes_cli.tui._app_utils import (
    _HELIX_DELAY_S,
    _HELIX_FRAME_COUNT,
    _HELIX_MIN_CELLS,
    _log_lag,
)
from hermes_cli.tui.animation import shimmer_text
from .base import AppService

from hermes_cli.tui.braille_canvas import BrailleCanvas

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp


class SpinnerService(AppService):
    """Spinner tick, hint phase, FPS HUD."""

    def __init__(self, app: "HermesApp") -> None:
        super().__init__(app)
        # Service-owned cache — keyed by width_cells
        self._helix_frame_cache: dict[int, tuple[str, ...]] = {}

    # --- Spinner + hint bar ---

    def tick_spinner(self) -> None:
        """set_interval callback — runs ON the event loop (def, not async def)."""
        app = self.app
        _t0 = _time.perf_counter()
        if not (app.agent_running or app.command_running):
            return
        app._shimmer_tick += 1

        hint_suffix = self.build_hint_text()

        elapsed = 0.0
        if app._tool_start_time > 0:
            elapsed = max(0.0, _time.monotonic() - app._tool_start_time)
            hint_suffix = f"{hint_suffix} · {elapsed:.1f}s" if hint_suffix else f"{elapsed:.1f}s"

        try:
            inp = app._cached_input_area
            if inp is None or not inp.is_mounted:
                inp = app.query_one("#input-area")
                app._cached_input_area = inp
            overlay = app._cached_spinner_overlay
            if overlay is None or not overlay.is_mounted:
                overlay = app.query_one("#spinner-overlay", Static)
                app._cached_spinner_overlay = overlay
            overlay.display = False
            frame = self.next_spinner_frame(
                text_after_frame=hint_suffix,
                elapsed=elapsed,
                input_width=self.input_bar_width(inp),
            )
            spinner_display = f"{frame} {hint_suffix}" if frame and hint_suffix else (frame or hint_suffix)
            padded = f" {spinner_display}" if spinner_display else ""
            if hasattr(inp, "placeholder"):
                if padded and getattr(app, "_animations_enabled", True):
                    try:
                        _cvars = (
                            app._theme_manager.css_variables
                            if app._theme_manager else {}
                        )
                        _shimmer_dim = _cvars.get("spinner-shimmer-dim", "#555555")
                        _shimmer_peak = _cvars.get("spinner-shimmer-peak", "#d8d8d8")
                        shimmer = shimmer_text(
                            padded,
                            tick=app._shimmer_tick,
                            dim=_shimmer_dim,
                            peak=_shimmer_peak,
                            period=60,
                        )
                        inp.placeholder = Content.from_rich_text(shimmer)
                    except Exception:
                        _log.debug("tick_spinner: shimmer_text failed", exc_info=True)
                        inp.placeholder = padded
                else:
                    inp.placeholder = padded
        except NoMatches:
            pass

        app._refresh_live_response_metrics()
        _dt = (_time.perf_counter() - _t0) * 1000
        if _dt > 16:
            _log_lag(f"_tick_spinner took {_dt:.1f}ms")
        if app._spinner_perf_alarm is not None:
            app._spinner_perf_alarm.observe(
                _dt,
                detail=f"agent_running={app.agent_running} command_running={app.command_running}",
            )

    @staticmethod
    def cell_width(text: str) -> int:
        """Return visible cell width for terminal layout math."""
        width = wcswidth(text)
        return max(0, width)

    def input_bar_width(self, inp: Any) -> int:
        """Best-effort live width of the input widget in terminal cells."""
        app = self.app
        region_width = getattr(getattr(inp, "content_size", None), "width", 0) or 0
        widget_width = getattr(getattr(inp, "size", None), "width", 0) or 0
        app_width = max(0, getattr(getattr(app, "size", None), "width", 0) - 4)
        return max(region_width, widget_width, app_width)

    def next_spinner_frame(self, text_after_frame: str, elapsed: float, input_width: int) -> str:
        """Return the next spinner frame."""
        app = self.app
        frames = app._spinner_frames
        if frames:
            app._spinner_idx = (app._spinner_idx + 1) % len(frames)
            return frames[app._spinner_idx]
        return ""

    def helix_width(self, text_after_frame: str, input_width: int) -> int:
        """Compute how many cells remain for the animated helix."""
        suffix_width = self.cell_width(text_after_frame)
        spacer = 1 if text_after_frame else 0
        available = max(0, input_width - suffix_width - spacer - 1)
        return available

    def helix_spinner_frame(self, elapsed: float, text_after_frame: str, input_width: int) -> str | None:
        """Return a cached helix frame when the timer has run long enough."""
        app = self.app
        if elapsed < _HELIX_DELAY_S:
            return None
        width_cells = self.helix_width(text_after_frame, input_width)
        if width_cells < _HELIX_MIN_CELLS:
            return None
        frames = self._helix_frame_cache.get(width_cells)
        if frames is None:
            frames = self.build_helix_frames(width_cells)
            self._helix_frame_cache[width_cells] = frames
        if not frames:
            return None
        return frames[app._spinner_idx % len(frames)]

    def build_helix_frames(self, width_cells: int) -> tuple[str, ...]:
        """Precompute one-line braille frames for a 3-strand helix."""
        if width_cells < _HELIX_MIN_CELLS:
            return ()

        width_points = max(2, width_cells * 2)
        amplitude = 1.35
        midpoint = 1.5
        frames: list[str] = []

        for frame_idx in range(_HELIX_FRAME_COUNT):
            canvas = BrailleCanvas()
            phase = (frame_idx / _HELIX_FRAME_COUNT) * (2 * math.pi)
            for strand_idx in range(3):
                strand_phase = phase + (strand_idx * 2 * math.pi / 3)
                for x in range(width_points):
                    theta = strand_phase + (x * 0.42)
                    y = midpoint + (math.sin(theta) * amplitude)
                    canvas.set(x, int(round(max(0.0, min(3.0, y)))))
            rendered = canvas.frame()
            frame = rendered.splitlines()[0] if rendered else ""
            frames.append(frame.ljust(width_cells)[:width_cells])

        return tuple(frames)

    def build_hint_text(self) -> str:
        """Build the hint suffix shown beside the spinner."""
        app = self.app
        parts: list[str] = []
        label_text = getattr(app, "spinner_label", "")
        if label_text:
            for prefix in ("Calling tool: ", "Running tool: ", "Tool: "):
                if label_text.startswith(prefix):
                    label_text = label_text[len(prefix):]
                    break
            parts.append(label_text)
        for label, state_attr in [
            ("approval", "approval_state"),
            ("clarify", "clarify_state"),
            ("sudo", "sudo_state"),
            ("secret", "secret_state"),
        ]:
            state = getattr(app, state_attr)
            if state is not None:
                parts.append(f" — waiting for {label} ({state.remaining}s)")
        return " ".join(parts) if parts else ""

    # --- Session / response timers ---

    def tick_duration(self) -> None:
        """Run 1-Hz diagnostics and refresh live response metrics."""
        import time as _t
        app = self.app
        _t0 = _t.perf_counter()
        if app._event_loop_probe is not None:
            app._event_loop_probe.tick()
        if app._worker_watcher is not None:
            app._worker_watcher.tick()
        from hermes_cli.tui.perf import _queue_probe
        _queue_probe.tick(app._output_queue)
        app._refresh_live_response_metrics()
        _dt = (_t.perf_counter() - _t0) * 1000
        if _dt > 16:
            _log_lag(f"_tick_duration took {_dt:.1f}ms")
        if app._duration_perf_alarm is not None:
            app._duration_perf_alarm.observe(
                _dt,
                detail=f"agent_running={app.agent_running} workers={len(app.workers)}",
            )

    # --- FPS HUD ticker ---

    def tick_fps(self) -> None:
        """Frame-rate probe ticker."""
        from hermes_cli.tui.widgets import FPSCounter
        app = self.app
        if app._frame_probe is None:
            return
        fps, avg_ms = app._frame_probe.tick()
        if app.fps_hud_visible:
            every = getattr(app, "_fps_hud_update_every", 1)
            if app._frame_probe._ticks % every == 0:
                try:
                    counter = app.query_one(FPSCounter)
                    counter.fps = fps
                    counter.avg_ms = avg_ms
                except NoMatches:
                    pass

    def on_fps_hud_visible(self, value: bool) -> None:
        """Show or hide the FPS HUD overlay."""
        from hermes_cli.tui.widgets import FPSCounter
        try:
            counter = self.app.query_one(FPSCounter)
            if value:
                counter.add_class("--visible")
            else:
                counter.remove_class("--visible")
        except NoMatches:
            pass

    # --- Reactive watchers ---

    def compute_hint_phase(self) -> str:
        """Compute hint phase from current app state, in priority order."""
        app = self.app
        if getattr(app, "voice_mode", False):
            return "voice"
        if any(
            getattr(app, attr) is not None
            for attr in ("approval_state", "clarify_state", "sudo_state", "secret_state")
        ):
            return "overlay"
        if getattr(app, "browse_mode", False):
            return "browse"
        if getattr(app, "agent_running", False) or getattr(app, "command_running", False):
            return "stream"
        if bool(getattr(app, "status_error", "")):
            return "error"
        try:
            inp = app.query_one("#input-area")
            if hasattr(inp, "value") and inp.value:
                return "typing"
        except NoMatches:
            pass
        return "idle"

    def set_hint_phase(self, phase: str) -> None:
        """Apply hint phase to HintBar safely."""
        from hermes_cli.tui.widgets import HintBar
        app = self.app
        app._hint_phase = phase
        try:
            app.query_one(HintBar).set_phase(phase)
        except NoMatches:
            pass

    def set_chevron_phase(self, phase: str) -> None:
        """Set exactly one phase class on #input-chevron, clearing all others."""
        app = self.app
        try:
            chevron = app.query_one("#input-chevron", Static)
            for cls in app._CHEVRON_PHASE_CLASSES:
                chevron.remove_class(cls)
            if phase:
                chevron.add_class(phase)
        except NoMatches:
            pass

    def drawbraille_show_hide(self, running: bool) -> None:
        """Show or hide the drawbraille overlay based on agent state + _anim_force."""
        app = self.app
        try:
            from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay as _DO, _overlay_config
            from hermes_cli.tui.widgets import OutputPanel
            overlay = app.query_one(_DO)
            cfg = _overlay_config()
            if app._anim_force == "on":
                cfg.enabled = True
                overlay.show(cfg)
                return
            if app._anim_force == "off":
                overlay.hide(cfg)
                return
            if running and cfg.trigger in ("agent_running", "always"):
                overlay.show(cfg)
                if cfg.dim_background:
                    try:
                        app.query_one(OutputPanel).add_class("-dim-bg")
                    except NoMatches:
                        pass
            else:
                overlay.hide(cfg)
                try:
                    app.query_one(OutputPanel).remove_class("-dim-bg")
                except NoMatches:
                    pass
        except NoMatches:
            pass
        except Exception:
            _log.debug("drawbraille_show_hide: overlay update failed", exc_info=True)
