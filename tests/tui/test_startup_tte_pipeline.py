from __future__ import annotations

import asyncio
import importlib
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.cells import cell_len
from rich.text import Text


def _load_cli_module():
    import cli as cli_module

    return importlib.reload(cli_module)


def _sync_call_from_thread(fn, *args, **kwargs):
    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        asyncio.run(result)
    return result


def _bind_cli(cli_module, app: MagicMock):
    cli = MagicMock()
    cli.enabled_toolsets = None
    cli.model = "test-model"
    cli.session_id = "test-session"
    cli.agent = None
    cli._startup_banner_template = None
    cli._startup_banner_static = None
    cli._build_startup_banner_template = MagicMock()
    cli._render_startup_banner_text = MagicMock()
    cli._splice_startup_banner_frame = MagicMock()
    cli._ensure_startup_banner_artefacts = cli_module.HermesCLI._ensure_startup_banner_artefacts.__get__(cli)
    cli._play_tte_in_output_panel = cli_module.HermesCLI._play_tte_in_output_panel.__get__(cli)
    cli._set_tui_startup_banner_static = cli_module.HermesCLI._set_tui_startup_banner_static.__get__(cli)
    cli.show_banner_with_startup_effect = cli_module.HermesCLI.show_banner_with_startup_effect.__get__(cli)
    cli._handle_tte_producer_exc = cli_module.HermesCLI._handle_tte_producer_exc
    app.call_from_thread.side_effect = _sync_call_from_thread
    return cli


def _template_line(text: str) -> Text:
    line = Text(text)
    line.no_wrap = True
    line.overflow = "ignore"
    return line


def test_fit_hero_line_pads_when_shorter():
    cli_module = _load_cli_module()

    fitted = cli_module._fit_hero_line(Text("abc"), 6)

    assert fitted.plain == "abc   "
    assert cell_len(fitted.plain) == 6


def test_fit_hero_line_crops_wide_chars_to_cell_budget():
    cli_module = _load_cli_module()

    fitted = cli_module._fit_hero_line(Text("中国"), 3)

    assert fitted.plain == "中 "
    assert cell_len(fitted.plain) == 3


def test_placeholder_marker_not_in_bundled_heroes():
    cli_module = _load_cli_module()
    from hermes_cli.banner import HERMES_CADUCEUS
    from hermes_cli.skin_engine import _BUILTIN_SKINS

    assert cli_module._STARTUP_BANNER_PLACEHOLDER_MARKER not in HERMES_CADUCEUS
    for skin in _BUILTIN_SKINS.values():
        hero = skin.get("banner_hero", "")
        assert cli_module._STARTUP_BANNER_PLACEHOLDER_MARKER not in hero


def test_template_strips_pua_marker_from_user_hero():
    cli_module = _load_cli_module()
    cli = MagicMock()
    cli._render_startup_banner_text = MagicMock(
        return_value=Text(f"left {cli_module._STARTUP_BANNER_PLACEHOLDER_MARKER * 3} right")
    )
    cli._build_startup_banner_template = cli_module.HermesCLI._build_startup_banner_template.__get__(cli)

    template = cli._build_startup_banner_template(
        f"A{cli_module._STARTUP_BANNER_PLACEHOLDER_MARKER}B"
    )

    assert template is not None
    assert template["hero_width"] == 3
    assert cli_module._sanitize_startup_hero_text(
        f"A{cli_module._STARTUP_BANNER_PLACEHOLDER_MARKER}B"
    ) == "A?B"


def test_output_panel_width_event_lifecycle():
    from hermes_cli.tui.widgets import OUTPUT_PANEL_WIDTH_READY, OutputPanel

    OUTPUT_PANEL_WIDTH_READY.clear()
    panel = MagicMock(spec=OutputPanel)
    panel.size.width = 41
    panel.app = SimpleNamespace(_startup_output_panel_width=0)
    panel._live_anchor.return_value = None

    OutputPanel.on_mount(panel)
    assert OUTPUT_PANEL_WIDTH_READY.is_set() is True
    assert panel.app._startup_output_panel_width == 40

    OutputPanel.on_unmount(panel)
    assert OUTPUT_PANEL_WIDTH_READY.is_set() is False


