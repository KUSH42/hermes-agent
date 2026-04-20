"""Tests for config picker overlays: /verbose, /yolo, /reasoning, /model, /skin.

All 5 overlays follow the same --visible class pattern as existing info overlays.
Tests use the full HermesApp harness with a MagicMock CLI, matching test_workspace_overlay.py.
Config writes are mocked to avoid touching ~/.hermes/config.yaml.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.overlays import (
    ModelPickerOverlay,
    ReasoningPickerOverlay,
    SkinPickerOverlay,
    VerbosePickerOverlay,
    YoloConfirmOverlay,
)
from textual.widgets import Button, Checkbox, OptionList, Static


def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.agent = MagicMock()
    cli.agent.model = "claude-sonnet-4-6"
    return HermesApp(cli=cli)


async def _submit(pilot, app, cmd: str) -> None:
    from hermes_cli.tui.input_widget import HermesInput

    inp = app.query_one(HermesInput)
    inp.value = cmd
    inp.action_submit()
    await pilot.pause()


# ---------------------------------------------------------------------------
# Phase 5: VerbosePickerOverlay (/verbose)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verbose_picker_hidden_by_default():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert not app.query_one(VerbosePickerOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_verbose_picker_opens_on_slash_verbose():
    app = _make_app()
    mock_cfg = {"display": {"tool_progress": "all"}}
    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            await _submit(pilot, app, "/verbose")
            await pilot.pause()
            assert app.query_one(VerbosePickerOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_verbose_all_four_options_rendered():
    app = _make_app()
    mock_cfg = {"display": {"tool_progress": "all"}}
    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(VerbosePickerOverlay)
            overlay.refresh_data(app.cli)
            overlay.add_class("--visible")
            await pilot.pause()
            ol = overlay.query_one("#vpo-list", OptionList)
            assert ol.option_count == 4


@pytest.mark.asyncio
async def test_verbose_picker_preselects_current_mode():
    app = _make_app()
    mock_cfg = {"display": {"tool_progress": "new"}}
    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(VerbosePickerOverlay)
            overlay.refresh_data(app.cli)
            await pilot.pause()
            ol = overlay.query_one("#vpo-list", OptionList)
            # "new" is index 1 in [off, new, all, verbose]
            assert ol.highlighted == 1


@pytest.mark.asyncio
async def test_verbose_picker_enter_applies_and_dismisses():
    app = _make_app()
    mock_cfg = {"display": {"tool_progress": "all"}}
    saved = {}

    def _fake_save(cfg):
        saved.update(cfg)

    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg), \
         patch("hermes_cli.tui.overlays._cfg_save_config", side_effect=_fake_save):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(VerbosePickerOverlay)
            overlay.refresh_data(app.cli)
            overlay.add_class("--visible")
            await pilot.pause()
            # Simulate selection of "verbose" (index 3)
            overlay._apply_and_dismiss("verbose")
            await pilot.pause()
            assert not overlay.has_class("--visible")
            assert saved.get("display", {}).get("tool_progress") == "verbose"


@pytest.mark.asyncio
async def test_verbose_picker_escape_no_change():
    app = _make_app()
    mock_cfg = {"display": {"tool_progress": "all"}}
    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg), \
         patch("hermes_cli.tui.overlays._cfg_save_config") as mock_save:
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(VerbosePickerOverlay)
            overlay.add_class("--visible")
            await pilot.pause()
            overlay.action_dismiss()
            await pilot.pause()
            assert not overlay.has_class("--visible")
            mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 4: YoloConfirmOverlay (/yolo)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_yolo_overlay_hidden_by_default():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert not app.query_one(YoloConfirmOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_yolo_overlay_opens_on_slash_yolo():
    app = _make_app()
    mock_cfg = {"approvals": {"mode": "manual"}}
    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            await _submit(pilot, app, "/yolo")
            await pilot.pause()
            assert app.query_one(YoloConfirmOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_yolo_overlay_shows_inactive_state():
    app = _make_app()
    mock_cfg = {"approvals": {"mode": "manual"}}
    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(YoloConfirmOverlay)
            overlay.refresh_data(app.cli)
            await pilot.pause()
            state_text = overlay.query_one("#yco-state", Static).content
            assert "inactive" in str(state_text)


@pytest.mark.asyncio
async def test_yolo_overlay_shows_active_state():
    app = _make_app()
    mock_cfg = {"approvals": {"mode": "off"}}
    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(YoloConfirmOverlay)
            overlay.refresh_data(app.cli)
            await pilot.pause()
            state_text = overlay.query_one("#yco-state", Static).content
            assert "ACTIVE" in str(state_text)


@pytest.mark.asyncio
async def test_yolo_enable_sets_approvals_off(monkeypatch):
    monkeypatch.setenv("HERMES_YOLO_MODE", "")
    app = _make_app()
    mock_cfg = {"approvals": {"mode": "manual"}}
    saved = {}

    def _fake_save(cfg):
        saved.update(cfg)

    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg), \
         patch("hermes_cli.tui.overlays._cfg_save_config", side_effect=_fake_save):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(YoloConfirmOverlay)
            overlay.refresh_data(app.cli)
            overlay.add_class("--visible")
            await pilot.pause()
            overlay._set_yolo(True)
            await pilot.pause()
            assert not overlay.has_class("--visible")
            assert saved.get("approvals", {}).get("mode") == "off"
            assert os.environ.get("HERMES_YOLO_MODE") == "1"
            assert app.yolo_mode is True


@pytest.mark.asyncio
async def test_yolo_disable_restores_previous_mode(monkeypatch):
    monkeypatch.setenv("HERMES_YOLO_MODE", "1")
    app = _make_app()
    mock_cfg = {"approvals": {"mode": "off"}}
    saved = {}

    def _fake_save(cfg):
        saved.update(cfg)

    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg), \
         patch("hermes_cli.tui.overlays._cfg_save_config", side_effect=_fake_save):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(YoloConfirmOverlay)
            overlay._previous_mode = "smart"
            overlay.refresh_data(app.cli)
            overlay.add_class("--visible")
            await pilot.pause()
            overlay._set_yolo(False)
            await pilot.pause()
            assert not overlay.has_class("--visible")
            assert saved.get("approvals", {}).get("mode") == "smart"
            assert os.environ.get("HERMES_YOLO_MODE") == ""
            assert app.yolo_mode is False


@pytest.mark.asyncio
async def test_yolo_cancel_no_change():
    app = _make_app()
    mock_cfg = {"approvals": {"mode": "manual"}}
    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg), \
         patch("hermes_cli.tui.overlays._cfg_save_config") as mock_save:
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(YoloConfirmOverlay)
            overlay.refresh_data(app.cli)
            overlay.add_class("--visible")
            await pilot.pause()
            # Simulate cancel button press
            cancel_btn = overlay.query_one("#yco-cancel", Button)
            await pilot.click(cancel_btn)
            await pilot.pause()
            assert not overlay.has_class("--visible")
            mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_yolo_escape_no_change():
    app = _make_app()
    mock_cfg = {"approvals": {"mode": "manual"}}
    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg), \
         patch("hermes_cli.tui.overlays._cfg_save_config") as mock_save:
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(YoloConfirmOverlay)
            overlay.add_class("--visible")
            await pilot.pause()
            overlay.action_dismiss()
            await pilot.pause()
            assert not overlay.has_class("--visible")
            mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# Phase 2: ReasoningPickerOverlay (/reasoning)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reasoning_picker_hidden_by_default():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert not app.query_one(ReasoningPickerOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_reasoning_picker_opens_on_bare_slash_reasoning():
    app = _make_app()
    mock_cfg = {"display": {"show_reasoning": False, "rich_reasoning": True}}
    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            await _submit(pilot, app, "/reasoning")
            await pilot.pause()
            assert app.query_one(ReasoningPickerOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_reasoning_level_buttons_rendered():
    app = _make_app()
    mock_cfg = {"display": {"show_reasoning": False, "rich_reasoning": True}}
    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(ReasoningPickerOverlay)
            buttons = [
                b for b in overlay.query(Button)
                if (b.id or "").startswith("rpo-btn-")
            ]
            labels = [str(b.label) for b in buttons]
            for lvl in ("none", "low", "minimal", "medium", "high", "xhigh"):
                assert lvl in labels


@pytest.mark.asyncio
async def test_reasoning_level_click_sends_command():
    app = _make_app()
    mock_cfg = {"display": {"show_reasoning": False, "rich_reasoning": True}}
    injected: list[str] = []

    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(ReasoningPickerOverlay)
            overlay.refresh_data(app.cli)
            overlay.add_class("--visible")
            await pilot.pause()

            # Capture what gets injected into the input
            from hermes_cli.tui.input_widget import HermesInput
            inp = app.query_one(HermesInput)
            original_submit = inp.action_submit

            def _capture_submit():
                injected.append(inp.value)
                # Don't actually forward to CLI in test
                inp.value = ""

            inp.action_submit = _capture_submit
            overlay._inject_level_command("high")
            await pilot.pause()

    assert any("high" in cmd for cmd in injected)
    assert not overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_reasoning_show_checkbox_toggles_config():
    app = _make_app()
    mock_cfg = {"display": {"show_reasoning": False, "rich_reasoning": True}}
    saved = {}

    def _fake_save(cfg):
        saved.update(cfg)

    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg), \
         patch("hermes_cli.tui.overlays._cfg_save_config", side_effect=_fake_save):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(ReasoningPickerOverlay)
            overlay.refresh_data(app.cli)
            overlay.add_class("--visible")
            await pilot.pause()
            # Toggle show_reasoning to True
            cb = overlay.query_one("#rpo-show", Checkbox)
            cb.value = True
            await pilot.pause()

    assert saved.get("display", {}).get("show_reasoning") is True


@pytest.mark.asyncio
async def test_reasoning_rich_checkbox_toggles_config():
    app = _make_app()
    mock_cfg = {"display": {"show_reasoning": False, "rich_reasoning": True}}
    saved = {}

    def _fake_save(cfg):
        saved.update(cfg)

    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg), \
         patch("hermes_cli.tui.overlays._cfg_save_config", side_effect=_fake_save):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(ReasoningPickerOverlay)
            overlay.refresh_data(app.cli)
            overlay.add_class("--visible")
            await pilot.pause()
            # Toggle rich_reasoning to False
            cb = overlay.query_one("#rpo-rich", Checkbox)
            cb.value = False
            await pilot.pause()

    assert saved.get("display", {}).get("rich_reasoning") is False


@pytest.mark.asyncio
async def test_reasoning_with_level_arg_bypasses_picker():
    """'/reasoning high' should NOT open the picker (return False → falls to CLI)."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        # /reasoning high has args → _handle_tui_command returns False (doesn't open overlay)
        result = app._handle_tui_command("/reasoning high")
        await pilot.pause()
        assert result is False
        assert not app.query_one(ReasoningPickerOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_reasoning_show_hide_args_bypass_picker():
    """'/reasoning show' and '/reasoning hide' fall through to CLI."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        result_show = app._handle_tui_command("/reasoning show")
        result_hide = app._handle_tui_command("/reasoning hide")
        await pilot.pause()
        assert result_show is False
        assert result_hide is False


# ---------------------------------------------------------------------------
# Phase 1: ModelPickerOverlay (/model)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_picker_hidden_by_default():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert not app.query_one(ModelPickerOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_model_picker_opens_on_bare_slash_model():
    app = _make_app()
    mock_cfg = {"models": {"claude-sonnet-4-6": {}, "claude-opus-4": {}}}
    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            await _submit(pilot, app, "/model")
            await pilot.pause()
            assert app.query_one(ModelPickerOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_model_picker_preselects_current_model():
    app = _make_app()
    mock_cfg = {"models": {"claude-sonnet-4-6": {}, "claude-opus-4": {}}}
    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(ModelPickerOverlay)
            overlay.refresh_data(app.cli)
            await pilot.pause()
            ol = overlay.query_one("#mpo-list", OptionList)
            # claude-sonnet-4-6 is index 0 (first in models dict)
            assert ol.highlighted == 0


@pytest.mark.asyncio
async def test_model_picker_enter_applies_and_dismisses():
    app = _make_app()
    mock_cfg = {"models": {"claude-sonnet-4-6": {}, "claude-opus-4": {}}}
    injected: list[str] = []

    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(ModelPickerOverlay)
            overlay.refresh_data(app.cli)
            overlay.add_class("--visible")
            await pilot.pause()

            from hermes_cli.tui.input_widget import HermesInput
            inp = app.query_one(HermesInput)

            def _capture_submit():
                injected.append(inp.value)
                inp.value = ""

            inp.action_submit = _capture_submit
            overlay._select_model("claude-opus-4")
            await pilot.pause()

    assert any("claude-opus-4" in cmd for cmd in injected)
    assert not overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_model_picker_escape_dismisses_no_change():
    app = _make_app()
    mock_cfg = {"models": {"claude-sonnet-4-6": {}}}
    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(ModelPickerOverlay)
            overlay.add_class("--visible")
            await pilot.pause()
            overlay.action_dismiss()
            await pilot.pause()
            assert not overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_model_with_args_bypasses_picker():
    """'/model claude-opus-4' has args → return False, picker stays hidden."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        result = app._handle_tui_command("/model claude-opus-4")
        await pilot.pause()
        assert result is False
        assert not app.query_one(ModelPickerOverlay).has_class("--visible")


# ---------------------------------------------------------------------------
# Phase 3: SkinPickerOverlay (/skin)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skin_picker_hidden_by_default():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert not app.query_one(SkinPickerOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_skin_picker_opens_on_bare_slash_skin():
    app = _make_app()
    mock_cfg = {"display": {"skin": "default"}}
    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg), \
         patch("hermes_cli.config.get_hermes_home", return_value=Path("/tmp/fake-hermes")):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            await _submit(pilot, app, "/skin")
            await pilot.pause()
            assert app.query_one(SkinPickerOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_skin_picker_preselects_current_skin(tmp_path):
    app = _make_app()
    skins_dir = tmp_path / "skins"
    skins_dir.mkdir()
    (skins_dir / "cyberpunk.yaml").write_text("fg: '#00ff00'\n")
    (skins_dir / "matrix.yaml").write_text("fg: '#00ff00'\n")
    mock_cfg = {"display": {"skin": "matrix"}}

    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg), \
         patch("hermes_cli.tui.overlays._cfg_get_hermes_home", return_value=tmp_path):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(SkinPickerOverlay)
            overlay.refresh_data(app.cli)
            await pilot.pause()
            ol = overlay.query_one("#spo-list", OptionList)
            # names = ["default", "cyberpunk", "matrix"] after sort+prepend
            # "matrix" is at index 2
            highlighted_name = overlay._skins[ol.highlighted]
            assert highlighted_name == "matrix"


