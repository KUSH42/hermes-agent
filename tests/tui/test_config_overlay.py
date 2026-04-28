"""Tests for ConfigOverlay — canonical 6-tab picker overlay (R3 Phase A)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from hermes_cli.tui.overlays import (
    ConfigOverlay,
    ModelPickerOverlay,
    ReasoningPickerOverlay,
    SkinPickerOverlay,
    TabbedSkinOverlay,
    VerbosePickerOverlay,
    YoloConfirmOverlay,
)


# ────────────────────────────────────────────────────────────────────────────
# Helpers / fixtures
# ────────────────────────────────────────────────────────────────────────────


async def _app_with_overlay():
    """Return an async context yielding (pilot, overlay)."""
    from textual.app import App, ComposeResult

    class _A(App):
        def compose(self) -> ComposeResult:
            yield ConfigOverlay(id="cfg")

    return _A()


def _fake_cfg(tool_progress="all", model="gpt-5", models=None, approvals_mode="manual",
              skin="default", show_reasoning=False, rich_reasoning=True):
    return {
        "display": {
            "tool_progress": tool_progress,
            "skin": skin,
            "show_reasoning": show_reasoning,
            "rich_reasoning": rich_reasoning,
            "skin_overrides": {"vars": {"preview-syntax-theme": "monokai"}},
        },
        "models": models or {"gpt-5": {}, "claude-opus-4-7": {}, "claude-sonnet-4-6": {}},
        "approvals": {"mode": approvals_mode},
    }


class _FakeCli:
    def __init__(self, model="gpt-5"):
        self.model = model
        self.agent = None


# ────────────────────────────────────────────────────────────────────────────
# Tab switching (T01-T07)
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_config_overlay_pre_mounted_hidden():
    app = await _app_with_overlay()
    async with app.run_test():
        ov = app.query_one(ConfigOverlay)
        assert not ov.has_class("--visible")


@pytest.mark.asyncio
async def test_show_overlay_default_tab_model():
    app = await _app_with_overlay()
    async with app.run_test():
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay()
        assert ov.has_class("--visible")
        assert ov.active_tab == "model"


@pytest.mark.asyncio
async def test_show_overlay_specific_tab():
    app = await _app_with_overlay()
    async with app.run_test():
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay(tab="verbose")
        assert ov.active_tab == "verbose"


@pytest.mark.asyncio
async def test_hotkeys_switch_tabs():
    app = await _app_with_overlay()
    async with app.run_test() as pilot:
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay()
        ov.focus()
        for hotkey, expected in [("2", "skin"), ("4", "reasoning"),
                                  ("5", "verbose"), ("6", "yolo"), ("1", "model")]:
            ov.focus()
            await pilot.press(hotkey)
            assert ov.active_tab == expected, f"after '{hotkey}'"


@pytest.mark.asyncio
async def test_tab_key_cycles_forward():
    app = await _app_with_overlay()
    async with app.run_test() as pilot:
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay(tab="model")
        ov.focus()
        await pilot.press("tab")
        assert ov.active_tab == "skin"


@pytest.mark.asyncio
async def test_shift_tab_cycles_backward():
    app = await _app_with_overlay()
    async with app.run_test() as pilot:
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay(tab="model")
        ov.focus()
        await pilot.press("shift+tab")
        assert ov.active_tab == "yolo"


@pytest.mark.asyncio
async def test_tab_cycle_wraps_around():
    app = await _app_with_overlay()
    async with app.run_test() as pilot:
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay(tab="yolo")
        ov.focus()
        await pilot.press("tab")
        assert ov.active_tab == "model"


@pytest.mark.asyncio
async def test_only_active_tab_body_visible():
    app = await _app_with_overlay()
    async with app.run_test():
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay(tab="reasoning")
        from textual.containers import Vertical
        for key in ("model", "skin", "syntax", "reasoning", "verbose", "yolo"):
            body = ov.query_one(f"#co-body-{key}", Vertical)
            if key == "reasoning":
                assert body.display
            else:
                assert not body.display, f"body {key} should be hidden"


# ────────────────────────────────────────────────────────────────────────────
# Per-tab refresh_data (T08-T14)
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_model_tab_populates_from_config():
    app = await _app_with_overlay()
    async with app.run_test():
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay(tab="model")
        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config",
                   return_value=_fake_cfg()):
            ov.refresh_data(_FakeCli())
        from textual.widgets import OptionList
        ol = ov.query_one("#co-model-list", OptionList)
        assert ol.option_count == 3


@pytest.mark.asyncio
async def test_model_tab_highlights_current():
    app = await _app_with_overlay()
    async with app.run_test():
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay(tab="model")
        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config",
                   return_value=_fake_cfg(model="claude-opus-4-7")):
            ov.refresh_data(_FakeCli(model="claude-opus-4-7"))
        from textual.widgets import Static
        cur = ov.query_one("#co-model-current", Static)
        assert "claude-opus-4-7" in str(cur.render())


@pytest.mark.asyncio
async def test_verbose_tab_has_four_options():
    app = await _app_with_overlay()
    async with app.run_test():
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay(tab="verbose")
        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config",
                   return_value=_fake_cfg()):
            ov.refresh_data(_FakeCli())
        from textual.widgets import OptionList
        ol = ov.query_one("#co-verbose-list", OptionList)
        assert ol.option_count == 4


@pytest.mark.asyncio
async def test_verbose_tab_preselects_current():
    app = await _app_with_overlay()
    async with app.run_test():
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay(tab="verbose")
        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config",
                   return_value=_fake_cfg(tool_progress="new")):
            ov.refresh_data(_FakeCli())
        from textual.widgets import OptionList
        ol = ov.query_one("#co-verbose-list", OptionList)
        assert ol.highlighted == 1  # "new" is index 1


@pytest.mark.asyncio
async def test_reasoning_tab_has_six_level_buttons():
    app = await _app_with_overlay()
    async with app.run_test():
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay(tab="reasoning")
        ov._update_reasoning_highlights()
        from textual.widgets import OptionList
        ol = ov.query_one("#co-rpo-list", OptionList)
        option_ids = [ol.get_option_at_index(i).id for i in range(ol.option_count)]
        assert ol.option_count == 6
        for level in ("none", "low", "minimal", "medium", "high", "xhigh"):
            assert f"co-rpo-opt-{level}" in option_ids, f"missing option for {level}"


@pytest.mark.asyncio
async def test_reasoning_tab_syncs_checkboxes_from_config():
    app = await _app_with_overlay()
    async with app.run_test():
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay(tab="reasoning")
        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config",
                   return_value=_fake_cfg(show_reasoning=True, rich_reasoning=False)):
            ov.refresh_data(_FakeCli())
        from textual.widgets import Checkbox
        assert ov.query_one("#co-rpo-show", Checkbox).value is True
        assert ov.query_one("#co-rpo-rich", Checkbox).value is False


@pytest.mark.asyncio
async def test_yolo_tab_inactive_shows_enable_btn():
    app = await _app_with_overlay()
    async with app.run_test():
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay(tab="yolo")
        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config",
                   return_value=_fake_cfg(approvals_mode="manual")):
            ov.refresh_data(_FakeCli())
        from textual.widgets import Button
        assert ov.query_one("#co-yolo-enable", Button).display
        assert not ov.query_one("#co-yolo-disable", Button).display


@pytest.mark.asyncio
async def test_yolo_tab_active_shows_disable_btn():
    app = await _app_with_overlay()
    async with app.run_test():
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay(tab="yolo")
        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config",
                   return_value=_fake_cfg(approvals_mode="off")):
            ov.refresh_data(_FakeCli())
        from textual.widgets import Button
        assert not ov.query_one("#co-yolo-enable", Button).display
        assert ov.query_one("#co-yolo-disable", Button).display


# ────────────────────────────────────────────────────────────────────────────
# Alias behaviour (T15-T22)  — §5 of spec
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alias_query_one_returns_canonical():
    app = await _app_with_overlay()
    async with app.run_test():
        cfg = app.query_one(ConfigOverlay)
        for alias in (ModelPickerOverlay, VerbosePickerOverlay, SkinPickerOverlay,
                      ReasoningPickerOverlay, YoloConfirmOverlay):
            got = app.query_one(alias)
            assert got is cfg, f"{alias.__name__} alias mismatch"


@pytest.mark.asyncio
async def test_alias_tabbed_skin_is_skin_alias():
    assert TabbedSkinOverlay is SkinPickerOverlay


@pytest.mark.asyncio
async def test_isinstance_true_in_matching_mode():
    app = await _app_with_overlay()
    async with app.run_test():
        cfg = app.query_one(ConfigOverlay)
        cfg.active_tab = "verbose"
        assert isinstance(cfg, VerbosePickerOverlay)
        cfg.active_tab = "yolo"
        assert isinstance(cfg, YoloConfirmOverlay)
        cfg.active_tab = "skin"
        assert isinstance(cfg, SkinPickerOverlay)
        assert isinstance(cfg, TabbedSkinOverlay)


@pytest.mark.asyncio
async def test_isinstance_false_in_wrong_mode():
    app = await _app_with_overlay()
    async with app.run_test():
        cfg = app.query_one(ConfigOverlay)
        cfg.active_tab = "model"
        assert not isinstance(cfg, VerbosePickerOverlay)
        assert not isinstance(cfg, YoloConfirmOverlay)
        assert not isinstance(cfg, ReasoningPickerOverlay)


def test_aliases_are_not_subclasses_of_canonical():
    """Per §5.3 — aliases subclass Widget directly, not ConfigOverlay."""
    for alias in (ModelPickerOverlay, VerbosePickerOverlay, SkinPickerOverlay,
                  ReasoningPickerOverlay, YoloConfirmOverlay):
        assert not issubclass(alias, ConfigOverlay), (
            f"{alias.__name__} must not subclass ConfigOverlay — breaks mount target invariant"
        )


def test_alias_names_registered_in_css_types():
    for name in ("ModelPickerOverlay", "VerbosePickerOverlay", "SkinPickerOverlay",
                 "TabbedSkinOverlay", "ReasoningPickerOverlay", "YoloConfirmOverlay"):
        assert name in ConfigOverlay._css_type_names, f"missing {name}"


# ────────────────────────────────────────────────────────────────────────────
# Tab state preservation (T23-T24)
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tab_state_refreshed_across_switch():
    """CO-H2: switching back to model tab refreshes the list (highlight → current model)."""
    app = await _app_with_overlay()
    async with app.run_test() as pilot:
        ov = app.query_one(ConfigOverlay)
        fake = _fake_cfg()
        cli = _FakeCli()  # model = "gpt-5", index 0 in the list
        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config",
                   return_value=fake):
            ov.show_overlay(tab="model")
            ov.refresh_data(cli)
        from textual.widgets import OptionList
        ol = ov.query_one("#co-model-list", OptionList)
        # Switch away and back — tab-switch now triggers refresh
        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config",
                   return_value=fake):
            await pilot.press("5")  # verbose
            assert ov.active_tab == "verbose"
            await pilot.press("1")  # back to model
            assert ov.active_tab == "model"
        # highlight refreshed to current model's position (gpt-5 is index 0)
        assert ol.highlighted == 0, "highlight refreshed to current model after tab switch"


# ────────────────────────────────────────────────────────────────────────────
# Escape dispatch (T25)
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_escape_dismisses_via_action():
    app = await _app_with_overlay()
    async with app.run_test():
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay()
        assert ov.has_class("--visible")
        ov.action_dismiss()
        assert not ov.has_class("--visible")


# ────────────────────────────────────────────────────────────────────────────
# End-to-end confirm (T26-T29)
# ────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verbose_confirm_writes_config():
    app = await _app_with_overlay()
    async with app.run_test():
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay(tab="verbose")
        saved = {}

        def _save(cfg):
            saved.update(cfg)

        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config",
                   return_value=_fake_cfg()), \
             patch("hermes_cli.tui.overlays.config._cfg_save_config", side_effect=_save):
            ov.refresh_data(_FakeCli())
            ov._confirm_verbose("off")
        assert saved["display"]["tool_progress"] == "off"


@pytest.mark.asyncio
async def test_yolo_enable_persists_off_mode():
    app = await _app_with_overlay()
    async with app.run_test():
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay(tab="yolo")
        saved = {}
        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config",
                   return_value=_fake_cfg(approvals_mode="manual")), \
             patch("hermes_cli.tui.overlays.config._cfg_save_config",
                   side_effect=lambda c: saved.update(c)):
            ov.refresh_data(_FakeCli())
            ov._set_yolo(True)
        assert saved["approvals"]["mode"] == "off"


@pytest.mark.asyncio
async def test_yolo_disable_restores_previous_mode():
    app = await _app_with_overlay()
    async with app.run_test():
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay(tab="yolo")
        saved = {}
        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config",
                   return_value=_fake_cfg(approvals_mode="manual")), \
             patch("hermes_cli.tui.overlays.config._cfg_save_config",
                   side_effect=lambda c: saved.update(c)):
            ov.refresh_data(_FakeCli())
            assert ov._yolo_previous_mode == "manual"
        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config",
                   return_value=_fake_cfg(approvals_mode="off")), \
             patch("hermes_cli.tui.overlays.config._cfg_save_config",
                   side_effect=lambda c: saved.update(c)):
            ov._set_yolo(False)
        assert saved["approvals"]["mode"] == "manual"


@pytest.mark.asyncio
async def test_reasoning_checkbox_persists_config():
    app = await _app_with_overlay()
    async with app.run_test():
        ov = app.query_one(ConfigOverlay)
        ov.show_overlay(tab="reasoning")
        saved = {}
        from textual.widgets import Checkbox
        cb = ov.query_one("#co-rpo-show", Checkbox)
        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config",
                   return_value=_fake_cfg()), \
             patch("hermes_cli.tui.overlays.config._cfg_save_config",
                   side_effect=lambda c: saved.update(c)):
            cb.value = True
            # Textual does not auto-dispatch synchronously; call handler directly
            from textual.widgets import Checkbox as _CB
            ov.on_checkbox_changed(_CB.Changed(cb, True))
        assert saved["display"]["show_reasoning"] is True


# ────────────────────────────────────────────────────────────────────────────
# Import sanity (T30)
# ────────────────────────────────────────────────────────────────────────────


def test_all_alias_names_importable():
    from hermes_cli.tui import overlays
    for name in ("ConfigOverlay", "ModelPickerOverlay", "VerbosePickerOverlay",
                 "SkinPickerOverlay", "TabbedSkinOverlay", "ReasoningPickerOverlay",
                 "YoloConfirmOverlay"):
        assert hasattr(overlays, name), f"missing {name}"
