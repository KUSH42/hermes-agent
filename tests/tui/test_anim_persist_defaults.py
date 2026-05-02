"""Tests for spec_anim_persist_defaults.md (AP-1..AP-4).

22 tests covering:
- AP-1: AnimConfigPanel.action_dismiss auto-persists via _save_fields_only.
- AP-2: DrawbrailleOverlay.on_mouse_up persists drag offset; failures log.
- AP-3: DrawbrailleOverlay._effective_size compact override.
- AP-4: DrawbrailleOverlayCfg.position default + _cfg_from_mapping fallback.
"""
from __future__ import annotations

from unittest.mock import ANY, MagicMock, PropertyMock, call, patch

import pytest

from textual.events import MouseUp
from textual.geometry import Size

import hermes_cli.tui.drawbraille_overlay as _dbo
import hermes_cli.tui.widgets.anim_config_panel as _acp
from hermes_cli.tui.drawbraille_overlay import (
    AnimConfigPanel,
    DrawbrailleOverlay,
    DrawbrailleOverlayCfg,
    _cfg_from_mapping,
)
from hermes_cli.tui.anim_engines import AnimParams


# ── helpers ───────────────────────────────────────────────────────────────────

def _new_overlay() -> DrawbrailleOverlay:
    """Build a bare DrawbrailleOverlay safe for unit testing."""
    ov = DrawbrailleOverlay()
    ov.styles = MagicMock()
    ov._start_anim = MagicMock()
    ov._anim_params = AnimParams(width=1, height=1)
    return ov


def _new_panel() -> AnimConfigPanel:
    """Build an AnimConfigPanel with a fresh _fields list (no app context)."""
    panel = AnimConfigPanel()
    panel._build_fields(DrawbrailleOverlayCfg())
    return panel


def _make_mouse_up(screen_x: int = 15, screen_y: int = 8) -> MouseUp:
    """Build a real MouseUp event (isinstance guard requires it)."""
    event = MouseUp(
        widget=None,
        x=screen_x,
        y=screen_y,
        delta_x=0,
        delta_y=0,
        button=1,
        shift=False,
        meta=False,
        ctrl=False,
        screen_x=screen_x,
        screen_y=screen_y,
    )
    event.stop = MagicMock()
    return event


# ── AP-4: default position bottom-right ───────────────────────────────────────

def test_ap4_default_position_is_bottom_right():
    assert DrawbrailleOverlayCfg().position == "bottom-right"


def test_ap4_cfg_from_mapping_empty_defaults():
    assert _cfg_from_mapping({}).position == "bottom-right"


def test_ap4_cfg_from_mapping_explicit_center():
    assert _cfg_from_mapping({"position": "center"}).position == "center"


def test_ap4_dataclass_and_mapping_consistent():
    assert (
        DrawbrailleOverlayCfg().position
        == _cfg_from_mapping({}).position
        == "bottom-right"
    )


def test_ap4_bottom_right_offset_within_bounds(monkeypatch):
    ov = _new_overlay()
    mock_app = MagicMock(size=Size(120, 30))
    ov._cfg = DrawbrailleOverlayCfg(position_margin=2)
    ov.size_name = "medium"
    monkeypatch.setattr(ov, "_has_nameplate", lambda: False)
    monkeypatch.setattr(ov, "_set_offset", MagicMock())
    ov.position = "bottom-right"
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov._apply_layout()
    assert ov._set_offset.call_args == call(68, 14)


# ── AP-3: compact_size + _effective_size + show() wiring ──────────────────────

def test_ap3_compact_mode_uses_small():
    ov = _new_overlay()
    mock_app = MagicMock(compact=True)
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        out = ov._effective_size(DrawbrailleOverlayCfg(size="medium"))
    assert out == "small"


def test_ap3_normal_mode_uses_medium():
    ov = _new_overlay()
    mock_app = MagicMock(compact=False)
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        out = ov._effective_size(DrawbrailleOverlayCfg(size="medium"))
    assert out == "medium"


def test_ap3_explicit_size_not_overridden():
    ov = _new_overlay()
    mock_app = MagicMock(compact=True)
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        out = ov._effective_size(DrawbrailleOverlayCfg(size="large"))
    assert out == "large"


def test_ap3_compact_size_field_roundtrip():
    cfg = _cfg_from_mapping({"compact_size": "medium"})
    assert cfg.compact_size == "medium"


def test_ap3_compact_size_field_default():
    assert DrawbrailleOverlayCfg().compact_size == "small"


