"""Rotating power-key tips shown in the hint row — one per completed response."""
from __future__ import annotations

POWER_KEY_TIPS: tuple[tuple[str, str], ...] = (
    ("Y", "copy input"),
    ("C", "copy +color"),
    ("H", "copy HTML"),
    ("I", "copy invocation"),
    ("O", "open URL"),
    ("E", "edit cmd"),
    ("P", "copy full path"),
)

_tips = list(POWER_KEY_TIPS)
_idx: int = 0


def current_tip() -> tuple[str, str]:
    """Return the current tip without advancing."""
    return _tips[_idx % len(_tips)]


def advance() -> None:
    """Advance to the next tip. Call once per response completion."""
    global _idx
    _idx += 1


def reset() -> None:
    """Test-only reset. Do not call in production code."""
    global _idx
    _idx = 0
