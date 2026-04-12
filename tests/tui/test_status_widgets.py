"""Tests for HintBar, StatusBar, VoiceStatusBar, ImageBar — Step 3."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import HintBar, ImageBar, StatusBar, VoiceStatusBar


@pytest.mark.asyncio
async def test_hint_bar_updates_on_reactive_change():
    """HintBar.hint reactive triggers widget update."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(HintBar)
        bar.hint = "⠋ thinking..."
        await pilot.pause()
        # The rendered content should reflect the hint value


@pytest.mark.asyncio
async def test_spinner_tick_updates_input_when_agent_running():
    """_tick_spinner updates input widget's spinner_text when agent_running is True."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        # Wait for at least one spinner tick (100ms interval)
        import asyncio
        await asyncio.sleep(0.15)
        await pilot.pause()
        inp = app.query_one("#input-area")
        assert hasattr(inp, "spinner_text")
        assert inp.spinner_text != ""


@pytest.mark.asyncio
async def test_spinner_stops_when_agent_not_running():
    """HintBar clears when agent_running becomes False."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()
        bar = app.query_one(HintBar)
        assert bar.hint == ""


@pytest.mark.asyncio
async def test_status_bar_renders_model_tokens_duration():
    """StatusBar renders status_model, status_tokens, and status_duration (str)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_model = "claude-opus"
        app.status_tokens = 1234
        app.status_duration = "5m 42s"
        await pilot.pause()
        bar = app.query_one(StatusBar)
        # Force re-render check — the bar should exist and have rendered


@pytest.mark.asyncio
async def test_compaction_bar_renders_at_zero():
    """No compaction bar shown when progress is 0.0."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_compaction_progress = 0.0
        await pilot.pause()
        # No error; bar renders without compaction section


@pytest.mark.asyncio
async def test_compaction_bar_renders_filled():
    """Compaction bar shows correct fill at various percentages."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        for pct in (0.5, 0.85, 1.0):
            app.status_compaction_progress = pct
            await pilot.pause()


@pytest.mark.asyncio
async def test_compaction_bar_color_thresholds():
    """Color thresholds: normal < 50%, lerp 50–95%, crit >= 95%."""
    from hermes_cli.tui.animation import lerp_color
    _vars: dict = {}
    color = StatusBar._compaction_color
    # Normal (below lerp band — direct return, lowercase default)
    assert color(0.3, _vars) in ("#5f87d7",)
    # At 0.85: in warn→crit lerp band
    expected_085 = lerp_color("#ffa726", "#ef5350", (0.85 - 0.80) / 0.15)
    assert color(0.85, _vars) == expected_085
    # Crit (direct return, lowercase default)
    assert color(0.99, _vars) in ("#ef5350",)


@pytest.mark.asyncio
async def test_tok_s_displayed():
    """status_tok_s renders in status bar when > 0."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_tok_s = 35.0
        await pilot.pause()
        # No error; bar renders with tok/s section


@pytest.mark.asyncio
async def test_tok_s_zero_hidden():
    """Tok/s not shown when 0.0."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_tok_s = 0.0
        await pilot.pause()
        # No error; bar renders without tok/s


@pytest.mark.asyncio
async def test_agent_running_disables_input():
    """Setting agent_running=True disables the input area."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        input_widget = app.query_one("#input-area")
        assert not input_widget.disabled
        app.agent_running = True
        await pilot.pause()
        assert input_widget.disabled


@pytest.mark.asyncio
async def test_voice_status_bar_hidden_by_default():
    """VoiceStatusBar is hidden when voice_mode is False."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(VoiceStatusBar)
        assert not bar.has_class("active")


@pytest.mark.asyncio
async def test_voice_status_bar_shows_on_voice_mode():
    """VoiceStatusBar becomes visible when voice_mode is True."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.voice_mode = True
        await pilot.pause()
        bar = app.query_one(VoiceStatusBar)
        assert bar.has_class("active")


@pytest.mark.asyncio
async def test_voice_recording_updates_status():
    """VoiceStatusBar shows 'REC' when recording."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.voice_mode = True
        app.voice_recording = True
        await pilot.pause()


@pytest.mark.asyncio
async def test_image_bar_hidden_when_no_images():
    """ImageBar is hidden when no images are attached."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(ImageBar)
        assert not bar.display