def test_ap3_explicit_medium_in_compact_still_overridden():
    """User-set medium in compact still overridden — known tradeoff."""
    cfg = _cfg_from_mapping({"size": "medium"})
    ov = _new_overlay()
    mock_app = MagicMock(compact=True)
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        out = ov._effective_size(cfg)
    assert out == "small"


def test_ap3_show_compact_sets_size_name_small(monkeypatch):
    """Wiring test: show() must call self._effective_size(cfg)."""
    ov = _new_overlay()
    mock_app = MagicMock(compact=True)
    mock_app.size = Size(120, 30)
    monkeypatch.setattr(ov, "_apply_layout", MagicMock())
    cfg = DrawbrailleOverlayCfg(enabled=True, size="medium")
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov.show(cfg)
    assert ov.size_name == "small"


def test_ap3_enabled_false_compact_override_skipped():
    """show() returns early when enabled=False; size_name reactive untouched."""
    ov = _new_overlay()
    mock_app = MagicMock(compact=True)
    # Baseline via reactive descriptor (NOT __dict__ — reactive shadows __dict__).
    ov.set_reactive(DrawbrailleOverlay.size_name, "medium")
    cfg = DrawbrailleOverlayCfg(enabled=False, size="medium")
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov.show(cfg)
    assert ov.size_name == "medium"


def test_ap3_no_active_app_falls_back_to_cfg_size():
    """RuntimeError on self.app access → return cfg.size unchanged."""
    ov = _new_overlay()
    with patch.object(
        type(ov), "app", new_callable=PropertyMock, side_effect=RuntimeError("no app")
    ):
        out = ov._effective_size(DrawbrailleOverlayCfg(size="medium"))
    assert out == "medium"


# ── AP-2: drag-release persist + log ──────────────────────────────────────────

def test_ap2_drag_release_persists_position(monkeypatch):
    ov = _new_overlay()
    mock_app = MagicMock(size=MagicMock(width=120, height=30))
    mock_app._svc_commands.persist_anim_config = MagicMock()
    ov._dragging = True
    ov._drag_start_sx = 10
    ov._drag_start_sy = 5
    ov._drag_base_ox = 0
    ov._drag_base_oy = 0
    ov._cfg = DrawbrailleOverlayCfg(position_margin=2)
    monkeypatch.setattr(ov, "_has_nameplate", lambda: False)
    monkeypatch.setattr(ov, "_set_offset", MagicMock())
    event = _make_mouse_up(15, 8)
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app), \
         patch.object(type(ov), "size", new_callable=PropertyMock, return_value=Size(50, 14)), \
         patch.object(ov, "_clamp_offset", wraps=ov._clamp_offset) as spy:
        ov.on_mouse_up(event)
    mock_app._svc_commands.persist_anim_config.assert_called_once_with({
        "position": "custom",
        "custom_offset_x": 5,
        "custom_offset_y": 3,
    })
    # Spec: verify the persist chain calls _clamp_offset with raw drag args.
    # Use assert_any_call (not assert_called_once_with) — the position="custom"
    # reactive assignment fires watchers that re-invoke _clamp_offset with the
    # clamped values; we only need to confirm the initial raw call happened.
    spy.assert_any_call(5, 3, 50, 14, 120, 30)


def test_ap2_drag_release_exception_logged(monkeypatch):
    ov = _new_overlay()
    mock_app = MagicMock(size=MagicMock(width=120, height=30))
    mock_app._svc_commands.persist_anim_config = MagicMock(side_effect=RuntimeError)
    ov._dragging = True
    ov._drag_start_sx = 10
    ov._drag_start_sy = 5
    ov._drag_base_ox = 0
    ov._drag_base_oy = 0
    ov._cfg = DrawbrailleOverlayCfg(position_margin=2)
    monkeypatch.setattr(ov, "_has_nameplate", lambda: False)
    mock_log = MagicMock()
    monkeypatch.setattr(_dbo, "_log", mock_log)
    event = _make_mouse_up(15, 8)
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app), \
         patch.object(type(ov), "size", new_callable=PropertyMock, return_value=Size(50, 14)):
        ov.on_mouse_up(event)
    assert mock_log.debug.call_args[1]["exc_info"] is True
    assert mock_log.warning.call_count == 0


def test_ap2_no_drag_no_persist():
    ov = _new_overlay()
    mock_app = MagicMock(size=MagicMock(width=120, height=30))
    mock_app._svc_commands.persist_anim_config = MagicMock()
    ov._dragging = False
    event = _make_mouse_up(15, 8)
    with patch.object(type(ov), "app", new_callable=PropertyMock, return_value=mock_app):
        ov.on_mouse_up(event)
    mock_app._svc_commands.persist_anim_config.assert_not_called()


