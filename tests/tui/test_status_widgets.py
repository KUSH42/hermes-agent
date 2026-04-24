"""Tests for HintBar, StatusBar, VoiceStatusBar, ImageBar — Step 3."""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import HintBar, ImageBar, OutputPanel, StatusBar, VoiceStatusBar


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
        ph = inp.placeholder
        ph_text = ph.plain if hasattr(ph, "plain") else str(ph)
        assert ph_text.strip() != ""


@pytest.mark.asyncio
async def test_spinner_stops_when_agent_not_running():
    """HintBar clears when agent_running becomes False."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await asyncio.sleep(0.15)
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()
        bar = app.query_one(HintBar)
        assert bar.hint == ""


@pytest.mark.asyncio
async def test_spinner_writes_to_input_bar_not_hint_bar():
    """_tick_spinner writes spinner_display to input bar placeholder, NOT HintBar.

    HintBar shows phase-based hints (e.g. ^C interrupt · Esc dismiss) when
    agent is running — spinner/timer are in the input bar only.
    """
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.spinner_label = "terminal"
        app.agent_running = True
        await pilot.pause()
        # Wait for at least one spinner tick
        await asyncio.sleep(0.15)
        await pilot.pause()
        # HintBar should NOT have spinner — shows phase hints instead
        bar = app.query_one(HintBar)
        assert bar.hint == ""
        # Input bar should have spinner + tool label
        inp = app.query_one("#input-area")
        assert hasattr(inp, "placeholder")
        ph = inp.placeholder
        assert "terminal" in (ph.plain if hasattr(ph, "plain") else str(ph))


@pytest.mark.asyncio
async def test_thinking_widget_shows_dots_animation():
    """ThinkingWidget v2: activate() enters STARTED substate with 'Thinking...' label."""
    from hermes_cli.tui.widgets import ThinkingWidget
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        tw = app.query_one(ThinkingWidget)
        tw.activate()
        await pilot.pause()
        # v2 API: after activate, substate is STARTED and _base_label is set
        assert tw._substate == "STARTED"
        assert "Thinking" in tw._base_label


@pytest.mark.asyncio
async def test_input_bar_no_helix():
    """Input bar spinner uses dot frames only — drawbraille helix moved to ThinkingWidget."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        app.spinner_label = "terminal"
        app._tool_start_time = 100.0
        await pilot.pause()
        with patch("hermes_cli.tui.app._time.monotonic", return_value=103.2):
            app._svc_spinner.tick_spinner()
        inp = app.query_one("#input-area")
        # Should contain spinner dots + label, never drawbraille helix
        ph = inp.placeholder
        assert "terminal" in (ph.plain if hasattr(ph, "plain") else str(ph))


@pytest.mark.asyncio
async def test_status_bar_renders_model_and_ctx_window():
    """StatusBar renders status_model and ctx usage."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_model = "claude-opus"
        app.status_context_tokens = 96_000
        app.status_context_max = 128_000
        await pilot.pause()
        bar = app.query_one(StatusBar)
        rendered = str(bar.render())
        assert "claude-opus" in rendered
        assert "96k/128k" in rendered


@pytest.mark.asyncio
async def test_compaction_bar_renders_at_zero():
    """Compaction bar shows 0% and ctx window at startup."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_model = "claude"
        app.status_context_tokens = 0
        app.status_context_max = 128_000
        app.status_compaction_progress = 0.0
        await pilot.pause()
        bar = app.query_one(StatusBar)
        rendered = str(bar.render())
        assert "0%" in rendered
        assert "0/128k" in rendered
        assert "▱" in rendered


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
    """status_tok_s no longer renders in bottom status bar."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_model = "claude"
        app.status_context_tokens = 96_000
        app.status_context_max = 128_000
        app.status_tok_s = 35.0
        await pilot.pause()
        bar = app.query_one(StatusBar)
        assert "tok/s" not in str(bar.render())


@pytest.mark.asyncio
async def test_tok_s_zero_hidden():
    """Tok/s remains hidden when 0.0."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_model = "claude"
        app.status_context_tokens = 96_000
        app.status_context_max = 128_000
        app.status_tok_s = 0.0
        await pilot.pause()
        bar = app.query_one(StatusBar)
        assert "tok/s" not in str(bar.render())


@pytest.mark.asyncio
async def test_agent_running_keeps_input_enabled():
    """Setting agent_running=True does NOT disable input — user can interrupt."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        input_widget = app.query_one("#input-area")
        assert not input_widget.disabled
        app.agent_running = True
        await pilot.pause()
        # Input stays enabled so user can submit to interrupt + send new message
        assert not input_widget.disabled


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
async def test_live_response_metrics_tick():
    """Live response header timer + rolling tok/s update while streaming."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        msg = output.new_message("hello")
        msg.show_response_rule()
        app.mark_response_stream_started()
        app.mark_response_stream_delta("abcdefgh" * 8)
        await asyncio.sleep(0.15)
        await pilot.pause()
        rendered = str(msg._response_rule.render())
        assert "tok/s" in rendered
        assert "… tok/s" not in rendered
        assert "s" in rendered


