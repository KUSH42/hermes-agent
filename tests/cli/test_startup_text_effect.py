"""Tests for startup banner text effects."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from rich.text import Text


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
        patch("hermes_cli.banner.resolve_banner_hero_assets", return_value=("[gold]hero[/]", "hero")),
        patch("hermes_cli.tui.tte_runner.run_effect", return_value=True) as run_effect,
    ):
        cli.HermesCLI.show_banner_with_startup_effect(obj)

    obj.console.clear.assert_called_once()
    # Banner prints first with hero in panel
    obj._show_banner_body.assert_called_once_with(clear=False, print_hero=True)
    # Effect plays after banner (replaces caduceus region on stdout)
    run_effect.assert_called_once_with("matrix", "hero", params={"rain_time": 7})


def test_show_banner_with_startup_effect_disabled_prints_hero_statically(_isolate):
    import cli

    obj = _make_cli_obj()

    with patch("shutil.get_terminal_size", return_value=os.terminal_size((120, 40))):
        cli.HermesCLI.show_banner_with_startup_effect(obj)

    obj.console.clear.assert_called_once()
    obj._show_banner_body.assert_called_once_with(clear=False, print_hero=True)


def test_show_banner_with_startup_effect_tui_updates_startup_widget(_isolate):
    """In TUI mode: frames are spliced into the banner widget and the last frame stays."""
    import cli

    obj = _make_cli_obj()
    obj.enabled_toolsets = []
    obj.model = "test-model"
    obj.session_id = "test-session"
    obj.config["display"]["startup_text_effect"] = {
        "enabled": True,
        "effect": "beams",
        "params": {"beam_delay": 3},
    }

    fake_widget = MagicMock()

    def fake_call_from_thread(fn, *args):
        fn(*args)

    fake_app = SimpleNamespace(
        call_from_thread=fake_call_from_thread,
    )

    with (
        patch("shutil.get_terminal_size", return_value=os.terminal_size((120, 40))),
        patch("hermes_cli.banner.resolve_banner_hero_assets", return_value=("[gold]hero[/]", "hero")),
        patch("hermes_cli.tui.tte_runner.iter_frames", return_value=["\x1b[38;2;0;255;0mA\x1b[0m"]),
        patch.object(obj, "_ensure_tui_startup_banner_widget", return_value=fake_widget),
        patch.object(obj, "_build_startup_banner_template", return_value={"template": True}),
        patch.object(obj, "_splice_startup_banner_frame", return_value=Text("spliced-frame")) as mock_splice,
        patch.object(obj, "_set_tui_startup_banner_static") as mock_set_static,
        patch.object(obj, "_show_banner_postamble") as mock_postamble,
        patch.object(cli, "_hermes_app", fake_app),
    ):
        cli.HermesCLI.show_banner_with_startup_effect(obj, tui=True)

    obj.console.clear.assert_not_called()
    mock_splice.assert_called_once_with({"template": True}, "\x1b[38;2;0;255;0mA\x1b[0m")
    assert fake_widget.set_frame.call_count == 1
    assert fake_widget.set_frame.call_args_list[0][0][0].plain == "spliced-frame"
    mock_set_static.assert_not_called()
    obj._show_banner_body.assert_not_called()
    mock_postamble.assert_called_once()


def test_render_startup_banner_text_uses_live_tui_width(_isolate):
    import cli

    obj = _make_cli_obj()
    obj.enabled_toolsets = []
    obj.model = "test-model"
    obj.session_id = "test-session"

    def fake_call_from_thread(fn, *args):
        fn(*args)

    fake_app = SimpleNamespace(
        size=SimpleNamespace(width=101),
        call_from_thread=fake_call_from_thread,
        query_one=MagicMock(side_effect=RuntimeError("not mounted yet")),
    )
    seen = {}

    def fake_build_welcome_banner(*, console, **kwargs):
        seen["width"] = console.width
        console.print("ok")

    with (
        patch("model_tools.get_tool_definitions", return_value=[]),
        patch("hermes_cli.banner.build_welcome_banner", side_effect=fake_build_welcome_banner),
        patch.object(cli, "_hermes_app", fake_app),
    ):
        obj._render_startup_banner_text(print_hero=True)

    assert seen["width"] == 100


def test_splice_startup_banner_frame_replaces_only_hero_region(_isolate):
    from rich.text import Text

    import cli

    obj = _make_cli_obj()
    template = {
        "lines": [
            Text("header"),
            Text("AA" + ("#" * 3) + "ZZ"),
            Text("BB" + ("#" * 3) + "YY"),
            Text("footer"),
        ],
        "hero_row": 1,
        "hero_col": 2,
        "hero_width": 3,
        "hero_height": 2,
    }

    out = obj._splice_startup_banner_frame(template, "xyz\nq")
    assert out.plain == "header\nAAxyzZZ\nBBq  YY\nfooter"


def test_splice_startup_banner_frame_pads_or_crops_to_hero_region(_isolate):
    from rich.text import Text

    import cli

    obj = _make_cli_obj()
    template = {
        "lines": [Text("L" + ("#" * 4) + "R")],
        "hero_row": 0,
        "hero_col": 1,
        "hero_width": 4,
        "hero_height": 1,
    }

    short = obj._splice_startup_banner_frame(template, "x")
    long = obj._splice_startup_banner_frame(template, "abcdef")

    assert short.plain == "Lx   R"
    assert long.plain == "LabcdR"


def test_plain_skin_hero_gets_banner_text_color(_isolate):
    from rich.console import Console

    from hermes_cli.banner import render_banner_hero_text

    hero = render_banner_hero_text("/\\\\")
    console = Console(record=True, force_terminal=True, color_system="truecolor", width=20)
    console.print(hero)

    rendered = console.export_text(styles=True)
    assert "\x1b[" in rendered
