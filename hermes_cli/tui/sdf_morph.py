"""SDF Morph Engine — braille-canvas letter morphing via Signed Distance Fields.

Renders letter forms that smoothly morph into each other using SDF interpolation.
Three render modes: filled, outline, dissolve. No scipy dependency required.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

import numpy as np
from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    pass

# ── Font loading ──────────────────────────────────────────────────────────────

_FONT_SEARCH_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "C:/Windows/Fonts/consola.ttf",
]

def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Load a monospace font, falling back to PIL default."""
    for path in _FONT_SEARCH_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()

# ── SDF computation ───────────────────────────────────────────────────────────

def _sdf_from_mask(mask: np.ndarray) -> np.ndarray:
    """Signed distance field from binary mask. scipy preferred, fallback numpy."""
    try:
        from scipy.ndimage import distance_transform_edt
        outside = distance_transform_edt(~mask).astype(np.float32)
        inside = distance_transform_edt(mask).astype(np.float32)
        return outside - inside
    except ImportError:
        return _dead_reckon_sdf(mask)

def _dead_reckon_sdf(mask: np.ndarray) -> np.ndarray:
    """Approximate signed distance transform via iterative numpy roll propagation."""
    h, w = mask.shape
    INF = float(h + w + 1)
    MAX_ITER = h + w

    def _dt(m: np.ndarray) -> np.ndarray:
        d = np.where(m, 0.0, INF).astype(np.float32)
        for _ in range(MAX_ITER):
            prev_sum = d.sum()
            d = np.minimum(d, np.roll(d,  1, axis=0) + 1)
            d = np.minimum(d, np.roll(d, -1, axis=0) + 1)
            d = np.minimum(d, np.roll(d,  1, axis=1) + 1)
            d = np.minimum(d, np.roll(d, -1, axis=1) + 1)
            if d.sum() == prev_sum:
                break
        return d

    return _dt(mask) - _dt(~mask)

# ── SDFBaker ──────────────────────────────────────────────────────────────────

class SDFBaker:
    """Bakes character glyphs to normalized SDF arrays. Thread-safe via Event."""

    def __init__(self, resolution: int = 128, font_size: int = 96,
                 timeout_s: float = 5.0) -> None:
        self._resolution = resolution
        self._font_size = font_size
        self._timeout_s = timeout_s
        self._cache: dict[str, np.ndarray] = {}
        self.ready = threading.Event()
        self.failed = threading.Event()
        self._start_time: float = 0.0

    def bake(self, chars: str) -> None:
        """Blocking. Call from worker thread only."""
        self._start_time = time.monotonic()
        try:
            for ch in set(chars):
                if ch not in self._cache:
                    # Check timeout between glyph renders
                    if time.monotonic() - self._start_time > self._timeout_s:
                        self.failed.set()
                        return
                    self._cache[ch] = self._bake_char(ch)
            self.ready.set()
        except Exception:
            logger.warning("_SDFBaker.bake: glyph baking failed; splash will fall back", exc_info=True)
            self.failed.set()

    def get(self, ch: str) -> np.ndarray:
        return self._cache[ch]

    def _bake_char(self, ch: str) -> np.ndarray:
        res = self._resolution
        img = Image.new("L", (res, res), 0)
        draw = ImageDraw.Draw(img)
        font = _load_font(self._font_size)

        bbox = draw.textbbox((0, 0), ch, font=font)
        glyph_w = bbox[2] - bbox[0]
        glyph_h = bbox[3] - bbox[1]
        x = (res - glyph_w) // 2 - bbox[0]
        y = (res - glyph_h) // 2 - bbox[1]
        draw.text((x, y), ch, fill=255, font=font)

        mask = np.array(img) > 127
        sdf = _sdf_from_mask(mask)

        CLAMP = 20.0
        sdf = np.clip(sdf, -CLAMP, CLAMP) / CLAMP
        return sdf.astype(np.float32)

# ── MorphState ────────────────────────────────────────────────────────────────

@dataclass
class MorphState:
    char_a: str
    char_b: str
    t: float = 0.0
    phase: str = "hold"
    phase_elapsed: float = 0.0
    seq_idx: int = 0

# ── Helper functions ──────────────────────────────────────────────────────────

def _resize_sdf(sdf: np.ndarray, target_w: int, target_h: int) -> np.ndarray:
    """Resize SDF grid without uint8 quantization. scipy preferred."""
    src_h, src_w = sdf.shape
    try:
        from scipy.ndimage import zoom
        zy = target_h / src_h
        zx = target_w / src_w
        return zoom(sdf, (zy, zx), order=1).astype(np.float32)
    except ImportError:
        # numpy fallback: nearest-neighbor
        yi = (np.arange(target_h) * src_h / target_h).astype(int)
        xi = (np.arange(target_w) * src_w / target_w).astype(int)
        return sdf[np.ix_(yi, xi)]

def _apply_render_mode(sdf: np.ndarray, mode: str, t: float,
                        outline_w: float, dissolve_spread: float) -> np.ndarray:
    """Convert SDF to boolean dot mask based on render mode."""
    if mode == "filled":
        return sdf < 0.0
    elif mode == "outline":
        return np.abs(sdf) < outline_w
    else:  # dissolve
        noise = _noise_grid(sdf.shape[1], sdf.shape[0], t)
        return sdf < (noise * dissolve_spread)

# Module-level noise cache
_noise_cache: dict[tuple, np.ndarray] = {}

