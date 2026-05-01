"""Tests for ANIM-TIMER-1..4: timer lifecycle and animation state fixes."""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_gallery_preview():
    # Import drawbraille_overlay first to complete the circular init, then anim_config_panel
    from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay  # noqa: F401
    from hermes_cli.tui.widgets.anim_config_panel import _GalleryPreview
    gp = object.__new__(_GalleryPreview)
    gp._engine = None
    gp._engine_key = ""
    gp._preview_timer = None
    gp.set_interval = MagicMock(return_value=MagicMock())
    gp.update = MagicMock()
    gp.refresh = MagicMock()
    return gp


def _make_anim_config_panel():
    from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay  # noqa: F401
    from hermes_cli.tui.widgets.anim_config_panel import AnimConfigPanel
    gp = object.__new__(AnimConfigPanel)
    gp._preview_timer = None
    gp._fields = []
    gp._focus_idx = 0
    gp._color_editing = False
    return gp


def _make_anim_params():
    from hermes_cli.tui.anim_engines import AnimParams
    return AnimParams(width=40, height=24, heat=0.5)


# ── ANIM-TIMER-1: timer leak on unmount ──────────────────────────────────────

class TestAnimTimer1TimerLeak:

    def test_gallery_preview_timer_stopped_on_unmount(self):
        gp = _make_gallery_preview()
        mock_timer = MagicMock()
        gp._params = _make_anim_params()
        gp._preview_timer = mock_timer

        gp.on_unmount()

        mock_timer.stop.assert_called_once()
        assert gp._preview_timer is None

    def test_anim_config_panel_timer_stopped_on_unmount(self):
        panel = _make_anim_config_panel()
        mock_timer = MagicMock()
        panel._preview_timer = mock_timer

        panel.on_unmount()

        mock_timer.stop.assert_called_once()
        assert panel._preview_timer is None

    def test_gallery_preview_on_unmount_noop_when_no_timer(self):
        gp = _make_gallery_preview()
        gp._preview_timer = None
        gp.on_unmount()
        assert gp._preview_timer is None


# ── ANIM-TIMER-2: params persist across ticks ─────────────────────────────────

class TestAnimTimer2ParamsPersist:

    def test_preview_tick_advances_t(self):
        gp = _make_gallery_preview()
        from hermes_cli.tui.anim_engines import PlasmaEngine
        gp._engine = PlasmaEngine()
        gp._params = _make_anim_params()
        initial_dt = gp._params.dt

        gp._preview_tick()
        assert gp._params.t == pytest.approx(initial_dt)

        gp._preview_tick()
        assert gp._params.t == pytest.approx(2 * initial_dt)

        gp._preview_tick()
        assert gp._params.t == pytest.approx(3 * initial_dt)

    def test_preview_tick_t_resets_on_engine_change(self):
        gp = _make_gallery_preview()
        from hermes_cli.tui.anim_engines import PlasmaEngine
        gp._engine = PlasmaEngine()
        gp._params = _make_anim_params()
        expected_dt = gp._params.dt

        gp._preview_tick()
        assert gp._params.t > 0

        gp.set_engine("plasma")
        assert gp._params.t == pytest.approx(0.0)

        gp._preview_tick()
        assert gp._params.t == pytest.approx(expected_dt)

    def test_preview_tick_engine_exception_debug_logged(self, caplog):
        gp = _make_gallery_preview()
        bad_engine = MagicMock()
        bad_engine.next_frame.side_effect = RuntimeError("boom")
        gp._engine = bad_engine
        gp._params = _make_anim_params()

        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.widgets.anim_config_panel"):
            gp._preview_tick()

        assert any(
            "_GalleryPreview._preview_tick raised" in r.message
            for r in caplog.records
        )
        assert any(r.exc_info is not None for r in caplog.records)

    def test_preview_tick_noop_when_no_engine(self):
        gp = _make_gallery_preview()
        gp._engine = None
        gp._params = _make_anim_params()

        gp._preview_tick()

        gp.update.assert_not_called()


# ── ANIM-TIMER-3: watch_fps guard ─────────────────────────────────────────────

class TestAnimTimer3WatchFps:

    def _make_overlay(self):
        from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay
        ov = object.__new__(DrawbrailleOverlay)
        ov._anim_handle = None
        ov._stop_anim = MagicMock()
        ov._start_anim = MagicMock()
        return ov

    def test_watch_fps_while_hidden_does_not_start_timer(self):
        ov = self._make_overlay()
        assert ov._anim_handle is None

        ov.watch_fps(30)

        ov._stop_anim.assert_not_called()
        ov._start_anim.assert_not_called()
        assert ov._anim_handle is None

    def test_watch_fps_while_visible_restarts_timer(self):
        ov = self._make_overlay()
        ov._anim_handle = MagicMock()

        ov.watch_fps(30)

        ov._stop_anim.assert_called_once()
        ov._start_anim.assert_called_once()

    def test_watch_fps_restart_uses_new_fps(self):
        # _anim_handle set → watch_fps must stop then start (both called exactly once)
        ov = self._make_overlay()
        ov._anim_handle = MagicMock()

        ov.watch_fps(40)

        ov._stop_anim.assert_called_once()
        ov._start_anim.assert_called_once()


