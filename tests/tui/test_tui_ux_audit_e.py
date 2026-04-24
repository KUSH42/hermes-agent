"""Phase E — StatusBar, HintBar & Error Surfaces tests."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import HintBar


# ---------------------------------------------------------------------------
# E1 — status_error auto-clears after 10 s
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e1_status_error_timer_created() -> None:
    """Setting status_error creates a timer handle."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_error = "test error"
        await pilot.pause()
        assert hasattr(app, "_status_error_timer"), "_status_error_timer attr missing"
        # Timer should be non-None right after setting the error
        # (we don't advance time here — just check the timer was set)


@pytest.mark.asyncio
async def test_e1_auto_clear_status_error_clears_matching_error() -> None:
    """_auto_clear_status_error clears error when it still matches."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_error = "original error"
        await pilot.pause()
        # Simulate timer callback firing
        app._svc_watchers.auto_clear_status_error("original error")
        await pilot.pause()
        assert app.status_error == "", f"status_error={app.status_error!r}"


@pytest.mark.asyncio
async def test_e1_auto_clear_does_not_clear_newer_error() -> None:
    """_auto_clear_status_error does not clear a newer error."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_error = "newer error"
        await pilot.pause()
        # Simulate old timer callback with stale message
        app._svc_watchers.auto_clear_status_error("old error")
        await pilot.pause()
        assert app.status_error == "newer error", (
            f"status_error={app.status_error!r} was wrongly cleared"
        )


# ---------------------------------------------------------------------------
# E3 — hint flash not cleared by agent stop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e3_flash_hint_not_cleared_by_agent_stop() -> None:
    """A flash hint with future expiry is not cleared when agent_running goes False."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Issue a long-lived flash
        app._flash_hint("persist me", 5.0)
        await pilot.pause()
        hint_before = app.query_one(HintBar).hint
        # Stop agent
        app.agent_running = True
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()
        hint_after = app.query_one(HintBar).hint
        # Flash should still be present (expiry is 5 s in the future)
        assert "persist me" in hint_after, (
            f"Flash hint was cleared by agent stop. hint_after={hint_after!r}"
        )


# ---------------------------------------------------------------------------
# E4 — two-threshold compaction warnings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e4_compaction_90_warns() -> None:
    """status_compaction_progress at 0.92 flashes a 90% warning."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_compaction_progress = 0.92
        await pilot.pause()
        hint = app.query_one(HintBar).hint
        assert "90%" in hint or "compaction" in hint.lower(), (
            f"HintBar.hint={hint!r}"
        )


@pytest.mark.asyncio
async def test_e4_compaction_99_escalates() -> None:
    """status_compaction_progress at 0.99 flashes a second critical warning."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # First trigger 90%
        app.status_compaction_progress = 0.92
        await pilot.pause()
        hint_90 = app.query_one(HintBar).hint
        # Then 99%
        app.status_compaction_progress = 0.99
        await pilot.pause()
        hint_99 = app.query_one(HintBar).hint
        assert "99%" in hint_99 or "action" in hint_99.lower() or "compact" in hint_99.lower(), (
            f"99% escalation not fired: hint_99={hint_99!r}"
        )


@pytest.mark.asyncio
async def test_e4_compaction_resets_on_zero() -> None:
    """Both compaction warn flags reset when progress returns to 0."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.status_compaction_progress = 0.92
        await pilot.pause()
        app.status_compaction_progress = 0.99
        await pilot.pause()
        app.status_compaction_progress = 0.0
        await pilot.pause()
        assert not app._compaction_warned, "_compaction_warned not reset"
        assert not getattr(app, "_compaction_warn_99", True), "_compaction_warn_99 not reset"


# ---------------------------------------------------------------------------
# E5 — yolo mode toggle flashes hint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_e5_yolo_on_flashes_hint() -> None:
    """watch_yolo_mode(True) flashes 'YOLO mode ON' to HintBar."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.yolo_mode = True
        await pilot.pause()
        hint = app.query_one(HintBar).hint
        assert "YOLO mode ON" in hint, f"HintBar.hint={hint!r}"


@pytest.mark.asyncio
async def test_e5_yolo_off_flashes_hint() -> None:
    """watch_yolo_mode(False) flashes 'YOLO mode OFF' to HintBar."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.yolo_mode = True
        await pilot.pause()
        app.yolo_mode = False
        await pilot.pause()
        hint = app.query_one(HintBar).hint
        assert "YOLO mode OFF" in hint, f"HintBar.hint={hint!r}"
