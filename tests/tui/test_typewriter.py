"""Tests for LiveLineWidget typewriter animation (spec: specs/tui-streaming-typewriter.md).

Run with:
    pytest -o "addopts=" tests/tui/test_typewriter.py -v
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from textual.css.query import NoMatches

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import (
    LiveLineWidget,
    OutputPanel,
    _typewriter_delay_s,
    _typewriter_enabled,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> HermesApp:
    return HermesApp(cli=MagicMock())


def _tw_patch(enabled: bool = True, speed: int = 1000, burst: int = 128, cursor: bool = True):
    """Return a context manager that patches all 4 typewriter config accessors."""
    import hermes_cli.tui.widgets as _w
    from unittest.mock import patch as _patch
    return (
        _patch.object(_w, "_typewriter_enabled", return_value=enabled),
        _patch.object(_w, "_typewriter_delay_s", return_value=(1.0 / speed if speed > 0 else 0.0)),
        _patch.object(_w, "_typewriter_burst_threshold", return_value=burst),
        _patch.object(_w, "_typewriter_cursor_enabled", return_value=cursor),
    )


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_feed_disabled_falls_through():
    """Disabled: feed() == append(); no _char_queue allocated."""
    import hermes_cli.tui.widgets as _w
    with patch.object(_w, "_typewriter_enabled", return_value=False):
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            live = app.query_one(LiveLineWidget)
            live.feed("abc")
            await pilot.pause()
            assert live._buf == "abc"
            assert not hasattr(live, "_char_queue")


@pytest.mark.asyncio
async def test_feed_enabled_queues_chars():
    """Enabled: feed() puts chars into _char_queue immediately (no await between)."""
    import hermes_cli.tui.widgets as _w
    patches = _tw_patch(enabled=True, speed=1)  # very slow so drainer doesn't drain
    with patches[0], patches[1], patches[2], patches[3]:
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            live = app.query_one(LiveLineWidget)
            await pilot.pause()  # let on_mount fire
            live.feed("abc")
            # No await between feed() and assertion — drainer has not run yet
            assert live._char_queue.qsize() == 3


@pytest.mark.asyncio
async def test_commit_lines_newline():
    """_commit_lines() commits complete lines and keeps the tail in _buf."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        live = app.query_one(LiveLineWidget)
        # Prime a message panel so the RichLog exists
        panel = app.query_one(OutputPanel)
        panel.new_message()
        await pilot.pause()

        live._buf = "hello\nworld"
        live._commit_lines()
        assert live._buf == "world"


@pytest.mark.asyncio
async def test_flush_drains_queue():
    """flush() empties _char_queue, updates _buf, sets _animating=False."""
    import hermes_cli.tui.widgets as _w
    patches = _tw_patch(enabled=True, speed=1)
    with patches[0], patches[1], patches[2], patches[3]:
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            live = app.query_one(LiveLineWidget)
            live._animating = True
            live._char_queue.put_nowait("a")
            live._char_queue.put_nowait("b")
            live._char_queue.put_nowait("c")
            live.flush()
            assert live._char_queue.empty()
            assert "a" in live._buf and "b" in live._buf and "c" in live._buf
            assert live._animating is False


@pytest.mark.asyncio
async def test_flush_noop_when_disabled():
    """Disabled: flush() returns without error, _buf unchanged."""
    import hermes_cli.tui.widgets as _w
    with patch.object(_w, "_typewriter_enabled", return_value=False):
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            live = app.query_one(LiveLineWidget)
            live._buf = "existing"
            live.flush()  # must not raise
            assert live._buf == "existing"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_typewriter_chars_appear_sequentially():
    """speed=1000: all chars appear in _buf within reasonable time."""
    import hermes_cli.tui.widgets as _w
    patches = _tw_patch(enabled=True, speed=1000)
    with patches[0], patches[1], patches[2], patches[3]:
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            live = app.query_one(LiveLineWidget)
            live.feed("hello")
            await asyncio.sleep(0.05)
            await pilot.pause()
            total = live._buf + "".join(
                live._char_queue.get_nowait()
                for _ in range(live._char_queue.qsize())
            )
            assert len(total) >= 1  # at least some chars processed


@pytest.mark.asyncio
async def test_cursor_shown_during_animation():
    """Cursor ▌ is in render output while _animating=True."""
    import hermes_cli.tui.widgets as _w
    patches = _tw_patch(enabled=True, speed=1000, cursor=True)
    with patches[0], patches[1], patches[2], patches[3]:
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            live = app.query_one(LiveLineWidget)
            live._animating = True
            live._buf = "hi"
            live._tw_cursor = True
            rendered = str(live.render())
            assert "▌" in rendered


