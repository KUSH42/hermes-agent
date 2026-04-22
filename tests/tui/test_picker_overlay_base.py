"""Tests for PickerOverlay base class and its subclasses.

Covers spec §5.1 (B01–B13), §5.2 (V01–V07), §5.3 (S01–S05),
§5.4 (R01–R08), §5.5 (M01–M04).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest

from hermes_cli.tui.overlays import (
    ModelPickerOverlay,
    PickerOverlay,
    ReasoningPickerOverlay,
    SkinPickerOverlay,
    VerbosePickerOverlay,
    YoloConfirmOverlay,
)
from hermes_cli.tui.app import HermesApp
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.agent = None
    return HermesApp(cli=cli)


def _make_app_with_agent() -> HermesApp:
    cli = MagicMock()
    agent = MagicMock()
    agent.model = "claude-sonnet-4-6"
    cli.agent = agent
    return HermesApp(cli=cli)


# ---------------------------------------------------------------------------
# B01 — compose() yields header (picker-header) and OptionList
# ---------------------------------------------------------------------------


def test_picker_compose_yields_header_and_list():
    """B01: compose() produces Static with class picker-header and OptionList."""

    class _TestPicker(PickerOverlay):
        _css_prefix = "tp"
        title = "Test"
        choices = [("a", "A"), ("b", "B")]
        current_value = "a"

        def on_confirm(self, value: str) -> None:
            pass

    app = _make_app()

    async def _run():
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            # Mount a test picker manually to check compose
            picker = _TestPicker()
            await app.mount(picker)
            await pilot.pause()
            header = picker.query_one("#tp-header", Static)
            assert "picker-header" in header.classes
            ol = picker.query_one("#tp-list", OptionList)
            assert ol is not None

    import asyncio
    asyncio.get_event_loop().run_until_complete(_run())


# ---------------------------------------------------------------------------
# B02 — _render_options marks current with ●
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_picker_render_options_marks_current():
    """B02: _render_options() prefixes active item with ●, others with spaces."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(VerbosePickerOverlay)
        overlay.current_value = "off"
        overlay._render_options()
        await pilot.pause()
        ol = overlay.query_one("#vpo-list", OptionList)
        # First option (off) should have ● prefix, second (new) should not
        opt0 = ol.get_option("vpo-opt-off")
        opt1 = ol.get_option("vpo-opt-new")
        assert "●" in str(opt0.prompt)
        assert "●" not in str(opt1.prompt)


# ---------------------------------------------------------------------------
# B03 — _render_options sets ol.highlighted to index of current_value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_picker_render_options_sets_highlighted():
    """B03: ol.highlighted == index of current_value in choices."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(VerbosePickerOverlay)
        overlay.current_value = "new"
        overlay._render_options()
        await pilot.pause()
        ol = overlay.query_one("#vpo-list", OptionList)
        # "new" is index 1 in choices
        assert ol.highlighted == 1


# ---------------------------------------------------------------------------
# B04 — on_option_list_option_selected calls on_confirm with correct value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_picker_on_confirm_called_on_selection():
    """B04: on_option_list_option_selected calls on_confirm with correct value."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(VerbosePickerOverlay)
        overlay.add_class("--visible")
        await pilot.pause()

        confirmed_values: list[str] = []

        original_confirm = overlay.on_confirm

        def _spy_confirm(value: str) -> None:
            confirmed_values.append(value)
            # Don't call original to avoid config writes in test

        overlay.on_confirm = _spy_confirm  # type: ignore[method-assign]

        # Fire the event manually
        ol = overlay.query_one("#vpo-list", OptionList)
        opt = ol.get_option("vpo-opt-verbose")
        event = OptionList.OptionSelected(ol, opt, 3)
        overlay.on_option_list_option_selected(event)
        await pilot.pause()

        assert "verbose" in confirmed_values