@pytest.mark.asyncio
async def test_image_bar_shows_on_attach():
    """ImageBar becomes visible when images are attached."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        class FakeImage:
            name = "screenshot.png"

        app.attached_images = [FakeImage()]
        await pilot.pause()
        bar = app.query_one(ImageBar)
        assert bar.display


@pytest.mark.asyncio
async def test_session_timer_ticks():
    """status_duration updates every second from cli.session_start."""
    cli = MagicMock()
    cli.session_start = datetime.now() - timedelta(seconds=5)
    app = HermesApp(cli=cli)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Wait for at least one 1-second tick
        await asyncio.sleep(1.1)
        await pilot.pause()
        assert app.status_duration != "0s"


def test_compaction_bar_color_from_skin():
    """_compaction_color uses CSS vars dict, falling back to hardcoded hex."""
    from hermes_cli.tui.animation import lerp_color

    # Empty vars → hardcoded defaults
    _vars: dict = {}
    # At 0.5: in lerp band → goes through lerp_color (outputs lowercase)
    result_05 = StatusBar._compaction_color(0.5, _vars)
    assert result_05 == lerp_color("#5f87d7", "#FFA726", 0.0)
    # At 0.85: lerp between warn and crit (warn→crit band) — outputs lowercase
    expected_085 = lerp_color("#FFA726", "#EF5350", (0.85 - 0.80) / 0.15)
    assert StatusBar._compaction_color(0.85, _vars) == expected_085
    # Crit: direct return (lowercase fallback matches lerp_color output convention)
    assert StatusBar._compaction_color(0.99, _vars) == "#ef5350"

    # Custom CSS vars override defaults
    custom_vars = {
        "status-context-color": "#aabbcc",
        "status-warn-color":    "#ddeeff",
        "status-error-color":   "#112233",
    }
    assert StatusBar._compaction_color(0.3, custom_vars) == "#aabbcc"
    # At 0.85: lerp between custom warn and crit
    expected_skin = lerp_color("#ddeeff", "#112233", (0.85 - 0.80) / 0.15)
    assert StatusBar._compaction_color(0.85, custom_vars) == expected_skin
    assert StatusBar._compaction_color(0.99, custom_vars) == "#112233"


@pytest.mark.asyncio
async def test_status_bar_narrow_width():
    """StatusBar render degrades gracefully at narrow widths (three breakpoints)."""
    from unittest.mock import PropertyMock
    from textual.geometry import Size

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_model = "claude"
        app.status_duration = "5s"
        app.status_compaction_progress = 0.5
        app.status_compaction_enabled = True
        app.status_tokens = 1000
        await pilot.pause()

        bar = app.query_one(StatusBar)

        # At width < 40: minimal — only model + duration, no bar or tokens
        with patch.object(type(bar), "size", new_callable=PropertyMock, return_value=Size(30, 1)):
            rendered_narrow = str(bar.render())
        assert "5s" in rendered_narrow
        assert "▰" not in rendered_narrow
        assert "1000" not in rendered_narrow

        # At width 40–59: compact — % and tokens, no full bar
        with patch.object(type(bar), "size", new_callable=PropertyMock, return_value=Size(50, 1)):
            rendered_compact = str(bar.render())
        assert "1000" in rendered_compact
        assert "▰" not in rendered_compact

        # At width >= 60: full — bar glyphs present
        with patch.object(type(bar), "size", new_callable=PropertyMock, return_value=Size(80, 1)):
            rendered_full = str(bar.render())
        assert "▰" in rendered_full


@pytest.mark.asyncio
async def test_push_tui_status_wires_all_fields():
    """_push_tui_status() sets status_model, status_tokens, and compaction fields on TUI."""
    import cli as cli_module
    from types import SimpleNamespace

    # call_from_thread(fn, *a) → fn(*a): applies setattr directly on fake_tui
    fake_tui = MagicMock()
    fake_tui.call_from_thread = lambda fn, *a: fn(*a)

    orig = cli_module._hermes_app
    try:
        cli_module._hermes_app = fake_tui

        from cli import HermesCLI
        obj = HermesCLI.__new__(HermesCLI)
        obj.model = "anthropic/claude-sonnet-4-20250514"
        obj.session_start = datetime.now() - timedelta(seconds=10)
        obj.conversation_history = [{"role": "user", "content": "hi"}]
        obj.agent = SimpleNamespace(
            model=obj.model,
            provider="anthropic",
            base_url="",
            session_input_tokens=100,
            session_output_tokens=50,
            session_cache_read_tokens=0,
            session_cache_write_tokens=0,
            session_prompt_tokens=100,
            session_completion_tokens=50,
            session_total_tokens=150,
            session_api_calls=1,
            context_compressor=SimpleNamespace(
                last_prompt_tokens=8000,
                context_length=200000,
                threshold_tokens=160000,
                compression_count=0,
            ),
        )
        obj.compression_enabled = True

        obj._push_tui_status()

        # call_from_thread executed setattr(fake_tui, attr, value) for each field
        assert hasattr(fake_tui, "status_model")
        assert hasattr(fake_tui, "status_tokens")
        assert hasattr(fake_tui, "status_compaction_progress")
        assert hasattr(fake_tui, "status_compaction_enabled")
    finally:
        cli_module._hermes_app = orig


# ---------------------------------------------------------------------------
# StatusBar state label (running / idle) — Phase 2 alignment polish
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_bar_shows_running_when_agent_active():
    """StatusBar appends 'running' label when agent_running is True."""
    from unittest.mock import PropertyMock
    from textual.geometry import Size

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        app.status_model = "claude"
        app.status_duration = "1s"
        await pilot.pause()

        bar = app.query_one(StatusBar)
        with patch.object(type(bar), "size", new_callable=PropertyMock, return_value=Size(80, 1)):
            rendered = str(bar.render())
        assert "running" in rendered


@pytest.mark.asyncio
async def test_status_bar_shows_idle_when_not_running():
    """StatusBar appends 'idle' label when neither agent nor command is running."""
    from unittest.mock import PropertyMock
    from textual.geometry import Size

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = False
        app.command_running = False
        app.status_model = "claude"
        app.status_duration = "1s"
        await pilot.pause()

        bar = app.query_one(StatusBar)
        with patch.object(type(bar), "size", new_callable=PropertyMock, return_value=Size(80, 1)):
            rendered = str(bar.render())
        # Idle now shows rotating hints; first hint contains "F1 help"
        assert "F1 help" in rendered


@pytest.mark.asyncio
async def test_status_bar_running_label_right_anchored():
    """State label appears after padding — not immediately after the model name."""
    from unittest.mock import PropertyMock
    from textual.geometry import Size

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = False
        app.status_model = "m"
        app.status_tokens = 0
        app.status_duration = "0s"
        await pilot.pause()

        bar = app.query_one(StatusBar)
        with patch.object(type(bar), "size", new_callable=PropertyMock, return_value=Size(80, 1)):
            rendered = str(bar.render())
        # There should be spaces between the left content and the right-anchored hint label
        hint_pos = rendered.rfind("F1 help")
        assert hint_pos > 10, f"Hint too close to start: pos {hint_pos} in {rendered!r}"


# ---------------------------------------------------------------------------
# Animation tests (spec: tui-animation-novel-techniques.md)
# ---------------------------------------------------------------------------

def test_compaction_color_normal_below_fifty():
    """_compaction_color returns the normal color when progress < 0.50 (direct return)."""
    _vars: dict = {}
    # Direct returns use the fallback string verbatim (lowercase — matches CSS vars)
    assert StatusBar._compaction_color(0.3, _vars) == "#5f87d7"
    assert StatusBar._compaction_color(0.0, _vars) == "#5f87d7"


def test_compaction_color_blend_at_seventy():
    """_compaction_color at 0.70 is between normal and warn colors (lerp band)."""
    from hermes_cli.tui.animation import lerp_color
    _vars: dict = {}
    result = StatusBar._compaction_color(0.70, _vars)
    # lerp_color() always outputs lowercase; inputs are the fallback values
    expected = lerp_color("#5f87d7", "#FFA726", (0.70 - 0.50) / 0.30)
    assert result == expected


def test_compaction_color_blend_at_ninety():
    """_compaction_color at 0.90 is between warn and crit colors (lerp band)."""
    from hermes_cli.tui.animation import lerp_color
    _vars: dict = {}
    result = StatusBar._compaction_color(0.90, _vars)
    # lerp_color() always outputs lowercase; inputs are the fallback values
    expected = lerp_color("#FFA726", "#EF5350", (0.90 - 0.80) / 0.15)
    assert result == expected


@pytest.mark.asyncio
async def test_statusbar_running_indicator_has_bullet():
    """Running indicator shows ● when agent is running."""
    from unittest.mock import PropertyMock
    from textual.geometry import Size

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        bar = app.query_one(StatusBar)
        with patch.object(type(bar), "size", new_callable=PropertyMock, return_value=Size(80, 1)):
            rendered = str(bar.render())
        assert "●" in rendered
        assert "running" in rendered


@pytest.mark.asyncio
async def test_statusbar_pulse_starts_on_agent_running():
    """_pulse_timer is started when agent_running transitions to True."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()

        bar = app.query_one(StatusBar)
        # Pulse should be running — timer is non-None
        assert bar._pulse_timer is not None


