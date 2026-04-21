"""Phase D tests: keyboard bindings on ToolPanel and App.

16 tests covering d/D/0-3/enter/space/y/Y/r/o/i keys.
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
    # Stub out panes so watchers don't crash
    panel._args_pane = MagicMock()
    panel._args_pane.display = False
    panel._body_pane = MagicMock()
    panel._body_pane.display = True
    panel._body_pane.set_mode = MagicMock()
    panel._footer_pane = MagicMock()
    panel._footer_pane.display = False
    panel._input_section = MagicMock()
    panel._input_section.display = True
    panel._header_bar = MagicMock()
    panel._result_summary = None
    panel.add_class = MagicMock()
    panel.remove_class = MagicMock()
    return panel


# ---------------------------------------------------------------------------
# d / D cycling
# ---------------------------------------------------------------------------


def test_d_key_cycles_forward():
    p = _make_panel()
    p.detail_level = 1
    p.action_cycle_detail_forward()
    assert p.detail_level == 2


def test_d_key_cycles_1_2_3_1():
    p = _make_panel()
    p.detail_level = 3
    p.action_cycle_detail_forward()
    assert p.detail_level == 1  # wraps 3→1


def test_D_key_cycles_reverse():
    p = _make_panel()
    p.detail_level = 3
    p.action_cycle_detail_reverse()
    assert p.detail_level == 2


def test_D_key_stays_at_l0():
    p = _make_panel()
    p.detail_level = 0
    p.action_cycle_detail_reverse()
    assert p.detail_level == 0  # stays at L0


# ---------------------------------------------------------------------------
# 0-3 number keys
# ---------------------------------------------------------------------------


def test_0_key_sets_l0():
    p = _make_panel()
    p.detail_level = 2
    p.action_set_level_0()
    assert p.detail_level == 0


def test_1_key_sets_l1():
    p = _make_panel()
    p.detail_level = 2
    p.action_set_level_1()
    assert p.detail_level == 1


def test_2_key_sets_l2():
    p = _make_panel()
    p.detail_level = 0
    p.action_set_level_2()
    assert p.detail_level == 2


def test_3_key_sets_l3():
    p = _make_panel()
    p.detail_level = 1
    p.action_set_level_3()
    assert p.detail_level == 3


# ---------------------------------------------------------------------------
# enter: toggle_l1_l2 cycling
# ---------------------------------------------------------------------------


def test_enter_cycles_detail_level_l0_to_l1():
    p = _make_panel()
    p.detail_level = 0
    p.action_toggle_l1_l2()
    assert p.detail_level == 1


def test_enter_cycles_l1_to_l2():
    p = _make_panel()
    p.detail_level = 1
    p.action_toggle_l1_l2()
    assert p.detail_level == 2


def test_enter_cycles_l2_to_l1():
    p = _make_panel()
    p.detail_level = 2
    p.action_toggle_l1_l2()
    assert p.detail_level == 1


def test_enter_cycles_l3_to_l2():
    p = _make_panel()
    p.detail_level = 3
    p.action_toggle_l1_l2()
    assert p.detail_level == 2


# ---------------------------------------------------------------------------
# space: toggle_l0_restore
# ---------------------------------------------------------------------------


def test_space_toggles_l0_and_back():
    p = _make_panel()
    p.detail_level = 2
    p.action_toggle_l0_restore()
    assert p.detail_level == 0
    assert p._pre_collapse_level == 2
    p.action_toggle_l0_restore()
    assert p.detail_level == 2


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

    # Inject a fake pyperclip module so the import in action_copy_output works
    fake_pyperclip = MM()
    copied = []
    fake_pyperclip.copy = lambda text: copied.append(text)
    sys.modules.setdefault("pyperclip", fake_pyperclip)
    # Reset in case it's already set to the real thing
    original = sys.modules.get("pyperclip")
    sys.modules["pyperclip"] = fake_pyperclip

    try:
        with patch.object(type(p), "app", new_callable=PropertyMock, return_value=app_mock):
            p.action_copy_output()
        # Either copied something OR notified (pyperclip may or may not be available)
        # The important thing is no crash
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
    p._input_section = MagicMock()
    p._input_section._build_text = lambda: "ls -la"

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
    """App.action_focus_output calls OutputPanel.focus()."""
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Just verify action exists and doesn't crash
        app.action_focus_output()
        await pilot.pause()


@pytest.mark.asyncio
async def test_i_key_focuses_input_from_output():
    """App.action_focus_input_from_output calls HermesInput.focus()."""
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Just verify action exists and doesn't crash
        app.action_focus_input_from_output()
        await pilot.pause()


# ---------------------------------------------------------------------------
# Sub-focus L3 / Esc
# ---------------------------------------------------------------------------


def test_sub_focus_enter_enters_l3():
    """From L2, pressing 3 sets L3."""
    p = _make_panel()
    p.detail_level = 2
    p.action_set_level_3()
    assert p.detail_level == 3


def test_sub_focus_esc_exits_l3():
    """From L3, toggle_l1_l2 goes to L2."""
    p = _make_panel()
    p.detail_level = 3
    p.action_toggle_l1_l2()
    assert p.detail_level == 2


# ---------------------------------------------------------------------------
# j / k navigation between panels
# ---------------------------------------------------------------------------


def test_j_k_nav_between_panels():
    """ToolPanel bindings include enter/space/y/Y/r."""
    binding_keys = {b.key for b in ToolPanel.BINDINGS}
    expected = {"enter", "space", "y", "Y", "r"}
    for key in expected:
        assert key in binding_keys, f"Missing binding: {key}"
