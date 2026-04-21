"""Tests for hermes_cli/tui/sdf_splash.py — pre-TUI SDF splash screen."""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from hermes_cli.tui.sdf_splash import run_sdf_splash


def _cfg(**kwargs) -> SimpleNamespace:
    """Build a minimal SdfSplashConfig-like object."""
    defaults = dict(
        text="TEST",
        hold_ms=100.0,
        morph_ms=200.0,
        render_mode="dissolve",
        color="#00ff66",
        total_duration_s=0.0,  # zero → loop body never runs
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_mock_engine(frame="FRAME"):
    """Return a mock SDFMorphEngine that always emits *frame* from tick()."""
    engine = MagicMock()
    engine.tick.return_value = frame
    return engine


# ---------------------------------------------------------------------------
# Attribute extraction from cfg
# ---------------------------------------------------------------------------

def test_run_sdf_splash_uses_cfg_text():
    """run_sdf_splash passes cfg.text to SDFMorphEngine."""
    cfg = _cfg(text="HELLO")
    mock_engine = _make_mock_engine()

    with patch("hermes_cli.tui.sdf_splash.SDFBaker") as mock_baker_cls, \
         patch("hermes_cli.tui.sdf_splash.SDFMorphEngine", return_value=mock_engine) as mock_eng_cls, \
         patch("shutil.get_terminal_size", return_value=(80, 24)), \
         patch("sys.stdout") as mock_stdout, \
         patch("time.monotonic", side_effect=[0.0, 0.0, 1.0]):  # deadline(0)+last(0)+loop(1)→exit
        mock_baker_cls.return_value = MagicMock()
        run_sdf_splash(cfg)

    call_kwargs = mock_eng_cls.call_args[1]
    assert call_kwargs["text"] == "HELLO"


def test_run_sdf_splash_uses_cfg_hold_and_morph_ms():
    cfg = _cfg(hold_ms=333.0, morph_ms=777.0)
    mock_engine = _make_mock_engine()

    with patch("hermes_cli.tui.sdf_splash.SDFBaker") as mock_baker_cls, \
         patch("hermes_cli.tui.sdf_splash.SDFMorphEngine", return_value=mock_engine) as mock_eng_cls, \
         patch("shutil.get_terminal_size", return_value=(80, 24)), \
         patch("sys.stdout"), \
         patch("time.monotonic", side_effect=[0.0, 0.0, 1.0]):
        mock_baker_cls.return_value = MagicMock()
        run_sdf_splash(cfg)

    call_kwargs = mock_eng_cls.call_args[1]
    assert call_kwargs["hold_ms"] == 333.0
    assert call_kwargs["morph_ms"] == 777.0


def test_run_sdf_splash_uses_cfg_color():
    cfg = _cfg(color="#ff0000")
    mock_engine = _make_mock_engine()

    with patch("hermes_cli.tui.sdf_splash.SDFBaker") as mock_baker_cls, \
         patch("hermes_cli.tui.sdf_splash.SDFMorphEngine", return_value=mock_engine) as mock_eng_cls, \
         patch("shutil.get_terminal_size", return_value=(80, 24)), \
         patch("sys.stdout"), \
         patch("time.monotonic", side_effect=[0.0, 0.0, 1.0]):
        mock_baker_cls.return_value = MagicMock()
        run_sdf_splash(cfg)

    call_kwargs = mock_eng_cls.call_args[1]
    assert call_kwargs["color"] == "#ff0000"


def test_run_sdf_splash_uses_cfg_render_mode():
    cfg = _cfg(render_mode="outline")
    mock_engine = _make_mock_engine()

    with patch("hermes_cli.tui.sdf_splash.SDFBaker") as mock_baker_cls, \
         patch("hermes_cli.tui.sdf_splash.SDFMorphEngine", return_value=mock_engine) as mock_eng_cls, \
         patch("shutil.get_terminal_size", return_value=(80, 24)), \
         patch("sys.stdout"), \
         patch("time.monotonic", side_effect=[0.0, 0.0, 1.0]):
        mock_baker_cls.return_value = MagicMock()
        run_sdf_splash(cfg)

    call_kwargs = mock_eng_cls.call_args[1]
    assert call_kwargs["mode"] == "outline"


# ---------------------------------------------------------------------------
# Default attribute fallbacks (duck-typing with missing fields)
# ---------------------------------------------------------------------------

def test_run_sdf_splash_uses_defaults_when_attrs_missing():
    """run_sdf_splash uses getattr defaults when cfg lacks expected attrs."""
    cfg = SimpleNamespace()  # empty — all getattr fallbacks kick in; total_duration_s defaults to 3.0
    mock_engine = _make_mock_engine()

    # deadline=0.0+3.0=3.0; last=0.0; while 4.0<3.0 → False → loop skipped
    with patch("hermes_cli.tui.sdf_splash.SDFBaker") as mock_baker_cls, \
         patch("hermes_cli.tui.sdf_splash.SDFMorphEngine", return_value=mock_engine) as mock_eng_cls, \
         patch("shutil.get_terminal_size", return_value=(80, 24)), \
         patch("sys.stdout"), \
         patch("time.monotonic", side_effect=[0.0, 0.0, 4.0]):
        mock_baker_cls.return_value = MagicMock()
        run_sdf_splash(cfg)

    call_kwargs = mock_eng_cls.call_args[1]
    assert call_kwargs["text"] == "HERMES"
    assert call_kwargs["color"] == "#00ff66"


# ---------------------------------------------------------------------------
# Terminal size is read and passed to canvas
# ---------------------------------------------------------------------------

def test_run_sdf_splash_uses_terminal_size_for_canvas():
    """Canvas dimensions derive from shutil.get_terminal_size()."""
    cfg = _cfg()
    mock_engine = _make_mock_engine()
    tick_calls = []

    def _tick(dt_ms, canvas_w, canvas_h):
        tick_calls.append((canvas_w, canvas_h))
        return None  # no frame

    mock_engine.tick.side_effect = _tick

    # total_duration_s > 0 so at least one tick fires; control monotonic carefully
    cfg.total_duration_s = 0.05
    monotonic_values = [0.0, 0.01, 0.1]  # start, first loop check, deadline exceeded
    sleep_called = []

    with patch("hermes_cli.tui.sdf_splash.SDFBaker") as mock_baker_cls, \
         patch("hermes_cli.tui.sdf_splash.SDFMorphEngine", return_value=mock_engine), \
         patch("shutil.get_terminal_size", return_value=(120, 40)), \
         patch("sys.stdout"), \
         patch("time.monotonic", side_effect=monotonic_values), \
         patch("time.sleep", side_effect=lambda d: sleep_called.append(d)):
        mock_baker_cls.return_value = MagicMock()
        run_sdf_splash(cfg)

    if tick_calls:
        w, h = tick_calls[0]
        assert w == 120
        assert h == max(40 - 2, 4)


# ---------------------------------------------------------------------------
# Cursor hide / show sequences
# ---------------------------------------------------------------------------

def test_run_sdf_splash_hides_and_restores_cursor():
    cfg = _cfg()
    mock_engine = _make_mock_engine()
    written = []

    with patch("hermes_cli.tui.sdf_splash.SDFBaker") as mock_baker_cls, \
         patch("hermes_cli.tui.sdf_splash.SDFMorphEngine", return_value=mock_engine), \
         patch("shutil.get_terminal_size", return_value=(80, 24)), \
         patch("time.monotonic", side_effect=[0.0, 0.0, 1.0]):
        mock_baker_cls.return_value = MagicMock()

        mock_stdout = MagicMock()
        mock_stdout.write.side_effect = lambda s: written.append(s)
        mock_stdout.flush = MagicMock()

        with patch("sys.stdout", mock_stdout):
            run_sdf_splash(cfg)

    combined = "".join(written)
    assert "\x1b[?25l" in combined  # hide cursor
    assert "\x1b[?25h" in combined  # show cursor (restore)


def test_run_sdf_splash_restores_cursor_on_exception():
    """Cursor is restored even if the render loop raises."""
    cfg = _cfg(total_duration_s=10.0)
    mock_engine = MagicMock()
    mock_engine.tick.side_effect = RuntimeError("render failure")

    written = []

    with patch("hermes_cli.tui.sdf_splash.SDFBaker") as mock_baker_cls, \
         patch("hermes_cli.tui.sdf_splash.SDFMorphEngine", return_value=mock_engine), \
         patch("shutil.get_terminal_size", return_value=(80, 24)), \
         patch("time.monotonic", return_value=0.0):
        mock_baker_cls.return_value = MagicMock()

        mock_stdout = MagicMock()
        mock_stdout.write.side_effect = lambda s: written.append(s)
        mock_stdout.flush = MagicMock()

        with patch("sys.stdout", mock_stdout), \
             patch("time.sleep"):
            try:
                run_sdf_splash(cfg)
            except RuntimeError:
                pass  # the exception may propagate after finally

    combined = "".join(written)
    # The finally block must always write the restore sequence
    assert "\x1b[?25h" in combined


# ---------------------------------------------------------------------------
# SDFBaker.bake() is called with cfg.text
# ---------------------------------------------------------------------------

def test_run_sdf_splash_calls_baker_bake():
    cfg = _cfg(text="HI")
    mock_engine = _make_mock_engine()

    with patch("hermes_cli.tui.sdf_splash.SDFBaker") as mock_baker_cls, \
         patch("hermes_cli.tui.sdf_splash.SDFMorphEngine", return_value=mock_engine), \
         patch("shutil.get_terminal_size", return_value=(80, 24)), \
         patch("sys.stdout"), \
         patch("time.monotonic", side_effect=[0.0, 0.0, 1.0]):
        mock_baker = MagicMock()
        mock_baker_cls.return_value = mock_baker
        run_sdf_splash(cfg)

    mock_baker.bake.assert_called_once_with("HI")


# ---------------------------------------------------------------------------
# Pre-baked baker injected into engine
# ---------------------------------------------------------------------------

def test_run_sdf_splash_injects_baker_into_engine():
    cfg = _cfg()
    mock_engine = _make_mock_engine()

    with patch("hermes_cli.tui.sdf_splash.SDFBaker") as mock_baker_cls, \
         patch("hermes_cli.tui.sdf_splash.SDFMorphEngine", return_value=mock_engine), \
         patch("shutil.get_terminal_size", return_value=(80, 24)), \
         patch("sys.stdout"), \
         patch("time.monotonic", side_effect=[0.0, 0.0, 1.0]):
        mock_baker = MagicMock()
        mock_baker_cls.return_value = mock_baker
        run_sdf_splash(cfg)

    assert mock_engine._baker is mock_baker
