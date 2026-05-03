"""Tests for CSS-1..CSS-7 + IL-S1 skin/CSS-var diagnostic logging gate.

Spec: /home/xush/.hermes/spec_css_skin_var_diagnostics.md
"""
from __future__ import annotations

import logging
import pathlib
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).parents[2]
_TUI_ROOT = _REPO_ROOT / "hermes_cli" / "tui"


def _make_mock_app(css_vars: "dict | None" = None, raise_exc: "Exception | None" = None) -> MagicMock:
    """Create a mock app whose get_css_variables() either returns css_vars or raises."""
    app = MagicMock()
    if raise_exc is not None:
        app.get_css_variables.side_effect = raise_exc
    else:
        app.get_css_variables.return_value = css_vars or {}
    return app


def _inject_app(widget_instance: Any, mock_app: Any) -> "property | None":
    """Inject a mock app into a widget whose `app` is a read-only Textual property.

    Overrides the class-level property with a simple lambda for this instance type.
    Returns the original property so callers can restore it.
    """
    cls = type(widget_instance)
    original = cls.__dict__.get("app")
    # Store mock_app as _fake_app so the lambda can close over it stably
    widget_instance._fake_app = mock_app
    cls.app = property(lambda self: self._fake_app)
    return original


def _restore_app(cls: type, original: Any) -> None:
    """Restore the app property on cls after a test."""
    if original is not None:
        cls.app = original
    elif "app" in cls.__dict__:
        try:
            delattr(cls, "app")
        except AttributeError:
            pass


# ---------------------------------------------------------------------------
# CSS-1: AssistantNameplate / TestNameplateSkinDiagnostics
# ---------------------------------------------------------------------------

class TestNameplateSkinDiagnostics:
    """CSS-1 — AssistantNameplate logs warnings on get_css_variables() failure."""

    def _make_nameplate(self, raise_exc: "Exception | None" = None) -> "tuple[Any, Any]":
        """Return (widget, original_app_property) with patched app."""
        from hermes_cli.tui.widgets import AssistantNameplate  # type: ignore[attr-defined]

        widget = AssistantNameplate.__new__(AssistantNameplate)
        widget._accent_hex = "#7C3AED"
        widget._text_hex = "#E0E0E0"
        widget._active_style = None
        widget._idle_color_hex = "#ffffff"
        widget._error_color_hex = "#ef5350"
        widget._decrypt_style = None
        widget._morph_dim_style = None

        mock_app = _make_mock_app(raise_exc=raise_exc)
        original = _inject_app(widget, mock_app)
        return widget, original

    def test_nameplate_logs_warning_on_get_css_variables_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        """refresh_skin_colors emits _log.warning with exc_info on get_css_variables() failure."""
        from hermes_cli.tui.widgets import AssistantNameplate
        widget, orig = self._make_nameplate(raise_exc=RuntimeError("skin broken"))
        try:
            with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.widgets"):
                try:
                    widget.refresh_skin_colors()
                except Exception:
                    pass  # refresh() may fail without DOM — only care about log
            warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
            assert any(r.exc_info for r in warning_records), (
                "Expected at least one WARNING with exc_info on get_css_variables() failure; "
                f"got records: {[r.getMessage() for r in caplog.records]}"
            )
        finally:
            _restore_app(AssistantNameplate, orig)

    def test_nameplate_set_tier_logs_on_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        """set_tier emits _log.warning with exc_info on get_css_variables() failure."""
        from hermes_cli.tui.widgets import AssistantNameplate
        widget, orig = self._make_nameplate(raise_exc=RuntimeError("skin broken"))
        try:
            with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.widgets"):
                try:
                    widget.set_tier("primary")
                except Exception:
                    pass
            warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
            assert any(r.exc_info for r in warning_records), (
                "Expected at least one WARNING with exc_info from set_tier; "
                f"got records: {[r.getMessage() for r in caplog.records]}"
            )
        finally:
            _restore_app(AssistantNameplate, orig)

    def test_nameplate_falls_back_when_css_vars_raises(self, caplog: pytest.LogCaptureFixture) -> None:
        """After get_css_variables() raises, a warning is logged and widget state remains valid."""
        from hermes_cli.tui.widgets import AssistantNameplate
        widget, orig = self._make_nameplate(raise_exc=RuntimeError("bad skin"))
        try:
            with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.widgets"):
                try:
                    widget.refresh_skin_colors()
                except Exception:
                    pass
            assert widget._accent_hex == "#7C3AED"
            assert any(r.levelno >= logging.WARNING for r in caplog.records)
        finally:
            _restore_app(AssistantNameplate, orig)


# ---------------------------------------------------------------------------
# CSS-2: ThemeService.populate_slash_commands / TestSlashCommandLogging
# ---------------------------------------------------------------------------

