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


def _run_coro(coro) -> None:
    """Drive a coroutine that makes no async I/O without an event loop.

    .send(None) avoids asyncio touching time.monotonic — safe with finite mock side_effects.
    """
    try:
        coro.send(None)
    except StopIteration:
        pass


def _sync_execute(fn, *args, **kwargs):
    """Synchronously execute a call_later / call_from_thread callback for testing."""
    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        _run_coro(result)
    return True


def _make_draining_call_from_thread(app_mock):
    """Return a call_from_thread side_effect that drains set_interval ticks to completion.

    When call_from_thread(_install_timer) is called, it:
    1. Runs _install_timer (which calls app.set_interval, capturing _tick)
    2. Drains all _tick calls until the timer's stop() is called
    This replaces playback_done.wait() blocking in unit tests.
    """
    _tick_fn: list = []
    _stop: list[bool] = [False]

    class _MockTimer:
        def stop(self) -> None:
            _stop[0] = True

    def _set_interval_side_effect(interval, fn):
        _tick_fn.append(fn)
        return _MockTimer()

    app_mock.set_interval.side_effect = _set_interval_side_effect

    def _call_from_thread_side_effect(fn, *a, **kw):
        # Run the callable (e.g. _install_timer — installs timer, populates timer_ref)
        r = fn(*a, **kw)
        if inspect.isawaitable(r):
            _run_coro(r)
        while _tick_fn and not _stop[0]:
            _run_coro(_tick_fn[0]())
        return r

    app_mock.call_from_thread.side_effect = _call_from_thread_side_effect


def _tte_cfg(cli_module, **overrides):
    data = {
        "effect_name": "matrix",
        "params": {},
        "max_wall_s": 30.0,
        "max_frames": 3000,
        "fps": 60,
    }
    data.update(overrides)
    return cli_module._StartupTteConfig(**data)


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
    app.call_later.side_effect = _sync_execute
    # call_from_thread drives both _install_timer dispatch AND tick drain
    _make_draining_call_from_thread(app)
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


def test_sanitize_startup_hero_replaces_braille_blank_with_space():
    cli_module = _load_cli_module()

    assert cli_module._sanitize_startup_hero_text("A\u2800B") == "A B"


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
    """pre-flight via call_later + anim frame + static via set_interval tick drain."""
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
    # splice calls: preflight (call_later), frame-1 (pre-render), static (end of anim_frames)
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
        "hermes_cli.tui.widgets.STARTUP_TTE_SKIP.is_set", return_value=False
    ), patch(
        "hermes_cli.tui.tte_runner.iter_frames", return_value=iter(["frame"])
    ):
        rendered = cli._play_tte_in_output_panel(_tte_cfg(cli_module), "hero")

    assert rendered is True
    # preflight (call_later path) + frame-1 (tick 1) + static (tick 2) + stop (tick 3)
    assert [f.plain for f in widget.frames] == ["preflight", "frame-1", "static"]
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
        rendered = cli._play_tte_in_output_panel(_tte_cfg(cli_module), "hero")

    assert rendered is False
    warning_mock.assert_called_once()
    assert "OutputPanel width" in warning_mock.call_args.args[0]
    # pre-flight fires even when rendered=False; widget has the static frame
    assert any(f.plain == "static" for f in widget.frames)


def test_skip_queues_final_static_frame():
    """Skip during pre-render still plays collected frames + static via tick drain."""
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
    # splice calls: preflight, frame-1 (before skip), static (appended at end)
    cli._splice_startup_banner_frame.side_effect = [
        Text("preflight"),
        Text("frame-1"),
        Text("static"),
    ]

    skip_calls = [0]

    def _is_set():
        skip_calls[0] += 1
        # Return False for pre-flight + first pre-render frame; True after that
        # Call order: pre-flight's NoMatches check is n/a; pre-render loop: call 1=False, call 2=True
        return skip_calls[0] > 1

    def _frames(_name, _text, params=None):
        yield "frame-1"
        yield "frame-2"

    with patch.object(cli_module, "_hermes_app", app), patch(
        "hermes_cli.tui.widgets.STARTUP_BANNER_READY.wait", return_value=True
    ), patch(
        "hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY.wait", return_value=True
    ), patch(
        "hermes_cli.tui.widgets.STARTUP_TTE_SKIP.is_set", side_effect=_is_set
    ), patch(
        "hermes_cli.tui.tte_runner.iter_frames", side_effect=_frames
    ):
        rendered = cli._play_tte_in_output_panel(_tte_cfg(cli_module), "hero")

    assert rendered is True
    # preflight + frame-1 + static; frame-2 skipped
    assert "preflight" in [f.plain for f in widget.frames]
    assert "static" in [f.plain for f in widget.frames]


def test_producer_breaks_when_app_not_running():
    """app.is_running=False: pre-render loop breaks immediately; preflight still fires."""
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
        rendered = cli._play_tte_in_output_panel(_tte_cfg(cli_module), "hero")

    assert rendered is False
    assert frame_counter["count"] == 1
    # pre-flight fires via call_later even when rendered=False
    assert any(f.plain == "static" for f in widget.frames)


def test_set_tui_startup_banner_static_renders_via_call_from_thread():
    """_set_tui_startup_banner_static always calls _render_startup_banner_text
    (not the splice path) and delivers the result via call_from_thread."""
    cli_module = _load_cli_module()
    widget = SimpleNamespace(frames=[])
    widget.set_frame = widget.frames.append
    app = MagicMock()
    app.query_one.return_value = widget
    cli = _bind_cli(cli_module, app)
    static_text = Text("static-banner")
    cli._render_startup_banner_text.return_value = static_text

    with patch.object(cli_module, "_hermes_app", app):
        cli._set_tui_startup_banner_static()

    assert widget.frames[-1] is static_text
    cli._render_startup_banner_text.assert_called_once_with(print_hero=True)
    cli._splice_startup_banner_frame.assert_not_called()


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
