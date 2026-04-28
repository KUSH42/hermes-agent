"""Regression tests for R2-H1 — ThinkingWidget hex-color leak.

Validates that _normalize_hex rejects non-hex CSS values (e.g. Textual's
"auto 87%" for the `text` variable) before they reach _parse_rgb.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.widgets.thinking import (
    _DEFAULT_ACCENT_HEX,
    _DEFAULT_TEXT_HEX,
    ThinkingWidget,
    _normalize_hex,
)

_LOGGER_NAME = "hermes_cli.tui.widgets.thinking"


# ── Isolated subclass (avoids PropertyMock session leakage) ───────────────────

class _ThinkingWithMockApp(ThinkingWidget):
    """Overrides the read-only `app` property for unit tests without a running App."""
    _mock_app: object = None

    @property  # type: ignore[override]
    def app(self):
        return self._mock_app


# ── _normalize_hex unit tests ─────────────────────────────────────────────────

def test_normalize_hex_accepts_six_char_with_hash():
    assert _normalize_hex("#ff0000", "#888888") == "#ff0000"


def test_normalize_hex_accepts_six_char_no_hash():
    assert _normalize_hex("ff0000", "#888888") == "#ff0000"


def test_normalize_hex_expands_three_char_shorthand():
    assert _normalize_hex("#abc", "#888888") == "#aabbcc"


def test_normalize_hex_rejects_textual_auto_value():
    # Regression test for R2-H1: "auto 87%" is Textual's default for `text`.
    assert _normalize_hex("auto 87%", "#ffffff") == "#ffffff"


# ── _refresh_colors integration tests ────────────────────────────────────────

def _make_widget(css_vars: dict | None = None, raises: Exception | None = None) -> _ThinkingWithMockApp:
    widget = _ThinkingWithMockApp.__new__(_ThinkingWithMockApp)
    widget._accent_hex = _DEFAULT_ACCENT_HEX
    widget._text_hex = _DEFAULT_TEXT_HEX
    mock_app = MagicMock()
    if raises is not None:
        mock_app.get_css_variables.side_effect = raises
    else:
        mock_app.get_css_variables.return_value = css_vars or {}
    widget._mock_app = mock_app
    return widget


def test_refresh_colors_uses_default_when_app_returns_auto(caplog):
    widget = _make_widget({"accent": "#FEA62B", "text": "auto 87%"})

    caplog.set_level(logging.WARNING, logger=_LOGGER_NAME)
    widget._refresh_colors()

    assert widget._text_hex == "#ffffff"
    assert widget._accent_hex == "#fea62b"
    assert caplog.records == [], f"Unexpected log records: {caplog.records}"


def test_refresh_colors_warns_on_get_css_variables_exception(caplog):
    widget = _make_widget(raises=RuntimeError("no css"))
    widget._accent_hex = "#123456"
    widget._text_hex = "#abcdef"

    caplog.set_level(logging.WARNING, logger=_LOGGER_NAME)
    widget._refresh_colors()

    assert widget._accent_hex == _DEFAULT_ACCENT_HEX
    assert widget._text_hex == _DEFAULT_TEXT_HEX
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "get_css_variables failed" in warnings[0].message
    assert warnings[0].exc_info is not None