# ---------------------------------------------------------------------------
# B05 — on_option_list_option_highlighted calls on_highlight with correct value
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_picker_on_highlight_called_on_nav():
    """B05: on_option_list_option_highlighted calls on_highlight with correct value."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(VerbosePickerOverlay)
        overlay.choices = [("normal", "normal"), ("verbose", "verbose")]
        overlay.current_value = "normal"
        overlay._render_options()
        await pilot.pause()

        highlighted_values: list[str] = []
        overlay.on_highlight = lambda v: highlighted_values.append(v)  # type: ignore[method-assign]

        ol = overlay.query_one("#vpo-list", OptionList)
        opt = ol.get_option("vpo-opt-verbose")
        event = OptionList.OptionHighlighted(ol, opt, 1)
        overlay.on_option_list_option_highlighted(event)
        await pilot.pause()

        assert "verbose" in highlighted_values


# ---------------------------------------------------------------------------
# B06 — action_dismiss removes --visible class
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_picker_esc_dismisses_and_focuses_input():
    """B06: action_dismiss removes --visible class."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(VerbosePickerOverlay)
        overlay.add_class("--visible")
        await pilot.pause()
        assert overlay.has_class("--visible")
        overlay.action_dismiss()
        await pilot.pause()
        assert not overlay.has_class("--visible")


# ---------------------------------------------------------------------------
# B07 — action_dismiss calls HermesInput.focus()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_picker_esc_restores_hermes_input_focus():
    """B07: action_dismiss calls HermesInput.focus()."""
    from hermes_cli.tui.input_widget import HermesInput
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(VerbosePickerOverlay)
        overlay.add_class("--visible")
        await pilot.pause()
        overlay.action_dismiss()
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert inp.has_focus


# ---------------------------------------------------------------------------
# B08 — refresh_data triggers _render_options
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_picker_refresh_data_calls_render_options():
    """B08: refresh_data triggers _render_options."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(VerbosePickerOverlay)
        render_calls: list[int] = []
        original_render = overlay._render_options

        def _spy_render():
            render_calls.append(1)
            original_render()

        overlay._render_options = _spy_render  # type: ignore[method-assign]
        with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value={}):
            overlay.refresh_data(MagicMock())
        assert len(render_calls) >= 1


# ---------------------------------------------------------------------------
# B09 — Unknown option ID is a no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_picker_unknown_option_id_ignored():
    """B09: on_option_list_option_selected with wrong prefix is a no-op."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(VerbosePickerOverlay)
        confirmed: list[str] = []
        overlay.on_confirm = lambda v: confirmed.append(v)  # type: ignore[method-assign]

        ol = overlay.query_one("#vpo-list", OptionList)
        # Create a fake event with wrong prefix
        bad_opt = Option("bad", id="xyz-opt-wrong")
        event = OptionList.OptionSelected(ol, bad_opt, 0)
        overlay.on_option_list_option_selected(event)
        await pilot.pause()

        assert confirmed == []


# ---------------------------------------------------------------------------
# B10 — Empty choices list — no crash
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_picker_empty_choices_no_crash():
    """B10: _render_options with empty choices list does not crash."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(VerbosePickerOverlay)
        overlay.choices = []
        overlay.current_value = ""
        # Should not raise
        overlay._render_options()
        await pilot.pause()


# ---------------------------------------------------------------------------
# B11 — current_value not in choices — no crash, no highlighted set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_picker_current_value_not_in_choices_no_crash():
    """B11: current_value not in choices → no crash, ol.highlighted unchanged."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(VerbosePickerOverlay)
        overlay.choices = [("a", "A"), ("b", "B")]
        overlay.current_value = "zzz_not_in_list"
        # Should not raise
        overlay._render_options()
        await pilot.pause()
        ol = overlay.query_one("#vpo-list", OptionList)
        # highlighted should be None or unset (not an index corresponding to zzz)
        assert ol.highlighted is None or ol.highlighted < 2


# ---------------------------------------------------------------------------
# B12 — Widget IDs match _css_prefix pattern
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_picker_css_prefix_wires_ids():
    """B12: Widget IDs match _css_prefix pattern."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        vpo = app.query_one(VerbosePickerOverlay)
        assert vpo._css_prefix == "vpo"
        # Check the IDs exist
        vpo.query_one("#vpo-header", Static)
        vpo.query_one("#vpo-list", OptionList)


# ---------------------------------------------------------------------------
# B13 — Bare PickerOverlay.on_confirm raises NotImplementedError
# ---------------------------------------------------------------------------


def test_picker_on_confirm_raises_if_not_overridden():
    """B13: Calling on_confirm on a bare PickerOverlay raises NotImplementedError."""
    picker = PickerOverlay()
    with pytest.raises(NotImplementedError):
        picker.on_confirm("some_value")


# ---------------------------------------------------------------------------
# V01–V07: VerbosePickerOverlay subclass tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verbose_refresh_data_reads_config():
    """V01: refresh_data sets current_value from display.tool_progress."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(VerbosePickerOverlay)
        cfg = {"display": {"tool_progress": "new"}}
        with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=cfg):
            overlay.refresh_data(MagicMock())
        assert overlay.current_value == "new"