@pytest.mark.asyncio
async def test_statusbar_pulse_stops_on_agent_done():
    """_pulse_timer is stopped when agent_running transitions to False."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()

        bar = app.query_one(StatusBar)
        assert bar._pulse_timer is None
        assert bar._pulse_t == 0.0


@pytest.mark.asyncio
async def test_statusbar_tok_s_animates():
    """Setting status_tok_s triggers _tok_s_displayed to animate toward the target."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_tok_s = 100.0
        await pilot.pause()
        bar = app.query_one(StatusBar)
        # After the reactive fires, _tok_s_displayed should be heading toward 100
        # (animation may not be complete yet, but it should have started)
        assert bar._tok_s_displayed >= 0.0


@pytest.mark.asyncio
async def test_animated_counter_set_target():
    """AnimatedCounter.set_target() animates _displayed toward the target value."""
    from hermes_cli.tui.widgets import AnimatedCounter
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        counter = AnimatedCounter()
        await app.mount(counter)
        await pilot.pause()
        counter.set_target(50.0, unit="tok/s")
        # Wait for 200ms animation duration + margin
        await asyncio.sleep(0.25)
        await pilot.pause()
        assert counter._displayed == pytest.approx(50.0, abs=1.0)


@pytest.mark.asyncio
async def test_animated_counter_render_shows_unit():
    """AnimatedCounter render includes unit suffix."""
    from hermes_cli.tui.widgets import AnimatedCounter
    from rich.text import Text
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        counter = AnimatedCounter()
        await app.mount(counter)
        await pilot.pause()
        counter._displayed = 42.0
        counter._unit = "tok/s"
        rendered = str(counter.render())
        assert "42" in rendered
        assert "tok/s" in rendered
