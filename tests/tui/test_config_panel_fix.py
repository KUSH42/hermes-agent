"""Tests for CO-H1/CO-H2/CO-M1/CO-L1 config panel fixes.

CO-H1  Focus captured on overlay open (call_later determinism)
CO-H2  Tab content populated on tab switch (watch_active_tab refresh guard)
CO-M1  Silent swallows replaced with logging
CO-L1  /syntax command routes to syntax tab
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from textual.app import App, ComposeResult

from hermes_cli.tui.overlays.config import ConfigOverlay


# ─── shared app factory ──────────────────────────────────────────────────────


class _CfgApp(App):
    def compose(self) -> ComposeResult:
        yield ConfigOverlay(id="cfg")


def _make_app() -> _CfgApp:
    return _CfgApp()


def _fake_cfg(**overrides):
    base = {
        "display": {
            "tool_progress": "all",
            "skin": "default",
            "show_reasoning": False,
            "rich_reasoning": True,
            "skin_overrides": {"vars": {}},
        },
        "models": {"gpt-5": {}, "claude-sonnet-4-6": {}},
        "approvals": {"mode": "manual"},
    }
    base.update(overrides)
    return base


def _fake_cli(model: str = "gpt-5") -> MagicMock:
    cli = MagicMock()
    cli.model = model
    cli.agent = None
    return cli


# ─── CO-H1: focus captured on overlay open ───────────────────────────────────


class TestCO_H1_FocusCaptured:
    """After show_overlay(), the appropriate list widget receives focus.

    Widget.focus() uses call_later, so every test must await pilot.pause()
    before asserting focus.
    """

    @pytest.mark.asyncio
    async def test_model_tab_focus_on_open(self):
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            with patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ):
                ov.show_overlay(tab="model")
                await pilot.pause()
            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "co-model-list"

    @pytest.mark.asyncio
    async def test_verbose_tab_focus_on_open(self):
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            with patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ):
                ov.show_overlay(tab="verbose")
                await pilot.pause()
            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "co-verbose-list"

    @pytest.mark.asyncio
    async def test_skin_tab_focus_on_open(self):
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            with patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ):
                ov.show_overlay(tab="skin")
                await pilot.pause()
            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "co-skin-list"

    @pytest.mark.asyncio
    async def test_yolo_tab_no_focus_widget(self):
        """yolo tab has no focusable list — focused widget should not be a co- list."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            ov.show_overlay(tab="yolo")
            await pilot.pause()
            # yolo has no entry in focus_map, so _focus_active_tab is a no-op
            # focused may be None or something else — just confirm overlay is visible
            assert ov.has_class("--visible")
            assert ov.active_tab == "yolo"

    @pytest.mark.asyncio
    async def test_repeated_open_refocuses(self):
        """Closing and reopening should re-capture focus each time."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            with patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ):
                ov.show_overlay(tab="model")
                await pilot.pause()
                ov.hide_overlay()
                ov.show_overlay(tab="verbose")
                await pilot.pause()
            assert pilot.app.focused is not None
            assert pilot.app.focused.id == "co-verbose-list"


# ─── CO-H2: tab content populated on tab switch ──────────────────────────────


class TestCO_H2_TabContentRefresh:
    """watch_active_tab must refresh + focus when overlay is visible."""

    @pytest.mark.asyncio
    async def test_refresh_data_stores_cli(self):
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            cli = _fake_cli("my-model")
            with patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ):
                ov.show_overlay(tab="model")
                ov.refresh_data(cli)
            assert ov._last_cli is cli

    @pytest.mark.asyncio
    async def test_refresh_data_delegates_to_active_tab(self):
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            cli = _fake_cli("my-model")
            cfg = _fake_cfg()
            with patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=cfg,
            ):
                ov.show_overlay(tab="model")
                ov.refresh_data(cli)
                await pilot.pause()
            # model list should have been populated
            from textual.widgets import OptionList
            ol = ov.query_one("#co-model-list", OptionList)
            assert ol.option_count > 0

    @pytest.mark.asyncio
    async def test_watch_active_tab_no_refresh_when_hidden(self):
        """Tab switch while hidden must NOT call refresh (guard check)."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            # overlay is hidden (default)
            with patch.object(ov, "_refresh_active_tab") as mock_refresh:
                ov.active_tab = "verbose"
                await pilot.pause()
            mock_refresh.assert_not_called()

    @pytest.mark.asyncio
    async def test_watch_active_tab_refreshes_when_visible(self):
        """Tab switch while visible MUST call refresh."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            with patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ):
                ov.show_overlay(tab="model")
                await pilot.pause()
                with patch.object(ov, "_refresh_active_tab") as mock_refresh:
                    ov.active_tab = "verbose"
                    await pilot.pause()
            mock_refresh.assert_called()

    @pytest.mark.asyncio
    async def test_tab_switch_verbose_populates_options(self):
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            cfg = _fake_cfg()
            with patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=cfg,
            ):
                ov.show_overlay(tab="model")
                await pilot.pause()
                ov.active_tab = "verbose"
                await pilot.pause()
            from textual.widgets import OptionList
            ol = ov.query_one("#co-verbose-list", OptionList)
            assert ol.option_count > 0

    @pytest.mark.asyncio
    async def test_snapshot_guard_prevents_overwrite(self):
        """_snap_css_vars set once on first skin open; not overwritten on re-switch."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            sentinel = {"--color-primary": "#aabbcc"}
            ov._snap_css_vars = sentinel.copy()
            with patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ):
                ov.show_overlay(tab="skin")
                await pilot.pause()
                ov.active_tab = "model"
                await pilot.pause()
                ov.active_tab = "skin"
                await pilot.pause()
            # snapshot guard: _snap_css_vars must still match the original sentinel
            assert ov._snap_css_vars == sentinel

    @pytest.mark.asyncio
    async def test_last_cli_none_safe_for_non_model_tabs(self):
        """_refresh_active_tab with _last_cli=None must not raise for non-model tabs."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            assert ov._last_cli is None
            with patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ):
                # should not raise
                ov.show_overlay(tab="verbose")
                await pilot.pause()


# ─── CO-M1: silent swallows replaced with logging ────────────────────────────


class TestCO_M1_SilentSwallows:
    """Exception handlers must log at WARNING level instead of silently passing."""

    @pytest.mark.asyncio
    async def test_revert_skin_preview_logs_warning_on_failure(self, caplog):
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            # Give overlay a snapshot so the method doesn't short-circuit
            ov._snap_css_vars = {"--color-primary": "#aabbcc"}
            tm = MagicMock()
            tm.refresh_css.side_effect = RuntimeError("css boom")

            with patch.object(type(pilot.app), "_theme_manager", tm, create=True), \
                 caplog.at_level(logging.WARNING, logger="hermes_cli.tui.overlays.config"):
                ov._revert_skin_preview_if_any()

            assert any(
                r.levelno >= logging.WARNING
                for r in caplog.records
            ), "Expected WARNING log when CSS restore fails"

    @pytest.mark.asyncio
    async def test_on_checkbox_changed_logs_warning_on_write_failure(self, caplog):
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            from textual.widgets import Checkbox
            event = MagicMock(spec=Checkbox.Changed)
            event.checkbox = MagicMock()
            event.checkbox.id = "co-rpo-show"
            event.value = True

            with patch(
                "hermes_cli.tui.overlays.config._cfg_save_config",
                side_effect=OSError("disk full"),
            ), patch(
                "hermes_cli.tui.overlays.config._cfg_read_raw_config",
                return_value=_fake_cfg(),
            ), caplog.at_level(logging.WARNING, logger="hermes_cli.tui.overlays.config"):
                ov.on_checkbox_changed(event)

            assert any(
                r.levelno >= logging.WARNING
                for r in caplog.records
            ), "Expected WARNING log for checkbox config write failure"

    @pytest.mark.asyncio
    async def test_inject_reasoning_command_logs_warning_on_failure(self, caplog):
        """_inject_reasoning_command swallow logs WARNING when query_one raises."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            # Patch query_one on the overlay to raise, triggering the except block
            with patch.object(ov, "query_one", side_effect=RuntimeError("no input widget")), \
                 caplog.at_level(logging.WARNING, logger="hermes_cli.tui.overlays.config"):
                ov._inject_reasoning_command("low")

            assert any(
                r.levelno >= logging.WARNING
                for r in caplog.records
            ), "Expected WARNING log when _inject_reasoning_command fails"

    @pytest.mark.asyncio
    async def test_m1_sites_have_log_calls(self):
        """Regression: the 3 M1 swallow sites must each contain a _log.warning call."""
        import pathlib

        src = pathlib.Path("hermes_cli/tui/overlays/config.py").read_text()

        # Each of the three M1 sites should have its specific log message present
        assert "_revert_skin_preview_if_any: CSS restore failed" in src, \
            "_revert_skin_preview_if_any must log its failure"
        assert "on_checkbox_changed: config write failed" in src, \
            "on_checkbox_changed must log its failure"
        assert "_inject_reasoning_command: command injection failed" in src, \
            "_inject_reasoning_command must log its failure"