# ── ANIM-TIMER-4: no-op lambda timers replaced ───────────────────────────────

class TestAnimTimer4NoOpTimers:

    def _make_mock_app(self, timer_callbacks: list, query_one_fn=None):
        mock_app = MagicMock()

        def capture_set_timer(delay, cb):
            timer_callbacks.append((delay, cb))
            return MagicMock()

        mock_app.set_timer = capture_set_timer
        if query_one_fn is not None:
            mock_app.query_one = query_one_fn
        mock_app._svc_commands = MagicMock()
        return mock_app

    def test_do_save_hint_cleared_after_timer(self):
        from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay  # noqa: F401
        from hermes_cli.tui.widgets.anim_config_panel import AnimConfigPanel

        timer_callbacks: list = []
        mock_hint_bar = MagicMock()
        mock_hint_bar.hint = ""
        mock_app = self._make_mock_app(timer_callbacks)

        def query_one_side_effect(cls):
            from hermes_cli.tui.widgets import HintBar
            if cls is HintBar:
                return mock_hint_bar
            raise Exception(f"Unexpected query_one({cls})")

        mock_app.query_one = query_one_side_effect

        class _IsolatedPanel(AnimConfigPanel):
            app = property(lambda s: mock_app)  # type: ignore[assignment]

        panel = object.__new__(_IsolatedPanel)
        panel._preview_timer = None
        panel._fields = []
        panel._focus_idx = 0
        panel._color_editing = False

        with patch("hermes_cli.tui.widgets.anim_config_panel._fields_to_dict", return_value={}):
            panel._do_save()

        matching = [(d, cb) for d, cb in timer_callbacks if d == 2.0]
        assert matching, "Expected a 2.0s timer callback"
        _, clear_cb = matching[0]

        clear_cb()

        assert mock_hint_bar.hint == ""

    def test_action_preview_reverts_after_timer(self):
        from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay  # noqa: F401
        from hermes_cli.tui.widgets.anim_config_panel import AnimGalleryOverlay

        mock_ov = MagicMock()
        timer_callbacks: list = []
        mock_app = self._make_mock_app(timer_callbacks)
        mock_app.query_one.return_value = mock_ov

        class _IsolatedGallery(AnimGalleryOverlay):
            app = property(lambda s: mock_app)  # type: ignore[assignment]

        gallery = object.__new__(_IsolatedGallery)
        gallery._engine_list = ["plasma", "matrix_rain"]
        gallery._focus_idx = 0

        pre_cfg = MagicMock()
        pre_cfg.enabled = True
        mutable_cfg = MagicMock()
        mutable_cfg.enabled = True

        cfg_iter = iter([pre_cfg, mutable_cfg])

        with patch("hermes_cli.tui.drawbraille_overlay._overlay_config", side_effect=lambda: next(cfg_iter)):
            gallery.action_preview()

        matching = [(d, cb) for d, cb in timer_callbacks if d == 5.0]
        assert matching, "Expected a 5.0s revert timer"
        _, revert_cb = matching[0]

        revert_cb()

        mock_ov.show.assert_called_with(pre_cfg)

    def test_action_preview_revert_noop_when_overlay_unmounted(self):
        from textual.css.query import NoMatches
        from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay  # noqa: F401
        from hermes_cli.tui.widgets.anim_config_panel import AnimGalleryOverlay

        mock_ov = MagicMock()
        timer_callbacks: list = []
        call_count = [0]

        def query_one_side_effect(cls):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_ov
            raise NoMatches("gone")

        mock_app = self._make_mock_app(timer_callbacks, query_one_fn=query_one_side_effect)

        class _IsolatedGallery(AnimGalleryOverlay):
            app = property(lambda s: mock_app)  # type: ignore[assignment]

        gallery = object.__new__(_IsolatedGallery)
        gallery._engine_list = ["plasma"]
        gallery._focus_idx = 0

        pre_cfg = MagicMock()
        pre_cfg.enabled = True
        mutable_cfg = MagicMock()

        cfg_iter = iter([pre_cfg, mutable_cfg])

        with patch("hermes_cli.tui.drawbraille_overlay._overlay_config", side_effect=lambda: next(cfg_iter)):
            gallery.action_preview()

        _, revert_cb = [(d, cb) for d, cb in timer_callbacks if d == 5.0][0]

        # Must not raise
        revert_cb()