def test_startup_banner_widget_skip_action_sets_event():
    from hermes_cli.tui.widgets import STARTUP_TTE_SKIP, StartupBannerWidget

    STARTUP_TTE_SKIP.clear()
    widget = MagicMock(spec=StartupBannerWidget)

    StartupBannerWidget.action_skip_tte(widget)

    assert STARTUP_TTE_SKIP.is_set() is True
    widget.refresh.assert_called_once()
    STARTUP_TTE_SKIP.clear()


@pytest.mark.asyncio
async def test_first_printable_key_triggers_skip():
    from textual.widgets import TextArea
    from hermes_cli.tui.input.widget import HermesInput
    from hermes_cli.tui.widgets import STARTUP_TTE_SKIP

    STARTUP_TTE_SKIP.clear()
    widget = HermesInput()
    event = SimpleNamespace(
        is_printable=True,
        key="a",
        prevent_default=lambda: None,
        stop=lambda: None,
    )

    with patch.object(TextArea, "_on_key", new=AsyncMock(return_value=None)):
        await widget._on_key(event)

    assert STARTUP_TTE_SKIP.is_set() is True
    STARTUP_TTE_SKIP.clear()


def test_play_tte_uses_splice_for_preflight_and_post_static():
    cli_module = _load_cli_module()
    widget = SimpleNamespace(frames=[])
    widget.set_frame = widget.frames.append
    app = MagicMock()
    app.is_running = True
    app.query_one.return_value = widget
    cli = _bind_cli(cli_module, app)
    template = {
        "lines": [_template_line("X" * 20)],
        "hero_row": 0,
        "hero_col": 5,
        "hero_width": 4,
        "hero_height": 1,
    }
    cli._build_startup_banner_template.return_value = template
    cli._splice_startup_banner_frame.side_effect = [
        Text("preflight"),
        Text("frame-1"),
        Text("static"),
    ]
    cli._render_startup_banner_text.side_effect = AssertionError("unexpected render")

    with patch.object(cli_module, "_hermes_app", app), patch(
        "hermes_cli.tui.widgets.STARTUP_BANNER_READY.wait", return_value=True
    ), patch(
        "hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY.wait", return_value=True
    ), patch(
        "hermes_cli.tui.widgets.STARTUP_TTE_SKIP.is_set", side_effect=[False, False]
    ), patch(
        "hermes_cli.tui.tte_runner.iter_frames", return_value=iter(["frame"])
    ), patch(
        "cli.time.sleep", return_value=None
    ):
        rendered = cli._play_tte_in_output_panel("matrix", "hero", {})

    assert rendered is True
    assert [frame.plain for frame in widget.frames] == ["preflight", "frame-1", "static"]
    assert cli._build_startup_banner_template.call_count == 1


def test_width_timeout_logs_warning_and_uses_terminal_fallback():
    cli_module = _load_cli_module()
    widget = SimpleNamespace(frames=[])
    widget.set_frame = widget.frames.append
    app = MagicMock()
    app.is_running = True
    app.query_one.return_value = widget
    cli = _bind_cli(cli_module, app)
    cli._build_startup_banner_template.return_value = None
    cli._render_startup_banner_text.return_value = Text("static")

    with patch.object(cli_module, "_hermes_app", app), patch(
        "hermes_cli.tui.widgets.STARTUP_BANNER_READY.wait", return_value=True
    ), patch(
        "hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY.wait", return_value=False
    ), patch(
        "hermes_cli.tui.tte_runner.iter_frames", return_value=iter([])
    ), patch.object(cli_module.logger, "warning") as warning_mock:
        rendered = cli._play_tte_in_output_panel("matrix", "hero", {})

    assert rendered is False
    warning_mock.assert_called_once()
    assert "OutputPanel width" in warning_mock.call_args.args[0]
    assert widget.frames[-1].plain == "static"


