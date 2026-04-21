"""Canonical icon / glyph constants for the Hermes TUI.

Import from here instead of scattering literals across widgets.
All widgets should reference these symbols so a single edit changes
the icon everywhere.
"""

import os as _os


def accessibility_mode() -> bool:
    """Return True when the user has requested reduced-unicode / accessible output.

    Checks both HERMES_NO_UNICODE and HERMES_ACCESSIBLE env vars so either
    convention works.  Callers should guard NF icons and braille characters
    behind this function.
    """
    for key in ("HERMES_NO_UNICODE", "HERMES_ACCESSIBLE"):
        if _os.environ.get(key, "").strip().lower() in ("1", "true", "yes"):
            return True
    return False

# Input prompt
CHEVRON          = "❯"

# Hermes brand / response separator
CADUCEUS         = "⚕"

# Streaming / reasoning gutter bar
BAR_CURSOR       = "▌"

# Tool block state
ICON_EXPAND      = "▸"
ICON_COLLAPSE    = "▾"
ICON_COPY        = "⎘"
ICON_COPY_OK     = "✓"

# File / path references (used in StatusBar breadcrumb AND path autocomplete)
ICON_FILE        = "📄"
ICON_IMAGE       = "📎"

# Agent state
ICON_RUNNING     = "●"
ICON_ROTATE      = "⟳"

# Severity
ICON_WARNING     = "⚠"
