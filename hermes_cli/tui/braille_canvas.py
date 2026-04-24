"""Pure-Python braille canvas — drop-in replacement for drawbraille.Canvas.

Bit encoding matches drawbraille exactly so existing set(x,y)/frame() call sites
work unchanged.  Each terminal cell covers a 2×4 dot grid; the unicode braille
block starts at U+2800.
"""
from __future__ import annotations

_PIXEL_MAP: tuple[tuple[int, int], ...] = (
    (0x01, 0x08),
    (0x02, 0x10),
    (0x04, 0x20),
    (0x40, 0x80),
)
_BRAILLE_OFFSET = 0x2800


class BrailleCanvas:
    """Minimal braille canvas with set(x,y) / frame() API."""

    __slots__ = ("_chars",)

    def __init__(self) -> None:
        self._chars: dict[tuple[int, int], int] = {}

    def set(self, x: int, y: int) -> None:  # noqa: A003
        if x < 0 or y < 0:
            return
        ix, iy = int(x), int(y)
        col, dx = ix >> 1, ix & 1
        row, dy = iy >> 2, iy & 3
        key = (col, row)
        self._chars[key] = self._chars.get(key, 0) | _PIXEL_MAP[dy][dx]

    def frame(self) -> str:
        if not self._chars:
            return ""
        max_col = max(c for c, _ in self._chars) + 1
        max_row = max(r for _, r in self._chars) + 1
        rows = []
        for r in range(max_row):
            row = "".join(
                chr(_BRAILLE_OFFSET | self._chars.get((c, r), 0))
                for c in range(max_col)
            )
            rows.append(row)
        return "\n".join(rows)
