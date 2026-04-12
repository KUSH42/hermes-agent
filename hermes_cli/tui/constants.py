"""Canonical icon / glyph constants for the Hermes TUI.

Import from here instead of scattering literals across widgets.
All widgets should reference these symbols so a single edit changes
the icon everywhere.
"""

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
