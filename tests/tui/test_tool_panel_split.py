"""B16 — tool_panel subpackage split import tests."""
from __future__ import annotations

import pytest


def test_tool_panel_import_from_old_path():
    """from hermes_cli.tui.tool_panel import ToolPanel succeeds."""
    from hermes_cli.tui.tool_panel import ToolPanel
    assert ToolPanel is not None


def test_footer_pane_import_from_old_path():
    """from hermes_cli.tui.tool_panel import FooterPane succeeds."""
    from hermes_cli.tui.tool_panel import FooterPane
    assert FooterPane is not None


def test_child_panel_import_from_old_path():
    """from hermes_cli.tui.child_panel import ChildPanel succeeds."""
    from hermes_cli.tui.child_panel import ChildPanel
    assert ChildPanel is not None


def test_tool_panel_core_not_empty():
    """tool_panel._core.ToolPanel has compose method."""
    from hermes_cli.tui.tool_panel import _core
    assert hasattr(_core.ToolPanel, "compose")


def test_actions_in_actions_module():
    """tool_panel._actions._ToolPanelActionsMixin has action_retry method."""
    from hermes_cli.tui.tool_panel import _actions
    assert hasattr(_actions._ToolPanelActionsMixin, "action_retry")


def test_footer_in_footer_module():
    """tool_panel._footer.FooterPane exists."""
    from hermes_cli.tui.tool_panel import _footer
    assert _footer.FooterPane is not None


def test_completion_in_completion_module():
    """tool_panel._completion._ToolPanelCompletionMixin has _apply_complete_auto_collapse."""
    from hermes_cli.tui.tool_panel import _completion
    assert hasattr(_completion._ToolPanelCompletionMixin, "_apply_complete_auto_collapse")


def test_no_circular_imports():
    """Importing all submodules in order raises no ImportError."""
    import importlib
    for name in [
        "hermes_cli.tui.tool_panel._footer",
        "hermes_cli.tui.tool_panel._completion",
        "hermes_cli.tui.tool_panel._actions",
        "hermes_cli.tui.tool_panel._core",
        "hermes_cli.tui.tool_panel._child",
        "hermes_cli.tui.tool_panel",
    ]:
        mod = importlib.import_module(name)
        assert mod is not None