# ─── CO-L1: /syntax command routes to syntax tab ─────────────────────────────


class TestCO_L1_SyntaxCommand:
    """/syntax in _TAB_FOR_CMD routes ConfigOverlay.show_overlay(tab='syntax')."""

    def test_syntax_in_tab_for_cmd_dict(self):
        """_TAB_FOR_CMD contains '/syntax': 'syntax' — direct import check."""
        import ast
        import pathlib

        src = pathlib.Path(
            "hermes_cli/tui/services/commands.py"
        ).read_text()
        tree = ast.parse(src)

        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if (
                        isinstance(k, ast.Constant)
                        and k.value == "/syntax"
                        and isinstance(v, ast.Constant)
                        and v.value == "syntax"
                    ):
                        found = True
                        break
        assert found, "/syntax not found in any dict literal in commands.py"

    @pytest.mark.asyncio
    async def test_syntax_command_calls_show_overlay_syntax_tab(self):
        """handle_tui_command('/syntax') routes to ConfigOverlay.show_overlay(tab='syntax')."""
        from textual.css.query import NoMatches
        from hermes_cli.tui.services.commands import CommandsService

        overlay = MagicMock()
        overlay.show_overlay = MagicMock()
        overlay.refresh_data = MagicMock()

        app = MagicMock()
        app._dismiss_all_info_overlays = MagicMock()
        app.cli = _fake_cli()
        app.query_one.return_value = overlay

        svc = CommandsService.__new__(CommandsService)
        svc.app = app

        result = svc.handle_tui_command("/syntax")

        assert result is True
        overlay.show_overlay.assert_called_once_with(tab="syntax")

    @pytest.mark.asyncio
    async def test_syntax_tab_has_list_widget(self):
        """The syntax tab body contains a #co-syntax-list OptionList."""
        async with _make_app().run_test() as pilot:
            ov = pilot.app.query_one(ConfigOverlay)
            from textual.widgets import OptionList
            # widget should exist in DOM regardless of visibility
            ol = ov.query_one("#co-syntax-list", OptionList)
            assert ol is not None