class TestSlashCommandLogging:
    """CSS-2 — populate_slash_commands logs warning on unexpected exception."""

    def test_populate_slash_commands_logs_on_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        from hermes_cli.tui.services.theme import ThemeService

        svc = ThemeService.__new__(ThemeService)
        mock_app = MagicMock()
        svc.app = mock_app  # type: ignore[attr-defined]

        import hermes_cli.commands as _cmds
        original_reg = getattr(_cmds, "COMMAND_REGISTRY", None)
        _cmds.COMMAND_REGISTRY = _FailingIterable()  # type: ignore[attr-defined]
        try:
            with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.services.theme"):
                svc.populate_slash_commands()
        finally:
            if original_reg is not None:
                _cmds.COMMAND_REGISTRY = original_reg

        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(
            "populate_slash_commands" in r.getMessage() for r in warning_records
        ), f"Expected warning about populate_slash_commands; got: {[r.getMessage() for r in warning_records]}"
        assert any(r.exc_info for r in warning_records)


class _FailingIterable:
    """An iterable that raises RuntimeError on the first __iter__ call."""
    def __iter__(self):
        raise RuntimeError("COMMAND_REGISTRY broken during test")


# ---------------------------------------------------------------------------
# CSS-3: IOService.play_effects_blocking / TestPlayEffectsLogging
# ---------------------------------------------------------------------------

class TestPlayEffectsLogging:
    """CSS-3 — play_effects_blocking logs on timeout and on other exceptions."""

    def _make_svc(self) -> Any:
        from hermes_cli.tui.services.io import IOService
        svc = IOService.__new__(IOService)
        mock_app = MagicMock()
        mock_app._event_loop = MagicMock()
        svc.app = mock_app  # type: ignore[attr-defined]
        return svc

    def test_play_effects_blocking_logs_timeout(self, caplog: pytest.LogCaptureFixture) -> None:
        import concurrent.futures

        svc = self._make_svc()
        future = MagicMock()
        future.result.side_effect = concurrent.futures.TimeoutError()

        with (
            caplog.at_level(logging.WARNING, logger="hermes_cli.tui.services.io"),
            patch("asyncio.run_coroutine_threadsafe", return_value=future),
        ):
            result = svc.play_effects_blocking("fade", "hello")

        assert result is False
        timeout_records = [r for r in caplog.records if "timed out" in r.getMessage()]
        assert timeout_records, f"Expected a warning containing 'timed out'; got {[r.getMessage() for r in caplog.records]}"
        # TimeoutError should NOT include exc_info
        assert not any(r.exc_info for r in timeout_records)

    def test_play_effects_blocking_logs_other_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        svc = self._make_svc()
        future = MagicMock()
        future.result.side_effect = ValueError("unexpected")

        with (
            caplog.at_level(logging.WARNING, logger="hermes_cli.tui.services.io"),
            patch("asyncio.run_coroutine_threadsafe", return_value=future),
        ):
            result = svc.play_effects_blocking("fade", "hello")

        assert result is False
        exc_records = [r for r in caplog.records if r.exc_info]
        assert exc_records, "Expected a warning with exc_info for ValueError"


# ---------------------------------------------------------------------------
# CSS-4: HintBar._get_key_color / TestStatusBarKeyColor
# ---------------------------------------------------------------------------

class TestStatusBarKeyColor:
    """CSS-4 — HintBar._get_key_color logs at DEBUG on get_css_variables() failure."""

    def test_get_key_color_logs_at_debug_on_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        from hermes_cli.tui.widgets.status_bar import HintBar

        widget = HintBar.__new__(HintBar)
        mock_app = _make_mock_app(raise_exc=RuntimeError("css vars broken"))
        original = _inject_app(widget, mock_app)
        try:
            with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.widgets.status_bar"):
                result = widget._get_key_color()
        finally:
            _restore_app(HintBar, original)

        assert result == "#5f87d7", f"Expected fallback hex; got {result!r}"
        debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG and r.exc_info]
        assert debug_records, "Expected a DEBUG record with exc_info from _get_key_color"


# ---------------------------------------------------------------------------
# CSS-5: DrawbrailleOverlay watchers / TestDrawbrailleWatchers
# ---------------------------------------------------------------------------

