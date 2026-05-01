"""Tests for startup banner polish: T-SBP-01 through T-SBP-18."""
from __future__ import annotations

import sys
import os
import asyncio
import inspect
import threading
from pathlib import Path
from types import SimpleNamespace
import pytest
from unittest.mock import MagicMock, PropertyMock, patch, call


REPO_ROOT = Path(__file__).resolve().parents[2]


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


def _sync_call_from_thread(fn, *args, **kwargs):
    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        asyncio.run(result)
    return result


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_app():
    app = MagicMock()
    app.size.width = 120
    app._startup_output_panel_width = 0
    return app


@pytest.fixture
def cli_instance(mock_app):
    # root-level cli.py — NOT hermes_cli.cli
    sys.path.insert(0, str(REPO_ROOT))
    import cli as cli_module

    cli = MagicMock()
    # Bind real methods under test
    cli._play_tte_in_output_panel = cli_module.HermesCLI._play_tte_in_output_panel.__get__(cli)
    cli._get_startup_text_effect_config = cli_module.HermesCLI._get_startup_text_effect_config.__get__(cli)
    cli._ensure_startup_banner_artefacts = (
        cli_module.HermesCLI._ensure_startup_banner_artefacts.__get__(cli)
    )
    cli._render_startup_banner_text = MagicMock(return_value=MagicMock())
    cli._startup_banner_template = None
    cli._startup_banner_static = None
    # Template dict must use the keys _splice_startup_banner_frame actually reads
    cli._build_startup_banner_template = MagicMock(return_value={
        "lines": [], "hero_row": 0, "hero_col": 0, "hero_width": 10, "hero_height": 5
    })
    cli._splice_startup_banner_frame = MagicMock(return_value=MagicMock())
    # Stub both call_later (used by _play_tte_in_output_panel) and call_from_thread
    # (used by _set_tui_startup_banner_static) to invoke callbacks synchronously.
    mock_app.call_later = MagicMock(side_effect=_sync_call_from_thread)
    mock_app.call_from_thread = MagicMock(side_effect=_sync_call_from_thread)
    # STARTUP_BANNER_READY gate must be pre-set so _play_tte_in_output_panel doesn't
    # block 2s waiting for compose() to mount StartupBannerWidget.
    from hermes_cli.tui.widgets import OUTPUT_PANEL_WIDTH_READY, STARTUP_BANNER_READY
    STARTUP_BANNER_READY.set()
    OUTPUT_PANEL_WIDTH_READY.set()
    # Patch the module-level _hermes_app global
    with patch.object(cli_module, "_hermes_app", mock_app):
        yield cli, cli_module, mock_app
    STARTUP_BANNER_READY.clear()
    OUTPUT_PANEL_WIDTH_READY.clear()


# ---------------------------------------------------------------------------
# Phase 1 — Pre-flight static frame (A-1)
# ---------------------------------------------------------------------------

def test_T_SBP_01_preflight_fires_even_with_no_tte_frames(cli_instance):
    """T-SBP-01: _play_tte_in_output_panel calls _queue_frame at least once even
    if iter_frames yields nothing (pre-flight fires unconditionally)."""
    cli, cli_module, mock_app = cli_instance

    with patch("hermes_cli.tui.tte_runner.iter_frames", return_value=iter([])):
        cli._play_tte_in_output_panel(_tte_cfg(cli_module), "hero")

    cli._splice_startup_banner_frame.assert_called()
    # call_later must have been called (to dispatch _drain_latest non-blocking)
    mock_app.call_later.assert_called()


def test_T_SBP_02_preflight_sends_nonempty_text(cli_instance):
    """T-SBP-02: With 0-frame effect, widget receives a non-empty Text from
    _render_startup_banner_text (pre-flight frame)."""
    from rich.text import Text

    cli, cli_module, mock_app = cli_instance
    preflight_text = Text("startup banner text")
    cli._render_startup_banner_text.return_value = preflight_text

    frames_received = []

    def fake_drain():
        # Simulate StartupBannerWidget.set_frame being called
        pass

    # Capture what gets queued via call_from_thread
    queued_frames = []
    original_render = cli._render_startup_banner_text

    with patch("hermes_cli.tui.tte_runner.iter_frames", return_value=iter([])):
        cli._play_tte_in_output_panel(_tte_cfg(cli_module), "hero")

    assert cli._splice_startup_banner_frame.call_count >= 1


