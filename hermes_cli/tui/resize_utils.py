"""Terminal resize utilities — thresholds and hysteresis helper."""

from __future__ import annotations

# Column thresholds — import these everywhere; no magic numbers in on_resize methods
THRESHOLD_ULTRA_NARROW = 40   # below: show MinSizeOverlay, hide all decorations
THRESHOLD_NARROW       = 60   # ToolPanel compact, ToolsScreen dismiss
THRESHOLD_TOOL_NARROW  = 80   # ToolGroup --narrow
THRESHOLD_COMP_NARROW  = 100  # CompletionOverlay --narrow

# Row thresholds
THRESHOLD_MIN_HEIGHT   = 8    # below: show MinSizeOverlay
THRESHOLD_BAR_HIDE     = 12   # below: hide bottom bar widgets (legacy — watch_size uses 8/9/10)

# Dead-band ± cols around each threshold; prevents class flip-flop on drag
HYSTERESIS             = 2


def crosses_threshold(old: int, new: int, threshold: int, hyst: int = HYSTERESIS) -> bool:
    """Return True only when the value cleanly crosses through the dead-band zone.

    Dead-band is [threshold-hyst, threshold+hyst).  Within this zone no state
    change fires, preventing CSS-class flip-flop when the user drags the terminal
    edge back and forth near a boundary.

    Initial-state note: passing old=0 always triggers for thresholds >= HYSTERESIS
    (all our thresholds are >= 8), so widgets initialise correctly on first resize.
    """
    lo, hi = threshold - hyst, threshold + hyst
    was_above = old >= hi
    now_below  = new  <  lo
    was_below  = old  <  lo
    now_above  = new  >= hi
    return (was_above and now_below) or (was_below and now_above)
