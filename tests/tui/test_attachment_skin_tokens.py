"""Tests for SPEC-X-DESIGN-TOKENS: attachment skin token coverage and usage.

Spec: /home/xush/.hermes/spec-x-design-tokens.md
"""
from __future__ import annotations

import logging
import pathlib
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).parents[2]

ALL_SKINS = [
    "ares", "catppuccin", "charizard", "hermes", "matrix",
    "mono", "poseidon", "sisyphus", "slate", "solarized-dark", "tokyo-night",
]

_REQUIRED_ATTACHMENT_TOKENS = frozenset({
    "attachment-chip-fg",
    "attachment-chip-bg",
    "attachment-chip-shimmer-dim",
    "attachment-chip-shimmer-peak",
    "attachment-chip-remove-fg",
})


def _make_mock_app(css_vars: "dict | None" = None) -> MagicMock:
    app = MagicMock()
    app.get_css_variables.return_value = css_vars or {}
    return app


def _inject_app(widget_instance: Any, mock_app: Any) -> Any:
    """Override the class-level app property for this widget's class."""
    cls = type(widget_instance)
    original = cls.__dict__.get("app")
    widget_instance._fake_app = mock_app
    cls.app = property(lambda self: self._fake_app)
    return original


def _restore_app(cls: type, original: Any) -> None:
    if original is not None:
        cls.app = original
    elif "app" in cls.__dict__:
        try:
            delattr(cls, "app")
        except AttributeError:
            pass


def _make_image_bar() -> Any:
    """Construct an ImageBar without mounting it in a real app."""
    from rich.text import Text
    from hermes_cli.tui.widgets.status_bar import ImageBar

    widget = ImageBar.__new__(ImageBar)
    widget._shimmer_timer = None
    widget._shimmer_base = None
    widget._shimmer_skip = []
    widget._static_content = Text()
    widget._tokens_checked = False
    # Satisfy Textual reactive internals — reactive descriptor checks for _id
    widget.__dict__["_id"] = "image-bar-mock"
    widget.__dict__["id"] = "image-bar-mock"
    widget.__dict__["_reactive_data"] = {}
    widget.__dict__["_shimmer_tick"] = 0
    return widget


# ---------------------------------------------------------------------------
# TestSkinTokenCoverage — X-DT-1 (1 test)
# ---------------------------------------------------------------------------

class TestSkinTokenCoverage:
    """X-DT-1 — All 11 bundled skin DESIGN.md files contain the five attachment tokens."""

    def test_design_tokens_present_in_all_bundled_skins(self) -> None:
        from hermes_cli.skin_engine import load_design_md_payload, _bundled_skins_dir

        skins_dir = _bundled_skins_dir()
        failures: list[str] = []
        for skin_name in ALL_SKINS:
            dm_path = skins_dir / skin_name / "DESIGN.md"
            payload = load_design_md_payload(dm_path)
            # attachment tokens land in component_vars (x-hermes.component-vars section)
            present = set(payload.component_vars.keys())
            missing = _REQUIRED_ATTACHMENT_TOKENS - present
            if missing:
                failures.append(
                    f"{skin_name}: missing keys {sorted(missing)}"
                )
        assert not failures, (
            "Skins missing attachment tokens (X-DT-1):\n" + "\n".join(failures)
        )


# ---------------------------------------------------------------------------
# TestDefaultCssTokenUsage — X-DT-2 (5 tests)
# ---------------------------------------------------------------------------