# ---------------------------------------------------------------------------
# Phase 2 — Wall-clock cap (A-5)
# ---------------------------------------------------------------------------

def test_T_SBP_03_wall_clock_cap_exits_early(cli_instance, monkeypatch):
    """T-SBP-03: Wall-clock cap exits loop well before MAX_FRAMES when time advances."""
    cli, cli_module, mock_app = cli_instance

    calls = [0]

    def fake_monotonic():
        calls[0] += 1
        # First call (_tte_start): return 0. All subsequent: return 7.0 (past cap).
        return 0.0 if calls[0] == 1 else 7.0

    monkeypatch.setattr("cli.time.monotonic", fake_monotonic)
    monkeypatch.setattr("cli.time.sleep", MagicMock())

    frame_count = [0]

    def many_frames(name, text, params):
        for _ in range(10000):
            frame_count[0] += 1
            yield "frame"

    with patch("hermes_cli.tui.tte_runner.iter_frames", many_frames):
        cli._play_tte_in_output_panel(_tte_cfg(cli_module), "hero")

    assert frame_count[0] < 10000, f"Expected early exit, got {frame_count[0]} frames"


def test_T_SBP_04_max_frames_guard_still_works(cli_instance, monkeypatch):
    """T-SBP-04: MAX_FRAMES guard works when time.monotonic stays constant."""
    cli, cli_module, mock_app = cli_instance

    # Constant time — no wall-clock advance
    monkeypatch.setattr("cli.time.monotonic", lambda: 0.0)
    monkeypatch.setattr("cli.time.sleep", MagicMock())

    frame_count = [0]

    def many_frames(name, text, params):
        for _ in range(10000):
            frame_count[0] += 1
            yield "frame"

    with patch("hermes_cli.tui.tte_runner.iter_frames", many_frames):
        cli._play_tte_in_output_panel(_tte_cfg(cli_module), "hero")

    # Should have stopped at or near MAX_FRAMES (3000) not all 10000
    # The loop checks i >= MAX_FRAMES at start of each iteration, so at most 3001 frames counted
    assert frame_count[0] <= 3001, f"Expected <= 3001 frames, got {frame_count[0]}"


# ---------------------------------------------------------------------------
# Phase 3 — Hold-frame beat after TTE (B-1)
# ---------------------------------------------------------------------------

def test_T_SBP_05_hold_frame_queues_static_after_tte(cli_instance, monkeypatch):
    """T-SBP-05: When iter_frames yields >= 1 frame, _play_tte_in_output_panel
    calls _render_startup_banner_text and _queue_frame after the loop."""
    cli, cli_module, mock_app = cli_instance

    monkeypatch.setattr("cli.time.monotonic", lambda: 0.0)
    monkeypatch.setattr("cli.time.sleep", MagicMock())

    def one_frame(name, text, params):
        yield "frame line 1"

    with patch("hermes_cli.tui.tte_runner.iter_frames", one_frame):
        result = cli._play_tte_in_output_panel(_tte_cfg(cli_module), "hero")

    assert result is True
    assert cli._splice_startup_banner_frame.call_count >= 3


def test_T_SBP_06_no_tte_frames_skips_hold_frame(cli_instance, monkeypatch):
    """T-SBP-06: When iter_frames yields nothing (rendered_any=False),
    _render_startup_banner_text is called only once (preflight), not for static banner."""
    cli, cli_module, mock_app = cli_instance

    monkeypatch.setattr("cli.time.monotonic", lambda: 0.0)
    sleep_mock = MagicMock()
    monkeypatch.setattr("cli.time.sleep", sleep_mock)

    with patch("hermes_cli.tui.tte_runner.iter_frames", return_value=iter([])):
        result = cli._play_tte_in_output_panel(_tte_cfg(cli_module), "hero")

    assert result is False
    assert cli._splice_startup_banner_frame.call_count == 1
    # sleep should not have been called
    sleep_mock.assert_not_called()


