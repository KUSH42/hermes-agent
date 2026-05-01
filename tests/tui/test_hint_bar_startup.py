"""Tests for HS-1 (render guard) and HS-2 (creation guards) in HintBar."""
from __future__ import annotations

import types
from unittest.mock import Mock

import pytest
from rich.text import Text


# ---------------------------------------------------------------------------
# Shared fixture — app stub + HintBar isolated instance
# ---------------------------------------------------------------------------

def _make_stub_app(**kwargs) -> types.SimpleNamespace:
    defaults = dict(
        agent_running=False,
        command_running=False,
        _animations_enabled=True,
        status_streaming=False,
    )
    defaults.update(kwargs)
    stub = types.SimpleNamespace(**defaults)
    stub.has_class = lambda *a: False
    stub.get_css_variables = lambda: {}
    return stub


def _make_bar():
    from hermes_cli.tui.widgets.status_bar import HintBar

    class _IsolatedBar(HintBar):
        app = None  # type: ignore[assignment]
        content_size = None  # type: ignore[assignment]

    bar = object.__new__(_IsolatedBar)
    # Textual reactive descriptors check hasattr(obj, "_id") on __set__
    # and hasattr(obj, "id") on __get__ — provide both so reactives work.
    bar.__dict__["_id"] = "test-hint-bar"
    bar.__dict__["id"] = "test-hint-bar"
    bar.__dict__["_reactive_hint"] = ""
    bar.__dict__["_reactive__shimmer_tick"] = 0
    # Non-reactive instance fields
    bar._phase = "idle"
    bar._shimmer_base = None
    bar._shimmer_timer = None
    bar._shimmer_skip = []
    bar._flash_text = ""
    bar._density_tier = None
    bar._has_ghost_suggestion = False
    # refresh() needs _is_mounted etc — mock it out for unit tests
    bar.refresh = Mock()
    return bar


@pytest.fixture
def bar_and_app():
    """Return (bar, stub_app, orig_app_descriptor, orig_content_size_descriptor)."""
    bar = _make_bar()
    stub = _make_stub_app()

    orig_app = bar.__class__.app
    orig_cs = bar.__class__.content_size

    content_size_ns = types.SimpleNamespace(width=80, height=1)
    bar.__class__.app = property(lambda s: stub)
    bar.__class__.content_size = property(lambda s: content_size_ns)

    yield bar, stub

    bar.__class__.app = orig_app
    bar.__class__.content_size = orig_cs


# ---------------------------------------------------------------------------
# HS-1 — render() guard
# ---------------------------------------------------------------------------

class TestHS1RenderGuard:
    def test_shimmer_stale_no_agent_shows_idle_hints(self, bar_and_app):
        bar, stub = bar_and_app
        stub.agent_running = False
        stub.command_running = False
        bar._phase = "idle"
        bar._shimmer_base = Text("^C interrupt · Esc dismiss")
        bar._shimmer_timer = Mock()

        result = bar.render()
        markup = result.markup if hasattr(result, "markup") else str(result)
        assert "F1" in markup or "help" in markup.lower()
        assert "interrupt" not in markup

    def test_shimmer_stale_clears_after_render(self, bar_and_app):
        bar, stub = bar_and_app
        stub.agent_running = False
        stub.command_running = False
        bar._phase = "idle"
        bar._shimmer_base = Text("^C interrupt · Esc dismiss")
        bar._shimmer_timer = Mock()

        bar.render()
        assert bar._shimmer_base is None

    def test_shimmer_active_agent_running_shows_shimmer(self, bar_and_app):
        bar, stub = bar_and_app
        stub.agent_running = True
        stub.command_running = False
        bar._shimmer_base = Text("^C interrupt · Esc dismiss")
        bar._shimmer_timer = Mock()

        result = bar.render()
        assert isinstance(result, Text)
        assert "interrupt" in result.plain

    def test_shimmer_active_command_running_shows_shimmer(self, bar_and_app):
        bar, stub = bar_and_app
        stub.agent_running = False
        stub.command_running = True
        bar._shimmer_base = Text("^C interrupt · Esc dismiss")
        bar._shimmer_timer = Mock()

        result = bar.render()
        assert isinstance(result, Text)
        assert "interrupt" in result.plain

    def test_streaming_with_agent_running_shows_interrupt(self, bar_and_app):
        """Streaming + agent_running=True → interrupt/dismiss shown (correct)."""
        bar, stub = bar_and_app
        stub.agent_running = True
        stub.command_running = False
        stub.status_streaming = True
        bar._shimmer_base = None
        bar._shimmer_timer = None

        result = bar.render()
        assert isinstance(result, Text)
        assert "interrupt" in result.plain

    def test_streaming_stale_no_agent_shows_idle_hints(self, bar_and_app):
        """Streaming=True but agent_running=False → stale; show idle hints instead."""
        bar, stub = bar_and_app
        stub.agent_running = False
        stub.command_running = False
        stub.status_streaming = True
        bar._phase = "idle"
        bar._shimmer_base = None
        bar._shimmer_timer = None

        result = bar.render()
        markup = result.markup if hasattr(result, "markup") else str(result)
        assert "interrupt" not in markup


# ---------------------------------------------------------------------------
# HS-2 — set_phase() guard
# ---------------------------------------------------------------------------

class TestHS2SetPhaseGuard:
    def test_set_phase_stream_no_agent_no_shimmer(self, bar_and_app):
        bar, stub = bar_and_app
        stub.agent_running = False
        stub.command_running = False
        stub.status_streaming = False
        bar._phase = "idle"

        bar.set_phase("stream")
        assert bar._shimmer_timer is None

    def test_set_phase_stream_agent_running_shimmer_starts(self, bar_and_app):
        bar, stub = bar_and_app
        stub.agent_running = True
        stub.command_running = False
        stub.status_streaming = False
        bar._phase = "idle"

        # _shimmer_start calls set_interval or clock.subscribe; mock set_interval
        bar.set_interval = Mock(return_value=Mock())
        bar.set_phase("stream")
        assert bar._shimmer_timer is not None

    def test_set_phase_stream_command_running_shimmer_starts(self, bar_and_app):
        bar, stub = bar_and_app
        stub.agent_running = False
        stub.command_running = True
        stub.status_streaming = False
        bar._phase = "idle"

        bar.set_interval = Mock(return_value=Mock())
        bar.set_phase("stream")
        assert bar._shimmer_timer is not None

    def test_set_phase_stream_while_streaming_no_shimmer(self, bar_and_app):
        bar, stub = bar_and_app
        stub.agent_running = True
        stub.command_running = False
        stub.status_streaming = True
        bar._phase = "idle"

        bar.set_phase("stream")
        assert bar._shimmer_timer is None


# ---------------------------------------------------------------------------
# HS-2 — _on_streaming_change() guard
# ---------------------------------------------------------------------------

class TestHS2StreamingChangeGuard:
    def test_streaming_change_no_agent_no_shimmer(self, bar_and_app):
        bar, stub = bar_and_app
        stub.agent_running = False
        stub.command_running = False
        bar._phase = "stream"
        bar._shimmer_base = None
        bar._shimmer_timer = None

        bar._on_streaming_change(False)
        assert bar._shimmer_timer is None

    def test_streaming_change_agent_running_shimmer_starts(self, bar_and_app):
        bar, stub = bar_and_app
        stub.agent_running = True
        stub.command_running = False
        bar._phase = "stream"
        bar._shimmer_base = None
        bar._shimmer_timer = None

        bar.set_interval = Mock(return_value=Mock())
        bar._on_streaming_change(False)
        assert bar._shimmer_timer is not None
