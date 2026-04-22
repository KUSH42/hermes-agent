"""E2: mini-mode tests — ToolPanelMini deleted; mini is now --minified class on ToolPanel.

Covers:
- E2: tool_panel_mini.py deleted (import raises ImportError)
- E2: _maybe_activate_mini gates on display.auto_mini_mode config (default False)
- E2: auto_mini_mode=False → --minified class NOT applied after qualifying SHELL complete
- E2: auto_mini_mode=True → --minified class applied after qualifying SHELL complete
- E2: non-SHELL / error / >3L / stderr → no --minified even when config enabled
- E2: /density auto-mini enables config flag; /density full disables and clears --minified
- E1: _post_complete_tidy called after set_result_summary (collapse + mini sequenced)
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, PropertyMock


# ---------------------------------------------------------------------------
# E2: ToolPanelMini deleted
# ---------------------------------------------------------------------------


def test_tool_panel_mini_module_deleted():
    """E2: tool_panel_mini.py no longer exists; importing it raises ImportError."""
    import importlib
    import sys
    sys.modules.pop("hermes_cli.tui.tool_panel_mini", None)
    with pytest.raises((ImportError, ModuleNotFoundError)):
        importlib.import_module("hermes_cli.tui.tool_panel_mini")


# ---------------------------------------------------------------------------
# E2: _maybe_activate_mini — config gate
# ---------------------------------------------------------------------------


def _make_panel_with_cfg(auto_mini: bool = False):
    """Return a ToolPanel wired with cli._cfg[display][auto_mini_mode]."""
    from hermes_cli.tui.tool_panel import ToolPanel

    block = MagicMock()
    block._total_received = 0
    block._all_plain = ["line 1", "line 2"]

    panel = ToolPanel(block=block, tool_name="bash")
    panel._body_pane = MagicMock()
    panel._footer_pane = MagicMock()
    panel._footer_pane._remediation_row = MagicMock()
    panel._footer_pane.add_class = MagicMock()
    panel._footer_pane.styles = MagicMock()
    panel._accent = MagicMock()
    panel.add_class = MagicMock()
    panel.remove_class = MagicMock()
    panel.post_message = MagicMock()
    panel.set_timer = MagicMock()
    panel.call_after_refresh = MagicMock(side_effect=lambda fn, *a, **kw: fn(*a, **kw))

    cli_mock = MagicMock()
    cli_mock._cfg = {"display": {"auto_mini_mode": auto_mini}}
    app_mock = MagicMock()
    app_mock.cli = cli_mock

    return panel, app_mock


def test_mini_mode_disabled_by_default():
    """E2: default config → --minified NOT applied after clean SHELL complete."""
    from hermes_cli.tui.tool_category import ToolCategory
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    panel, app_mock = _make_panel_with_cfg(auto_mini=False)
    panel._category = ToolCategory.SHELL

    summary = ResultSummaryV4(primary=None, is_error=False, exit_code=0, stderr_tail="", chips=(), actions=(), artifacts=())

    with patch.object(type(panel), "app", new_callable=PropertyMock, return_value=app_mock):
        panel._maybe_activate_mini(summary)

    # add_class("--minified") must NOT have been called
    calls = [c[0][0] for c in panel.add_class.call_args_list if c[0]]
    assert "--minified" not in calls, f"--minified applied despite auto_mini_mode=False: {calls}"


def test_mini_mode_opt_in_renders_stub():
    """E2: auto_mini_mode=True → --minified applied after qualifying SHELL complete."""
    from hermes_cli.tui.tool_category import ToolCategory
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    panel, app_mock = _make_panel_with_cfg(auto_mini=True)
    panel._category = ToolCategory.SHELL

    # Wire _body_line_count to return 2
    panel._body_line_count = lambda: 2

    summary = ResultSummaryV4(primary=None, is_error=False, exit_code=0, stderr_tail="", chips=(), actions=(), artifacts=())

    with patch.object(type(panel), "app", new_callable=PropertyMock, return_value=app_mock):
        panel._maybe_activate_mini(summary)

    calls = [c[0][0] for c in panel.add_class.call_args_list if c[0]]
    assert "--minified" in calls, f"--minified not applied with auto_mini_mode=True: {calls}"


def test_mini_mode_non_shell_skipped():
    """E2: non-SHELL category → no --minified even when enabled."""
    from hermes_cli.tui.tool_category import ToolCategory
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    panel, app_mock = _make_panel_with_cfg(auto_mini=True)
    panel._category = ToolCategory.FILE
    panel._body_line_count = lambda: 2

    summary = ResultSummaryV4(primary=None, is_error=False, exit_code=0, stderr_tail="", chips=(), actions=(), artifacts=())

    with patch.object(type(panel), "app", new_callable=PropertyMock, return_value=app_mock):
        panel._maybe_activate_mini(summary)

    calls = [c[0][0] for c in panel.add_class.call_args_list if c[0]]
    assert "--minified" not in calls


def test_mini_mode_error_skipped():
    """E2: error result → no --minified."""
    from hermes_cli.tui.tool_category import ToolCategory
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    panel, app_mock = _make_panel_with_cfg(auto_mini=True)
    panel._category = ToolCategory.SHELL
    panel._body_line_count = lambda: 2

    summary = ResultSummaryV4(primary=None, is_error=True, exit_code=1, stderr_tail="", chips=(), actions=(), artifacts=())

    with patch.object(type(panel), "app", new_callable=PropertyMock, return_value=app_mock):
        panel._maybe_activate_mini(summary)

    calls = [c[0][0] for c in panel.add_class.call_args_list if c[0]]
    assert "--minified" not in calls


def test_mini_mode_too_many_lines_skipped():
    """E2: >3 lines → no --minified."""
    from hermes_cli.tui.tool_category import ToolCategory
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    panel, app_mock = _make_panel_with_cfg(auto_mini=True)
    panel._category = ToolCategory.SHELL
    panel._body_line_count = lambda: 5

    summary = ResultSummaryV4(primary=None, is_error=False, exit_code=0, stderr_tail="", chips=(), actions=(), artifacts=())

    with patch.object(type(panel), "app", new_callable=PropertyMock, return_value=app_mock):
        panel._maybe_activate_mini(summary)

    calls = [c[0][0] for c in panel.add_class.call_args_list if c[0]]
    assert "--minified" not in calls


def test_mini_mode_stderr_skipped():
    """E2: stderr present → no --minified."""
    from hermes_cli.tui.tool_category import ToolCategory
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    panel, app_mock = _make_panel_with_cfg(auto_mini=True)
    panel._category = ToolCategory.SHELL
    panel._body_line_count = lambda: 2

    summary = ResultSummaryV4(primary=None, is_error=False, exit_code=0, stderr_tail="some error", chips=(), actions=(), artifacts=())

    with patch.object(type(panel), "app", new_callable=PropertyMock, return_value=app_mock):
        panel._maybe_activate_mini(summary)

    calls = [c[0][0] for c in panel.add_class.call_args_list if c[0]]
    assert "--minified" not in calls


# ---------------------------------------------------------------------------
# E1: _post_complete_tidy sequencing
# ---------------------------------------------------------------------------


def test_post_complete_tidy_called_via_call_after_refresh():
    """E1: set_result_summary schedules _post_complete_tidy via call_after_refresh."""
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    panel, app_mock = _make_panel_with_cfg(auto_mini=False)

    # Replace call_after_refresh to capture what it's called with (without auto-executing)
    scheduled = []
    panel.call_after_refresh = lambda fn, *a, **kw: scheduled.append((fn, a))

    summary = ResultSummaryV4(primary=None, is_error=False, exit_code=0, stderr_tail="", chips=(), actions=(), artifacts=())

    with patch.object(type(panel), "app", new_callable=PropertyMock, return_value=app_mock):
        panel.set_result_summary(summary)

    # _post_complete_tidy should have been scheduled
    assert any(fn == panel._post_complete_tidy for fn, _ in scheduled), (
        "_post_complete_tidy not scheduled via call_after_refresh"
    )


def test_post_complete_tidy_error_expands():
    """E1: _post_complete_tidy with is_error=True forces collapsed=False."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    panel, app_mock = _make_panel_with_cfg(auto_mini=False)
    panel.collapsed = True

    summary = ResultSummaryV4(primary=None, is_error=True, exit_code=1, stderr_tail="", chips=(), actions=(), artifacts=())

    with patch.object(type(panel), "app", new_callable=PropertyMock, return_value=app_mock):
        panel._post_complete_tidy(summary)

    assert panel.collapsed is False


