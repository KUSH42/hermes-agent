"""Module-level threading.Event sentinels shared between widget sub-modules.

These are defined here (not in __init__.py) so they can be imported by sub-modules
without creating circular imports while still being re-exported at the
hermes_cli.tui.widgets package level.
"""
from __future__ import annotations

import threading as _threading

# Set when StartupBannerWidget enters on_mount. Producer threads (the CLI TTE
# worker) wait on this before assuming query_one() will succeed.
STARTUP_BANNER_READY = _threading.Event()

# Set when OutputPanel.on_mount/on_resize has recorded a non-zero panel width.
OUTPUT_PANEL_WIDTH_READY = _threading.Event()

# Set when the user presses Escape or 's' to skip the startup TTE animation.
STARTUP_TTE_SKIP = _threading.Event()