# ── AP-1: AnimConfigPanel auto-persist on dismiss ─────────────────────────────

def test_ap1_dismiss_calls_save_fields_only(monkeypatch):
    panel = _new_panel()
    spy_save = MagicMock()
    spy_do_save = MagicMock()
    spy_rm = MagicMock()
    monkeypatch.setattr(panel, "_save_fields_only", spy_save)
    monkeypatch.setattr(panel, "_do_save", spy_do_save)
    monkeypatch.setattr(panel, "remove_class", spy_rm)
    mock_app = MagicMock()
    # query_one(HermesInput) inside action_dismiss — make it raise NoMatches so
    # the except (NoMatches, ImportError) branch handles it cleanly.
    from textual.css.query import NoMatches
    mock_app.query_one.side_effect = NoMatches()
    with patch.object(type(panel), "app", new_callable=PropertyMock, return_value=mock_app):
        panel.action_dismiss()
    assert spy_save.call_count == 1
    assert spy_rm.call_args == call("--visible")
    spy_do_save.assert_not_called()


def test_ap1_save_fields_only_does_not_call_push_to_overlay_all(monkeypatch):
    panel = _new_panel()
    monkeypatch.setattr(_dbo, "_overlay_config", lambda: DrawbrailleOverlayCfg())
    spy_push = MagicMock()
    monkeypatch.setattr(panel, "_push_to_overlay_all", spy_push)
    mock_app = MagicMock()
    mock_app._svc_commands.persist_anim_config = MagicMock()
    with patch.object(type(panel), "app", new_callable=PropertyMock, return_value=mock_app):
        panel._save_fields_only()
    spy_push.assert_not_called()


def test_ap1_dismiss_no_crash_svc_not_ready(monkeypatch):
    panel = _new_panel()
    monkeypatch.setattr(_dbo, "_overlay_config", lambda: DrawbrailleOverlayCfg())
    mock_log = MagicMock()
    monkeypatch.setattr(_acp, "_log", mock_log)
    mock_app = MagicMock()
    mock_app._svc_commands.persist_anim_config = MagicMock(side_effect=RuntimeError)
    with patch.object(type(panel), "app", new_callable=PropertyMock, return_value=mock_app):
        # Must not propagate.
        panel.action_dismiss()
    assert mock_log.debug.call_args[1]["exc_info"] is True
    # Hint path never entered — _save_fields_only returned before query_one(HintBar).
    # query_one is also called in action_dismiss for HermesInput, so check by class name.
    hintbar_class_calls = [
        c for c in mock_app.query_one.call_args_list
        if c.args and getattr(c.args[0], "__name__", "") == "HintBar"
    ]
    assert hintbar_class_calls == []


def test_ap1_overlay_stays_hidden_after_dismiss(monkeypatch):
    panel = _new_panel()
    monkeypatch.setattr(_dbo, "_overlay_config", lambda: DrawbrailleOverlayCfg())
    panel._build_fields(DrawbrailleOverlayCfg(enabled=True, trigger="always"))
    mock_app = MagicMock()
    mock_app._svc_commands.persist_anim_config = MagicMock()
    overlay = _new_overlay()
    spy_show = MagicMock()
    monkeypatch.setattr(overlay, "show", spy_show)
    # Force any panel-side overlay lookup to return our overlay (defensive — action_dismiss
    # itself does not look up the overlay; this guards against future regression).
    if hasattr(panel, "_get_overlay"):
        monkeypatch.setattr(panel, "_get_overlay", lambda: overlay)
    with patch.object(type(panel), "app", new_callable=PropertyMock, return_value=mock_app):
        panel.action_dismiss()
    spy_show.assert_not_called()


def test_ap1_dismiss_hint_shown(monkeypatch):
    panel = _new_panel()
    monkeypatch.setattr(_dbo, "_overlay_config", lambda: DrawbrailleOverlayCfg())
    mock_app = MagicMock()
    mock_app._svc_commands.persist_anim_config = MagicMock()
    mock_app.set_timer = MagicMock()
    with patch.object(type(panel), "app", new_callable=PropertyMock, return_value=mock_app):
        panel.action_dismiss()
    # MagicMock returns the same child mock for repeated identical-args calls,
    # so `mock_app.query_one(HintBar).hint` reads the value set by _save_fields_only.
    from hermes_cli.tui.widgets import HintBar
    assert mock_app.query_one(HintBar).hint == "✓ Saved to config"
    mock_app.set_timer.assert_called_once_with(2.0, ANY)
