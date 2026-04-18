"""Kitty Terminal Graphics Protocol renderer + Unicode halfblock fallback.

Architecture: specs/kitty-graphics-charts.md §4–§8.
"""

from __future__ import annotations

import base64
import fcntl
import io
import math
import os
import struct
import sys
import termios
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

import rich.color
from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip

try:
    from PIL import Image as PILImage
    _PIL_AVAILABLE = True
except ImportError:
    PILImage = None  # type: ignore[assignment,misc]
    _PIL_AVAILABLE = False


# ---------------------------------------------------------------------------
# § 4.1  Capability enum
# ---------------------------------------------------------------------------

class GraphicsCap(Enum):
    TGP       = auto()   # Kitty TGP — full pixel fidelity
    SIXEL     = auto()   # Sixel — stretch goal (Phase D)
    HALFBLOCK = auto()   # Unicode ▀/▄/█ 2-pixel-per-cell approximation
    NONE      = auto()   # Text placeholder only


# ---------------------------------------------------------------------------
# § 4.2  Detection
# ---------------------------------------------------------------------------

_caps: GraphicsCap | None = None


def get_caps() -> GraphicsCap:
    global _caps
    if _caps is None:
        _caps = _detect_caps()
    return _caps


def _reset_caps() -> None:
    """Test-only: clear cached detection result."""
    global _caps
    _caps = None


def _detect_caps() -> GraphicsCap:
    # Step 1: env override
    override = os.environ.get("HERMES_GRAPHICS", "").lower().strip()
    if override == "tgp":
        return GraphicsCap.TGP
    if override == "sixel":
        return GraphicsCap.SIXEL
    if override == "halfblock":
        return GraphicsCap.HALFBLOCK
    if override == "none":
        return GraphicsCap.NONE

    # Step 2: PIL required for all image rendering
    if not _PIL_AVAILABLE:
        return GraphicsCap.NONE

    # Step 3: TERM_PROGRAM heuristics
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    if term_program in ("kitty", "wezterm", "ghostty"):
        # Step 5: tmux intercepts TGP — downgrade (checked after TERM_PROGRAM)
        if os.environ.get("TMUX"):
            return GraphicsCap.HALFBLOCK
        return GraphicsCap.TGP

    # Step 4: TERM heuristic
    term = os.environ.get("TERM", "")
    if term.startswith("xterm-kitty"):
        if os.environ.get("TMUX"):
            return GraphicsCap.HALFBLOCK
        return GraphicsCap.TGP

    # Step 5: tmux after TERM_PROGRAM / TERM checks
    if os.environ.get("TMUX"):
        return GraphicsCap.HALFBLOCK

    # Step 6: active APC query
    if term != "dumb" and sys.stdout.isatty():
        if _apc_probe():
            return GraphicsCap.TGP

    # Step 7: truecolor env
    if os.environ.get("COLORTERM", "").lower() == "truecolor":
        return GraphicsCap.HALFBLOCK

    # Step 8: xterm / screen prefix
    if term.startswith(("xterm", "screen")):
        return GraphicsCap.HALFBLOCK

    # Step 9: default
    return GraphicsCap.NONE


def _apc_probe() -> bool:
    """Send a Kitty TGP query to stdout; return True if terminal responds with OK.

    Sets stdin to raw mode with 100 ms read timeout. Always restores cooked
    mode in a finally block.
    """
    import select
    import tty
    old_settings = None
    try:
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        tty.setraw(fd)
        # Query: transmit a 1×1 white pixel PNG as a capability probe
        sys.stdout.write("\x1b_Gi=31,s=1,v=1,a=q,t=d,f=32;AAAA\x1b\\")
        sys.stdout.flush()
        # Wait up to 100 ms for a response
        rlist, _, _ = select.select([sys.stdin], [], [], 0.1)
        if not rlist:
            return False
        response = ""
        while rlist:
            chunk = os.read(fd, 256)
            if not chunk:
                break
            response += chunk.decode("ascii", errors="replace")
            rlist, _, _ = select.select([sys.stdin], [], [], 0.01)
        return ";OK" in response
    except Exception:
        return False
    finally:
        if old_settings is not None:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# § 4.3  Cell dimension detection
# ---------------------------------------------------------------------------

