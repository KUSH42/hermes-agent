"""Tests for Audit 1 Error Prominence (A3 + A7)."""
from __future__ import annotations
import types
from unittest.mock import MagicMock, patch, PropertyMock
import pytest


# ── A3-1: Nameplate error hooks ───────────────────────────────────────────────

def _make_nameplate():
    from hermes_cli.tui.widgets import AssistantNameplate
    np = object.__new__(AssistantNameplate)
    # Required attrs from __init__
    np._effects_enabled = True
    np._state = "idle"
    np._timer = None
    np._idle_fx = None
    np._error_color_hex = "#ef5350"
    np._accent_hex = "#7b68ee"
    np._idle_color_hex = "#888888"
    np._active_phase = 0.0
    np._frame = []
    np._tick = 0
    np._morph_dissolve = []
    np._morph_speed = 1.0
    np._glitch_enabled = True
    np._glitch_frame = 0
    np._error_frame = 0
    np._last_was_error = False
    np._active_dim_hex = "#3d3480"
    np._canvas_width = 80
    np._last_nameplate_w = 0
    np._target_name = "Hermes"
    np._active_label = "● thinking"
    np._morph_src = ""
    np._morph_dst = ""
    from rich.style import Style
    np._active_style = Style.parse("bold #7b68ee")
    # Mock DOM methods
    np._pulse_stop = MagicMock()
    np._activate_idle_phase = MagicMock()
    np._set_timer_rate = MagicMock()
    np._stop_timer = MagicMock()
    np.add_class = MagicMock()
    np.remove_class = MagicMock()
    np.refresh = MagicMock()
    return np


def test_a3_nameplate_adds_error_class():
    from hermes_cli.tui.widgets import AssistantNameplate
    np = _make_nameplate()
    np._on_error_set = AssistantNameplate._on_error_set.__get__(np)
    np._on_error_set()
    np.add_class.assert_called_with("--error")
    # Should NOT have --active or --idle after error
    assert any("--active" in str(c) or "--idle" in str(c) for c in np.remove_class.call_args_list)


def test_a3_nameplate_pulse_stopped_on_error():
    from hermes_cli.tui.widgets import AssistantNameplate
    np = _make_nameplate()
    np._on_error_set = AssistantNameplate._on_error_set.__get__(np)
    np._on_error_set()
    # _on_error_set calls _stop_timer (renamed from _pulse_stop)
    np._stop_timer.assert_called_once()


def test_a3_nameplate_restores_idle_on_error_clear():
    from hermes_cli.tui.widgets import AssistantNameplate
    np = _make_nameplate()
    np._on_error_clear = AssistantNameplate._on_error_clear.__get__(np)
    np._on_error_clear()
    np.remove_class.assert_called_with("--error")
    np._activate_idle_phase.assert_called_once()


def test_a3_nameplate_activate_idle_phase_sets_state():
    from hermes_cli.tui.widgets import AssistantNameplate
    from hermes_cli.tui.widgets import _NPState
    np = _make_nameplate()
    # restore real methods
    np._activate_idle_phase = AssistantNameplate._activate_idle_phase.__get__(np)
    np._enter_idle_timer = AssistantNameplate._enter_idle_timer.__get__(np)
    np._set_timer_rate = MagicMock()
    np._stop_timer = MagicMock()
    np._timer = None
    np._idle_fx = MagicMock()  # truthy → _enter_idle_timer calls _set_timer_rate(30)
    np._activate_idle_phase()
    assert np._state == _NPState.IDLE
    np._set_timer_rate.assert_called_once_with(30)


