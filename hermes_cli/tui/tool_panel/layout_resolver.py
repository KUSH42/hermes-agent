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

_HERO_KINDS = frozenset({ResultKind.DIFF, ResultKind.JSON, ResultKind.TABLE})

# ---------------------------------------------------------------------------
# THRESHOLDS — single canonical home for tier quantitative constants
# (concept.md v3.6 §"Per-tier behavior contract" line 383).
#
# Read via `THRESHOLDS["KEY"]`. Do not introduce module-level duplicates;
# keep all integer thresholds here so a single grep finds every clause-bound
# value.
# ---------------------------------------------------------------------------

THRESHOLDS: dict[str, int] = {
    # HERO tier
    "HERO_MIN_BODY_ROWS":       5,    # min body rows for HERO eligibility
    "HERO_MAX_LINES":           8,    # max body rows before HERO is ineligible
    "HERO_MIN_WIDTH":         100,    # min cols for auto-promote (user override bypasses)
    "MIN_HERO_VIEWPORT_ROWS":  16,    # min terminal rows for any HERO at all

    # DEFAULT tier
    "DEFAULT_BODY_CLAMP":      12,    # rows shown before clamp kicks in

    # COMPACT tier
    "COMPACT_SIBLING_CAP":      4,    # max siblings shown at COMPACT before overflow chip

    # Group caps (TB-MED-2 lands here)
    "GROUP_CAP_DEFAULT":       12,
    "GROUP_CAP_COMPACT":        4,
    "GROUP_CAP_TRACE":          0,

    # Promotion thresholds (TB-MED-1 lands here)
    "LONG_CALL_THRESHOLD_S":    5,    # duration_s above which duration chip is promoted
    "LARGE_PAYLOAD_ROWS":     200,    # body rows above which linecount chip is promoted

    # Viewport gates
    "MIN_BLOCK_COLS":          40,    # block too narrow → placeholder
    "MIN_VIEWPORT_COLS":       24,    # viewport too narrow → degrade gracefully
}


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
    "trace_pending", # state indicator — preserve longer than decorative segments
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
    "trace_pending", # state indicator — preserve
    "exit",
]

_DROP_ORDER_COMPACT: list[str] = [
    "chip",
    "linecount",
    "flash",
    "kind",          # kind override — after flash, before diff
    "diff",
    "duration",      # B1: duration dropped before hero; hero is the load-bearing word
    "hero",
    "chevron",
    "trace_pending", # state indicator — preserve
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
    """Drop tail chips by name until total cell width ≤ budget.

    Note: PHASE=ERR is *not* handled here. The ERR cell rule (concept
    §ER-cell-rule, ER-1..ER-5) is enforced at the header level
    (`tool_blocks/_header.py::_render_v4`) which bypasses this trim
    entirely and emits a fixed 2-chip pinned tail (category + ERR) plus
    optional remediation hint. This resolver only governs density-driven
    trimming on non-ERR phases.
    """
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
    *,
    duration_s: float = 0.0,
    row_count: int = 0,
) -> "list[tuple[str, Text]]":
    """Tier-aware wrapper around _trim_tail_segments.

    Promotions (concept lines 411-415):
    - duration_s > THRESHOLDS["LONG_CALL_THRESHOLD_S"]: 'duration' chip is
      promoted — kept through COMPACT, dropped only at TRACE.
    - row_count > THRESHOLDS["LARGE_PAYLOAD_ROWS"]: 'linecount' chip is
      promoted one tier longer than baseline.
    """
    if tier == DensityTier.TRACE:
        # TRACE drops everything regardless of promotion; concept line 413
        # explicitly caps long-call promotion at "dropped only at TRACE".
        return list(tail_segments)

    order = _DROP_ORDER_BY_TIER.get(tier, _DROP_ORDER_DEFAULT)

    long_call = duration_s > THRESHOLDS["LONG_CALL_THRESHOLD_S"]
    large_payload = row_count > THRESHOLDS["LARGE_PAYLOAD_ROWS"]
    if long_call or large_payload:
        order = _promote_drop_order(order, tier,
                                    promote_duration=long_call,
                                    promote_linecount=large_payload)

    protect = (tier == DensityTier.HERO)
    return _trim_tail_segments(tail_segments, tail_budget, drop_order=order, protect_hero=protect)


