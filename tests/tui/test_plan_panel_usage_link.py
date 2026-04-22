"""tests/tui/test_plan_panel_usage_link.py — Budget click → UsageOverlay (Phase 3, 3 tests)."""
from __future__ import annotations

import pytest


# T1: _BudgetSection has on_click method
def test_budget_section_has_on_click():
    from hermes_cli.tui.widgets.plan_panel import _BudgetSection
    assert hasattr(_BudgetSection, "on_click")


# T2: _BudgetSection.on_click tries to open UsageOverlay
def test_budget_section_on_click_opens_usage_overlay():
    import inspect
    from hermes_cli.tui.widgets.plan_panel import _BudgetSection
    src = inspect.getsource(_BudgetSection.on_click)
    assert "UsageOverlay" in src


# T3: _reset_turn_state is called from on_hermes_input_submitted
def test_reset_called_on_submit():
    import inspect
    from hermes_cli.tui._app_key_handler import _KeyHandlerMixin
    src = inspect.getsource(_KeyHandlerMixin.on_hermes_input_submitted)
    assert "_reset_turn_state" in src