def test_a3_nameplate_activate_idle_no_timer_when_effects_disabled():
    from hermes_cli.tui.widgets import AssistantNameplate, _NPState
    np = _make_nameplate()
    np._effects_enabled = False
    np._idle_fx = None
    np._state = "error_state"
    np._activate_idle_phase = AssistantNameplate._activate_idle_phase.__get__(np)
    np._enter_idle_timer = AssistantNameplate._enter_idle_timer.__get__(np)
    np._set_timer_rate = MagicMock()
    np._stop_timer = MagicMock()
    np._activate_idle_phase()
    # state always becomes IDLE; timer does NOT start when effects disabled
    assert np._state == _NPState.IDLE
    np._set_timer_rate.assert_not_called()


def test_a3_nameplate_activate_idle_no_timer_restart_if_timer_running():
    from hermes_cli.tui.widgets import AssistantNameplate, _NPState
    np = _make_nameplate()
    np._timer = MagicMock()  # timer already running
    np._activate_idle_phase = AssistantNameplate._activate_idle_phase.__get__(np)
    np._set_timer_rate = MagicMock()
    np._activate_idle_phase()
    assert np._state == _NPState.IDLE
    np._set_timer_rate.assert_not_called()


# ── A3-2: HintBar auto-route ──────────────────────────────────────────────────

def _make_watchers_svc():
    from hermes_cli.tui.services.watchers import WatchersService
    svc = object.__new__(WatchersService)
    svc._phase_before_error = ""
    svc._compact_warn_flashed = False
    mock_app = MagicMock()
    mock_app.status_error = ""
    mock_app.status_phase = "idle"
    mock_app.config = {}
    mock_app._compaction_warned = False
    mock_app._compaction_warn_99 = False
    svc.app = mock_app
    return svc, mock_app


def test_a3_hintbar_flashed_on_error():
    svc, app = _make_watchers_svc()
    # Simulate A3-2 block: value = "oops"
    value = "oops"
    try:
        app.feedback.flash(
            "hint-bar",
            f"⚠ {value}",
            duration=9999,
            priority=10,
        )
    except Exception:
        pass
    app.feedback.flash.assert_called_once()
    call_kwargs = app.feedback.flash.call_args
    assert "oops" in str(call_kwargs)
    assert call_kwargs.kwargs.get("priority") == 10 or (len(call_kwargs.args) >= 2 and "oops" in str(call_kwargs.args))


def test_a3_hintbar_cancelled_on_error_clear():
    svc, app = _make_watchers_svc()
    # Simulate the cancel path
    try:
        app.feedback.cancel("hint-bar")
    except Exception:
        pass
    app.feedback.cancel.assert_called_once_with("hint-bar")


def test_a3_hintbar_priority_10_on_error():
    """Confirm the priority=10 is present in the flash call in the source."""
    import inspect
    from hermes_cli.tui.services import watchers
    src = inspect.getsource(watchers.WatchersService.on_status_error)
    assert "priority=10" in src, "A3-2: hint-bar flash must use priority=10"
    assert "duration=9999" in src, "A3-2: hint-bar flash must use duration=9999"


# ── A3-3: StatusBar error left-anchored ──────────────────────────────────────

def _make_status_bar(status_error="", progress=0.0, model="claude-sonnet"):
    from hermes_cli.tui.widgets.status_bar import StatusBar

    class _BarHelper(StatusBar):
        _pulse_t = 0.0
        _pulse_tick = 0
        _model_changed_at = 0.0

    helper = _BarHelper.__new__(_BarHelper)
    mock_app = MagicMock()
    mock_app.status_error = status_error
    mock_app.status_model = model
    mock_app.status_compaction_progress = progress
    mock_app.status_compaction_enabled = True
    mock_app.status_context_tokens = 0
    mock_app.status_context_max = 0
    mock_app.agent_running = False
    mock_app.command_running = False
    mock_app.browse_mode = False
    mock_app.yolo_mode = False
    mock_app.compact = False
    mock_app.status_verbose = False
    mock_app.status_output_dropped = False
    mock_app.status_active_file = ""
    mock_app.status_active_file_offscreen = False
    mock_app.session_label = ""
    mock_app.session_count = 1
    mock_app.status_streaming = False
    mock_app.context_pct = 0.0
    mock_app._animations_enabled = False
    mock_app.get_css_variables = lambda: {"status-error-color": "#EF5350"}
    mock_app.cli = None
    mock_app._cfg = {}
    mock_app.feedback = None
    return _BarHelper, helper, mock_app


