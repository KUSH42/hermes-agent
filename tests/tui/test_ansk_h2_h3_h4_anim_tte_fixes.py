"""Tests for ANSK-H2, ANSK-H3, ANSK-H4 fixes.

ANSK-H2: TTEWidget._run_animation captures done_event locally (no race with play/stop).
ANSK-H3: ThinkingWidget._load_config logs warning instead of bare swallow.
ANSK-H4+M7: _apply_effect_params returns bool, early returns yield False, print→_log.warning.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest


# ── ANSK-H2: TTEWidget done_event local capture ──────────────────────────────

class TestANSKH2:
    """is_mounted and app are read-only Textual properties; patch via PropertyMock."""

    def _run_worker(self, w, effect_name, text, fake_frames, fake_app=None):
        """Run _run_animation.__wrapped__ with mocked Textual properties."""
        from unittest.mock import PropertyMock

        if fake_app is None:
            fake_app = SimpleNamespace(call_from_thread=lambda fn, *a: fn(*a))

        def fake_iter_frames(en, t, params=None):
            yield from fake_frames(en, t, params=params)

        with patch.object(type(w), "is_mounted", new_callable=PropertyMock, return_value=True), \
             patch.object(type(w), "app", new_callable=PropertyMock, return_value=fake_app), \
             patch("hermes_cli.tui.widgets.tte_widget.TTEWidget.remove_class", MagicMock()), \
             patch("hermes_cli.tui.tte_runner.iter_frames", fake_iter_frames):
            w._run_animation.__wrapped__(w, effect_name, text)

    def _make_widget(self):
        from hermes_cli.tui.widgets.tte_widget import TTEWidget
        w = object.__new__(TTEWidget)
        w._done_event = None
        return w

    def test_done_event_set_on_completion(self):
        """Worker signals done_event after iterating all frames."""
        done = threading.Event()
        w = self._make_widget()
        w._done_event = done

        self._run_worker(w, "helix", "hello", lambda *a, **kw: iter(["frame1"]))

        assert done.is_set(), "done_event must be set after worker completes"

    def test_done_event_not_clobbered_when_stop_called_first(self):
        """Worker must signal its own captured event; must not touch a later event."""
        event_a = threading.Event()
        event_b = threading.Event()

        w = self._make_widget()
        w._done_event = event_a

        def mid_iter(en, t, params=None):
            # Simulate stop() + new play() between frame yields
            w._done_event = None   # stop() nulled it
            w._done_event = event_b  # new play() assigned event_b
            yield "frame"

        self._run_worker(w, "helix", "hello", mid_iter)

        assert event_a.is_set(), "worker must signal its own captured done_event"
        assert not event_b.is_set(), "worker must not clobber the new done_event"

    def test_done_event_none_is_safe(self):
        """Worker with done_event=None must complete without error."""
        w = self._make_widget()
        w._done_event = None

        # Must not raise
        self._run_worker(w, "helix", "hello", lambda *a, **kw: iter(["frame"]))


# ── ANSK-H3: ThinkingWidget._load_config warning log ─────────────────────────

class TestANSKH3:
    def _make_widget(self):
        from hermes_cli.tui.widgets.thinking import ThinkingWidget
        w = object.__new__(ThinkingWidget)
        w._cfg_loaded = False
        # Set default field values that _load_config would set
        w._cfg_mode = "default"
        w._cfg_engine = "dna"
        w._cfg_effect = "breathe"
        w._cfg_tick_hz = 12.0
        w._cfg_long_wait_after_s = 8.0
        w._cfg_deep_after_s = 120.0
        w._cfg_show_elapsed = True
        w._cfg_allow_intense = False
        w._cfg_long_wait_engine = "wave_function"
        w._cfg_long_wait_effect = "shimmer"
        return w

    def test_load_config_logs_warning_on_exception(self):
        """Config read failure must log a warning with exc_info, not swallow silently."""
        w = self._make_widget()

        with patch("hermes_cli.tui.widgets.thinking._log") as mock_log, \
             patch("hermes_cli.config.read_raw_config", side_effect=ValueError("bad yaml")):
            w._load_config()

        assert mock_log.warning.called, "_log.warning must be called on config read failure"
        call_kwargs = mock_log.warning.call_args
        assert call_kwargs.kwargs.get("exc_info") is True, "exc_info=True required"

    def test_load_config_still_uses_defaults_after_exception(self):
        """Defaults must be intact after a config read failure."""
        w = self._make_widget()

        with patch("hermes_cli.tui.widgets.thinking._log"), \
             patch("hermes_cli.config.read_raw_config", side_effect=RuntimeError("oops")):
            w._load_config()

        assert w._cfg_mode == "default"
        assert w._cfg_tick_hz == 12.0

    def test_load_config_noop_when_already_loaded(self):
        """Second call must not invoke read_raw_config."""
        w = self._make_widget()
        w._cfg_loaded = True

        with patch("hermes_cli.config.read_raw_config") as mock_read:
            w._load_config()

        mock_read.assert_not_called()

    def test_load_config_reads_values_from_config(self):
        """Valid config dict must populate widget fields."""
        w = self._make_widget()

        fake_config = {"tui": {"thinking": {"mode": "line", "tick_hz": 24.0}}}
        with patch("hermes_cli.tui.widgets.thinking._log"), \
             patch("hermes_cli.config.read_raw_config", return_value=fake_config):
            w._load_config()

        assert w._cfg_mode == "line"
        assert w._cfg_tick_hz == 24.0
        assert w._cfg_loaded is True


# ── ANSK-H4+M7: _apply_effect_params return type + print→log ─────────────────

class TestANSKH4:
    def test_no_params_returns_false_not_none(self):
        """Empty/None params must return False (not implicit None)."""
        from hermes_cli.tui.tte_runner import _apply_effect_params

        effect = SimpleNamespace(effect_config=SimpleNamespace())
        result = _apply_effect_params("helix", effect, None, None)
        assert result is False, "must return False, not None"

        result2 = _apply_effect_params("helix", effect, None, {})
        assert result2 is False

    def test_no_cfg_returns_false_and_logs_warning(self):
        """Effect without effect_config must return False and log a warning."""
        from hermes_cli.tui.tte_runner import _apply_effect_params

        effect = SimpleNamespace()  # no effect_config attribute

        with patch("hermes_cli.tui.tte_runner._log") as mock_log:
            result = _apply_effect_params("helix", effect, None, {"some_key": 1})

        assert result is False
        assert mock_log.warning.called

    def test_colors_override_returns_true(self):
        """final_gradient_stops key must return True."""
        from hermes_cli.tui.tte_runner import _apply_effect_params

        cfg = SimpleNamespace(final_gradient_stops=("red", "blue"))
        effect = SimpleNamespace(effect_config=cfg)

        result = _apply_effect_params("helix", effect, None, {"final_gradient_stops": ["#ff0000"]})
        assert result is True

    def test_no_print_called_in_worker_path(self):
        """_apply_effect_params must not call print() — any print() corrupts live TUI."""
        from hermes_cli.tui.tte_runner import _apply_effect_params

        cfg = SimpleNamespace(final_gradient_stops=("red",))
        effect = SimpleNamespace(effect_config=cfg)

        with patch("builtins.print", side_effect=AssertionError("print() called in worker path")):
            # unknown key — previously would print
            _apply_effect_params("helix", effect, None, {"unknown_key": 42})
            # colors override — previously would print
            _apply_effect_params("helix", effect, None, {"final_gradient_stops": ["#ff0000"]})
            # no cfg — previously would print
            _apply_effect_params("helix", SimpleNamespace(), None, {"x": 1})

    def test_unknown_key_logs_warning_not_print(self):
        """Unknown param must log a warning, not print."""
        from hermes_cli.tui.tte_runner import _apply_effect_params

        cfg = SimpleNamespace()
        effect = SimpleNamespace(effect_config=cfg)

        with patch("hermes_cli.tui.tte_runner._log") as mock_log:
            _apply_effect_params("helix", effect, None, {"totally_unknown": 99})

        assert mock_log.warning.called