@pytest.mark.asyncio
async def test_skin_picker_arrow_applies_live_preview(tmp_path):
    app = _make_app()
    skins_dir = tmp_path / "skins"
    skins_dir.mkdir()
    (skins_dir / "cyberpunk.yaml").write_text("fg: '#00ff00'\n")
    mock_cfg = {"display": {"skin": "default"}}
    applied: list[object] = []

    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg), \
         patch("hermes_cli.tui.overlays._cfg_get_hermes_home", return_value=tmp_path), \
         patch.object(app, "apply_skin", side_effect=lambda v: applied.append(v)):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(SkinPickerOverlay)
            overlay.refresh_data(app.cli)
            overlay.add_class("--visible")
            await pilot.pause()
            overlay._apply_skin_preview("cyberpunk")
            await pilot.pause()

    assert len(applied) >= 1


@pytest.mark.asyncio
async def test_skin_picker_escape_reverts_skin(tmp_path):
    app = _make_app()
    skins_dir = tmp_path / "skins"
    skins_dir.mkdir()
    (skins_dir / "cyberpunk.yaml").write_text("fg: '#00ff00'\n")
    mock_cfg = {"display": {"skin": "default"}}
    reverted: list[object] = []

    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg), \
         patch("hermes_cli.tui.overlays._cfg_get_hermes_home", return_value=tmp_path):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(SkinPickerOverlay)
            overlay.refresh_data(app.cli)
            overlay.add_class("--visible")
            await pilot.pause()
            # Navigate away to trigger preview
            overlay._apply_skin_preview("cyberpunk")
            await pilot.pause()
            # Now escape — should revert
            with patch.object(app, "apply_skin", side_effect=lambda v: reverted.append(v)):
                overlay.action_dismiss()
                await pilot.pause()

    # Escape triggers revert (apply_skin called with original vars dict)
    assert len(reverted) >= 1
    assert not overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_skin_picker_enter_persists_skin(tmp_path):
    app = _make_app()
    skins_dir = tmp_path / "skins"
    skins_dir.mkdir()
    (skins_dir / "matrix.yaml").write_text("fg: '#00ff00'\n")
    mock_cfg = {"display": {"skin": "default"}}
    saved = {}

    def _fake_save(cfg):
        saved.update(cfg)

    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg), \
         patch("hermes_cli.tui.overlays._cfg_save_config", side_effect=_fake_save), \
         patch("hermes_cli.tui.overlays._cfg_get_hermes_home", return_value=tmp_path):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            overlay = app.query_one(SkinPickerOverlay)
            overlay.refresh_data(app.cli)
            overlay.add_class("--visible")
            await pilot.pause()
            overlay._confirm_skin("matrix")
            await pilot.pause()

    assert saved.get("display", {}).get("skin") == "matrix"
    assert not overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_skin_with_name_arg_bypasses_picker():
    """'/skin cyberpunk' has args → return False, picker stays hidden."""
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        result = app._handle_tui_command("/skin cyberpunk")
        await pilot.pause()
        assert result is False
        assert not app.query_one(SkinPickerOverlay).has_class("--visible")


# ---------------------------------------------------------------------------
# _dismiss_all_info_overlays covers all 5 new overlays
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dismiss_all_hides_all_config_pickers():
    app = _make_app()
    mock_cfg = {
        "display": {"tool_progress": "all", "show_reasoning": False, "rich_reasoning": True, "skin": "default"},
        "approvals": {"mode": "manual"},
        "models": {},
    }
    with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=mock_cfg), \
         patch("hermes_cli.tui.overlays._cfg_get_hermes_home", return_value=Path("/tmp/fake-hermes")):
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            # Show all 5
            for cls in (VerbosePickerOverlay, YoloConfirmOverlay, ReasoningPickerOverlay,
                        ModelPickerOverlay, SkinPickerOverlay):
                app.query_one(cls).add_class("--visible")
            await pilot.pause()
            app._dismiss_all_info_overlays()
            await pilot.pause()
            for cls in (VerbosePickerOverlay, YoloConfirmOverlay, ReasoningPickerOverlay,
                        ModelPickerOverlay, SkinPickerOverlay):
                assert not app.query_one(cls).has_class("--visible")