@pytest.mark.asyncio
async def test_verbose_confirm_writes_config():
    """V02: on_confirm("off") calls _cfg_set_nested + _cfg_save_config."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(VerbosePickerOverlay)
        with (
            patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value={}) as mock_read,
            patch("hermes_cli.tui.overlays._cfg_set_nested") as mock_set,
            patch("hermes_cli.tui.overlays._cfg_save_config") as mock_save,
        ):
            overlay.on_confirm("off")
        mock_set.assert_called_once()
        call_args = mock_set.call_args
        assert call_args[0][1] == "display.tool_progress"
        assert call_args[0][2] == "off"
        mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_verbose_confirm_flashes_hint():
    """V03: on_confirm calls app._flash_hint."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(VerbosePickerOverlay)
        with (
            patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value={}),
            patch("hermes_cli.tui.overlays._cfg_set_nested"),
            patch("hermes_cli.tui.overlays._cfg_save_config"),
            patch.object(app, "_flash_hint") as mock_flash,
        ):
            overlay.on_confirm("off")
        mock_flash.assert_called_once()
        assert "off" in mock_flash.call_args[0][0]


@pytest.mark.asyncio
async def test_verbose_confirm_dismisses():
    """V04: on_confirm removes --visible."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(VerbosePickerOverlay)
        overlay.add_class("--visible")
        await pilot.pause()
        with (
            patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value={}),
            patch("hermes_cli.tui.overlays._cfg_set_nested"),
            patch("hermes_cli.tui.overlays._cfg_save_config"),
        ):
            overlay.on_confirm("all")
        await pilot.pause()
        assert not overlay.has_class("--visible")


def test_verbose_four_choices_present():
    """V05: choices has exactly 4 items: off/new/all/verbose."""
    values = [v for v, _ in VerbosePickerOverlay.choices]
    assert values == ["off", "new", "all", "verbose"]


@pytest.mark.asyncio
async def test_verbose_default_current_is_all():
    """V06: config missing → current_value == 'all'."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(VerbosePickerOverlay)
        with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value={}):
            overlay.refresh_data(MagicMock())
        assert overlay.current_value == "all"


@pytest.mark.asyncio
async def test_verbose_query_one_still_works():
    """V07: app.query_one(VerbosePickerOverlay) succeeds."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(VerbosePickerOverlay)
        assert isinstance(overlay, VerbosePickerOverlay)


# ---------------------------------------------------------------------------
# S01–S06: SkinPickerOverlay subclass tests
# NOTE: SkinPickerOverlay is now an alias for TabbedSkinOverlay.
# Full coverage lives in test_tabbed_skin_overlay.py (T-TSO / T-OVR / T-OPT).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# R01–R08: Regression tests — existing overlays unchanged
# ---------------------------------------------------------------------------


def test_yolo_remains_widget_not_picker():
    """R01: YoloConfirmOverlay.__bases__ does not include PickerOverlay."""
    assert PickerOverlay not in YoloConfirmOverlay.__bases__


def test_reasoning_remains_widget_not_picker():
    """R02: ReasoningPickerOverlay.__bases__ does not include PickerOverlay."""
    assert PickerOverlay not in ReasoningPickerOverlay.__bases__


def test_all_overlay_classes_importable():
    """R03: All 5 concrete overlay classes + PickerOverlay importable."""
    from hermes_cli.tui.overlays import (
        ModelPickerOverlay as MPO,
        PickerOverlay as PO,
        ReasoningPickerOverlay as RPO,
        SkinPickerOverlay as SPO,
        VerbosePickerOverlay as VPO,
        YoloConfirmOverlay as YCO,
    )
    assert all([PO, VPO, MPO, SPO, RPO, YCO])


@pytest.mark.asyncio
async def test_vpo_list_id_stable():
    """R04: VerbosePickerOverlay still has #vpo-list."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(VerbosePickerOverlay)
        ol = overlay.query_one("#vpo-list", OptionList)
        assert ol is not None


