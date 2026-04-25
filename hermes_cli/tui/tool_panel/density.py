"""DensityTier — shared vocabulary for the DENSITY axis.

Resolver and write-sites land in Move 1. This module exists so view-state
and renderer code can import a stable type now.
"""
from __future__ import annotations
from enum import Enum


class DensityTier(str, Enum):
    """Tier ordering: HERO < DEFAULT < COMPACT < TRACE (more → tighter)."""
    HERO    = "hero"     # reserved; used by Move 1 follow-up
    DEFAULT = "default"  # current expanded ToolPanel
    COMPACT = "compact"  # current `collapsed=True` ToolPanel
    TRACE   = "trace"    # reserved; used by Move 1 follow-up

    @property
    def rank(self) -> int:
        return _RANKS[self]


_RANKS = {
    DensityTier.HERO:    0,
    DensityTier.DEFAULT: 1,
    DensityTier.COMPACT: 2,
    DensityTier.TRACE:   3,
}
