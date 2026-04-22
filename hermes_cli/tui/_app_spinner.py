"""_SpinnerMixin — adapter shell; logic lives in services/spinner.py."""
from __future__ import annotations


class _SpinnerMixin:
    """Adapter shell — all methods delegate to self._svc_spinner."""

    def _tick_spinner(self) -> None:  # DEPRECATED
        return self._svc_spinner.tick_spinner()  # type: ignore[attr-defined]

    @staticmethod
    def _cell_width(text: str) -> int:  # DEPRECATED
        from wcwidth import wcswidth
        return max(0, wcswidth(text))

    def _input_bar_width(self, inp) -> int:  # DEPRECATED
        return self._svc_spinner.input_bar_width(inp)  # type: ignore[attr-defined]

    def _next_spinner_frame(self, text_after_frame: str, elapsed: float, input_width: int) -> str:  # DEPRECATED
        return self._svc_spinner.next_spinner_frame(text_after_frame, elapsed, input_width)  # type: ignore[attr-defined]

    def _helix_width(self, text_after_frame: str, input_width: int) -> int:  # DEPRECATED
        return self._svc_spinner.helix_width(text_after_frame, input_width)  # type: ignore[attr-defined]

    def _helix_spinner_frame(self, elapsed: float, text_after_frame: str, input_width: int):  # DEPRECATED
        return self._svc_spinner.helix_spinner_frame(elapsed, text_after_frame, input_width)  # type: ignore[attr-defined]

    def _build_helix_frames(self, width_cells: int):  # DEPRECATED
        return self._svc_spinner.build_helix_frames(width_cells)  # type: ignore[attr-defined]

    def _build_hint_text(self) -> str:  # DEPRECATED
        return self._svc_spinner.build_hint_text()  # type: ignore[attr-defined]

    def _tick_duration(self) -> None:  # DEPRECATED
        return self._svc_spinner.tick_duration()  # type: ignore[attr-defined]

    def _tick_fps(self) -> None:  # DEPRECATED
        return self._svc_spinner.tick_fps()  # type: ignore[attr-defined]

    def watch_fps_hud_visible(self, value: bool) -> None:
        self._svc_spinner.on_fps_hud_visible(value)  # type: ignore[attr-defined]

    def action_toggle_fps_hud(self) -> None:
        self.fps_hud_visible = not self.fps_hud_visible  # type: ignore[attr-defined]

    def _compute_hint_phase(self) -> str:  # DEPRECATED
        return self._svc_spinner.compute_hint_phase()  # type: ignore[attr-defined]

    def _set_hint_phase(self, phase: str) -> None:  # DEPRECATED
        return self._svc_spinner.set_hint_phase(phase)  # type: ignore[attr-defined]

    def _set_chevron_phase(self, phase: str) -> None:  # DEPRECATED
        return self._svc_spinner.set_chevron_phase(phase)  # type: ignore[attr-defined]

    def _drawille_show_hide(self, running: bool) -> None:  # DEPRECATED
        return self._svc_spinner.drawille_show_hide(running)  # type: ignore[attr-defined]