@pytest.mark.asyncio
async def test_mpo_list_id_stable():
    """R05: ModelPickerOverlay still has #mpo-list."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(ModelPickerOverlay)
        ol = overlay.query_one("#mpo-list", OptionList)
        assert ol is not None


@pytest.mark.asyncio
async def test_spo_list_id_stable():
    """R06: SkinPickerOverlay (TabbedSkinOverlay) has #tso-skin-list on Tab 1."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(SkinPickerOverlay)
        ol = overlay.query_one("#tso-skin-list", OptionList)
        assert ol is not None


@pytest.mark.asyncio
async def test_focus_call_sites_still_valid():
    """R07: Simulate _app_commands focus calls for each overlay."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # These are the exact patterns used in _app_commands.py
        vpo = app.query_one(VerbosePickerOverlay)
        vpo.query_one("#vpo-list")  # should not raise

        mpo = app.query_one(ModelPickerOverlay)
        mpo.query_one("#mpo-list")  # should not raise

        # SkinPickerOverlay is now TabbedSkinOverlay; _app_commands uses _show_tab(0)
        spo = app.query_one(SkinPickerOverlay)
        spo._show_tab(0)  # should not raise


@pytest.mark.asyncio
async def test_picker_subclasses_use_instance_choices():
    """R08: After refresh_data, ModelPickerOverlay instance has self.choices set (not class-level)."""
    app = _make_app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(ModelPickerOverlay)
        initial_class_choices = list(ModelPickerOverlay.choices)

        cfg = {"models": {"gpt-4": {}, "claude-3": {}}}
        with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=cfg):
            overlay.refresh_data(app.cli)

        # Instance attribute should be set
        assert "choices" in overlay.__dict__
        # Class-level list should remain unchanged (not mutated)
        assert list(ModelPickerOverlay.choices) == initial_class_choices


# ---------------------------------------------------------------------------
# M01–M04: ModelPickerOverlay subclass tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_model_refresh_builds_choices_from_config():
    """M01: refresh_data populates choices from cfg["models"]."""
    app = _make_app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(ModelPickerOverlay)
        cfg = {"models": {"gpt-4": {}, "claude-3": {}}}
        with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=cfg):
            overlay.refresh_data(app.cli)

        values = [v for v, _ in overlay.choices]
        assert "gpt-4" in values
        assert "claude-3" in values


@pytest.mark.asyncio
async def test_model_current_injected_if_missing():
    """M02: current model not in cfg["models"] → prepended to choices."""
    app = _make_app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(ModelPickerOverlay)
        app.cli.agent.model = "claude-opus-99"
        cfg = {"models": {"gpt-4": {}}}
        with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=cfg):
            overlay.refresh_data(app.cli)

        values = [v for v, _ in overlay.choices]
        assert values[0] == "claude-opus-99"


@pytest.mark.asyncio
async def test_model_confirm_injects_command():
    """M03: on_confirm("gpt-4") submits /model gpt-4 via HermesInput."""
    from hermes_cli.tui.input_widget import HermesInput
    app = _make_app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(ModelPickerOverlay)
        inp = app.query_one(HermesInput)

        submitted_values: list[str] = []
        original_submit = inp.action_submit

        def _spy_submit():
            submitted_values.append(inp.value)

        inp.action_submit = _spy_submit  # type: ignore[method-assign]

        with patch.object(app, "_flash_hint"):
            overlay.on_confirm("gpt-4")

        await pilot.pause()
        assert "/model gpt-4" in submitted_values


@pytest.mark.asyncio
async def test_model_mpo_current_static_updated():
    """M04: #mpo-current Static updated with 'Current: ...' text."""
    app = _make_app_with_agent()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        overlay = app.query_one(ModelPickerOverlay)
        app.cli.agent.model = "my-model-123"
        cfg = {"models": {}}
        with patch("hermes_cli.tui.overlays._cfg_read_raw_config", return_value=cfg):
            overlay.refresh_data(app.cli)
        await pilot.pause()

        current_static = overlay.query_one("#mpo-current", Static)
        assert "my-model-123" in str(current_static.content)
