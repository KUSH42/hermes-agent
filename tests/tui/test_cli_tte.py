"""Tests for TTE producer exception handling (R7-T-L1).

Tests call HermesCLI._handle_tte_producer_exc() directly — no Textual app,
no Pilot, no full TTE run needed.

Run with:
    pytest -o "addopts=" tests/tui/test_cli_tte.py -v
"""

from __future__ import annotations

import concurrent.futures
import logging

import pytest


class TestTteProducerTeardown:
    def test_runtime_error_event_loop_closed_demoted_to_debug(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from cli import HermesCLI

        exc = RuntimeError("Event loop is closed")
        with caplog.at_level(logging.DEBUG, logger="cli"):
            HermesCLI._handle_tte_producer_exc(exc)

        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        debug_records = [
            r for r in caplog.records
            if r.levelno == logging.DEBUG and "closed loop at teardown" in r.message
        ]
        assert not warning_records, (
            f"Expected zero WARNING records; got {warning_records}"
        )
        assert debug_records, "Expected ≥1 DEBUG record matching 'closed loop at teardown'"

    def test_runtime_error_other_message_still_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from cli import HermesCLI

        exc = RuntimeError("something else broke")
        with caplog.at_level(logging.DEBUG, logger="cli"):
            HermesCLI._handle_tte_producer_exc(exc)

        warning_records = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "something else broke" in r.message
        ]
        assert warning_records, (
            "Expected ≥1 WARNING record containing 'something else broke'"
        )