def _promote_drop_order(
    order: "list[str]",
    tier: DensityTier,
    *,
    promote_duration: bool,
    promote_linecount: bool,
) -> "list[str]":
    """Return a copy of `order` with promoted chip names moved tail-ward.

    The drop-order list is "first dropped first". Moving a name closer to the
    end of the list = drops later = effectively higher priority.
    """
    out = list(order)
    if promote_duration and "duration" in out:
        out.remove("duration")
        anchor = "chevron" if "chevron" in out else "trace_pending"
        if anchor in out:
            out.insert(out.index(anchor), "duration")
        else:
            out.append("duration")
    if promote_linecount and "linecount" in out:
        idx = out.index("linecount")
        if idx + 1 < len(out):
            out.pop(idx)
            out.insert(idx + 1, "linecount")
    return out


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
    is_streaming: bool = False
    # TB-H3: viewport pressure (rows_consumed_by_visible_blocks /
    # available_terminal_rows). 0.0 is "no pressure", 1.0 is "exactly full",
    # >1.0 is oversubscribed. Default 0.0 preserves prior behaviour for
    # call sites that have not yet been migrated.
    pressure: float = 0.0
    # TB-H3: terminal viewport rows (used to gate MIN_HERO_VIEWPORT_ROWS).
    # Default 999 (very tall) preserves prior behaviour.
    viewport_rows: int = 999
    # TB-H3: True when the block is below the fold (caller computes from
    # scroll position + block y-offset). Drives oversubscribe cascade.
    is_offscreen: bool = False


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
    clamp_rows: "int | None" = None  # None = no clamp; 0 = body suppressed (TRACE)


def _clamp_for_tier(tier: "DensityTier") -> "int | None":
    """Module-level helper so BodyPane can import without circular LayoutDecision dep."""
    return {
        DensityTier.HERO:    None,
        DensityTier.DEFAULT: THRESHOLDS["DEFAULT_BODY_CLAMP"],
        DensityTier.COMPACT: None,  # COMPACT uses summary_line(), not clamp
        DensityTier.TRACE:   0,
    }[tier]


def _pressure_band(pressure: float) -> int:
    """Map a pressure float to a coarse band index (0–3).

    Used by the two-pass fixed-point to detect band crossings between passes.
    Bands correspond to concept.md §"Per-tier behavior contract" crossing table
    (lines 370–373): < 0.6 → 0, 0.6–0.85 → 1, 0.85–1.0 → 2, >1.0 → 3.
    """
    if pressure < 0.6:
        return 0
    if pressure < 0.85:
        return 1
    if pressure <= 1.0:
        return 2
    return 3


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------