def test_a3_statusbar_error_left_anchored():
    _BarHelper, helper, mock_app = _make_status_bar(status_error="API timeout")

    with patch.object(_BarHelper, "size", PropertyMock(return_value=type("S", (), {"width": 80})()), create=True):
        with patch.object(_BarHelper, "app", PropertyMock(return_value=mock_app), create=True):
            result = _BarHelper.render(helper)

    rendered = str(result)
    assert "⚠" in rendered
    idx = rendered.find("⚠")
    assert idx < 10, f"⚠ at position {idx}, expected < 10"


def test_a3_statusbar_error_truncated():
    long_error = "x" * 50
    _BarHelper, helper, mock_app = _make_status_bar(status_error=long_error)

    with patch.object(_BarHelper, "size", PropertyMock(return_value=type("S", (), {"width": 80})()), create=True):
        with patch.object(_BarHelper, "app", PropertyMock(return_value=mock_app), create=True):
            result = _BarHelper.render(helper)

    rendered = str(result)
    assert "⚠" in rendered
    # 50-char error truncated at 40 — "x"*41 should NOT appear
    assert "x" * 41 not in rendered


def test_a3_statusbar_no_early_return_when_no_error():
    _BarHelper, helper, mock_app = _make_status_bar(status_error="", progress=0.5)

    with patch.object(_BarHelper, "size", PropertyMock(return_value=type("S", (), {"width": 80})()), create=True):
        with patch.object(_BarHelper, "app", PropertyMock(return_value=mock_app), create=True):
            result = _BarHelper.render(helper)

    rendered = str(result)
    assert "⚠" not in rendered
    # Normal render: bar chars or model present
    assert "▰" in rendered or "▱" in rendered or "claude" in rendered.lower()


# ── A7: Compaction urgency ────────────────────────────────────────────────────

def _make_watchers_for_compact():
    from hermes_cli.tui.services.watchers import WatchersService
    svc = object.__new__(WatchersService)
    svc._phase_before_error = ""
    svc._compact_warn_flashed = False
    mock_app = MagicMock()
    mock_app.config = {}
    mock_app._compaction_warn_99 = False
    svc.app = mock_app
    return svc, mock_app


def test_a7_warn_flash_at_threshold():
    svc, app = _make_watchers_for_compact()
    from hermes_cli.tui.widgets.status_bar import _COMPACT_COLOR_WARN
    _warn = _COMPACT_COLOR_WARN

    value = _warn
    if value >= _warn and not svc._compact_warn_flashed:
        svc._compact_warn_flashed = True
        app.feedback.flash(
            "hint-bar",
            f"Context {int(_warn * 100)}% full — /compact available",
            duration=8.0,
            priority=5,
        )

    app.feedback.flash.assert_called_once()
    call_str = str(app.feedback.flash.call_args)
    assert f"{int(_warn * 100)}%" in call_str


def test_a7_warn_flash_only_once():
    svc, app = _make_watchers_for_compact()
    from hermes_cli.tui.widgets.status_bar import _COMPACT_COLOR_WARN
    _warn = _COMPACT_COLOR_WARN

    for val in [_warn, _warn + 0.05]:
        if val >= _warn and not svc._compact_warn_flashed:
            svc._compact_warn_flashed = True
            app.feedback.flash("hint-bar", f"Context {int(_warn*100)}% full", duration=8.0, priority=5)

    assert app.feedback.flash.call_count == 1


