"""Tests for hermes_cli/tui/osc_progress.py — OSC 9;4 terminal progress bar."""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from hermes_cli.tui.osc_progress import (
    _OSC_PROGRESS_END,
    _OSC_PROGRESS_START,
    _SUPPORTED_TERM_PROGRAMS,
    is_supported,
    osc_progress_end,
    osc_progress_start,
)


def _clean_env(**overrides):
    keys = {"HERMES_OSC_PROGRESS", "TERM_PROGRAM", "WT_SESSION"}
    base = {k: v for k, v in os.environ.items() if k not in keys}
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# is_supported()
# ---------------------------------------------------------------------------

def test_is_supported_env_override_1():
    with patch.dict("os.environ", _clean_env(HERMES_OSC_PROGRESS="1"), clear=True):
        assert is_supported() is True


def test_is_supported_env_override_0():
    with patch.dict("os.environ", _clean_env(HERMES_OSC_PROGRESS="0"), clear=True):
        assert is_supported() is False


@pytest.mark.parametrize("term", ["ghostty", "iterm.app", "rio", "wezterm"])
def test_is_supported_known_term_programs(term):
    with patch.dict("os.environ", _clean_env(TERM_PROGRAM=term), clear=True):
        assert is_supported() is True


def test_is_supported_unknown_term_program_returns_false():
    with patch.dict("os.environ", _clean_env(TERM_PROGRAM="xterm"), clear=True):
        assert is_supported() is False


def test_is_supported_windows_terminal_via_wt_session():
    with patch.dict("os.environ", _clean_env(WT_SESSION="some-guid"), clear=True):
        assert is_supported() is True


def test_is_supported_no_env_returns_false():
    with patch.dict("os.environ", _clean_env(), clear=True):
        assert is_supported() is False


def test_supported_term_programs_set_contains_expected():
    assert "ghostty" in _SUPPORTED_TERM_PROGRAMS
    assert "wezterm" in _SUPPORTED_TERM_PROGRAMS
    assert "iterm.app" in _SUPPORTED_TERM_PROGRAMS
    assert "rio" in _SUPPORTED_TERM_PROGRAMS


# ---------------------------------------------------------------------------
# osc_progress_start()
# ---------------------------------------------------------------------------

def test_osc_progress_start_writes_start_bytes_when_supported():
    with patch.dict("os.environ", _clean_env(HERMES_OSC_PROGRESS="1"), clear=True), \
         patch("os.write") as mock_write, \
         patch("sys.stdout") as mock_stdout:
        mock_stdout.fileno.return_value = 1
        osc_progress_start()
    mock_write.assert_called_once_with(1, _OSC_PROGRESS_START)


def test_osc_progress_start_no_op_when_not_supported():
    with patch.dict("os.environ", _clean_env(HERMES_OSC_PROGRESS="0"), clear=True), \
         patch("os.write") as mock_write:
        osc_progress_start()
    mock_write.assert_not_called()


def test_osc_progress_start_swallows_os_write_exception():
    with patch.dict("os.environ", _clean_env(HERMES_OSC_PROGRESS="1"), clear=True), \
         patch("os.write", side_effect=OSError("bad fd")), \
         patch("sys.stdout") as mock_stdout:
        mock_stdout.fileno.return_value = 1
        # Should not raise
        osc_progress_start()


# ---------------------------------------------------------------------------
# osc_progress_end()
# ---------------------------------------------------------------------------

def test_osc_progress_end_writes_end_bytes_when_supported():
    with patch.dict("os.environ", _clean_env(HERMES_OSC_PROGRESS="1"), clear=True), \
         patch("os.write") as mock_write, \
         patch("sys.stdout") as mock_stdout:
        mock_stdout.fileno.return_value = 1
        osc_progress_end()
    mock_write.assert_called_once_with(1, _OSC_PROGRESS_END)


def test_osc_progress_end_no_op_when_not_supported():
    with patch.dict("os.environ", _clean_env(HERMES_OSC_PROGRESS="0"), clear=True), \
         patch("os.write") as mock_write:
        osc_progress_end()
    mock_write.assert_not_called()


def test_osc_progress_end_swallows_os_write_exception():
    with patch.dict("os.environ", _clean_env(HERMES_OSC_PROGRESS="1"), clear=True), \
         patch("os.write", side_effect=OSError("bad fd")), \
         patch("sys.stdout") as mock_stdout:
        mock_stdout.fileno.return_value = 1
        osc_progress_end()


# ---------------------------------------------------------------------------
# Sequence byte values
# ---------------------------------------------------------------------------

def test_start_sequence_contains_indeterminate_code():
    assert b"9;4;3;" in _OSC_PROGRESS_START


def test_end_sequence_contains_clear_code():
    assert b"9;4;0;" in _OSC_PROGRESS_END


def test_sequences_are_bytes():
    assert isinstance(_OSC_PROGRESS_START, bytes)
    assert isinstance(_OSC_PROGRESS_END, bytes)
