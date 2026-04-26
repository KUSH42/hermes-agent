"""Single resolver that owns row-budget negotiation across header-tail,
body-tier, and footer-visibility.

Replaces the parallel `DensityResolver` (body tier) +
`_DROP_ORDER_BY_TIER` / `trim_tail_for_tier` (header tail) split that
this spec collapses. See docs/spec_tool_density_unification.md.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Callable, Literal

from hermes_cli.tui.tool_payload import ResultKind

if TYPE_CHECKING:
    from rich.text import Text
    from hermes_cli.tui.services.tools import ToolCallState

_log = logging.getLogger(__name__)

_HERO_MAX_LINES = 8
_HERO_KINDS = frozenset({ResultKind.DIFF, ResultKind.JSON, ResultKind.TABLE})

# DU-4: width gate for HERO promotion. Default 100 cells. Read once from
# `display.tool_hero_min_width` at resolver construction.
DEFAULT_HERO_MIN_WIDTH = 100


class DensityTier(str, Enum):
    """Tier ordering: HERO < DEFAULT < COMPACT < TRACE (more → tighter)."""
    HERO    = "hero"
    DEFAULT = "default"
    COMPACT = "compact"
    TRACE   = "trace"

    @property
    def rank(self) -> int:
        return _RANKS[self]


_RANKS = {
    DensityTier.HERO:    0,
    DensityTier.DEFAULT: 1,
    DensityTier.COMPACT: 2,
    DensityTier.TRACE:   3,
}


# ---------------------------------------------------------------------------
# Per-tier drop order (moved from tool_blocks/_header.py in DU-1; deleted
# there in DU-3).
# ---------------------------------------------------------------------------

_DROP_ORDER_DEFAULT: list[str] = [
    "chip",          # browse-badge — purely contextual, lowest signal
    "linecount",     # size context, derivable
    "duration",      # often available via age microcopy in footer
    "kind",          # kind override label — drop before flash; invisible when no override
    "flash",         # ephemeral — accept loss when space is tight
    "chevron",       # collapse hint — preserve mid-priority
    "diff",          # structural — preserve
    "hero",          # primary summary — preserve
    "stderrwarn",    # "press e for stderr" — recovery affordance
    "remediation",   # error explanation — recovery affordance
    "exit",          # highest signal: always keep
]

_DROP_ORDER_HERO: list[str] = [
    "chip",
    "linecount",
    "duration",
    "kind",          # kind override — drop after duration, before flash
    "flash",
    "diff",
    "chevron",
    "stderrwarn",    # recovery affordance — preserve
    "remediation",   # recovery affordance — preserve
    "exit",
]

_DROP_ORDER_COMPACT: list[str] = [
    "chip",
    "linecount",
    "flash",
    "kind",          # kind override — after flash, before chevron
    "diff",
    "hero",
    "chevron",
    "duration",
    "stderrwarn",    # recovery affordance — preserve
    "remediation",   # moved from 1 → 8: recovery affordance now preserved
    "exit",
]

_DROP_ORDER_BY_TIER: "dict[DensityTier, list[str]]" = {
    DensityTier.HERO:    _DROP_ORDER_HERO,
    DensityTier.DEFAULT: _DROP_ORDER_DEFAULT,
    DensityTier.COMPACT: _DROP_ORDER_COMPACT,
    DensityTier.TRACE:   [],
}


def _trim_tail_segments(
    segments: "list[tuple[str, Text]]",
    budget: int,
    drop_order: "list[str] | None" = None,
    protect_hero: bool = False,
) -> "list[tuple[str, Text]]":
    """Drop tail chips by name until total cell width ≤ budget."""
    if drop_order is None:
        drop_order = _DROP_ORDER_DEFAULT
    result = list(segments)
    total_w = sum(s.cell_len for _, s in result)
    names = {name for name, _ in result}
    if (not protect_hero
            and total_w > budget
            and names <= {"hero", "flash"}
            and "hero" in names):
        for i in reversed(range(len(result))):
            if result[i][0] == "hero":
                total_w -= result[i][1].cell_len
                result.pop(i)
                break
    for name in drop_order:
        if total_w <= budget:
            break
        for i in reversed(range(len(result))):
            if result[i][0] == name:
                total_w -= result[i][1].cell_len
                result.pop(i)
                break
    return result


def trim_tail_for_tier(
    tail_segments: "list[tuple[str, Text]]",
    tail_budget: int,
    tier: DensityTier,
) -> "list[tuple[str, Text]]":
    """Tier-aware wrapper around _trim_tail_segments."""
    if tier == DensityTier.TRACE:
        return list(tail_segments)
    order = _DROP_ORDER_BY_TIER.get(tier, _DROP_ORDER_DEFAULT)
    protect = (tier == DensityTier.HERO)
    return _trim_tail_segments(tail_segments, tail_budget, drop_order=order, protect_hero=protect)


# ---------------------------------------------------------------------------
# Inputs / decision
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LayoutInputs:
    """Union of inputs the resolver needs across all 3 stages."""
    phase: "ToolCallState"
    is_error: bool
    has_focus: bool
    user_scrolled_up: bool
    user_override: bool
    user_override_tier: "DensityTier | None"
    body_line_count: int
    threshold: int
    row_budget: "int | None" = None
    kind: "ResultKind | None" = None
    parent_clamp: "DensityTier | None" = None
    width: int = 0
    user_collapsed: bool = False
    has_footer_content: bool = False


# Backward-compat alias used by DU-3 shim layer.
DensityInputs = LayoutInputs


@dataclass
class DensityResult:
    """Lightweight result from a density resolver call — tier + reason only.

    Used by panels to track last-seen tier and post flash messages (LL-1).
    Compare .tier directly; two DensityResult instances with the same tier but
    different reason are not equal (dataclass eq=True hashes all fields).
    """
    tier: DensityTier
    reason: Literal["auto", "user", "error_override", "initial"]


@dataclass(frozen=True)
class LayoutDecision:
    tier: DensityTier
    footer_visible: bool
    width: int
    reason: Literal["auto", "user", "error_override", "initial", "parent_clamp"]


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class ToolBlockLayoutResolver:
    """Single owner of layout decisions for one tool block."""

    def __init__(self, *, hero_min_width: "int | None" = None) -> None:
        self._tier: DensityTier = DensityTier.DEFAULT
        self._listeners: list[Callable[[DensityTier], None]] = []
        self._hero_min_width: int = (
            hero_min_width
            if hero_min_width is not None
            else _read_hero_min_width_config()
        )

    @property
    def tier(self) -> DensityTier:
        return self._tier

    @property
    def hero_min_width(self) -> int:
        return self._hero_min_width

    def subscribe(self, fn: Callable[[DensityTier], None]) -> None:
        self._listeners.append(fn)

    def resolve(self, inputs: LayoutInputs) -> DensityTier:
        """Backward-compat path used by callers that only need the tier."""
        decision = self.resolve_full(inputs)
        if decision.tier != self._tier:
            self._tier = decision.tier
            for fn in self._listeners:
                fn(decision.tier)
        return decision.tier

    def resolve_full(self, inputs: LayoutInputs) -> LayoutDecision:
        tier, reason = self._compute_tier(inputs)
        footer_visible = (
            tier != DensityTier.COMPACT
            and not inputs.user_collapsed
            and inputs.has_footer_content
        )
        return LayoutDecision(
            tier=tier,
            footer_visible=footer_visible,
            width=inputs.width,
            reason=reason,
        )

    def trim_header_tail(
        self,
        segments: "list[tuple[str, Text]]",
        budget: int,
        tier: DensityTier,
    ) -> "list[tuple[str, Text]]":
        return trim_tail_for_tier(segments, budget, tier)

    def _compute_tier(
        self, inp: LayoutInputs
    ) -> "tuple[DensityTier, Literal['auto', 'user', 'error_override', 'initial', 'parent_clamp']]":
        from hermes_cli.tui.services.tools import ToolCallState

        reason: Literal["auto", "user", "error_override", "initial", "parent_clamp"] = "auto"

        if inp.is_error:
            base = DensityTier.DEFAULT
            reason = "error_override"
        elif inp.phase in (ToolCallState.STREAMING, ToolCallState.STARTED):
            base = DensityTier.DEFAULT
        elif inp.has_focus:
            base = DensityTier.DEFAULT
        elif inp.user_override and inp.user_override_tier == DensityTier.HERO:
            # DU-4: user override beats the width gate; eligibility (kind /
            # line count) still applies so the promoted view is sensible.
            if (
                inp.kind not in _HERO_KINDS
                or inp.body_line_count == 0
                or inp.body_line_count > _HERO_MAX_LINES
            ):
                base = DensityTier.DEFAULT
            else:
                base = DensityTier.HERO
            reason = "user"
        elif inp.user_override and inp.user_override_tier is not None:
            base = inp.user_override_tier
            reason = "user"
        elif inp.user_scrolled_up:
            base = DensityTier.DEFAULT
        elif inp.phase in (ToolCallState.COMPLETING, ToolCallState.DONE):
            want_hero = (
                inp.body_line_count > 0
                and inp.body_line_count <= _HERO_MAX_LINES
                and inp.kind in _HERO_KINDS
            )
            # DU-4: width gate blocks auto-promote, never user override.
            if want_hero and inp.width and inp.width < self._hero_min_width:
                want_hero = False
            if want_hero:
                base = DensityTier.HERO
            elif inp.body_line_count > inp.threshold:
                base = DensityTier.COMPACT
            else:
                base = DensityTier.DEFAULT
        else:
            base = DensityTier.DEFAULT

        if (
            inp.parent_clamp is not None
            and not inp.is_error
            and inp.parent_clamp.rank > base.rank
        ):
            return inp.parent_clamp, "parent_clamp"
        return base, reason


# ---------------------------------------------------------------------------
# DensityResolver alias — kept identical to DensityResolver before DU-1
# ---------------------------------------------------------------------------

DensityResolver = ToolBlockLayoutResolver


# ---------------------------------------------------------------------------
# Module-level singleton for callers without a ToolPanel in scope.
# ---------------------------------------------------------------------------

_default_resolver: "ToolBlockLayoutResolver | None" = None


def default_resolver() -> ToolBlockLayoutResolver:
    """Process-wide singleton resolver (lazy)."""
    global _default_resolver
    if _default_resolver is None:
        _default_resolver = ToolBlockLayoutResolver()
    return _default_resolver


def _read_hero_min_width_config() -> int:
    try:
        from hermes_cli.config import load_config
        cfg = load_config()
        v = cfg.get("display", {}).get("tool_hero_min_width", DEFAULT_HERO_MIN_WIDTH)
        return int(v)
    except Exception:
        # Config may be unavailable in test envs; fall back to default.
        _log.debug("hero_min_width config read failed", exc_info=True)
        return DEFAULT_HERO_MIN_WIDTH