class TestDefaultCssTokenUsage:
    """X-DT-2 — _ATTACHMENT_CSS_DEFAULTS, ImageBar.render(), update_images() behaviour."""

    def test_attachment_chip_falls_back_to_defaults_when_token_missing(self) -> None:
        from hermes_cli.tui.widgets.status_bar import (
            _get_attachment_css_vars,
            _ATTACHMENT_CSS_DEFAULTS,
        )

        result = _get_attachment_css_vars({})
        assert result == _ATTACHMENT_CSS_DEFAULTS
        # All five keys must be present
        assert set(result.keys()) == set(_ATTACHMENT_CSS_DEFAULTS.keys())
        # Values must be hex strings, not $-alias literals
        for key, val in result.items():
            assert not val.startswith("$"), (
                f"{key}: value {val!r} is a literal alias, not resolved hex"
            )

    def test_image_bar_render_uses_attachment_shimmer_tokens(self) -> None:
        from rich.text import Text
        from hermes_cli.tui.widgets.status_bar import ImageBar

        widget = _make_image_bar()
        mock_app = _make_mock_app({
            "attachment-chip-shimmer-dim":  "#111111",
            "attachment-chip-shimmer-peak": "#eeeeee",
        })
        original = _inject_app(widget, mock_app)
        try:
            base = Text("📎 image.png")
            widget._shimmer_base = base
            widget._shimmer_timer = object()  # non-None sentinel

            captured: dict = {}

            def _fake_shimmer(text, tick, *, dim, peak, period, skip_ranges):
                captured["dim"] = dim
                captured["peak"] = peak
                return text

            with patch(
                "hermes_cli.tui.widgets.status_bar.shimmer_text",
                side_effect=_fake_shimmer,
            ):
                widget.render()

            assert captured.get("dim") == "#111111", (
                f"render() passed dim={captured.get('dim')!r}, expected '#111111'"
            )
            assert captured.get("peak") == "#eeeeee", (
                f"render() passed peak={captured.get('peak')!r}, expected '#eeeeee'"
            )
        finally:
            _restore_app(ImageBar, original)

    def test_image_bar_render_falls_back_when_no_attachment_tokens(self) -> None:
        from rich.text import Text
        from hermes_cli.tui.widgets.status_bar import ImageBar, _ATTACHMENT_CSS_DEFAULTS

        widget = _make_image_bar()
        mock_app = _make_mock_app({})  # no attachment tokens
        original = _inject_app(widget, mock_app)
        try:
            base = Text("📎 image.png")
            widget._shimmer_base = base
            widget._shimmer_timer = object()

            captured: dict = {}

            def _fake_shimmer(text, tick, *, dim, peak, period, skip_ranges):
                captured["dim"] = dim
                captured["peak"] = peak
                return text

            with patch(
                "hermes_cli.tui.widgets.status_bar.shimmer_text",
                side_effect=_fake_shimmer,
            ):
                widget.render()

            assert captured.get("dim") == _ATTACHMENT_CSS_DEFAULTS["attachment-chip-shimmer-dim"]
            assert captured.get("peak") == _ATTACHMENT_CSS_DEFAULTS["attachment-chip-shimmer-peak"]
        finally:
            _restore_app(ImageBar, original)

    def test_image_bar_update_images_uses_attachment_chip_fg(self) -> None:
        """X-DT-2: attachment-chip-fg token name is wired through the CSS pipeline.

        ImageBar now uses AttachmentChip children styled via CSS $-vars. Verify
        the token key name is present in _ATTACHMENT_CSS_DEFAULTS and that
        AttachmentChip.DEFAULT_CSS references it as a CSS variable.
        """
        from hermes_cli.tui.widgets.status_bar import (
            AttachmentChip,
            _ATTACHMENT_CSS_DEFAULTS,
        )

        assert "attachment-chip-fg" in _ATTACHMENT_CSS_DEFAULTS, (
            "attachment-chip-fg must be a key in _ATTACHMENT_CSS_DEFAULTS"
        )
        assert "attachment-chip-fg" in AttachmentChip.DEFAULT_CSS, (
            "AttachmentChip.DEFAULT_CSS must reference $attachment-chip-fg"
        )

    def test_attachment_chip_css_token_names_documented(self) -> None:
        from hermes_cli.tui.widgets.status_bar import _ATTACHMENT_CSS_DEFAULTS

        expected_keys = {
            "attachment-chip-fg",
            "attachment-chip-bg",
            "attachment-chip-shimmer-dim",
            "attachment-chip-shimmer-peak",
            "attachment-chip-remove-fg",
        }
        assert set(_ATTACHMENT_CSS_DEFAULTS.keys()) == expected_keys, (
            f"_ATTACHMENT_CSS_DEFAULTS keys mismatch: "
            f"got {set(_ATTACHMENT_CSS_DEFAULTS.keys())}, expected {expected_keys}"
        )


# ---------------------------------------------------------------------------
# TestLintGate — X-DT-3 (2 tests)
# ---------------------------------------------------------------------------

class TestLintGate:
    """X-DT-3 — _ATTACHMENT_REQUIRED_KEYS constant and _check_attachment_tokens helper."""

    def test_il_s1_required_keys_constant_matches_defaults(self) -> None:
        from hermes_cli.tui.widgets.status_bar import (
            _ATTACHMENT_REQUIRED_KEYS,
            _ATTACHMENT_CSS_DEFAULTS,
        )

        assert _ATTACHMENT_REQUIRED_KEYS == frozenset(_ATTACHMENT_CSS_DEFAULTS), (
            "_ATTACHMENT_REQUIRED_KEYS must equal frozenset(_ATTACHMENT_CSS_DEFAULTS). "
            "If a key is added to one, update the other (X-DT-3)."
        )

    def test_il_s1_warning_logged_when_token_missing_from_custom_skin(self) -> None:
        from hermes_cli.tui.widgets.status_bar import _check_attachment_tokens

        partial_vars = {"attachment-chip-fg": "#aaa"}  # four keys absent

        logger_name = "hermes_cli.tui.widgets.status_bar"
        with self._capture_warnings(logger_name) as records:
            _check_attachment_tokens(partial_vars, "ImageBar")

        assert len(records) == 4, (
            f"Expected exactly 4 warning records (one per missing key), got {len(records)}: "
            f"{[r.getMessage() for r in records]}"
        )
        warned_keys = {r.getMessage().split("'")[1] for r in records if "'" in r.getMessage()}
        expected_missing = {
            "attachment-chip-bg",
            "attachment-chip-shimmer-dim",
            "attachment-chip-shimmer-peak",
            "attachment-chip-remove-fg",
        }
        assert warned_keys == expected_missing, (
            f"Warned keys {warned_keys} != expected {expected_missing}"
        )

    @staticmethod
    def _capture_warnings(logger_name: str):
        """Context manager: capture WARNING-level log records from a named logger."""
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            handler = logging.handlers_list = []
            capturing = logging.handlers.MemoryHandler if False else None

            class _Capture(logging.Handler):
                def __init__(self):
                    super().__init__(level=logging.WARNING)
                    self.records: list[logging.LogRecord] = []

                def emit(self, record: logging.LogRecord) -> None:
                    self.records.append(record)

            cap = _Capture()
            log = logging.getLogger(logger_name)
            log.addHandler(cap)
            try:
                yield cap.records
            finally:
                log.removeHandler(cap)

        return _ctx()