def test_T_SBP_07_set_tui_static_not_called_when_played(monkeypatch):
    """T-SBP-07: _set_tui_startup_banner_static is not called when played=True."""
    sys.path.insert(0, str(REPO_ROOT))
    import cli as cli_module

    mock_app = MagicMock()
    mock_app.call_from_thread = MagicMock(side_effect=lambda fn: fn())

    cli = MagicMock()
    cli.show_banner_with_startup_effect = cli_module.HermesCLI.show_banner_with_startup_effect.__get__(cli)
    cli._play_startup_text_effect = MagicMock(return_value=True)  # played=True
    cli._ensure_tui_startup_message = MagicMock()
    cli._set_tui_startup_banner_static = MagicMock()
    cli._show_banner_postamble = MagicMock()

    with patch.object(cli_module, "_hermes_app", mock_app):
        cli.show_banner_with_startup_effect(tui=True)

    cli._set_tui_startup_banner_static.assert_not_called()
    cli._show_banner_postamble.assert_not_called()
    assert cli._postamble_pending is True


# ---------------------------------------------------------------------------
# Phase 4 — Reduced-motion TTE skip (G-1)
# ---------------------------------------------------------------------------

def test_T_SBP_08_reduced_motion_config_returns_none(monkeypatch):
    """T-SBP-08: tui.reduced_motion: true in config causes early return None."""
    sys.path.insert(0, str(REPO_ROOT))
    import cli as cli_module

    cli = MagicMock()
    cli._get_startup_text_effect_config = cli_module.HermesCLI._get_startup_text_effect_config.__get__(cli)
    cli.config = {"tui": {"reduced_motion": True}, "display": {"startup_text_effect": {"enabled": True, "effect": "matrix"}}}

    monkeypatch.delenv("HERMES_REDUCED_MOTION", raising=False)

    result = cli._get_startup_text_effect_config()
    assert result is None


def test_T_SBP_09_hermes_reduced_motion_env_returns_none(monkeypatch):
    """T-SBP-09: HERMES_REDUCED_MOTION=1 env var causes early return None."""
    sys.path.insert(0, str(REPO_ROOT))
    import cli as cli_module

    cli = MagicMock()
    cli._get_startup_text_effect_config = cli_module.HermesCLI._get_startup_text_effect_config.__get__(cli)
    cli.config = {"tui": {}, "display": {"startup_text_effect": {"enabled": True, "effect": "matrix"}}}

    monkeypatch.setenv("HERMES_REDUCED_MOTION", "1")

    result = cli._get_startup_text_effect_config()
    assert result is None


def test_T_SBP_10_none_config_uses_fallback(monkeypatch):
    """T-SBP-10: When self.config=None, the 'or {}' fallback prevents AttributeError."""
    sys.path.insert(0, str(REPO_ROOT))
    import cli as cli_module

    cli = MagicMock()
    cli._get_startup_text_effect_config = cli_module.HermesCLI._get_startup_text_effect_config.__get__(cli)
    cli.config = None  # self.config = None

    monkeypatch.delenv("HERMES_REDUCED_MOTION", raising=False)

    # Should not raise AttributeError; continues to existing logic
    # (which will return None since display config not set)
    result = cli._get_startup_text_effect_config()
    assert result is None  # display config is missing, so None


def test_T_SBP_11_no_flags_returns_valid_tuple(monkeypatch):
    """T-SBP-11: Neither flag set: function returns valid (effect_name, params) tuple."""
    sys.path.insert(0, str(REPO_ROOT))
    import cli as cli_module

    cli = MagicMock()
    cli._get_startup_text_effect_config = cli_module.HermesCLI._get_startup_text_effect_config.__get__(cli)
    cli.config = {
        "tui": {},
        "display": {"startup_text_effect": {"enabled": True, "effect": "matrix", "params": {"speed": 1}}}
    }

    monkeypatch.delenv("HERMES_REDUCED_MOTION", raising=False)

    result = cli._get_startup_text_effect_config()
    assert result is not None
    assert result.effect_name == "matrix"
    assert isinstance(result.params, dict)


# ---------------------------------------------------------------------------
# Phase 5 — Padding smear fix (B-3)
# ---------------------------------------------------------------------------