class TestDrawbrailleWatchers:
    """CSS-5 — DrawbrailleOverlay watchers log DEBUG on resolve failure."""

    def _make_overlay(self, fail_on_query: "Exception | None" = None) -> "tuple[Any, Any]":
        from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay

        overlay = DrawbrailleOverlay.__new__(DrawbrailleOverlay)
        overlay._renderer = None
        mock_app = MagicMock()
        if fail_on_query is not None:
            mock_app.query.side_effect = fail_on_query
        original = _inject_app(overlay, mock_app)
        overlay.__dict__["color"] = "#ff0000"
        overlay.__dict__["color_b"] = "#00ff00"
        overlay.__dict__["multi_color"] = []
        return overlay, original

    def test_watch_color_logs_on_resolve_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay

        overlay, orig = self._make_overlay()
        try:
            with (
                caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.drawbraille_overlay"),
                patch.object(overlay, "_ensure_renderer", side_effect=ValueError("renderer not ready")),
            ):
                overlay.watch_color("#bad")

            debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG and r.exc_info]
            assert debug_records, "Expected DEBUG with exc_info from watch_color on failure"
        finally:
            _restore_app(DrawbrailleOverlay, orig)

    def test_has_nameplate_narrow_swallow_for_nomatches(self, caplog: pytest.LogCaptureFixture) -> None:
        """NoMatches → False with no debug log; other Exception → False with DEBUG log."""
        from textual.css.query import NoMatches
        from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay

        # Case 1: NoMatches should be silent
        overlay, orig = self._make_overlay(fail_on_query=NoMatches())
        try:
            with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.drawbraille_overlay"):
                result_nomatches = overlay._has_nameplate()
            assert result_nomatches is False
            assert not any(r.levelno == logging.DEBUG for r in caplog.records), (
                "NoMatches in _has_nameplate should NOT produce a debug log"
            )
        finally:
            _restore_app(DrawbrailleOverlay, orig)
            caplog.clear()

        # Case 2: unexpected Exception should produce a DEBUG log
        overlay2, orig2 = self._make_overlay(fail_on_query=OSError("unexpected DOM error"))
        try:
            with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.drawbraille_overlay"):
                result_exc = overlay2._has_nameplate()
            assert result_exc is False
            debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG and r.exc_info]
            assert debug_records, "Expected DEBUG with exc_info from _has_nameplate on unexpected Exception"
        finally:
            _restore_app(DrawbrailleOverlay, orig2)


# ---------------------------------------------------------------------------
# CSS-6: ThemeService.refresh_slash_commands / TestThemeRefreshSplit
# ---------------------------------------------------------------------------

class TestThemeRefreshSplit:
    """CSS-6 — refresh_slash_commands: NoMatches is silent; other Exception logs warning."""

    def _make_svc(self) -> Any:
        from hermes_cli.tui.services.theme import ThemeService
        svc = ThemeService.__new__(ThemeService)
        svc.app = MagicMock()  # type: ignore[attr-defined]
        return svc

    def test_theme_refresh_logs_on_unexpected_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        from textual.css.query import NoMatches

        svc = self._make_svc()

        # Subtest A: unexpected ValueError should produce a warning
        # We need query_one to raise when called inside refresh_slash_commands
        svc.app.query_one.side_effect = ValueError("unexpected overlay error")
        with (
            caplog.at_level(logging.WARNING, logger="hermes_cli.tui.services.theme"),
            patch.object(svc, "populate_slash_commands"),
            # Make sure HelpOverlay import succeeds so we reach query_one
            patch.dict("sys.modules", {"hermes_cli.tui.overlays": MagicMock(HelpOverlay=MagicMock())}),
        ):
            svc.refresh_slash_commands()

        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(r.exc_info for r in warning_records), (
            f"Expected WARNING with exc_info on ValueError; got: {[r.getMessage() for r in caplog.records]}"
        )

        caplog.clear()
        # Subtest B: NoMatches should NOT produce a warning
        svc2 = self._make_svc()
        svc2.app.query_one.side_effect = NoMatches()
        with (
            caplog.at_level(logging.WARNING, logger="hermes_cli.tui.services.theme"),
            patch.object(svc2, "populate_slash_commands"),
            patch.dict("sys.modules", {"hermes_cli.tui.overlays": MagicMock(HelpOverlay=MagicMock())}),
        ):
            svc2.refresh_slash_commands()

        warning_records_b = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert not warning_records_b, (
            f"NoMatches should NOT produce a warning; got: {warning_records_b}"
        )


# ---------------------------------------------------------------------------
# CSS-7: _builtin_skin_to_css / TestBuiltinSkinFallback
# ---------------------------------------------------------------------------

class TestBuiltinSkinFallback:
    """CSS-7 — _builtin_skin_to_css logs debug when skin produces no color keys."""

    def test_builtin_skin_logs_when_all_keys_missing(self, caplog: pytest.LogCaptureFixture) -> None:
        from hermes_cli.tui.theme_manager import _builtin_skin_to_css

        class _EmptySkin:
            name = "test-empty-skin"
            css_vars: Dict[str, str] = {}

        skin = _EmptySkin()
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.theme_manager"):
            result = _builtin_skin_to_css(skin)

        assert result == {}
        debug_records = [r for r in caplog.records if "no usable color keys" in r.getMessage()]
        assert debug_records, (
            f"Expected DEBUG log containing 'no usable color keys'; got: "
            f"{[r.getMessage() for r in caplog.records]}"
        )
