"""_SpinnerMixin — spinner rendering, hint bar, FPS HUD, and phase methods for HermesApp."""
from __future__ import annotations

import math
import time as _time
from typing import Any

from textual.css.query import NoMatches
from textual.content import Content
from textual.widgets import Static
from wcwidth import wcswidth

from hermes_cli.tui._app_utils import (
    _HELIX_DELAY_S,
    _HELIX_FRAME_COUNT,
    _HELIX_MIN_CELLS,
    _log_lag,
)
from hermes_cli.tui.animation import shimmer_text

try:
    import drawille as _drawille
except ImportError:
    _drawille = None  # type: ignore[assignment]


class _SpinnerMixin:
    """Spinner frame rendering, hint text, FPS HUD, and hint-phase CSS methods.

    Extracted from HermesApp to reduce file size.  Self is always a HermesApp
    instance at runtime — all attribute access on self is valid.
    """

    # --- Spinner + hint bar ---

    def _tick_spinner(self) -> None:
        """set_interval callback — runs ON the event loop (def, not async def).

        Reads overlay deadlines and agent state to assemble hint text.
        Updates the input widget's spinner_text so the spinner renders
        inside the input field when the agent is running.
        """
        _t0 = _time.perf_counter()
        if not (self.agent_running or self.command_running):  # type: ignore[attr-defined]
            return
        self._shimmer_tick += 1  # type: ignore[attr-defined]

        hint_suffix = self._build_hint_text()

        # Append per-tool elapsed time when a tool call is in progress
        elapsed = 0.0
        if self._tool_start_time > 0:  # type: ignore[attr-defined]
            elapsed = max(0.0, _time.monotonic() - self._tool_start_time)  # type: ignore[attr-defined]
            hint_suffix = f"{hint_suffix} · {elapsed:.1f}s" if hint_suffix else f"{elapsed:.1f}s"

        # Deliver spinner text to input bar (placeholder + spinner_text).
        # HintBar shows phase-based hints (e.g. "^C interrupt · Esc dismiss")
        # — spinner/elapsed are already visible in the input bar, no duplication.
        try:
            inp = self._cached_input_area  # type: ignore[attr-defined]
            if inp is None or not inp.is_mounted:
                inp = self.query_one("#input-area")  # type: ignore[attr-defined]
                self._cached_input_area = inp  # type: ignore[attr-defined]
            overlay = self._cached_spinner_overlay  # type: ignore[attr-defined]
            if overlay is None or not overlay.is_mounted:
                overlay = self.query_one("#spinner-overlay", Static)  # type: ignore[attr-defined]
                self._cached_spinner_overlay = overlay  # type: ignore[attr-defined]
            overlay.display = False  # always hidden; placeholder replaces overlay
            frame = self._next_spinner_frame(
                text_after_frame=hint_suffix,
                elapsed=elapsed,
                input_width=self._input_bar_width(inp),
            )
            spinner_display = f"{frame} {hint_suffix}" if frame and hint_suffix else (frame or hint_suffix)
            # Leading space so cursor doesn't obscure first char when input is focused
            padded = f" {spinner_display}" if spinner_display else ""
            if hasattr(inp, "placeholder"):
                if padded and getattr(self, "_animations_enabled", True):
                    try:
                        # F1: read shimmer colors from skin/theme vars so light-bg
                        # skins remain readable (falls back to original defaults)
                        _cvars = (
                            self._theme_manager.css_variables  # type: ignore[attr-defined]
                            if self._theme_manager else {}  # type: ignore[attr-defined]
                        )
                        _shimmer_dim = _cvars.get("spinner-shimmer-dim", "#555555")
                        _shimmer_peak = _cvars.get("spinner-shimmer-peak", "#d8d8d8")
                        shimmer = shimmer_text(
                            padded,
                            tick=self._shimmer_tick,  # type: ignore[attr-defined]
                            dim=_shimmer_dim,
                            peak=_shimmer_peak,
                            period=60,
                        )
                        inp.placeholder = Content.from_rich_text(shimmer)
                    except Exception:
                        inp.placeholder = padded
                else:
                    inp.placeholder = padded
        except NoMatches:
            pass

        self._refresh_live_response_metrics()  # type: ignore[attr-defined]
        _dt = (_time.perf_counter() - _t0) * 1000
        if _dt > 16:
            _log_lag(f"_tick_spinner took {_dt:.1f}ms")
        if self._spinner_perf_alarm is not None:  # type: ignore[attr-defined]
            self._spinner_perf_alarm.observe(  # type: ignore[attr-defined]
                _dt,
                detail=f"agent_running={self.agent_running} command_running={self.command_running}",  # type: ignore[attr-defined]
            )

    @staticmethod
    def _cell_width(text: str) -> int:
        """Return visible cell width for terminal layout math."""
        width = wcswidth(text)
        return max(0, width)

    def _input_bar_width(self, inp: Any) -> int:
        """Best-effort live width of the input widget in terminal cells."""
        region_width = getattr(getattr(inp, "content_size", None), "width", 0) or 0
        widget_width = getattr(getattr(inp, "size", None), "width", 0) or 0
        app_width = max(0, getattr(getattr(self, "size", None), "width", 0) - 4)
        return max(region_width, widget_width, app_width)

    def _next_spinner_frame(self, text_after_frame: str, elapsed: float, input_width: int) -> str:
        """Return the next spinner frame. Drawille helix moved to ThinkingWidget."""
        frames = self._spinner_frames  # type: ignore[attr-defined]
        if frames:
            self._spinner_idx = (self._spinner_idx + 1) % len(frames)  # type: ignore[attr-defined]
            return frames[self._spinner_idx]  # type: ignore[attr-defined]
        return ""

    def _helix_width(self, text_after_frame: str, input_width: int) -> int:
        """Compute how many cells remain for the animated helix."""
        suffix_width = self._cell_width(text_after_frame)
        spacer = 1 if text_after_frame else 0
        # Reserve the leading padding cell added before placeholder text.
        available = max(0, input_width - suffix_width - spacer - 1)
        return available

    def _helix_spinner_frame(self, elapsed: float, text_after_frame: str, input_width: int) -> str | None:
        """Return a cached drawille helix frame when the timer has run long enough."""
        if _drawille is None or elapsed < _HELIX_DELAY_S:
            return None
        width_cells = self._helix_width(text_after_frame, input_width)
        if width_cells < _HELIX_MIN_CELLS:
            return None
        frames = self._helix_frame_cache.get(width_cells)  # type: ignore[attr-defined]
        if frames is None:
            frames = self._build_helix_frames(width_cells)
            self._helix_frame_cache[width_cells] = frames  # type: ignore[attr-defined]
        if not frames:
            return None
        return frames[self._spinner_idx % len(frames)]  # type: ignore[attr-defined]

    def _build_helix_frames(self, width_cells: int) -> tuple[str, ...]:
        """Precompute one-line drawille frames for a 3-strand helix."""
        if _drawille is None or width_cells < _HELIX_MIN_CELLS:
            return ()

        width_points = max(2, width_cells * 2)
        amplitude = 1.35
        midpoint = 1.5
        frames: list[str] = []

        for frame_idx in range(_HELIX_FRAME_COUNT):
            canvas = _drawille.Canvas()
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

    def _build_hint_text(self) -> str:
        """Build the hint suffix shown beside the spinner.

        Reads overlay deadlines and agent state to assemble context hints
        (e.g. " — waiting for approval (12s)"). Extracts the logic from
        the get_hint_text() closure (cli.py:8258).
        """
        parts: list[str] = []
        label_text = getattr(self, "spinner_label", "")
        if label_text:
            # Strip verbose prefixes — the tool name is the signal, not the verb
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
            state = getattr(self, state_attr)
            if state is not None:
                parts.append(f" — waiting for {label} ({state.remaining}s)")
        return " ".join(parts) if parts else ""

    # --- Session / response timers ---

    def _tick_duration(self) -> None:
        """Run 1-Hz diagnostics and refresh live response metrics."""
        import time as _t
        _t0 = _t.perf_counter()
        # --- Diagnostic probes (run unconditionally at 1 Hz) ---
        if self._event_loop_probe is not None:  # type: ignore[attr-defined]
            self._event_loop_probe.tick()  # type: ignore[attr-defined]
        if self._worker_watcher is not None:  # type: ignore[attr-defined]
            self._worker_watcher.tick()  # type: ignore[attr-defined]
        self._refresh_live_response_metrics()  # type: ignore[attr-defined]
        _dt = (_t.perf_counter() - _t0) * 1000
        if _dt > 16:
            _log_lag(f"_tick_duration took {_dt:.1f}ms")
        if self._duration_perf_alarm is not None:  # type: ignore[attr-defined]
            self._duration_perf_alarm.observe(  # type: ignore[attr-defined]
                _dt,
                detail=f"agent_running={self.agent_running} workers={len(self.workers)}",  # type: ignore[attr-defined]
            )

    # --- FPS HUD ticker ---

    def _tick_fps(self) -> None:
        """Frame-rate probe ticker — runs at 1/MAX_FPS (matches Screen._update_timer).

        Probes at the render cadence so the HUD reflects actual event-loop frame
        delivery rate rather than an arbitrary coarse interval.  DOM is only
        touched every ~4 Hz (fps_hud_update_every ticks) to keep the HUD readable
        and avoid adding repaint pressure from the HUD itself.
        """
        from hermes_cli.tui.widgets import FPSCounter
        if self._frame_probe is None:  # type: ignore[attr-defined]
            return
        fps, avg_ms = self._frame_probe.tick()  # type: ignore[attr-defined]
        if self.fps_hud_visible:  # type: ignore[attr-defined]
            every = getattr(self, "_fps_hud_update_every", 1)
            if self._frame_probe._ticks % every == 0:  # type: ignore[attr-defined]
                try:
                    counter = self.query_one(FPSCounter)  # type: ignore[attr-defined]
                    counter.fps = fps
                    counter.avg_ms = avg_ms
                except NoMatches:
                    pass

    def watch_fps_hud_visible(self, value: bool) -> None:
        """Show or hide the FPS HUD overlay."""
        from hermes_cli.tui.widgets import FPSCounter
        try:
            counter = self.query_one(FPSCounter)  # type: ignore[attr-defined]
            if value:
                counter.add_class("--visible")
            else:
                counter.remove_class("--visible")
        except NoMatches:
            pass

    def action_toggle_fps_hud(self) -> None:
        """Toggle the FPS / avg-ms HUD (Ctrl+\\)."""
        self.fps_hud_visible = not self.fps_hud_visible  # type: ignore[attr-defined]

    # --- Reactive watchers ---

    def _compute_hint_phase(self) -> str:
        """Compute hint phase from current app state, in priority order."""
        if getattr(self, "voice_mode", False):
            return "voice"
        # Any overlay open?
        if any(
            getattr(self, attr) is not None
            for attr in ("approval_state", "clarify_state", "sudo_state", "secret_state")
        ):
            return "overlay"
        if getattr(self, "browse_mode", False):
            return "browse"
        if getattr(self, "agent_running", False) or getattr(self, "command_running", False):
            return "stream"
        if bool(getattr(self, "status_error", "")):
            return "error"
        # Typing phase: check if input has content
        try:
            inp = self.query_one("#input-area")  # type: ignore[attr-defined]
            if hasattr(inp, "value") and inp.value:
                return "typing"
        except NoMatches:
            pass
        return "idle"

    def _set_hint_phase(self, phase: str) -> None:
        """Apply hint phase to HintBar safely."""
        from hermes_cli.tui.widgets import HintBar
        self._hint_phase = phase  # type: ignore[attr-defined]
        try:
            self.query_one(HintBar).set_phase(phase)  # type: ignore[attr-defined]
        except NoMatches:
            pass

    def _set_chevron_phase(self, phase: str) -> None:
        """Set exactly one phase class on #input-chevron, clearing all others."""
        try:
            chevron = self.query_one("#input-chevron", Static)  # type: ignore[attr-defined]
            for cls in self._CHEVRON_PHASE_CLASSES:  # type: ignore[attr-defined]
                chevron.remove_class(cls)
            if phase:
                chevron.add_class(phase)
        except NoMatches:
            pass

    def _drawille_show_hide(self, running: bool) -> None:
        """Show or hide the drawille overlay based on agent state + _anim_force."""
        try:
            from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO, _overlay_config
            from hermes_cli.tui.widgets import OutputPanel
            overlay = self.query_one(_DO)  # type: ignore[attr-defined]
            cfg = _overlay_config()
            # _anim_force overrides normal trigger logic
            if self._anim_force == "on":  # type: ignore[attr-defined]
                cfg.enabled = True
                overlay.show(cfg)
                return
            if self._anim_force == "off":  # type: ignore[attr-defined]
                overlay.hide(cfg)
                return
            if running and cfg.trigger in ("agent_running", "always"):
                overlay.show(cfg)
                if cfg.dim_background:
                    try:
                        self.query_one(OutputPanel).add_class("-dim-bg")  # type: ignore[attr-defined]
                    except NoMatches:
                        pass
            else:
                overlay.hide(cfg)
                try:
                    self.query_one(OutputPanel).remove_class("-dim-bg")  # type: ignore[attr-defined]
                except NoMatches:
                    pass
        except NoMatches:
            pass
        except Exception:
            pass