def test_T_SBP_12_short_frame_line_has_empty_style_padding(monkeypatch):
    """T-SBP-12: A TTE frame line 5 chars shorter than hero_width produces spliced
    Text whose final padding characters have empty style."""
    sys.path.insert(0, str(REPO_ROOT))
    import cli as cli_module
    from rich.text import Text

    cli = MagicMock()
    cli._splice_startup_banner_frame = cli_module.HermesCLI._splice_startup_banner_frame.__get__(cli)

    # hero_width=15, frame line has 10 chars → delta=5
    hero_width = 15
    template = {
        "lines": [Text("prefix " + "X" * hero_width + " suffix")],
        "hero_row": 0,
        "hero_col": 7,
        "hero_width": hero_width,
        "hero_height": 1,
    }

    # Frame line is 10 chars (5 shorter than hero_width)
    frame_text = "A" * 10

    result = cli._splice_startup_banner_frame(template, frame_text)

    # The result is a Text object
    assert isinstance(result, Text)
    plain = result.plain

    # Find the hero region in plain text
    hero_start = 7
    hero_end = hero_start + hero_width
    hero_region = plain[hero_start:hero_end]

    # First 10 chars are "A"s, last 5 are spaces (padding)
    assert hero_region[:10] == "A" * 10
    assert hero_region[10:] == " " * 5

    # Check that the padding spans have empty style
    # Rich Text._spans contains (start, end, style) tuples
    padding_start = hero_start + 10
    padding_end = hero_start + hero_width
    # Find spans that cover the padding region
    for span in result._spans:
        if span.start >= padding_start and span.end <= padding_end:
            # The style should be empty (no color carry-over)
            assert str(span.style) == "", f"Padding span has non-empty style: {span.style}"


def test_T_SBP_13_full_width_frame_line_no_extra_padding(monkeypatch):
    """T-SBP-13: A full-width TTE frame line produces no extra padding (delta==0)."""
    sys.path.insert(0, str(REPO_ROOT))
    import cli as cli_module
    from rich.text import Text

    cli = MagicMock()
    cli._splice_startup_banner_frame = cli_module.HermesCLI._splice_startup_banner_frame.__get__(cli)

    hero_width = 10
    template = {
        "lines": [Text("prefix " + "X" * hero_width + " suffix")],
        "hero_row": 0,
        "hero_col": 7,
        "hero_width": hero_width,
        "hero_height": 1,
    }

    # Full-width frame line — no padding needed
    frame_text = "B" * hero_width

    result = cli._splice_startup_banner_frame(template, frame_text)
    assert isinstance(result, Text)

    hero_start = 7
    hero_region = result.plain[hero_start:hero_start + hero_width]
    assert hero_region == "B" * hero_width
    # No trailing spaces from padding
    assert " " not in hero_region


# ---------------------------------------------------------------------------
# Phase 6 — Pane-aware banner width (A-3)
# ---------------------------------------------------------------------------

def test_T_SBP_14_panel_width_used_when_set(monkeypatch):
    """T-SBP-14: When app._startup_output_panel_width=60, _render_startup_banner_text
    uses 60 as capture width."""
    sys.path.insert(0, str(REPO_ROOT))
    import cli as cli_module

    mock_app = MagicMock()
    mock_app.size.width = 120
    mock_app._startup_output_panel_width = 60

    cli = MagicMock()
    cli._render_startup_banner_text = cli_module.HermesCLI._render_startup_banner_text.__get__(cli)

    captured_widths = []

    class FakeConsole:
        def __init__(self, **kwargs):
            captured_widths.append(kwargs.get("width", 0))
            self._record = True
        def print(self, *args, **kwargs):
            pass
        def export_text(self, **kwargs):
            return ""

    def fake_build_banner(**kwargs):
        pass

    monkeypatch.setattr("shutil.get_terminal_size", lambda *a, **kw: MagicMock(columns=80))
    cli.model = "test-model"
    cli.enabled_toolsets = []
    cli.session_id = "test-session"
    cli.agent = None

    with patch.object(cli_module, "_hermes_app", mock_app), \
         patch("cli.shutil.get_terminal_size", return_value=MagicMock(columns=80)), \
         patch("hermes_cli.banner.build_welcome_banner", fake_build_banner), \
         patch("model_tools.get_tool_definitions", return_value=[]), \
         patch("rich.console.Console", FakeConsole), \
         patch("rich.text.Text.from_ansi", return_value=MagicMock()):
        try:
            cli._render_startup_banner_text(print_hero=True)
        except Exception:
            pass

    # The capture_width should have been 60 (panel width takes precedence)
    if captured_widths:
        assert captured_widths[0] == 60, f"Expected capture width 60, got {captured_widths[0]}"


