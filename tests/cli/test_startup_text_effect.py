"""Tests for startup banner text effects."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _isolate(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))


def _make_cli_obj():
    from cli import HermesCLI

    obj = HermesCLI.__new__(HermesCLI)
    obj.compact = False
    obj.console = MagicMock()
    obj.config = {"display": {}}
    obj._show_banner_body = MagicMock()
    return obj


def test_show_banner_with_startup_effect_non_tui_success(_isolate):
    import cli

    obj = _make_cli_obj()
    obj.config["display"]["startup_text_effect"] = {
        "enabled": True,
        "effect": "matrix",
        "params": {"rain_time": 7},
    }

    with (
        patch("shutil.get_terminal_size", return_value=os.terminal_size((120, 40))),
        patch("cli.resolve_banner_logo_assets", return_value=("[gold]logo[/]", "logo")),
        patch("hermes_cli.tui.tte_runner.run_effect", return_value=True) as run_effect,
    ):
        cli.HermesCLI.show_banner_with_startup_effect(obj)

    obj.console.clear.assert_called_once()
    run_effect.assert_called_once_with("matrix", "logo", params={"rain_time": 7})
    obj._show_banner_body.assert_called_once_with(clear=False, print_logo=False)


def test_show_banner_with_startup_effect_disabled_keeps_static_logo(_isolate):
    import cli

    obj = _make_cli_obj()

    with patch("shutil.get_terminal_size", return_value=os.terminal_size((120, 40))):
        cli.HermesCLI.show_banner_with_startup_effect(obj)

    obj.console.clear.assert_called_once()
    obj._show_banner_body.assert_called_once_with(clear=False, print_logo=True)


def test_show_banner_with_startup_effect_tui_uses_app_blocking_runner(_isolate):
    import cli

    obj = _make_cli_obj()
    obj.config["display"]["startup_text_effect"] = {
        "enabled": True,
        "effect": "beams",
        "params": {"beam_delay": 3},
    }
    fake_app = SimpleNamespace(play_effects_blocking=MagicMock(return_value=True))

    with (
        patch("shutil.get_terminal_size", return_value=os.terminal_size((120, 40))),
        patch("cli.resolve_banner_logo_assets", return_value=("[gold]logo[/]", "logo")),
        patch.object(cli, "_hermes_app", fake_app),
    ):
        cli.HermesCLI.show_banner_with_startup_effect(obj, tui=True)

    obj.console.clear.assert_not_called()
    fake_app.play_effects_blocking.assert_called_once_with(
        "beams",
        "logo",
        {"beam_delay": 3},
    )
    obj._show_banner_body.assert_called_once_with(clear=False, print_logo=False)
