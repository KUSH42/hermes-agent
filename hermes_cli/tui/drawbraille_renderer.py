"""DrawbrailleRenderer — frame string → Rich Text with color, gradient, fade.

No Textual dependency. Owned by DrawbrailleOverlay at self._renderer.
Stateless w.r.t. heat/carousel — receives resolved colors + fade params.
"""
from __future__ import annotations

import math
import logging
from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text

from hermes_cli.tui._color_utils import _resolve_color, _hex_to_rgb
from hermes_cli.tui.animation import lerp_color, lerp_color_rgb, _parse_rgb

if TYPE_CHECKING:
    from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlayCfg

_LOG = logging.getLogger(__name__)


class DrawbrailleRenderer:
    """Braille frame → Rich Text with color, gradient, fade.

    Owned by DrawbrailleOverlay at self._renderer.
    Stateless w.r.t. heat/carousel — receives resolved colors + fade params.
    """

    def __init__(self) -> None:
        self._resolved_color: str = "#00d7ff"
        self._resolved_color_b: str = "#8800ff"
        self._resolved_multi_colors: list[str] = []
        self._resolved_multi_color_rgbs: list | None = None
        self._multi_color_row_buf: list[str] = []
        self._fade_step: int = 0
        self._fade_state: str = "stable"   # "in" | "out" | "stable"
        self._fade_alpha: float = 1.0

    # ── color resolution ───────────────────────────────────────────────────

    def resolve_colors(
        self,
        color: str,
        color_b: str,
        multi_color: list[str],
        app: object,
    ) -> None:
        """Refresh _resolved_color* from reactive values + CSS vars.

        Called from DrawbrailleOverlay.on_mount() and all watch_color*() watchers.
        """
        try:
            self._resolved_color = _resolve_color(color, app)
            self._resolved_color_b = _resolve_color(color_b, app)
            self._resolved_multi_colors = [
                _resolve_color(c, app) for c in multi_color
            ]
            self._resolved_multi_color_rgbs = [
                _parse_rgb(c) for c in self._resolved_multi_colors
            ]
        except Exception:
            _LOG.debug("DrawbrailleRenderer.resolve_colors failed", exc_info=True)

    # ── fade control ───────────────────────────────────────────────────────

    def start_fade_out(self, cfg: "DrawbrailleOverlayCfg") -> None:
        """Begin fade-out. Sets _fade_state='out', _fade_step=cfg.fade_out_frames."""
        self._fade_state = "out"
        self._fade_step = cfg.fade_out_frames

    def start_fade_in(self, cfg: "DrawbrailleOverlayCfg") -> None:
        """Begin fade-in. Always resets _fade_alpha=1.0 to avoid flicker."""
        self._fade_state = "in"
        self._fade_step = cfg.fade_in_frames
        self._fade_alpha = 1.0

    def cancel_fade_out(self) -> None:
        """Abort fade-out and reset to stable. Sets _fade_state='stable' and _fade_alpha=1.0."""
        self._fade_state = "stable"
        self._fade_alpha = 1.0

    # ── frame rendering ────────────────────────────────────────────────────

    def render_frame(
        self,
        frame_str: str,
        t: float,
        cfg: "DrawbrailleOverlayCfg | None",
        visibility_state: str,
        gradient: bool,
        hue_shift_speed: float,
    ) -> "Text | None":
        """Convert frame_str to Rich Text, applying fade and gradient.

        Returns None when fade-out reaches zero (signal to caller to call _do_hide).
        The caller must call cancel_fade_out() before this method if _waiting=True
        to prevent the None-return hide signal.
        """
        render_color = self._resolved_color

        if self._fade_state == "out" and cfg is not None:
            self._fade_step -= 1
            if self._fade_step <= 0:
                # Signal to caller: time to _do_hide()
                return None
            self._fade_alpha = self._fade_step / max(cfg.fade_out_frames, 1)
            # Apply dim to the pre-resolved color via _hex_to_rgb scalar multiply
            r, g, b = _hex_to_rgb(self._resolved_color)
            a = self._fade_alpha
            render_color = "#{:02x}{:02x}{:02x}".format(
                int(r * a), int(g * a), int(b * a)
            )
        elif self._fade_state == "in" and self._fade_step > 0:
            fade_in_frames = cfg.fade_in_frames if cfg is not None else 3
            alpha = 1.0 - self._fade_step / max(fade_in_frames, 1)
            render_color = lerp_color("#000000", self._resolved_color, alpha)
            self._fade_step -= 1
            if self._fade_step <= 0:
                self._fade_state = "stable"
        elif visibility_state == "ambient" and cfg is not None:
            # Phase D: ambient color-channel dimming (dim pre-resolved color)
            r, g, b = _hex_to_rgb(self._resolved_color)
            a = cfg.ambient_alpha
            render_color = "#{:02x}{:02x}{:02x}".format(
                int(r * a), int(g * a), int(b * a)
            )
            self._fade_state = "stable"
        else:
            self._fade_state = "stable"
            render_color = self._resolved_color

        if self._resolved_multi_colors:
            return self._render_multi_color(frame_str, t, hue_shift_speed)
        elif gradient:
            rows = frame_str.split("\n")
            n = max(len(rows), 1)
            pieces: list[tuple[str, Style]] = []
            for i, row in enumerate(rows):
                hex_c = lerp_color(self._resolved_color, self._resolved_color_b, i / n)
                pieces.append((row + "\n", Style(color=hex_c)))
            return Text.assemble(*pieces)
        else:
            style = Style(color=render_color)
            return Text(frame_str, style=style)

    def _render_multi_color(self, frame_str: str, t: float, hue_shift_speed: float) -> Text:
        """Per-character N-stop gradient with time-based hue-shift drift.

        Each character's column position maps to a position on the gradient.
        A sinusoidal drift (hue_shift_speed) oscillates the gradient left/right
        over time, creating the shifting-hue effect.
        """
        colors = self._resolved_multi_colors
        n_stops = len(colors)
        drift = math.sin(t * hue_shift_speed) * 0.25

        # Use pre-parsed RGB tuples (cached at resolve time, not per-frame).
        stop_rgbs = self._resolved_multi_color_rgbs
        if stop_rgbs is None:
            stop_rgbs = [_parse_rgb(c) for c in colors]

        rows = frame_str.split("\n")
        pieces: list[tuple[str, Style]] = []
        for row in rows:
            row_len = len(row)
            if row_len == 0:
                pieces.append(("\n", Style()))
                continue

            # Pre-compute color per position
            row_inv = 1.0 / max(row_len - 1, 1)
            if len(self._multi_color_row_buf) != row_len:
                self._multi_color_row_buf = [""] * row_len
            row_colors = self._multi_color_row_buf
            for char_idx in range(row_len):
                pos = char_idx * row_inv + drift
                pos = abs(pos % 2.0)
                if pos > 1.0:
                    pos = 2.0 - pos

                if n_stops == 1:
                    hex_c = colors[0]
                else:
                    segment = pos * (n_stops - 1)
                    seg_idx = min(int(segment), n_stops - 2)
                    seg_t = segment - seg_idx
                    hex_c = lerp_color_rgb(stop_rgbs[seg_idx], stop_rgbs[seg_idx + 1], seg_t)
                row_colors[char_idx] = hex_c

            # Batch consecutive same-color runs
            run_start = 0
            run_color = row_colors[0]
            for i in range(1, row_len + 1):
                c = row_colors[i] if i < row_len else None
                if c != run_color:
                    span = row[run_start:i]
                    pieces.append((span, Style(color=run_color)))
                    run_start = i
                    run_color = c

            pieces.append(("\n", Style()))
        return Text.assemble(*pieces)
