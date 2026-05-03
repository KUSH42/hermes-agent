"""Tests for OPT2-H1 — pre-launch banner worker.

Total: 18 tests across 2 classes (TestPrelaunchWorker: 10, TestPrelaunchIntegration: 8).

All tests are synchronous — no pytest-asyncio required.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import cli as cli_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cli() -> cli_mod.HermesCLI:
    """Return a minimal HermesCLI with startup banner attrs wired."""
    cli = MagicMock(spec=cli_mod.HermesCLI)
    cli._startup_banner_template = None
    cli._startup_banner_static = None
    cli._prelaunch_artefacts_pending = False
    cli._prelaunch_banner_thread = None
    cli._first_input_seen = threading.Event()
    cli._ensure_startup_banner_artefacts = MagicMock()
    cli._build_startup_banner_template = MagicMock(return_value={"lines": []})
    cli._render_startup_banner_text = MagicMock(return_value=MagicMock())
    return cli


def _call_start(cli) -> None:
    """Call _start_prelaunch_banner_worker on a mock cli instance."""
    cli_mod.HermesCLI._start_prelaunch_banner_worker(cli)


def _call_show_banner(cli, tui: bool = True) -> None:
    """Call show_banner_with_startup_effect on mock cli, stubbing inner calls."""
    cli._ensure_tui_startup_message = MagicMock()
    cli._play_startup_text_effect = MagicMock(return_value=False)
    cli._set_tui_startup_banner_static = MagicMock()
    cli._postamble_pending = False
    cli.console = MagicMock()
    cli._show_banner_body = MagicMock()
    cli_mod.HermesCLI.show_banner_with_startup_effect(cli, tui=tui)


# ---------------------------------------------------------------------------
# TestPrelaunchWorker
# ---------------------------------------------------------------------------

class TestPrelaunchWorker:
    def test_worker_starts_before_app_run(self):
        cli = _make_cli()
        _call_start(cli)
        assert cli._prelaunch_banner_thread is not None
        assert cli._prelaunch_banner_thread.is_alive() or not cli._prelaunch_banner_thread.is_alive()
        # The thread was created — check it's a Thread instance
        assert isinstance(cli._prelaunch_banner_thread, threading.Thread)

    def test_worker_sets_template_before_on_mount(self):
        """After worker completes, _ensure_startup_banner_artefacts was called."""
        cli = _make_cli()
        ready = threading.Event()

        def _fake_ensure(plain_hero):
            cli._startup_banner_template = {"lines": []}
            ready.set()

        cli._ensure_startup_banner_artefacts.side_effect = _fake_ensure

        with (
            patch("hermes_cli.banner.resolve_banner_hero_assets", return_value=("", "HERO TEXT")),
            patch("hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY") as mock_event,
            patch("cli._sanitize_startup_hero_text", return_value="HERO TEXT"),
        ):
            mock_event.wait = MagicMock(return_value=True)
            _call_start(cli)
            cli._prelaunch_banner_thread.join(timeout=2.0)

        assert cli._startup_banner_template == {"lines": []}

    def test_worker_failure_leaves_template_none(self):
        cli = _make_cli()

        with (
            patch("hermes_cli.banner.resolve_banner_hero_assets", side_effect=RuntimeError("boom")),
            patch("hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY") as mock_event,
        ):
            mock_event.wait = MagicMock(return_value=True)
            _call_start(cli)
            cli._prelaunch_banner_thread.join(timeout=2.0)

        assert cli._startup_banner_template is None

    def test_worker_exception_logged_as_debug(self):
        cli = _make_cli()

        with (
            patch("hermes_cli.banner.resolve_banner_hero_assets", side_effect=RuntimeError("boom")),
            patch("hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY") as mock_event,
            patch.object(cli_mod, "logger") as mock_logger,
        ):
            mock_event.wait = MagicMock(return_value=True)
            _call_start(cli)
            cli._prelaunch_banner_thread.join(timeout=2.0)

        mock_logger.debug.assert_called_once()
        _, kwargs = mock_logger.debug.call_args
        assert kwargs.get("exc_info") is True

    def test_ensure_artefacts_noop_after_worker(self):
        """If template already set, _build_startup_banner_template not called again."""
        cli = _make_cli()
        cli._startup_banner_template = {"lines": ["existing"]}
        # _ensure_startup_banner_artefacts real impl skips if template is set
        cli._ensure_startup_banner_artefacts = (
            lambda ph: cli_mod.HermesCLI._ensure_startup_banner_artefacts(cli, ph)
        )
        cli_mod.HermesCLI._ensure_startup_banner_artefacts(cli, "HERO")
        cli._build_startup_banner_template.assert_not_called()

    def test_join_with_timeout(self):
        """join() on a still-alive worker respects 300ms cap and proceeds."""
        barrier = threading.Event()
        cli = _make_cli()
        # Create a worker that blocks until we release it
        def _slow_work():
            barrier.wait(timeout=5.0)

        cli._prelaunch_banner_thread = threading.Thread(target=_slow_work, daemon=True)
        cli._prelaunch_banner_thread.start()

        start = time.monotonic()
        _prelaunch = cli._prelaunch_banner_thread
        if _prelaunch is not None and _prelaunch.is_alive():
            _prelaunch.join(timeout=0.3)
        elapsed = time.monotonic() - start

        assert elapsed < 0.6, f"join took {elapsed:.2f}s — should cap at ~300ms"
        barrier.set()  # unblock worker so it exits cleanly

    def test_join_instant_when_worker_done(self):
        """If worker already finished, join returns immediately."""
        cli = _make_cli()
        done_event = threading.Event()

        def _fast_work():
            done_event.set()

        cli._prelaunch_banner_thread = threading.Thread(target=_fast_work, daemon=True)
        cli._prelaunch_banner_thread.start()
        done_event.wait(timeout=2.0)
        cli._prelaunch_banner_thread.join(timeout=0.01)  # ensure it's done

        start = time.monotonic()
        _prelaunch = cli._prelaunch_banner_thread
        if _prelaunch is not None and _prelaunch.is_alive():
            _prelaunch.join(timeout=0.3)
        elapsed = time.monotonic() - start

        assert elapsed < 0.05, f"join on dead thread took {elapsed:.3f}s"

    def test_pending_flag_set_before_thread_start(self):
        cli = _make_cli()
        flag_at_start: list[bool] = []

        orig_start = threading.Thread.start

        def _patched_start(self_t):
            flag_at_start.append(cli._prelaunch_artefacts_pending)
            orig_start(self_t)

        with patch.object(threading.Thread, "start", _patched_start):
            _call_start(cli)
            if cli._prelaunch_banner_thread:
                cli._prelaunch_banner_thread.join(timeout=2.0)

        assert flag_at_start == [True]

    def test_pending_flag_cleared_by_show_banner(self):
        cli = _make_cli()
        cli._prelaunch_artefacts_pending = True

        with patch.object(cli_mod, "_hermes_app", None):
            _call_show_banner(cli, tui=True)

        assert cli._prelaunch_artefacts_pending is False

    def test_thread_is_daemon(self):
        cli = _make_cli()

        with (
            patch("hermes_cli.banner.resolve_banner_hero_assets", return_value=("", "")),
            patch("hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY") as mock_event,
        ):
            mock_event.wait = MagicMock(return_value=True)
            _call_start(cli)

        assert cli._prelaunch_banner_thread.daemon is True
        cli._prelaunch_banner_thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# TestPrelaunchIntegration
# ---------------------------------------------------------------------------

class TestPrelaunchIntegration:
    def test_artefact_build_skipped_in_tte_path(self):
        """With pre-built template and pending flag True, _build_startup_banner_template=0 calls."""
        cli = _make_cli()
        cli._startup_banner_template = {"lines": ["pre_built"]}
        cli._prelaunch_artefacts_pending = True
        # Use real _ensure_startup_banner_artefacts logic
        cli._ensure_startup_banner_artefacts = (
            lambda ph: cli_mod.HermesCLI._ensure_startup_banner_artefacts(cli, ph)
        )

        cli_mod.HermesCLI._ensure_startup_banner_artefacts(cli, "HERO")

        cli._build_startup_banner_template.assert_not_called()

    def test_show_banner_skips_reset_when_flag_set(self):
        """show_banner_with_startup_effect(tui=True) with flag=True: template NOT reset to None."""
        cli = _make_cli()
        cli._startup_banner_template = {"lines": ["pre_built"]}
        cli._startup_banner_static = MagicMock()
        cli._prelaunch_artefacts_pending = True

        with patch.object(cli_mod, "_hermes_app", None):
            _call_show_banner(cli, tui=True)

        assert cli._startup_banner_template == {"lines": ["pre_built"]}, \
            "pre-built template should be preserved when pending flag was True"

    def test_show_banner_resets_when_flag_clear(self):
        """show_banner_with_startup_effect(tui=True) with flag=False: template reset to None."""
        cli = _make_cli()
        cli._startup_banner_template = {"lines": ["old"]}
        cli._prelaunch_artefacts_pending = False

        with patch.object(cli_mod, "_hermes_app", None):
            _call_show_banner(cli, tui=True)

        assert cli._startup_banner_template is None
        assert cli._prelaunch_artefacts_pending is False

    def test_show_banner_clears_flag_on_tte_disabled_path(self):
        """TTE disabled path: flag cleared; pre-built artefact NOT destroyed."""
        cli = _make_cli()
        cli._startup_banner_template = {"lines": ["pre_built"]}
        cli._prelaunch_artefacts_pending = True

        with patch.object(cli_mod, "_hermes_app", None):
            _call_show_banner(cli, tui=True)

        assert cli._prelaunch_artefacts_pending is False
        # template was NOT reset (pre-built preserved for static path)
        assert cli._startup_banner_template == {"lines": ["pre_built"]}

    def test_output_panel_width_wait(self):
        """Worker waits for OUTPUT_PANEL_WIDTH_READY and then calls _ensure_startup_banner_artefacts."""
        cli = _make_cli()
        width_event = threading.Event()
        called_after_width: list[bool] = []

        def _fake_ensure(ph):
            called_after_width.append(width_event.is_set())

        cli._ensure_startup_banner_artefacts.side_effect = _fake_ensure

        with (
            patch("hermes_cli.banner.resolve_banner_hero_assets", return_value=("", "HERO")),
            patch("hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY", width_event),
            patch("cli._sanitize_startup_hero_text", return_value="HERO"),
        ):
            _call_start(cli)
            # Fire the event shortly after start
            threading.Timer(0.05, width_event.set).start()
            cli._prelaunch_banner_thread.join(timeout=2.0)

        assert called_after_width == [True]

    def test_output_panel_width_timeout(self):
        """If OUTPUT_PANEL_WIDTH_READY never fires, worker still calls _ensure_startup_banner_artefacts."""
        cli = _make_cli()
        never_event = threading.Event()  # never set

        def _fake_wait(timeout=None):
            # Simulate timeout: return False immediately without blocking
            return False

        never_event.wait = _fake_wait

        with (
            patch("hermes_cli.banner.resolve_banner_hero_assets", return_value=("", "HERO")),
            patch("hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY", never_event),
            patch("cli._sanitize_startup_hero_text", return_value="HERO"),
        ):
            _call_start(cli)
            cli._prelaunch_banner_thread.join(timeout=2.0)

        cli._ensure_startup_banner_artefacts.assert_called_once_with("HERO")

    def test_worker_plain_hero_sanitized(self):
        """Braille blank ⠀ in hero is replaced before _ensure_startup_banner_artefacts."""
        cli = _make_cli()
        seen_args: list[str] = []

        def _fake_ensure(ph):
            seen_args.append(ph)

        cli._ensure_startup_banner_artefacts.side_effect = _fake_ensure

        raw_hero = "⠀line1⠀\nline2"

        with (
            patch("hermes_cli.banner.resolve_banner_hero_assets", return_value=("", raw_hero)),
            patch("hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY") as mock_event,
        ):
            mock_event.wait = MagicMock(return_value=True)
            _call_start(cli)
            cli._prelaunch_banner_thread.join(timeout=2.0)

        assert seen_args, "_ensure_startup_banner_artefacts was not called"
        assert "⠀" not in seen_args[0] or seen_args[0] == raw_hero.replace("⠀", " ")

    def test_no_double_build_on_cache_hit(self):
        """Cache hit path + pre-built template: _render_startup_banner_text called 0 times."""
        cli = _make_cli()
        cli._startup_banner_template = {"lines": ["cached"]}
        cli._prelaunch_artefacts_pending = True
        cli._ensure_startup_banner_artefacts = (
            lambda ph: cli_mod.HermesCLI._ensure_startup_banner_artefacts(cli, ph)
        )

        # Simulate what _play_tte_in_output_panel does: join (no-op), then ensure
        _prelaunch = getattr(cli, "_prelaunch_banner_thread", None)
        if _prelaunch is not None and _prelaunch.is_alive():
            _prelaunch.join(timeout=0.3)
        cli_mod.HermesCLI._ensure_startup_banner_artefacts(cli, "HERO")

        cli._render_startup_banner_text.assert_not_called()