_TIOCGWINSZ = getattr(termios, "TIOCGWINSZ", 0x5413)
_cell_px_cache: tuple[int, int] | None = None


def _cell_px() -> tuple[int, int]:
    """Return (cell_width_px, cell_height_px)."""
    try:
        buf = b"\x00" * 8
        result = fcntl.ioctl(1, _TIOCGWINSZ, buf)
        ws_row, ws_col, ws_xpixel, ws_ypixel = struct.unpack("HHHH", result)
        if ws_col > 0 and ws_row > 0 and ws_xpixel > 0 and ws_ypixel > 0:
            return ws_xpixel // ws_col, ws_ypixel // ws_row
    except Exception:
        pass

    env = os.environ.get("HERMES_CELL_PX", "")
    if env:
        try:
            w, h = env.split("x")
            cw, ch = int(w), int(h)
            if cw > 0 and ch > 0:
                return cw, ch
        except (ValueError, AttributeError):
            pass

    return 10, 20  # safe fallback


def cell_width_px() -> int:
    global _cell_px_cache
    if _cell_px_cache is None:
        _cell_px_cache = _cell_px()
    return _cell_px_cache[0]


def cell_height_px() -> int:
    global _cell_px_cache
    if _cell_px_cache is None:
        _cell_px_cache = _cell_px()
    return _cell_px_cache[1]


def _reset_cell_px_cache() -> None:
    """Test-only: clear cell dimension cache."""
    global _cell_px_cache
    _cell_px_cache = None


# ---------------------------------------------------------------------------
# § 5.5  Chunking
# ---------------------------------------------------------------------------

def _chunk_b64(data: bytes) -> list[str]:
    """Split raw bytes into ≤4096-char base64 chunks."""
    b64 = base64.standard_b64encode(data).decode("ascii")
    return [b64[i : i + 4096] for i in range(0, len(b64), 4096)]


# ---------------------------------------------------------------------------
# § 5  TGP sequence builder
# ---------------------------------------------------------------------------

def _build_tgp_sequence(
    image: "PILImage.Image",
    cols: int,
    rows: int,
    image_id: int,
) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=False, compress_level=1)
    raw = buf.getvalue()
    pw, ph = image.size
    chunks = _chunk_b64(raw)

    if len(chunks) == 1:
        return (
            f"\x1b_Ga=T,f=100,s={pw},v={ph},c={cols},r={rows},"
            f"i={image_id},m=0,q=2;{chunks[0]}\x1b\\"
        )

    parts: list[str] = []
    parts.append(
        f"\x1b_Ga=T,f=100,s={pw},v={ph},c={cols},r={rows},"
        f"i={image_id},m=1,q=2;{chunks[0]}\x1b\\"
    )
    for chunk in chunks[1:-1]:
        parts.append(f"\x1b_Gm=1,q=2;{chunk}\x1b\\")
    parts.append(f"\x1b_Gm=0,q=2;{chunks[-1]}\x1b\\")
    return "".join(parts)


# ---------------------------------------------------------------------------
# § 5.6  Image sizing
# ---------------------------------------------------------------------------

def _fit_image(
    img: "PILImage.Image",
    max_cols: int,
    max_rows: int,
    cw: int,
    ch: int,
) -> "tuple[PILImage.Image, int, int]":
    """Resize img to fit max_cols×max_rows cells. Returns (image, cols, rows)."""
    assert cw > 0 and ch > 0, f"cell dimensions must be positive, got ({cw}, {ch})"
    max_px_w = max_cols * cw
    max_px_h = max_rows * ch
    img.thumbnail((max_px_w, max_px_h), PILImage.LANCZOS)
    pw, ph = img.size
    cols = math.ceil(pw / cw)
    rows = math.ceil(ph / ch)
    return img, cols, rows


# ---------------------------------------------------------------------------
# § 6  KittyRenderer
# ---------------------------------------------------------------------------