# ---------------------------------------------------------------------------
# E2: TCSS --minified rules present
# ---------------------------------------------------------------------------


def test_tcss_minified_height_1():
    """E2: hermes.tcss --minified uses height:1 (not height:0)."""
    import os
    tcss_path = os.path.realpath(os.path.join(
        os.path.dirname(__file__), "..", "..", "hermes_cli", "tui", "hermes.tcss"
    ))
    with open(tcss_path) as f:
        content = f.read()
    # Should have height: 1 (stub row) not height: 0 (invisible)
    assert "ToolPanel.--minified" in content
    # Extract block
    start = content.find("ToolPanel.--minified")
    block_end = content.find("}", start)
    block = content[start:block_end + 1]
    assert "height: 1" in block, f"Expected height:1 in --minified block; got: {block}"


def test_tcss_minified_hides_children():
    """E2: hermes.tcss hides BodyPane/FooterPane inside --minified."""
    import os
    tcss_path = os.path.realpath(os.path.join(
        os.path.dirname(__file__), "..", "..", "hermes_cli", "tui", "hermes.tcss"
    ))
    with open(tcss_path) as f:
        content = f.read()
    # Must hide body pane inside minified panel
    assert "ToolPanel.--minified BodyPane" in content or "ToolPanel.--minified .tool-body" in content, (
        "No rule hiding BodyPane inside --minified ToolPanel"
    )
