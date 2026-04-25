"""DensityTier — DENSITY axis vocabulary, inputs dataclass, and resolver.

DensityTier was added in Move 3 as a shared enum. Move 1 (this file) adds
DensityInputs and DensityResolver so ToolPanel owns a single, testable
collapse-decision boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from hermes_cli.tui.services.tools import ToolCallState


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


@dataclass(frozen=True)
class DensityInputs:
    """All inputs the resolver needs to produce a DensityTier decision."""
    phase: "ToolCallState"
    is_error: bool
    has_focus: bool
    user_scrolled_up: bool
    user_override: bool           # True if user manually toggled collapse
    user_override_tier: "DensityTier | None"  # the tier they last picked
    body_line_count: int
    threshold: int                # category default_collapsed_lines (possibly diff-overridden)
    row_budget: "int | None"      # viewport row clamp; None = unbounded (reserved, not yet read)


class DensityResolver:
    """Single owner of the density decision for one tool block.

    Pure logic: no Textual references, no widget mutation. Caller wires
    inputs in, reads ``tier``, applies it.
    """

    def __init__(self) -> None:
        self._tier: DensityTier = DensityTier.DEFAULT
        self._listeners: list[Callable[[DensityTier], None]] = []

    @property
    def tier(self) -> DensityTier:
        return self._tier

    def subscribe(self, fn: Callable[[DensityTier], None]) -> None:
        self._listeners.append(fn)

    def resolve(self, inputs: DensityInputs) -> DensityTier:
        new_tier = self._compute(inputs)
        if new_tier != self._tier:
            self._tier = new_tier
            for fn in self._listeners:
                fn(new_tier)
        return new_tier

    @staticmethod
    def _compute(inp: DensityInputs) -> DensityTier:
        from hermes_cli.tui.services.tools import ToolCallState
        # Modal overrides first — these win regardless of body size.
        if inp.is_error:
            return DensityTier.DEFAULT  # errors must remain readable
        if inp.phase in (ToolCallState.STREAMING, ToolCallState.STARTED):
            return DensityTier.DEFAULT  # never compact while running
        if inp.has_focus:
            return DensityTier.DEFAULT  # focused block stays expanded
        if inp.user_override and inp.user_override_tier is not None:
            return inp.user_override_tier
        if inp.user_scrolled_up:
            # Match today's behavior: don't yank content out from under the user.
            return DensityTier.DEFAULT
        # Auto-collapse rule: post-completion + body exceeds category threshold.
        if inp.phase in (ToolCallState.COMPLETING, ToolCallState.DONE):
            if inp.body_line_count > inp.threshold:
                return DensityTier.COMPACT
        return DensityTier.DEFAULT
