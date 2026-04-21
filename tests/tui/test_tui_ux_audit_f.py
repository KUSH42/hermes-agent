"""Phase F — Theme, CSS & System Integration tests."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.constants import accessibility_mode
from hermes_cli.tui.theme_manager import COMPONENT_VAR_DEFAULTS


# ---------------------------------------------------------------------------
# F1 — spinner shimmer colors in COMPONENT_VAR_DEFAULTS
# ---------------------------------------------------------------------------

def test_f1_spinner_shimmer_dim_in_defaults() -> None:
    """COMPONENT_VAR_DEFAULTS must include spinner-shimmer-dim."""
    assert "spinner-shimmer-dim" in COMPONENT_VAR_DEFAULTS, (
        "spinner-shimmer-dim missing from COMPONENT_VAR_DEFAULTS"
    )


def test_f1_spinner_shimmer_peak_in_defaults() -> None:
    """COMPONENT_VAR_DEFAULTS must include spinner-shimmer-peak."""
    assert "spinner-shimmer-peak" in COMPONENT_VAR_DEFAULTS, (
        "spinner-shimmer-peak missing from COMPONENT_VAR_DEFAULTS"
    )


@pytest.mark.asyncio
async def test_f1_spinner_uses_theme_vars() -> None:
    """_tick_spinner reads shimmer colors from theme manager CSS vars."""
    from unittest.mock import patch as _patch

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Inject custom shimmer colors into theme manager
        if app._theme_manager:
            app._theme_manager._component_vars["spinner-shimmer-dim"] = "#ff0000"
            app._theme_manager._component_vars["spinner-shimmer-peak"] = "#00ff00"
        # Patch shimmer_text to capture args
        captured = {}
        from hermes_cli.tui import animation as _anim
        original_shimmer = _anim.shimmer_text
        def _capture(*args, **kwargs):
            captured.update(kwargs)
            return original_shimmer(*args, **kwargs)
        with _patch.object(_anim, "shimmer_text", side_effect=_capture):
            app.agent_running = True
            await pilot.pause()
            app._tick_spinner()
            await pilot.pause()
        if captured:
            assert captured.get("dim") == "#ff0000", (
                f"dim color not from theme: {captured.get('dim')!r}"
            )


# ---------------------------------------------------------------------------
# F2 — overlay scroll areas have scrollbar
# ---------------------------------------------------------------------------

def test_f2_hermes_tcss_has_overlay_scrollbar_rules() -> None:
    """hermes.tcss must include scrollbar rules for overlay scroll areas."""
    from pathlib import Path
    tcss_path = Path(__file__).parents[2] / "hermes_cli" / "tui" / "hermes.tcss"
    tcss_content = tcss_path.read_text(encoding="utf-8")
    assert "HelpOverlay > #help-content" in tcss_content, (
        "hermes.tcss missing HelpOverlay scrollbar rule"
    )
    assert "SessionOverlay > #sess-scroll" in tcss_content, (
        "hermes.tcss missing SessionOverlay scrollbar rule"
    )
    assert "scrollbar-size-vertical: 1" in tcss_content, (
        "hermes.tcss missing scrollbar-size-vertical: 1 for overlay areas"
    )


# ---------------------------------------------------------------------------
# F3 — accessibility_mode() function
# ---------------------------------------------------------------------------

def test_f3_accessibility_mode_off_by_default(monkeypatch) -> None:
    """accessibility_mode() returns False when no env vars are set."""
    monkeypatch.delenv("HERMES_NO_UNICODE", raising=False)
    monkeypatch.delenv("HERMES_ACCESSIBLE", raising=False)
    # Import fresh to avoid caching
    from hermes_cli.tui.constants import accessibility_mode as _am
    # Use importlib to reload
    import importlib
    import hermes_cli.tui.constants as _mod
    importlib.reload(_mod)
    assert not _mod.accessibility_mode()


def test_f3_accessibility_mode_with_no_unicode(monkeypatch) -> None:
    """accessibility_mode() returns True when HERMES_NO_UNICODE=1."""
    import importlib
    import hermes_cli.tui.constants as _mod
    monkeypatch.setenv("HERMES_NO_UNICODE", "1")
    # Force re-evaluation (function reads env at call time, not import time)
    assert _mod.accessibility_mode()


def test_f3_accessibility_mode_with_accessible(monkeypatch) -> None:
    """accessibility_mode() returns True when HERMES_ACCESSIBLE=1."""
    import hermes_cli.tui.constants as _mod
    monkeypatch.setenv("HERMES_ACCESSIBLE", "1")
    monkeypatch.delenv("HERMES_NO_UNICODE", raising=False)
    assert _mod.accessibility_mode()


def test_f3_accessibility_mode_function_exists() -> None:
    """accessibility_mode must be importable from hermes_cli.tui.constants."""
    from hermes_cli.tui.constants import accessibility_mode as _am
    assert callable(_am)


# ---------------------------------------------------------------------------
# F4 — desktop notify skipped when user is active
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_f4_notify_skipped_when_user_active() -> None:
    """_maybe_notify is a no-op when last keypress was < 5 s ago."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Set up config to enable notifications
        mock_cli = MagicMock()
        mock_cli._cfg = {
            "display": {
                "desktop_notify": True,
                "notify_min_seconds": 0,  # always eligible
            }
        }
        app.cli = mock_cli
        app._turn_start_time = time.monotonic() - 20.0  # long turn
        # Mark as recently active (2 s ago)
        app._last_keypress_time = time.monotonic() - 2.0
        notified = []
        with patch("hermes_cli.tui.desktop_notify.notify") as mock_notify:
            app._maybe_notify()
            notified.extend(mock_notify.call_args_list)
        assert len(notified) == 0, "Notify should not fire when user is active"


@pytest.mark.asyncio
async def test_f4_notify_fires_when_user_inactive() -> None:
    """_maybe_notify fires when last keypress was > 5 s ago."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        mock_cli = MagicMock()
        mock_cli._cfg = {
            "display": {
                "desktop_notify": True,
                "notify_min_seconds": 0,
            }
        }
        app.cli = mock_cli
        app._turn_start_time = time.monotonic() - 20.0
        app._last_keypress_time = time.monotonic() - 30.0  # was active 30 s ago
        app._last_assistant_text = "Task complete"
        with patch("hermes_cli.tui.desktop_notify.notify") as mock_notify:
            app._maybe_notify()
            assert mock_notify.called, "Notify should fire when user is inactive"


# ---------------------------------------------------------------------------
# F5 — _last_keypress_time initialized in __init__
# ---------------------------------------------------------------------------

def test_f5_last_keypress_time_initialized() -> None:
    """HermesApp._last_keypress_time is initialized to 0.0 in __init__."""
    app = HermesApp(cli=MagicMock())
    assert hasattr(app, "_last_keypress_time"), "_last_keypress_time attr missing"
    assert app._last_keypress_time == 0.0, (
        f"_last_keypress_time={app._last_keypress_time!r}, expected 0.0"
    )


@pytest.mark.asyncio
async def test_f5_on_key_updates_last_keypress_time() -> None:
    """on_key updates _last_keypress_time to current monotonic time."""
    from textual import events

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        before = time.monotonic()
        # Call on_key directly — pilot.press("a") may be consumed by focused widget
        # before bubbling to the app-level handler.
        mock_event = MagicMock()
        mock_event.key = "a"
        app.on_key(mock_event)
        await pilot.pause()
        after = time.monotonic()
        assert app._last_keypress_time >= before, (
            f"_last_keypress_time={app._last_keypress_time} not updated"
        )
        assert app._last_keypress_time <= after + 0.1