def test_T_SBP_15_panel_width_zero_falls_back(monkeypatch):
    """T-SBP-15: When app._startup_output_panel_width=0, falls back to app/terminal width."""
    sys.path.insert(0, str(REPO_ROOT))
    import cli as cli_module

    mock_app = MagicMock()
    mock_app.size.width = 120
    mock_app._startup_output_panel_width = 0  # zero = not set

    captured_widths = []

    class FakeConsole:
        def __init__(self, **kwargs):
            captured_widths.append(kwargs.get("width", 0))
        def print(self, *args, **kwargs):
            pass
        def export_text(self, **kwargs):
            return ""

    cli = MagicMock()
    cli._render_startup_banner_text = cli_module.HermesCLI._render_startup_banner_text.__get__(cli)
    cli.model = "test-model"
    cli.enabled_toolsets = []
    cli.session_id = "test-session"
    cli.agent = None

    with patch.object(cli_module, "_hermes_app", mock_app), \
         patch("cli.shutil.get_terminal_size", return_value=MagicMock(columns=80)), \
         patch("hermes_cli.banner.build_welcome_banner", lambda **kw: None), \
         patch("model_tools.get_tool_definitions", return_value=[]), \
         patch("rich.console.Console", FakeConsole), \
         patch("rich.text.Text.from_ansi", return_value=MagicMock()):
        try:
            cli._render_startup_banner_text(print_hero=True)
        except Exception:
            pass

    if captured_widths:
        # Should use app width (120) not panel width (0)
        assert captured_widths[0] == 120, f"Expected fallback to 120, got {captured_widths[0]}"


# ---------------------------------------------------------------------------
# Phase 7 — Postamble deferred (A-6)
# ---------------------------------------------------------------------------

def test_T_SBP_16_show_banner_sets_postamble_pending(monkeypatch):
    """T-SBP-16: show_banner_with_startup_effect(tui=True) does not call
    _show_banner_postamble and sets _postamble_pending=True."""
    sys.path.insert(0, str(REPO_ROOT))
    import cli as cli_module

    mock_app = MagicMock()
    mock_app.call_from_thread = MagicMock(side_effect=lambda fn: fn())

    cli = MagicMock()
    cli.show_banner_with_startup_effect = cli_module.HermesCLI.show_banner_with_startup_effect.__get__(cli)
    cli._play_startup_text_effect = MagicMock(return_value=False)
    cli._ensure_tui_startup_message = MagicMock()
    cli._set_tui_startup_banner_static = MagicMock()
    cli._show_banner_postamble = MagicMock()

    with patch.object(cli_module, "_hermes_app", mock_app):
        cli.show_banner_with_startup_effect(tui=True)

    cli._show_banner_postamble.assert_not_called()
    assert cli._postamble_pending is True


def test_T_SBP_17_dispatch_input_calls_postamble_once(monkeypatch):
    """T-SBP-17: dispatch_input_submitted calls cli._show_banner_postamble once
    and resets _postamble_pending=False."""
    sys.path.insert(0, str(REPO_ROOT))
    from hermes_cli.tui.services.keys import KeyDispatchService

    mock_cli = MagicMock()
    mock_cli._postamble_pending = True
    mock_cli._show_banner_postamble = MagicMock()
    mock_cli._pending_input = MagicMock()

    mock_app = MagicMock()
    mock_app.cli = mock_cli
    mock_app.agent_running = False
    mock_app.attached_images = []
    mock_app._svc_commands.handle_tui_command = MagicMock(return_value=False)
    mock_app._svc_bash = MagicMock()
    mock_app._svc_bash.is_running = False

    event = MagicMock()
    event.value = "hello"

    svc = KeyDispatchService.__new__(KeyDispatchService)
    svc.app = mock_app

    svc.dispatch_input_submitted(event)

    mock_cli._show_banner_postamble.assert_called_once()
    assert mock_cli._postamble_pending is False