def test_skip_queues_final_static_frame():
    cli_module = _load_cli_module()
    widget = SimpleNamespace(frames=[])
    widget.set_frame = widget.frames.append
    app = MagicMock()
    app.is_running = True
    app.query_one.return_value = widget
    cli = _bind_cli(cli_module, app)
    template = {
        "lines": [_template_line("X" * 20)],
        "hero_row": 0,
        "hero_col": 5,
        "hero_width": 4,
        "hero_height": 1,
    }
    cli._build_startup_banner_template.return_value = template
    cli._splice_startup_banner_frame.side_effect = [
        Text("preflight"),
        Text("frame-1"),
        Text("static"),
    ]

    def _frames(_name, _text, params=None):
        yield "frame-1"
        yield "frame-2"

    with patch.object(cli_module, "_hermes_app", app), patch(
        "hermes_cli.tui.widgets.STARTUP_BANNER_READY.wait", return_value=True
    ), patch(
        "hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY.wait", return_value=True
    ), patch(
        "hermes_cli.tui.widgets.STARTUP_TTE_SKIP.is_set", side_effect=[False, True]
    ), patch(
        "hermes_cli.tui.tte_runner.iter_frames", side_effect=_frames
    ):
        rendered = cli._play_tte_in_output_panel("matrix", "hero", {})

    assert rendered is True
    assert [frame.plain for frame in widget.frames] == ["preflight", "frame-1", "static"]


def test_producer_breaks_when_app_not_running():
    cli_module = _load_cli_module()
    widget = SimpleNamespace(frames=[])
    widget.set_frame = widget.frames.append
    app = MagicMock()
    app.is_running = False
    app.query_one.return_value = widget
    cli = _bind_cli(cli_module, app)
    cli._build_startup_banner_template.return_value = None
    cli._render_startup_banner_text.return_value = Text("static")

    frame_counter = {"count": 0}

    def _frames(_name, _text, params=None):
        frame_counter["count"] += 1
        yield "frame-1"

    with patch.object(cli_module, "_hermes_app", app), patch(
        "hermes_cli.tui.widgets.STARTUP_BANNER_READY.wait", return_value=True
    ), patch(
        "hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY.wait", return_value=True
    ), patch(
        "hermes_cli.tui.tte_runner.iter_frames", side_effect=_frames
    ):
        rendered = cli._play_tte_in_output_panel("matrix", "hero", {})

    assert rendered is False
    assert frame_counter["count"] == 1
    assert widget.frames[-1].plain == "static"


def test_set_tui_startup_banner_static_uses_cached_template():
    cli_module = _load_cli_module()
    widget = SimpleNamespace(frames=[])
    widget.set_frame = widget.frames.append
    app = MagicMock()
    app.query_one.return_value = widget
    cli = _bind_cli(cli_module, app)
    cli._startup_banner_template = {
        "lines": [_template_line("X" * 20)],
        "hero_row": 0,
        "hero_col": 5,
        "hero_width": 4,
        "hero_height": 1,
    }
    cli._startup_banner_static = None
    cli._splice_startup_banner_frame.return_value = Text("spliced-static")

    with patch.object(cli_module, "_hermes_app", app), patch(
        "hermes_cli.banner.resolve_banner_hero_assets", return_value=("markup", "hero")
    ):
        cli._set_tui_startup_banner_static()

    assert widget.frames[-1].plain == "spliced-static"
    cli._splice_startup_banner_frame.assert_called_once()
    cli._render_startup_banner_text.assert_not_called()


def test_show_banner_with_startup_effect_clears_banner_cache_before_play():
    cli_module = _load_cli_module()
    cli = MagicMock()
    cli.show_banner_with_startup_effect = cli_module.HermesCLI.show_banner_with_startup_effect.__get__(cli)
    cli._startup_banner_template = {"cached": True}
    cli._startup_banner_static = Text("cached")
    cli._ensure_tui_startup_message = MagicMock()
    cli._set_tui_startup_banner_static = MagicMock()

    def _play(*, tui):
        assert cli._startup_banner_template is None
        assert cli._startup_banner_static is None
        return True

    cli._play_startup_text_effect = MagicMock(side_effect=_play)

    cli.show_banner_with_startup_effect(tui=True)

    cli._set_tui_startup_banner_static.assert_not_called()