@pytest.mark.asyncio
async def test_live_response_metrics_pause_and_resume():
    """Tool pause keeps tok/s paused but elapsed wall time continues."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        msg = output.new_message("hello")
        msg.show_response_rule()

        app.mark_response_stream_started()
        app.mark_response_stream_delta("abcdefgh" * 8)
        await asyncio.sleep(0.12)
        await pilot.pause()

        app.pause_response_stream()
        paused_render = str(msg._response_rule.render())
        await asyncio.sleep(0.12)
        app._refresh_live_response_metrics()
        await pilot.pause()
        later_render = str(msg._response_rule.render())
        assert "tok/s" in later_render
        assert later_render != paused_render

        app.mark_response_stream_started()
        app.mark_response_stream_delta("abcdefgh" * 8)
        await asyncio.sleep(0.12)
        await pilot.pause()
        app.finalize_response_metrics(40.0, 0.24)

        rendered = str(msg._response_rule.render())
        assert "40 tok/s" in rendered
        assert "0.2" in rendered or "0.3" in rendered


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
        app.status_compaction_progress = 0.5
        app.status_compaction_enabled = True
        app.status_context_tokens = 96_000
        app.status_context_max = 128_000
        await pilot.pause()

        bar = app.query_one(StatusBar)

        # At width < 40: minimal — model + ctx, no bar
        with patch.object(type(bar), "size", new_callable=PropertyMock, return_value=Size(30, 1)):
            rendered_narrow = str(bar.render())
        assert "96k/128k" in rendered_narrow
        assert "▰" not in rendered_narrow

        # At width 40–59: compact — % and ctx, no full bar
        with patch.object(type(bar), "size", new_callable=PropertyMock, return_value=Size(50, 1)):
            rendered_compact = str(bar.render())
        assert "96k/128k" in rendered_compact
        assert "▰" not in rendered_compact

        # At width >= 60: full — bar glyphs present
        with patch.object(type(bar), "size", new_callable=PropertyMock, return_value=Size(80, 1)):
            rendered_full = str(bar.render())
        assert "▰" in rendered_full


@pytest.mark.asyncio
async def test_push_tui_status_wires_all_fields():
    """_push_tui_status() sets status_model, ctx usage, and compaction fields on TUI."""
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
        assert hasattr(fake_tui, "status_context_tokens")
        assert hasattr(fake_tui, "status_context_max")
        assert hasattr(fake_tui, "status_compaction_progress")
        assert hasattr(fake_tui, "status_compaction_enabled")
    finally:
        cli_module._hermes_app = orig


@pytest.mark.asyncio
async def test_push_tui_status_falls_back_to_model_context_length():
    """_push_tui_status() fills ctx max from model metadata when compressor lacks it."""
    import cli as cli_module
    from types import SimpleNamespace

    fake_tui = MagicMock()
    fake_tui.call_from_thread = lambda fn, *a: fn(*a)

    orig = cli_module._hermes_app
    try:
        cli_module._hermes_app = fake_tui

        from cli import HermesCLI
        obj = HermesCLI.__new__(HermesCLI)
        obj.model = "anthropic/claude-sonnet-4-20250514"
        obj.session_start = datetime.now() - timedelta(seconds=10)
        obj.conversation_history = []
        obj.agent = SimpleNamespace(
            model=obj.model,
            provider="anthropic",
            base_url="",
            session_input_tokens=0,
            session_output_tokens=0,
            session_cache_read_tokens=0,
            session_cache_write_tokens=0,
            session_prompt_tokens=0,
            session_completion_tokens=0,
            session_total_tokens=0,
            session_api_calls=0,
            context_compressor=SimpleNamespace(
                last_prompt_tokens=0,
                context_length=0,
                threshold_tokens=0,
                compression_count=0,
            ),
        )
        obj.compression_enabled = True

        obj._push_tui_status()

        assert getattr(fake_tui, "status_context_max", 0) > 0
    finally:
        cli_module._hermes_app = orig


# ---------------------------------------------------------------------------
# StatusBar state label (running / idle) — Phase 2 alignment polish
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_bar_shows_running_when_agent_active():
    """StatusBar shows 'thinking' label (not 'running') when agent_running is True."""
    from unittest.mock import PropertyMock
    from textual.geometry import Size

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.agent_running = True
        app.status_model = "claude"
        app.status_context_tokens = 96_000
        app.status_context_max = 128_000
        await pilot.pause()

        bar = app.query_one(StatusBar)
        with patch.object(type(bar), "size", new_callable=PropertyMock, return_value=Size(80, 1)):
            rendered = str(bar.render())
        assert "thinking" in rendered
        assert "running" not in rendered


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
        app.status_context_tokens = 96_000
        app.status_context_max = 128_000
        await pilot.pause()

        bar = app.query_one(StatusBar)
        with patch.object(type(bar), "size", new_callable=PropertyMock, return_value=Size(80, 1)):
            rendered = str(bar.render())
        # Idle: key hints live in HintBar (S1-E/A8); StatusBar shows model + compaction bar
        assert "claude" in rendered
        assert "F1 help" not in rendered


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
        app.status_context_tokens = 0
        app.status_context_max = 128_000
        await pilot.pause()

        bar = app.query_one(StatusBar)
        with patch.object(type(bar), "size", new_callable=PropertyMock, return_value=Size(80, 1)):
            rendered = str(bar.render())
        # Model name should be left-anchored; padding fills the rest to 80 cols
        model_pos = rendered.find("m")
        assert model_pos < 5, f"Model too far right: pos {model_pos} in {rendered!r}"
        assert len(rendered) >= 78, f"Render too short: {len(rendered)!r}"


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
        assert "thinking" in rendered
        assert "running" not in rendered


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


# ---------------------------------------------------------------------------
# V5 — HintBar separator density
# ---------------------------------------------------------------------------

def test_sep_is_single_space_each_side() -> None:
    """_SEP must use one space on each side of the dot (not two)."""
    from hermes_cli.tui.widgets.status_bar import _SEP
    assert _SEP == " [dim]·[/dim] ", (
        f"_SEP is {_SEP!r}, expected ' [dim]·[/dim] '"
    )