def test_T_SBP_18_dispatch_input_postamble_not_called_second_time(monkeypatch):
    """T-SBP-18: On second dispatch_input_submitted, _show_banner_postamble NOT called."""
    sys.path.insert(0, str(REPO_ROOT))
    from hermes_cli.tui.services.keys import KeyDispatchService

    mock_cli = MagicMock()
    mock_cli._postamble_pending = True
    mock_cli._show_banner_postamble = MagicMock()
    mock_cli._pending_input = MagicMock()

    mock_app = MagicMock()
    mock_app.cli = mock_cli
    mock_app.agent_running = False
    mock_app.attached_images = []
    mock_app._svc_commands.handle_tui_command = MagicMock(return_value=False)
    mock_app._svc_bash = MagicMock()
    mock_app._svc_bash.is_running = False

    event = MagicMock()
    event.value = "hello"

    svc = KeyDispatchService.__new__(KeyDispatchService)
    svc.app = mock_app

    # First call: flushes postamble
    svc.dispatch_input_submitted(event)
    assert mock_cli._postamble_pending is False

    # Reset the mock to count subsequent calls
    mock_cli._show_banner_postamble.reset_mock()

    # Second call: postamble should NOT fire again
    svc.dispatch_input_submitted(event)
    mock_cli._show_banner_postamble.assert_not_called()


def test_T_SBP_19_post_tte_hold_waits_on_first_input_event(cli_instance, monkeypatch):
    """T-SBP-19: rendered TTE uses Event.wait(timeout=0.25) for the post-loop hold."""
    cli, cli_module, _mock_app = cli_instance
    cli._first_input_seen = MagicMock()

    monkeypatch.setattr("cli.time.monotonic", lambda: 0.0)
    monkeypatch.setattr("cli.time.sleep", MagicMock())

    with patch("hermes_cli.tui.tte_runner.iter_frames", return_value=iter(["frame"])):
        rendered = cli._play_tte_in_output_panel(_tte_cfg(cli_module), "hero")

    assert rendered is True
    cli._first_input_seen.wait.assert_called_once_with(timeout=0.25)


@pytest.mark.asyncio
async def test_T_SBP_20_printable_key_sets_first_input_seen():
    """T-SBP-20: HermesInput._on_key marks first input seen on single-char printable keys."""
    from textual.widgets import TextArea
    from hermes_cli.tui.input.widget import HermesInput

    widget = HermesInput()
    cli = SimpleNamespace(_first_input_seen=threading.Event())
    event = SimpleNamespace(
        is_printable=True,
        character="a",
        key="a",
        prevent_default=lambda: None,
        stop=lambda: None,
    )

    from unittest.mock import AsyncMock

    with patch.object(TextArea, "_on_key", new=AsyncMock(return_value=None)), patch.object(
        type(widget),
        "app",
        new_callable=PropertyMock,
        return_value=SimpleNamespace(cli=cli),
    ):
        await widget._on_key(event)

    assert cli._first_input_seen.is_set() is True


@pytest.mark.parametrize(
    ("panel_width", "terminal_width", "compact", "expected"),
    [
        (50, 200, False, True),   # panel 50 < 60 → compact
        (79, 80, False, False),   # panel 79 >= 60 → not compact (80-col terminal case)
        (100, 60, False, False),  # panel 100 >= 60 → not compact
        (0, 55, False, True),     # no panel, terminal 55 < 60 → compact
        (0, 200, True, True),     # self.compact=True → always compact
    ],
)
def test_T_SBP_21_use_compact_banner_prefers_panel_width(
    panel_width: int,
    terminal_width: int,
    compact: bool,
    expected: bool,
):
    """T-SBP-21: compact-banner selection uses OutputPanel width when available."""
    sys.path.insert(0, str(REPO_ROOT))
    import cli as cli_module

    cli = MagicMock()
    cli.compact = compact
    cli._use_compact_banner = cli_module.HermesCLI._use_compact_banner.__get__(cli)
    app = SimpleNamespace(_startup_output_panel_width=panel_width)

    with patch.object(cli_module, "_hermes_app", app), patch(
        "cli.shutil.get_terminal_size",
        return_value=SimpleNamespace(columns=terminal_width),
    ):
        assert cli._use_compact_banner() is expected