class ToolBlockLayoutResolver:
    """Single owner of layout decisions for one tool block."""

    def __init__(self, *, hero_min_width: "int | None" = None) -> None:
        self._tier: DensityTier = DensityTier.DEFAULT
        self._listeners: list[Callable[["LayoutDecision"], None]] = []
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

    def subscribe(self, fn: "Callable[[LayoutDecision], None]") -> None:
        self._listeners.append(fn)

    def resolve(self, inputs: LayoutInputs) -> DensityTier:
        """Backward-compat path used by callers that only need the tier."""
        decision = self.resolve_full(inputs)
        if decision.tier != self._tier:
            self._tier = decision.tier
            for fn in self._listeners:
                fn(decision)
        return decision.tier

    def resolve_full(self, inputs: LayoutInputs) -> LayoutDecision:
        tier, reason = self._compute_tier(inputs)
        # B2: error footer shown during streaming (error msg visible mid-flight);
        # non-error streaming still hides footer (FH-3 / concept §multi-block-rhythm).
        if inputs.is_streaming and not (inputs.is_error and inputs.has_footer_content):
            footer_visible = False
        else:
            # FH-5: COMPACT no longer force-hides; has_footer_content is sole content gate.
            footer_visible = (
                not inputs.user_collapsed
                and inputs.has_footer_content
            )
        return LayoutDecision(
            tier=tier,
            footer_visible=footer_visible,
            width=inputs.width,
            reason=reason,
            clamp_rows=_clamp_for_tier(tier),
        )

    def trim_header_tail(
        self,
        segments: "list[tuple[str, Text]]",
        budget: int,
        tier: DensityTier,
        *,
        duration_s: float = 0.0,
        row_count: int = 0,
    ) -> "list[tuple[str, Text]]":
        return trim_tail_for_tier(segments, budget, tier,
                                  duration_s=duration_s, row_count=row_count)

    @staticmethod
    def _compute(inp: "LayoutInputs") -> "DensityTier":
        """Shim for tests: returns just the tier from a fresh resolver instance."""
        return ToolBlockLayoutResolver()._compute_tier(inp)[0]

    def _compute_tier(
        self, inp: LayoutInputs
    ) -> "tuple[DensityTier, Literal['auto', 'user', 'error_override', 'initial', 'parent_clamp']]":
        from hermes_cli.tui.services.tools import ToolCallState

        reason: Literal["auto", "user", "error_override", "initial", "parent_clamp"] = "auto"

        # Pressure gates (concept lines 112–115, 365–373). Computed early so
        # downstream HERO eligibility honours them.
        pressure_blocks_hero = (
            inp.pressure >= 0.6 and not inp.has_focus
        ) or (
            inp.pressure >= 0.85
        ) or (
            inp.viewport_rows < THRESHOLDS["MIN_HERO_VIEWPORT_ROWS"]
        )
        pressure_forces_compact = (
            inp.pressure >= 0.85 and not inp.has_focus and not inp.is_error
        )
        pressure_cascades_trace = (
            inp.pressure > 1.0
            and not inp.has_focus
            and inp.is_offscreen
            and not inp.is_error
        )

        if inp.is_error:
            base = DensityTier.DEFAULT
            reason = "error_override"
        elif pressure_cascades_trace:
            # ERR bypasses (already handled above). Cascade applies only to
            # off-screen, unfocused, non-error blocks.
            return DensityTier.TRACE, "auto"
        elif inp.phase in (ToolCallState.STREAMING, ToolCallState.STARTED):
            # Active streaming: show body as it arrives at DEFAULT regardless of
            # focus or pressure. No HERO during streaming (no stable body).
            base = DensityTier.DEFAULT
        elif inp.user_override and inp.user_override_tier == DensityTier.HERO:
            # User override beats the width gate but NOT the pressure gate when
            # pressure is hard (>=0.85). At soft pressure (>=0.6) the user wins;
            # the focused-only restriction is only an automatic-promote rule.
            if (
                inp.kind not in _HERO_KINDS
                or inp.body_line_count == 0
                or inp.body_line_count > THRESHOLDS["HERO_MAX_LINES"]
                or (inp.pressure >= 0.85 and not inp.has_focus)
            ):
                base = DensityTier.DEFAULT
            else:
                base = DensityTier.HERO
            reason = "user"
        elif inp.user_override and inp.user_override_tier is not None:
            base = inp.user_override_tier
            reason = "user"
        elif inp.user_scrolled_up:
            # User has scrolled up: hold at DEFAULT so body remains visible.
            # Focused blocks are exempt from pressure-cascade but not from this
            # explicit user action — scroll trumps focus.
            base = DensityTier.DEFAULT
        elif inp.phase in (ToolCallState.COMPLETING, ToolCallState.DONE):
            # Both focused and unfocused DONE/COMPLETING blocks may qualify for HERO.
            # Concept tie-break (docs/concept.md line 108): focused ▸ only ▸ first ▸
            # most-recent. The `pressure_blocks_hero` flag already incorporates the
            # focus-exemption at soft pressure (0.6–0.85 restricts HERO to focused;
            # ≥0.85 disables it entirely).
            want_hero = (
                inp.body_line_count > 0
                and inp.body_line_count <= THRESHOLDS["HERO_MAX_LINES"]
                and inp.kind in _HERO_KINDS
                and not pressure_blocks_hero
            )
            if want_hero and inp.width and inp.width < self._hero_min_width:
                # Auto-promote width gate. User override (handled above) bypasses
                # this, but auto-promote does not.
                want_hero = False
            if want_hero:
                base = DensityTier.HERO
            elif inp.body_line_count > inp.threshold:
                base = DensityTier.COMPACT
            else:
                base = DensityTier.DEFAULT
        else:
            # Unknown/future phase: safe default.
            base = DensityTier.DEFAULT

        # Hard pressure: force COMPACT on unfocused, non-error blocks.
        if pressure_forces_compact and base.rank < DensityTier.COMPACT.rank:
            base = DensityTier.COMPACT

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
        v = cfg.get("display", {}).get("tool_hero_min_width", THRESHOLDS["HERO_MIN_WIDTH"])
        return int(v)
    except Exception:
        # Config may be unavailable in test envs; fall back to default.
        _log.debug("hero_min_width config read failed", exc_info=True)
        return THRESHOLDS["HERO_MIN_WIDTH"]
