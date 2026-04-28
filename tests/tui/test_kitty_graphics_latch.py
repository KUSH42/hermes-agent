"""Tests for the _tty_unavailable latch in kitty_graphics.py.

Kept separate from test_kitty_graphics.py because that file has a module-level
pytestmark that silently skips all tests when PIL is absent. The latch tests
have zero PIL dependency and must always run.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui import kitty_graphics


def test_apc_probe_short_circuits_when_latched(monkeypatch):
    monkeypatch.setattr(kitty_graphics, "_tty_unavailable", True)
    with patch("termios.tcgetattr") as mock_tca:
        result = kitty_graphics._apc_probe()
    assert result is False
    mock_tca.assert_not_called()


def test_sixel_probe_short_circuits_when_latched(monkeypatch):
    monkeypatch.setattr(kitty_graphics, "_tty_unavailable", True)
    with patch("termios.tcgetattr") as mock_tca:
        result = kitty_graphics._sixel_probe()
    assert result is False
    mock_tca.assert_not_called()


def test_probes_emit_no_log_calls_when_latched(monkeypatch):
    monkeypatch.setattr(kitty_graphics, "_tty_unavailable", True)
    mock_log = MagicMock()
    monkeypatch.setattr(kitty_graphics, "_log", mock_log)
    kitty_graphics._apc_probe()
    kitty_graphics._sixel_probe()
    assert mock_log.debug.call_count == 0
    assert mock_log.exception.call_count == 0