def _noise_grid(w: int, h: int, t: float) -> np.ndarray:
    """Spatially coherent noise for dissolve effect. Cache-bounded at 200."""
    t_q = round(t * 50) / 50.0
    key = (w, h, t_q)
    if key in _noise_cache:
        return _noise_cache[key]

    xs = np.linspace(0, 1, w, dtype=np.float32)
    ys = np.linspace(0, 1, h, dtype=np.float32)
    xx, yy = np.meshgrid(xs, ys)

    n = np.sin(xx * 6.28 * 2 + t_q * 2.1) * np.cos(yy * 6.28 * 3 + t_q * 1.7)
    n += np.sin(xx * 6.28 * 5 + t_q * 3.3) * np.cos(yy * 6.28 * 4 + t_q * 2.9) * 0.5
    n += np.sin(xx * 6.28 * 9 + t_q * 5.1) * np.cos(yy * 6.28 * 7 + t_q * 4.3) * 0.25
    n /= 1.75

    _noise_cache[key] = n
    if len(_noise_cache) > 200:
        _noise_cache.pop(next(iter(_noise_cache)))
    return n

def _mask_to_canvas(mask: np.ndarray, dot_w: int, dot_h: int) -> str:
    """Convert boolean dot mask to braille frame string."""
    from hermes_cli.tui.braille_canvas import BrailleCanvas
    canvas = BrailleCanvas()
    ys, xs = np.where(mask[:dot_h, :dot_w])
    for x, y in zip(xs.tolist(), ys.tolist()):
        canvas.set(x, y)
    return canvas.frame()

def _resolve_color(color: str, color_b: str | None,
                    t: float, is_morphing: bool) -> str:
    """Optionally lerp between two hex colors during morph."""
    if color_b is None or not is_morphing:
        return color
    from hermes_cli.tui.animation import lerp_color
    return lerp_color(color, color_b, t)

def _apply_ansi_color(text: str, hex_color: str) -> str:
    """Wrap braille frame string in ANSI 24-bit color escape."""
    r = int(hex_color[1:3], 16)
    g = int(hex_color[3:5], 16)
    b = int(hex_color[5:7], 16)
    return f"\x1b[38;2;{r};{g};{b}m{text}\x1b[0m"

# ── SDFMorphEngine ────────────────────────────────────────────────────────────

class SDFMorphEngine:
    """Drawbraille engine that morphs letter forms via SDF interpolation.

    Follows the existing AnimEngine protocol: next_frame(params) -> str.
    Returns empty string if baker isn't ready yet.
    """

    name = "sdf_morph"

    def __init__(self, text: str = "HERMES", hold_ms: float = 900,
                 morph_ms: float = 700, mode: str = "dissolve",
                 outline_w: float = 0.08, dissolve_spread: float = 0.15,
                 font_size: int = 96, color: str = "#00ff66",
                 color_b: str | None = None) -> None:
        text = text.strip()
        if len(text) < 2:
            text = (text + text + "HERMES")[:2]
        self._text = text
        self._hold_ms = hold_ms
        self._morph_ms = morph_ms
        self._mode = mode
        self._outline_w = outline_w
        self._dissolve_spread = dissolve_spread
        self._color = color
        self._color_b = color_b

        self._baker = SDFBaker(resolution=128, font_size=font_size, timeout_s=5.0)
        self._state = MorphState(
            char_a=text[0],
            char_b=text[1],
            t=0.0,
            phase="hold",
            phase_elapsed=0.0,
            seq_idx=0,
        )
        self._started = False

    def on_mount(self, overlay: object) -> None:
        """Start bake worker on a background thread."""
        if self._started:
            return
        self._started = True
        overlay.run_worker(self._bake_worker, thread=True, group="sdf-bake")  # type: ignore[attr-defined]

    def _bake_worker(self) -> None:
        self._baker.bake(self._text)

    def next_frame(self, params: object) -> str:
        """AnimEngine protocol. Returns braille frame or empty string."""
        if not self._baker.ready.is_set():
            return ""
        dt_ms = getattr(params, "dt", 1 / 15) * 1000.0
        self._advance_state(dt_ms)
        return self._render_frame(
            canvas_w=getattr(params, "width", 50),
            canvas_h=getattr(params, "height", 14),
        )

    def tick(self, dt_ms: float, canvas_w: int = 50, canvas_h: int = 14) -> str | None:
        """Direct tick interface (used by startup splash). Returns None if not ready."""
        if not self._baker.ready.is_set():
            return None
        self._advance_state(dt_ms)
        return self._render_frame(canvas_w=canvas_w, canvas_h=canvas_h)

    def _advance_state(self, dt_ms: float) -> None:
        s = self._state
        s.phase_elapsed += dt_ms
        if s.phase == "hold":
            if s.phase_elapsed >= self._hold_ms:
                s.phase = "morph"
                s.phase_elapsed = 0.0
                s.t = 0.0
        else:
            s.t = min(s.phase_elapsed / self._morph_ms, 1.0)
            if s.t >= 1.0:
                s.seq_idx = (s.seq_idx + 1) % len(self._text)
                s.char_a = self._text[s.seq_idx]
                s.char_b = self._text[(s.seq_idx + 1) % len(self._text)]
                s.t = 0.0
                s.phase = "hold"
                s.phase_elapsed = 0.0

    def _render_frame(self, canvas_w: int, canvas_h: int) -> str:
        s = self._state
        sdf_a = self._baker.get(s.char_a)
        sdf_b = self._baker.get(s.char_b)

        sdf = (1.0 - s.t) * sdf_a + s.t * sdf_b

        dot_h = canvas_h * 4
        dot_w = canvas_w * 2
        sdf_scaled = _resize_sdf(sdf, dot_w, dot_h)

        mask = _apply_render_mode(sdf_scaled, self._mode, s.t,
                                   self._outline_w, self._dissolve_spread)

        frame = _mask_to_canvas(mask, dot_w, dot_h)

        color = _resolve_color(self._color, self._color_b, s.t,
                                s.phase == "morph")
        return _apply_ansi_color(frame, color)
