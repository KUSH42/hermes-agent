"""Backward-compat re-export shim — all symbols moved to layout_resolver.py (DU-3)."""
from hermes_cli.tui.tool_panel.layout_resolver import (  # noqa: F401
    DensityTier,
    LayoutInputs,
    LayoutInputs as DensityInputs,
    LayoutDecision,
    ToolBlockLayoutResolver,
    ToolBlockLayoutResolver as DensityResolver,
    _DROP_ORDER_DEFAULT,
    _DROP_ORDER_HERO,
    _DROP_ORDER_COMPACT,
    _DROP_ORDER_BY_TIER,
    trim_tail_for_tier,
    _trim_tail_segments,
    default_resolver,
)
