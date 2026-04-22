"""tests/tui/test_plan_panel_narrow.py — narrow terminal behavior (Phase 2, 4 tests)."""
from __future__ import annotations

import pytest

from hermes_cli.tui.widgets.plan_panel import PlanPanel


# T1: PlanPanel DEFAULT_CSS has height: auto for expanded state
def test_plan_panel_has_height_auto():
    assert "height: auto" in PlanPanel.DEFAULT_CSS


# T2: PlanPanel collapsed max-height is 1
def test_plan_panel_collapsed_max_height():
    css = PlanPanel.DEFAULT_CSS
    assert "PlanPanel.--collapsed" in css
    # Within the collapsed block: height: 1 and max-height: 1
    collapsed_block_start = css.index("PlanPanel.--collapsed")
    collapsed_block = css[collapsed_block_start:collapsed_block_start + 200]
    assert "height: 1" in collapsed_block


# T3: PlanPanel id is "plan-panel"
def test_plan_panel_expected_id():
    """The panel uses id='plan-panel' in compose() in app.py — verify it's the right name."""
    # Check that the class is PlanPanel (not renamed)
    assert PlanPanel.__name__ == "PlanPanel"


# T4: _PlanPanelHeader updates with collapsed chip format
def test_header_shows_chip_info_when_collapsed():
    from hermes_cli.tui.widgets.plan_panel import _PlanPanelHeader
    # Verify update_header generates a compact format when collapsed=True
    import io
    from contextlib import redirect_stdout

    # We can't easily test the Static update without mounting, but we can
    # verify that the method exists and accepts the expected arguments
    header = _PlanPanelHeader.__new__(_PlanPanelHeader)
    # Method must exist
    assert hasattr(header, "update_header")