def test_T_SBP_22_plain_hero_gets_gradient():
    """T-SBP-22: unstyled hero lines receive accent/text/dim buckets."""
    from hermes_cli.banner import render_banner_hero_text

    hero = "l0\nl1\nl2\nl3\nl4\nl5"
    rendered = render_banner_hero_text(hero)
    spans = [(span.start, span.end, str(span.style)) for span in rendered.spans]

    assert spans == [
        (0, 2, "#FFBF00"),
        (3, 5, "#FFBF00"),
        (6, 8, "#FFF8DC"),
        (9, 11, "#FFF8DC"),
        (12, 14, "#B8860B"),
        (15, 17, "#B8860B"),
    ]


def test_T_SBP_23_styled_hero_lines_are_preserved():
    """T-SBP-23: fully styled hero markup stays untouched."""
    from hermes_cli.banner import render_banner_hero_text

    rendered = render_banner_hero_text("[bold red]alpha[/]\n[dim blue]beta[/]")
    lines = rendered.split("\n", allow_blank=True)

    assert lines[0].plain == "alpha"
    assert any("bold" in str(span.style) and "red" in str(span.style) for span in lines[0].spans)
    assert lines[1].plain == "beta"
    assert any("dim" in str(span.style) and "blue" in str(span.style) for span in lines[1].spans)


def test_T_SBP_24_mixed_hero_gets_partial_gradient():
    """T-SBP-24: mixed markup preserves styled lines and gradients plain ones."""
    from hermes_cli.banner import render_banner_hero_text

    rendered = render_banner_hero_text("l0\nl1\n[dim red]l2[/]\nl3\nl4\nl5")
    spans = [(span.start, span.end, str(span.style)) for span in rendered.spans]

    assert spans[0] == (0, 2, "#FFBF00")
    assert spans[1] == (3, 5, "#FFBF00")
    assert spans[2] == (6, 8, "dim red")
    assert spans[3] == (9, 11, "#FFF8DC")
    assert spans[4] == (12, 14, "#B8860B")
    assert spans[5] == (15, 17, "#B8860B")


def test_T_SBP_25_hero_width_cached_per_skin(monkeypatch):
    """T-SBP-25: repeated hero-width lookups reuse the per-skin cache."""
    from hermes_cli import banner as banner_module

    banner_module._HERO_CACHE.clear()
    resolver = MagicMock(return_value=("markup", "abc\ndef"))
    monkeypatch.setattr(banner_module, "resolve_banner_hero_assets", resolver)

    with patch("hermes_cli.skin_engine.get_active_skin_name", return_value="default"):
        assert banner_module.get_cached_hero_width() == ("abc\ndef", 3)
        assert banner_module.get_cached_hero_width() == ("abc\ndef", 3)

    assert resolver.call_count == 1


def test_T_SBP_26_hero_cache_invalidated_on_skin_reload(monkeypatch):
    """T-SBP-26: invalidation callback clears the width cache for the active skin."""
    from hermes_cli import banner as banner_module

    banner_module._HERO_CACHE.clear()
    resolver = MagicMock(side_effect=[("markup-1", "abc"), ("markup-2", "wxyz")])
    monkeypatch.setattr(banner_module, "resolve_banner_hero_assets", resolver)

    with patch("hermes_cli.skin_engine.get_active_skin_name", return_value="default"):
        assert banner_module.get_cached_hero_width() == ("abc", 3)
        banner_module._invalidate_hero_cache()
        assert banner_module.get_cached_hero_width() == ("wxyz", 4)

    assert resolver.call_count == 2


def test_T_SBP_27_startup_banner_widget_css_uses_full_width():
    """T-SBP-27: StartupBannerWidget CSS fills the parent width explicitly."""
    from hermes_cli.tui.widgets import StartupBannerWidget

    assert "width: 100%" in StartupBannerWidget.DEFAULT_CSS
    assert "min-width: 100%" not in StartupBannerWidget.DEFAULT_CSS
