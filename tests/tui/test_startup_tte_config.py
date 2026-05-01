from __future__ import annotations

import asyncio
import concurrent.futures
import importlib
import inspect
import logging
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from rich.text import Text


def _load_cli_module():
    import cli as cli_module

    return importlib.reload(cli_module)


def _run_coro(coro) -> None:
    """Drive a coroutine that makes no async I/O to completion without an event loop.

    Uses .send(None) so asyncio never calls time.monotonic() internally — safe when
    time.monotonic is mocked with a finite side_effect list.
    """
    try:
        coro.send(None)
    except StopIteration:
        pass


def _sync_call_from_thread(fn, *args, **kwargs):
    result = fn(*args, **kwargs)
    if inspect.isawaitable(result):
        _run_coro(result)
    return result


def _make_draining_call_from_thread(app_mock):
    """Install set_interval + call_from_thread side effects that drain ticks synchronously."""
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
        r = fn(*a, **kw)
        if inspect.isawaitable(r):
            _run_coro(r)
        while _tick_fn and not _stop[0]:
            tick_r = _tick_fn[0]()
            if inspect.isawaitable(tick_r):
                _run_coro(tick_r)
        return r

    app_mock.call_from_thread.side_effect = _call_from_thread_side_effect


def _bind_cli(cli_module):
    cli = MagicMock()
    cli._get_startup_text_effect_config = (
        cli_module.HermesCLI._get_startup_text_effect_config.__get__(cli)
    )
    cli._play_tte_in_output_panel = (
        cli_module.HermesCLI._play_tte_in_output_panel.__get__(cli)
    )
    cli._ensure_startup_banner_artefacts = (
        cli_module.HermesCLI._ensure_startup_banner_artefacts.__get__(cli)
    )
    cli._build_startup_banner_template = MagicMock(return_value=None)
    cli._render_startup_banner_text = MagicMock(return_value=Text("static"))
    cli._splice_startup_banner_frame = MagicMock(side_effect=lambda *_: Text("frame"))
    cli._startup_banner_template = None
    cli._startup_banner_static = None
    return cli


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


class TestConfigResolution:
    def test_default_max_wall_s_is_30s(self):
        cli_module = _load_cli_module()
        cli = _bind_cli(cli_module)
        cli.config = {
            "tui": {},
            "display": {"startup_text_effect": {"enabled": True, "effect": "matrix"}},
        }

        result = cli._get_startup_text_effect_config()

        assert result is not None
        assert result.max_wall_s == 30.0

    def test_max_wall_s_clamped_to_range(self, caplog: pytest.LogCaptureFixture):
        cli_module = _load_cli_module()
        cli = _bind_cli(cli_module)
        cli.config = {
            "tui": {},
            "display": {
                "startup_text_effect": {
                    "enabled": True,
                    "effect": "matrix",
                    "max_wall_s": 9999,
                }
            },
        }

        with caplog.at_level(logging.WARNING, logger="cli"):
            result = cli._get_startup_text_effect_config()

        assert result is not None
        assert result.max_wall_s == 600.0
        assert "max_wall_s=9999" in caplog.text

    def test_fps_clamped_below_one_to_one(self, caplog: pytest.LogCaptureFixture):
        cli_module = _load_cli_module()
        cli = _bind_cli(cli_module)
        cli.config = {
            "tui": {},
            "display": {
                "startup_text_effect": {
                    "enabled": True,
                    "effect": "matrix",
                    "fps": 0,
                }
            },
        }

        with caplog.at_level(logging.WARNING, logger="cli"):
            result = cli._get_startup_text_effect_config()

        assert result is not None
        assert result.fps == 1
        assert "fps=0" in caplog.text

    def test_fps_clamped_above_max_to_240(self, caplog: pytest.LogCaptureFixture):
        cli_module = _load_cli_module()
        cli = _bind_cli(cli_module)
        cli.config = {
            "tui": {},
            "display": {
                "startup_text_effect": {
                    "enabled": True,
                    "effect": "matrix",
                    "fps": 999,
                }
            },
        }

        with caplog.at_level(logging.WARNING, logger="cli"):
            result = cli._get_startup_text_effect_config()

        assert result is not None
        assert result.fps == 240
        assert "fps=999" in caplog.text

    def test_producer_loop_honours_configured_caps(self):
        cli_module = _load_cli_module()
        cli = _bind_cli(cli_module)
        widget = SimpleNamespace(frames=[])
        widget.set_frame = widget.frames.append
        app = MagicMock()
        app.is_running = True
        app.query_one.return_value = widget
        _make_draining_call_from_thread(app)
        app.call_later.side_effect = _sync_call_from_thread
        frame_counter = {"seen": 0}

        def _frames(_name, _text, params=None):
            while True:
                frame_counter["seen"] += 1
                yield f"frame-{frame_counter['seen']}"

        start = time.monotonic()
        with patch.object(cli_module, "_hermes_app", app), patch(
            "hermes_cli.tui.widgets.STARTUP_BANNER_READY.wait", return_value=True
        ), patch(
            "hermes_cli.tui.widgets.OUTPUT_PANEL_WIDTH_READY.wait", return_value=True
        ), patch(
            "hermes_cli.tui.widgets.STARTUP_TTE_SKIP.is_set", return_value=False
        ), patch(
            "hermes_cli.tui.tte_runner.iter_frames", side_effect=_frames
        ), patch(
            "cli.time.sleep", return_value=None
        ), patch(
            "cli.time.monotonic", side_effect=[0.0] * 20
        ):
            rendered = cli._play_tte_in_output_panel(
                _tte_cfg(cli_module, max_wall_s=0.5, max_frames=5),
                "hero",
            )
        elapsed = time.monotonic() - start

        assert rendered is True
        assert elapsed < 0.6
        animated_frames = [frame.plain for frame in widget.frames if frame.plain == "frame"]
        assert len(animated_frames) <= 5