class KittyRenderer:
    """Encode a PIL.Image into a TGP escape sequence string."""

    def __init__(
        self,
        max_cols: int = 80,
        max_rows: int = 24,
        cw: int | None = None,
        ch: int | None = None,
    ) -> None:
        self._max_cols = max_cols
        self._max_rows = max_rows
        self._cw = cw if cw is not None else cell_width_px()
        self._ch = ch if ch is not None else cell_height_px()
        self._next_id: int = 1

    def render(self, image: "PILImage.Image") -> "tuple[str, int, int, int]":
        """Return (escape_sequence, image_id, actual_cols, actual_rows)."""
        image_id = self._alloc_id()
        resized, cols, rows = _fit_image(
            image.convert("RGBA"),
            self._max_cols,
            self._max_rows,
            self._cw,
            self._ch,
        )
        seq = _build_tgp_sequence(resized, cols, rows, image_id)
        return seq, image_id, cols, rows

    def delete_sequence(self, image_id: int) -> str:
        return f"\x1b_Ga=d,d=I,i={image_id};\x1b\\"

    def delete_all_sequence(self) -> str:
        return "\x1b_Ga=d,d=A;\x1b\\"

    def _alloc_id(self) -> int:
        iid = self._next_id
        self._next_id = (self._next_id % 4_294_967_295) + 1
        return iid


# ---------------------------------------------------------------------------
# § 9.3  Module-level renderer singleton
# ---------------------------------------------------------------------------

_renderer: KittyRenderer | None = None


def _get_renderer() -> KittyRenderer:
    global _renderer
    if _renderer is None:
        _renderer = KittyRenderer()
    return _renderer


def _reset_renderer() -> None:
    """Test-only: discard singleton so next call rebuilds with fresh cell dims."""
    global _renderer
    _renderer = None


# ---------------------------------------------------------------------------
# § 7.1  Luminance
# ---------------------------------------------------------------------------

def _luminance(rgb: "tuple[int, int, int]") -> float:
    """Relative luminance per WCAG 2.1. Returns [0.0, 1.0]."""
    def _lin(c: int) -> float:
        v = c / 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


# ---------------------------------------------------------------------------
# § 7.2  HalfblockRenderer
# ---------------------------------------------------------------------------

HALF_UP   = "\u2580"   # ▀  top half block
HALF_DOWN = "\u2584"   # ▄  lower half block
BLOCK     = "\u2588"   # █  full block
SPACE     = " "


def render_halfblock(
    image: "PILImage.Image",
    max_cols: int = 80,
    max_rows: int = 24,
) -> "list[Strip]":
    """Render image as halfblock art. Returns list[Strip], one per output row."""
    img = image.convert("RGB")
    img = img.resize((max_cols, max_rows * 2), PILImage.LANCZOS)
    w, h = img.size
    px = img.load()
    strips: list[Strip] = []

    for cell_row in range(h // 2):
        segments: list[Segment] = []
        for col in range(w):
            top_rgb: tuple[int, int, int] = px[col, cell_row * 2]
            bot_rgb: tuple[int, int, int] = px[col, cell_row * 2 + 1]
            top_dark = _luminance(top_rgb) < 0.1
            bot_dark = _luminance(bot_rgb) < 0.1

            if top_dark and bot_dark:
                segments.append(Segment(SPACE))
            elif top_dark:
                segments.append(
                    Segment(HALF_DOWN, Style(color=rich.color.Color.from_rgb(*bot_rgb)))
                )
            elif bot_dark:
                segments.append(
                    Segment(HALF_UP, Style(color=rich.color.Color.from_rgb(*top_rgb)))
                )
            else:
                avg: tuple[int, int, int] = tuple(  # type: ignore[assignment]
                    (t + b) // 2 for t, b in zip(top_rgb, bot_rgb)
                )
                segments.append(
                    Segment(BLOCK, Style(color=rich.color.Color.from_rgb(*avg)))
                )
        strips.append(Strip(segments))

    return strips


# ---------------------------------------------------------------------------
# § 8  _load_image
# ---------------------------------------------------------------------------

def _load_image(
    source: "PILImage.Image | Path | str",
) -> "PILImage.Image | None":
    """Load image from PIL.Image, Path, or str. Returns None on any error."""
    if not _PIL_AVAILABLE:
        return None
    try:
        if isinstance(source, PILImage.Image):
            return source
        path = Path(source) if isinstance(source, str) else source
        if not path.exists():
            return None
        img = PILImage.open(path)
        img.load()  # force decode so errors surface here, not later
        return img
    except Exception:
        return None
