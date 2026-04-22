"""tests/tui/test_help_overlay_plan_entry.py — Help overlay F9 Plan panel entry (Phase 5, 3 tests)."""
from __future__ import annotations

import pytest


# T1: KeymapOverlay _CONTENT_WIDE mentions "Plan panel"
def test_keymap_overlay_wide_has_plan_panel():
    from hermes_cli.tui.widgets.overlays import KeymapOverlay
    assert "Plan panel" in KeymapOverlay._CONTENT_WIDE


# T2: KeymapOverlay _CONTENT_WIDE mentions F9
def test_keymap_overlay_wide_has_f9():
    from hermes_cli.tui.widgets.overlays import KeymapOverlay
    assert "F9" in KeymapOverlay._CONTENT_WIDE


# T3: KeymapOverlay _CONTENT_NARROW also mentions F9
def test_keymap_overlay_narrow_has_f9():
    from hermes_cli.tui.widgets.overlays import KeymapOverlay
    assert "F9" in KeymapOverlay._CONTENT_NARROW