class TestFpsPacing:
    def test_frame_interval_uses_configured_fps(self):
        cli_module = _load_cli_module()
        cfg = _tte_cfg(cli_module, fps=30)

        interval = 1.0 / max(1, cfg.fps)

        assert interval == pytest.approx(1.0 / 30.0)


class TestProducerExceptionRouting:
    def test_cancelled_error_logs_debug(self, caplog: pytest.LogCaptureFixture):
        cli_module = _load_cli_module()

        with caplog.at_level(logging.DEBUG, logger="cli"):
            cli_module.HermesCLI._handle_tte_producer_exc(
                concurrent.futures.CancelledError()
            )

        assert any(
            record.levelno == logging.DEBUG
            and "cancelled at teardown" in record.message
            for record in caplog.records
        )

    @pytest.mark.parametrize(
        "message",
        [
            "Event loop is closed",
            "no running event loop",
            "There is no current event loop in thread 'x'",
        ],
    )
    def test_loop_teardown_runtime_errors_log_debug(
        self,
        message: str,
        caplog: pytest.LogCaptureFixture,
    ):
        cli_module = _load_cli_module()

        with caplog.at_level(logging.DEBUG, logger="cli"):
            cli_module.HermesCLI._handle_tte_producer_exc(RuntimeError(message))

        assert any(
            record.levelno == logging.DEBUG and "loop teardown" in record.message
            for record in caplog.records
        )
        assert not any(
            record.name == "cli" and record.levelno >= logging.WARNING
            for record in caplog.records
        )

    def test_unrelated_runtime_error_logs_warning(
        self,
        caplog: pytest.LogCaptureFixture,
    ):
        cli_module = _load_cli_module()

        with caplog.at_level(logging.DEBUG, logger="cli"):
            cli_module.HermesCLI._handle_tte_producer_exc(RuntimeError("disk full"))

        assert any(
            record.levelno == logging.WARNING and "disk full" in record.message
            for record in caplog.records
        )

    def test_arbitrary_exception_logs_warning(
        self,
        caplog: pytest.LogCaptureFixture,
    ):
        cli_module = _load_cli_module()

        with caplog.at_level(logging.DEBUG, logger="cli"):
            cli_module.HermesCLI._handle_tte_producer_exc(ValueError("x"))

        assert any(
            record.levelno == logging.WARNING and "x" in record.message
            for record in caplog.records
        )


class TestTteMissingDiagnostics:
    @pytest.fixture(autouse=True)
    def reset_tte_missing_flag(self, monkeypatch):
        from hermes_cli.tui import tte_runner

        monkeypatch.setattr(tte_runner, "_TTE_MISSING_LOGGED", False)

    def test_iter_frames_logs_info_when_tte_missing(
        self,
        caplog: pytest.LogCaptureFixture,
    ):
        from hermes_cli.tui import tte_runner

        with patch("importlib.import_module", side_effect=ImportError("missing")):
            with caplog.at_level(logging.INFO, logger="hermes_cli.tui.tte_runner"):
                list(tte_runner.iter_frames("matrix", "Hermes"))

        info_records = [
            record
            for record in caplog.records
            if record.levelno == logging.INFO
        ]
        assert len(info_records) == 1
        assert "terminaltexteffects is not installed" in info_records[0].message

    def test_iter_frames_logs_only_once_per_process(
        self,
        caplog: pytest.LogCaptureFixture,
    ):
        from hermes_cli.tui import tte_runner

        with patch("importlib.import_module", side_effect=ImportError("missing")):
            with caplog.at_level(logging.INFO, logger="hermes_cli.tui.tte_runner"):
                list(tte_runner.iter_frames("matrix", "Hermes"))
                list(tte_runner.iter_frames("matrix", "Hermes"))

        info_records = [
            record
            for record in caplog.records
            if record.levelno == logging.INFO
        ]
        assert len(info_records) == 1
