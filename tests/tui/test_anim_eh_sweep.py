"""ANIM-EH sweep — exception handling & logging hygiene.

Covers ANIM-EH-1..ANIM-EH-5 from /home/xush/.hermes/2026-05-01-anim-eh-sweep-spec.md.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── ANIM-EH-1 ────────────────────────────────────────────────────────────────

class TestAnimEH1Logger:

    def test_logger_present(self):
        from hermes_cli.tui import drawbraille_overlay
        assert isinstance(drawbraille_overlay._log, logging.Logger)
        assert drawbraille_overlay._log.name == "hermes_cli.tui.drawbraille_overlay"


# ── ANIM-EH-2 ────────────────────────────────────────────────────────────────

def _signal_overlay_stub(engine):
    """Minimal DrawbrailleOverlay stub for exercising signal()."""
    from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay
    ov = DrawbrailleOverlay.__new__(DrawbrailleOverlay)
    ov._cfg = None
    ov._heat_target = 0.0
    ov._heat = 0.0
    ov._burst_counter = 0
    ov._burst_decay_ticks = 0
    ov._completion_burst_frames = 0
    ov._error_hold_frames = 0
    ov._waiting = False
    ov._current_phase = "idle"
    ov._visibility_state = "active"
    ov.__dict__["_orchestrator"] = SimpleNamespace(
        on_phase_signal=lambda *a, **kw: None,
        _current_engine_instance=engine,
    )
    ov._ensure_orchestrator = lambda: None
    return ov


class TestAnimEH2OnSignalLog:

    def test_on_signal_engine_exception_logged(self, caplog):
        engine = SimpleNamespace(
            on_signal=MagicMock(side_effect=RuntimeError("boom")),
        )
        ov = _signal_overlay_stub(engine)
        with caplog.at_level(logging.WARNING, logger="hermes_cli.tui.drawbraille_overlay"):
            ov.signal("tool", 1.0)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert any("on_signal" in r.getMessage() for r in warnings)
        assert any(r.exc_info is not None for r in warnings)

    def test_on_signal_engine_exception_does_not_propagate(self):
        engine = SimpleNamespace(
            on_signal=MagicMock(side_effect=RuntimeError("boom")),
        )
        ov = _signal_overlay_stub(engine)
        # Must not raise.
        ov.signal("tool", 1.0)

    def test_on_signal_no_exception_passes_through(self):
        flag = {"hit": False}

        def _on_signal(event, value):
            flag["hit"] = True

        engine = SimpleNamespace(on_signal=_on_signal)
        ov = _signal_overlay_stub(engine)
        ov.signal("tool", 1.0)
        assert flag["hit"] is True


# ── ANIM-EH-3 ────────────────────────────────────────────────────────────────

def _config_panel_stub():
    from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlayCfg
    from hermes_cli.tui.widgets.anim_config_panel import AnimConfigPanel
    with patch(
        "hermes_cli.tui.drawbraille_overlay._overlay_config",
        return_value=DrawbrailleOverlayCfg(enabled=True),
    ):
        panel = AnimConfigPanel()
    panel._classes = {"--visible"}
    panel.has_class = lambda cls: cls in panel._classes
    panel.call_after_refresh = MagicMock()
    return panel


class TestAnimEH3OnBlurComments:

    def test_on_blur_interrupt_not_mounted_refocuses(self):
        from textual.css.query import NoMatches
        panel = _config_panel_stub()
        fake_app = MagicMock()
        fake_app.query_one = MagicMock(side_effect=NoMatches("missing"))
        type(panel).app = property(lambda self: fake_app)
        try:
            panel.on_blur(None)
            assert panel.call_after_refresh.called
        finally:
            del type(panel).app

    def test_on_blur_interrupt_visible_skips_refocus(self):
        from hermes_cli.tui.overlays.interrupt import InterruptOverlay
        panel = _config_panel_stub()
        io = MagicMock(spec=InterruptOverlay)
        io.has_class = lambda cls: cls == "--visible"
        fake_app = MagicMock()
        fake_app.query_one = MagicMock(return_value=io)
        type(panel).app = property(lambda self: fake_app)
        try:
            panel.on_blur(None)
            assert not panel.call_after_refresh.called
        finally:
            del type(panel).app


# ── ANIM-EH-4 ────────────────────────────────────────────────────────────────

class TestAnimEH4DoSaveOuter:

    def test_do_save_set_status_error_unavailable_logs_warning(self, caplog, monkeypatch):
        from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlayCfg
        from hermes_cli.tui.widgets.anim_config_panel import AnimConfigPanel
        with patch(
            "hermes_cli.tui.drawbraille_overlay._overlay_config",
            return_value=DrawbrailleOverlayCfg(enabled=True),
        ):
            panel = AnimConfigPanel()
        panel._push_to_overlay_all = MagicMock()
        monkeypatch.setattr(
            "hermes_cli.tui.widgets.anim_config_panel._fields_to_dict",
            lambda fields: (_ for _ in ()).throw(RuntimeError("primary boom")),
        )
        fake_app = MagicMock()
        fake_app.set_status_error = MagicMock(
            side_effect=AttributeError("no such method"),
        )
        type(panel).app = property(lambda self: fake_app)
        try:
            with caplog.at_level(
                logging.WARNING,
                logger="hermes_cli.tui.widgets.anim_config_panel",
            ):
                panel._do_save()
            warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
            assert any("primary boom" in r.getMessage() for r in warnings)
            assert any(r.exc_info is not None for r in warnings)
        finally:
            del type(panel).app

    def test_do_save_success_does_not_log_warning(self, caplog):
        from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlayCfg
        from hermes_cli.tui.widgets.anim_config_panel import AnimConfigPanel
        with patch(
            "hermes_cli.tui.drawbraille_overlay._overlay_config",
            return_value=DrawbrailleOverlayCfg(enabled=True),
        ):
            panel = AnimConfigPanel()
        panel._push_to_overlay_all = MagicMock()
        panel._get_overlay = MagicMock(return_value=None)
        fake_app = MagicMock()
        fake_app._svc_commands = MagicMock()
        fake_app._svc_commands.persist_anim_config = MagicMock()
        type(panel).app = property(lambda self: fake_app)
        try:
            with caplog.at_level(
                logging.WARNING,
                logger="hermes_cli.tui.widgets.anim_config_panel",
            ):
                panel._do_save()
            warnings = [
                r for r in caplog.records
                if r.levelno == logging.WARNING
                and "set_status_error unavailable" in r.getMessage()
            ]
            assert warnings == []
        finally:
            del type(panel).app


# ── ANIM-EH-5 ────────────────────────────────────────────────────────────────

class TestAnimEH5LayerComment:

    def test_layer_frames_call_site_comments_present(self):
        import hermes_cli.tui.anim_engines as ae
        import pathlib
        source = pathlib.Path(ae.__file__).read_text()
        # One occurrence per call site comment (CompositeEngine + CrossfadeEngine).
        # The definition-site comment uses "Textual event loop" instead.
        assert source.count("UI-thread only") >= 2
