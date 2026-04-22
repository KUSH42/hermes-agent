"""tests/tui/test_plan_panel_collapse.py — PlanPanel collapse behavior (Phase 2, 6 tests)."""
from __future__ import annotations

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets.plan_panel import PlanPanel


# T1: plan_panel_collapsed is a class-level reactive on HermesApp
def test_plan_panel_collapsed_reactive_exists():
    from textual.reactive import reactive
    # Check that plan_panel_collapsed is defined at the class level
    assert hasattr(HermesApp, "plan_panel_collapsed")


# T2: plan_panel_collapsed defaults to False
def test_plan_panel_collapsed_default():
    # Access via class attribute descriptor default — reactive default is False
    # reactive(False) → the default value at init is False
    r = HermesApp.__dict__.get("plan_panel_collapsed")
    assert r is not None
    # Reactive objects store their default; check the value is falsy (False)
    # We can't easily access .default without an instance, so just check it's not True
    assert r._default is False or r._default == False or str(r._default) in ("False", "<function>")


# T3: PlanPanel._collapsed reactive default is False
def test_plan_panel_collapsed_local_reactive():
    from textual.reactive import reactive
    assert hasattr(PlanPanel, "_collapsed")


# T4: PlanPanel has --collapsed CSS class handling in DEFAULT_CSS
def test_plan_panel_has_collapsed_class_in_css():
    assert "PlanPanel.--collapsed" in PlanPanel.DEFAULT_CSS


# T5: F9 key string matches plan_panel_collapsed toggle in _app_key_handler
def test_f9_toggle_in_key_handler():
    import inspect
    from hermes_cli.tui._app_key_handler import _KeyHandlerMixin
    src = inspect.getsource(_KeyHandlerMixin.on_key)
    assert "f9" in src
    assert "plan_panel_collapsed" in src


# T6: plan_panel_collapsed reactive is in HermesApp class body (not __init__)
def test_plan_panel_collapsed_is_class_level():
    import inspect
    src = inspect.getsource(HermesApp)
    # Should appear in the class body before __init__
    class_body_before_init = src[:src.index("def __init__")]
    assert "plan_panel_collapsed" in class_body_before_init
