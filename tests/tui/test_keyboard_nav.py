"""C1/C2: keyboard bindings on ToolPanel after detail_level retirement.

After Pass 10 Phase 3:
- detail_level is a property (0↔collapsed=True, 1/2/3↔collapsed=False)
- action_toggle_l0_restore and Space binding removed
- Enter toggles collapsed bool
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from hermes_cli.tui.tool_panel import ToolPanel
from hermes_cli.tui.tool_payload import ResultKind


def _make_panel(tool_name: str = "bash") -> ToolPanel:
    block_mock = MagicMock()
    block_mock._total_received = 0
    block_mock._all_plain = []
    panel = ToolPanel(block=block_mock, tool_name=tool_name)
    panel._body_pane = MagicMock()
    panel._body_pane.display = True
    panel._footer_pane = MagicMock()
    panel._footer_pane.display = False
    panel.add_class = MagicMock()
    panel.remove_class = MagicMock()
    return panel


# ---------------------------------------------------------------------------
# C1: Enter toggle
# ---------------------------------------------------------------------------


def test_enter_toggles_collapsed_false_to_true():
    """Enter toggles collapsed from False → True."""
    p = _make_panel()
    p.collapsed = False
    p.action_toggle_collapse()
    assert p.collapsed is True


def test_enter_toggles_collapsed_true_to_false():
    """Enter toggles collapsed from True → False."""
    p = _make_panel()
    p.collapsed = True
    p.action_toggle_collapse()
    assert p.collapsed is False


def test_enter_clears_auto_collapsed():
    """C1: Enter toggle sets _auto_collapsed=False."""
    p = _make_panel()
    p._auto_collapsed = True
    p.collapsed = True
    p.action_toggle_collapse()
    assert p._auto_collapsed is False


# ---------------------------------------------------------------------------
# C1: detail_level property (binary compat)
# ---------------------------------------------------------------------------


def test_detail_level_0_maps_to_collapsed():
    p = _make_panel()
    p.detail_level = 0
    assert p.collapsed is True
    assert p.detail_level == 0


def test_detail_level_1_maps_to_expanded():
    p = _make_panel()
    p.detail_level = 1
    assert p.collapsed is False
    assert p.detail_level == 2  # property always returns 2 when not collapsed


def test_detail_level_2_stays_expanded():
    p = _make_panel()
    p.detail_level = 2
    assert p.collapsed is False


def test_detail_level_3_stays_expanded():
    p = _make_panel()
    p.detail_level = 3
    assert p.collapsed is False


# ---------------------------------------------------------------------------
# C2: Space no longer bound
# ---------------------------------------------------------------------------


def test_space_not_in_bindings():
    """C2: space removed from ToolPanel.BINDINGS."""
    space_bindings = [b for b in ToolPanel.BINDINGS if b.key == "space"]
    assert len(space_bindings) == 0


def test_toggle_l0_restore_not_present():
    """C2: action_toggle_l0_restore deleted."""
    p = _make_panel()
    assert not hasattr(p, "action_toggle_l0_restore")


# ---------------------------------------------------------------------------
# y / Y keys
# ---------------------------------------------------------------------------


def test_y_key_copies_output():
    """action_copy_output calls pyperclip and notifies."""
    import sys
    from unittest.mock import PropertyMock, MagicMock as MM

    p = _make_panel()
    p._block = MagicMock()
    p._block._all_plain = ["output line"]

    notified = []
    app_mock = MM()
    app_mock.notify = lambda *a, **kw: notified.append(a)

    fake_pyperclip = MM()
    copied = []
    fake_pyperclip.copy = lambda text: copied.append(text)
    original = sys.modules.get("pyperclip")
    sys.modules["pyperclip"] = fake_pyperclip

    try:
        with patch.object(type(p), "app", new_callable=PropertyMock, return_value=app_mock):
            p.action_copy_output()
    finally:
        if original is None:
            sys.modules.pop("pyperclip", None)
        else:
            sys.modules["pyperclip"] = original


def test_Y_key_copies_input():
    """action_copy_input calls pyperclip with input text."""
    import sys
    from unittest.mock import PropertyMock, MagicMock as MM

    p = _make_panel()
    p._tool_args = {"command": "ls -la"}

    notified = []
    app_mock = MM()
    app_mock.notify = lambda *a, **kw: notified.append(a)

    fake_pyperclip = MM()
    copied = []
    fake_pyperclip.copy = lambda text: copied.append(text)
    original = sys.modules.get("pyperclip")
    sys.modules["pyperclip"] = fake_pyperclip

    try:
        with patch.object(type(p), "app", new_callable=PropertyMock, return_value=app_mock):
            p.action_copy_input()
        assert "ls -la" in copied
    finally:
        if original is None:
            sys.modules.pop("pyperclip", None)
        else:
            sys.modules["pyperclip"] = original


# ---------------------------------------------------------------------------
# r key
# ---------------------------------------------------------------------------


def test_r_key_emits_rerun_message():
    """action_rerun posts ToolRerunRequested."""
    p = _make_panel()

    posted = []
    p.post_message = lambda msg: posted.append(msg)

    p.action_rerun()

    assert len(posted) == 1
    from hermes_cli.tui.messages import ToolRerunRequested
    assert isinstance(posted[0], ToolRerunRequested)
    assert posted[0].panel is p


# ---------------------------------------------------------------------------
# o / i keys: App-level focus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_o_key_focuses_output_panel():
    """App.action_focus_output doesn't crash."""
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.action_focus_output()
        await pilot.pause()


@pytest.mark.asyncio
async def test_i_key_focuses_input_from_output():
    """App.action_focus_input_from_output doesn't crash."""
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.action_focus_input_from_output()
        await pilot.pause()


# ---------------------------------------------------------------------------
# Binding presence check
# ---------------------------------------------------------------------------


def test_enter_in_bindings():
    """ToolPanel bindings include enter."""
    binding_keys = {b.key for b in ToolPanel.BINDINGS}
    assert "enter" in binding_keys


def test_c_copy_in_bindings():
    """ToolPanel bindings include c for copy."""
    binding_keys = {b.key for b in ToolPanel.BINDINGS}
    assert "c" in binding_keys