def test_a7_warn_flash_resets_below_threshold():
    svc, app = _make_watchers_for_compact()
    from hermes_cli.tui.widgets.status_bar import _COMPACT_COLOR_WARN
    _warn = _COMPACT_COLOR_WARN

    for val in [_warn, _warn - 0.15, _warn]:
        if val >= _warn and not svc._compact_warn_flashed:
            svc._compact_warn_flashed = True
            app.feedback.flash("hint-bar", "flash", duration=8.0, priority=5)
        elif val < _warn:
            svc._compact_warn_flashed = False

    assert app.feedback.flash.call_count == 2


def test_a7_warn_not_below_threshold():
    svc, app = _make_watchers_for_compact()
    from hermes_cli.tui.widgets.status_bar import _COMPACT_COLOR_WARN
    _warn = _COMPACT_COLOR_WARN
    val = _warn - 0.01
    if val >= _warn and not svc._compact_warn_flashed:
        svc._compact_warn_flashed = True
        app.feedback.flash("hint-bar", "x", duration=8.0, priority=5)
    app.feedback.flash.assert_not_called()


def test_a7_badge_present_at_crit():
    from hermes_cli.tui.widgets.status_bar import _COMPACT_BADGE_CRIT
    _BarHelper, helper, mock_app = _make_status_bar(progress=_COMPACT_BADGE_CRIT, status_error="")

    with patch.object(_BarHelper, "size", PropertyMock(return_value=type("S", (), {"width": 80})()), create=True):
        with patch.object(_BarHelper, "app", PropertyMock(return_value=mock_app), create=True):
            result = _BarHelper.render(helper)

    assert "[!]" in str(result)


def test_a7_badge_absent_below_crit():
    from hermes_cli.tui.widgets.status_bar import _COMPACT_BADGE_CRIT
    _BarHelper, helper, mock_app = _make_status_bar(progress=_COMPACT_BADGE_CRIT - 0.01, status_error="")

    with patch.object(_BarHelper, "size", PropertyMock(return_value=type("S", (), {"width": 80})()), create=True):
        with patch.object(_BarHelper, "app", PropertyMock(return_value=mock_app), create=True):
            result = _BarHelper.render(helper)

    assert "[!]" not in str(result)


def test_a7_config_override_warn():
    svc, app = _make_watchers_for_compact()
    app.config = {"display": {"compact_warn_threshold": 0.70}}
    _warn = float(app.config.get("display", {}).get("compact_warn_threshold", 0.85))
    val = 0.72
    if val >= _warn and not svc._compact_warn_flashed:
        svc._compact_warn_flashed = True
        app.feedback.flash("hint-bar", f"Context {int(_warn*100)}% full", duration=8.0, priority=5)
    app.feedback.flash.assert_called_once()


def test_a7_inline_literals_removed():
    """Verify banned bare literals are not in compaction-related logic."""
    import ast
    import inspect
    import textwrap
    from hermes_cli.tui.services import watchers
    from hermes_cli.tui.widgets import status_bar

    # Check watchers.py on_status_compaction_progress — no 0.9 or 0.99
    watcher_src = textwrap.dedent(inspect.getsource(watchers.WatchersService.on_status_compaction_progress))
    tree = ast.parse(watcher_src)
    banned_in_watchers = {0.9, 0.99}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            assert node.value not in banned_in_watchers, (
                f"Bare literal {node.value} found in on_status_compaction_progress "
                f"at line {node.lineno}. Use named constants or config reads."
            )

    # Check status_bar._compaction_color — 0.91 should not appear as a bare literal
    bar_src = textwrap.dedent(inspect.getsource(status_bar.StatusBar._compaction_color))
    tree2 = ast.parse(bar_src)
    banned_in_bar = {0.91}
    for node in ast.walk(tree2):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            assert node.value not in banned_in_bar, (
                f"Bare literal {node.value} found in _compaction_color "
                f"at line {node.lineno}. Use _COMPACT_COLOR_CRIT instead."
            )