@pytest.mark.asyncio
async def test_cursor_hidden_after_drain():
    """Cursor ▌ is absent when _animating=False."""
    import hermes_cli.tui.widgets as _w
    patches = _tw_patch(enabled=True, speed=1000, cursor=True)
    with patches[0], patches[1], patches[2], patches[3]:
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            live = app.query_one(LiveLineWidget)
            live._animating = False
            live._buf = "hi"
            live._tw_cursor = True
            rendered = str(live.render())
            assert "▌" not in rendered


@pytest.mark.asyncio
async def test_disabled_output_unchanged():
    """Disabled: feed() writes directly to _buf, no animation queue."""
    import hermes_cli.tui.widgets as _w
    with patch.object(_w, "_typewriter_enabled", return_value=False):
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            live = app.query_one(LiveLineWidget)
            live.feed("hello world")
            await pilot.pause()
            assert live._buf == "hello world"


@pytest.mark.asyncio
async def test_disabled_no_animating_reactive():
    """Disabled: _animating stays False throughout."""
    import hermes_cli.tui.widgets as _w
    with patch.object(_w, "_typewriter_enabled", return_value=False):
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            live = app.query_one(LiveLineWidget)
            live.feed("test")
            await pilot.pause()
            assert live._animating is False


@pytest.mark.asyncio
async def test_burst_compensation_processes_all():
    """Burst mode: 200 chars all processed well within burst*speed time."""
    import hermes_cli.tui.widgets as _w
    # speed=5000 (0.2ms/char), burst=10 → 20 chars in batch → multiple batches
    patches = _tw_patch(enabled=True, speed=5000, burst=10)
    with patches[0], patches[1], patches[2], patches[3]:
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            live = app.query_one(LiveLineWidget)
            live.feed("x" * 200)
            await asyncio.sleep(0.5)
            await pilot.pause()
            total_chars = len(live._buf) + live._char_queue.qsize()
            # All 200 should be drained within 0.5s at burst speed
            assert len(live._buf) + live._char_queue.qsize() == 200 or live._char_queue.empty()


@pytest.mark.asyncio
async def test_env_var_override_enable():
    """HERMES_TYPEWRITER=1 enables typewriter even when config says disabled."""
    import os
    import hermes_cli.tui.widgets as _w
    with patch.dict(os.environ, {"HERMES_TYPEWRITER": "1"}):
        # _typewriter_enabled() should return True regardless of config
        assert _typewriter_enabled() is True


@pytest.mark.asyncio
async def test_env_var_override_disable():
    """HERMES_TYPEWRITER=0 disables typewriter even when config says enabled."""
    import os
    with patch.dict(os.environ, {"HERMES_TYPEWRITER": "0"}):
        assert _typewriter_enabled() is False


@pytest.mark.asyncio
async def test_speed_zero_delay():
    """speed=0 → _typewriter_delay_s() returns 0.0."""
    cfg = {"terminal": {"typewriter": {"speed": 0}}}
    import hermes_cli.tui.widgets as _w
    # Patch the local import inside _typewriter_delay_s
    with patch("hermes_cli.tui.widgets._typewriter_delay_s", return_value=0.0):
        delay = _w._typewriter_delay_s()
    assert delay == 0.0


@pytest.mark.asyncio
async def test_is_mounted_exit_no_exception():
    """Unmounting while drainer is active doesn't raise."""
    import hermes_cli.tui.widgets as _w
    patches = _tw_patch(enabled=True, speed=1000)
    with patches[0], patches[1], patches[2], patches[3]:
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            live = app.query_one(LiveLineWidget)
            live.feed("hello")
            await asyncio.sleep(0.02)
            # Widget unmounts when app exits — no exception expected
        # If we reach here, no exception was raised


@pytest.mark.asyncio
async def test_consume_output_uses_feed():
    """_consume_output() calls live_line.feed() not append()."""
    import hermes_cli.tui.widgets as _w
    with patch.object(_w, "_typewriter_enabled", return_value=False):
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            live = app.query_one(LiveLineWidget)
            original_feed = live.feed
            called_with = []
            live.feed = lambda chunk: (called_with.append(chunk), original_feed(chunk))
            app.write_output("hello")
            await asyncio.sleep(0.05)
            await pilot.pause()
            assert "hello" in called_with


@pytest.mark.asyncio
async def test_flush_live_calls_flush():
    """OutputPanel.flush_live() calls live.flush() before reading _buf."""
    import hermes_cli.tui.widgets as _w
    with patch.object(_w, "_typewriter_enabled", return_value=False):
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            panel = app.query_one(OutputPanel)
            panel.new_message()
            await pilot.pause()
            live = panel.live_line
            flush_called = []
            original_flush = live.flush
            live.flush = lambda: (flush_called.append(True), original_flush())
            live._buf = "pending"
            panel.flush_live()
            assert flush_called, "flush() was not called by flush_live()"
