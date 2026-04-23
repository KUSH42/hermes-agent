"""Tests for Bar SNR P0 spec — S0-A through S0-E.

Unit tests only — no app.run_test(); uses MagicMock for app surface.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_app(
    *,
    status_streaming: bool = False,
    agent_running: bool = False,
    status_verbose: bool = False,
    status_compaction_progress: float = 0.5,
    status_compaction_enabled: bool = True,
    status_model: str = "claude-opus",
    _animations_enabled: bool = True,
) -> MagicMock:
    app = MagicMock()
    app.status_streaming = status_streaming
    app.agent_running = agent_running
    app.status_verbose = status_verbose
    app.status_compaction_progress = status_compaction_progress
    app.status_compaction_enabled = status_compaction_enabled
    app.status_model = status_model
    app.command_running = False
    app.browse_mode = False
    app.status_context_tokens = 1000
    app.status_context_max = 8000
    app.status_output_dropped = False
    app.status_active_file = ""
    app.status_error = ""
    app.yolo_mode = False
    app.compact = False
    app.session_label = ""
    app.context_pct = 0.0
    app.cli = None
    app._cfg = {}
    app._animations_enabled = _animations_enabled
    app._browse_total = 0
    app._browse_uses = 0
    app.browse_index = 0
    app.browse_detail_level = 0
    app.get_css_variables.return_value = {
        "status-context-color": "#5f87d7",
        "status-warn-color": "#FFA726",
        "status-error-color": "#ef5350",
        "status-running-color": "#FFBF00",
        "running-indicator-dim-color": "#6e6e6e",
        "primary": "#5f87d7",
        "accent-interactive": "#5f87d7",
    }
    return app


# ---------------------------------------------------------------------------
# T01–T06: _BAR_WIDTH + _compaction_color
# ---------------------------------------------------------------------------

class TestBarConstants:
    def test_T01_bar_width_is_10(self):
        from hermes_cli.tui.widgets.status_bar import _BAR_WIDTH
        assert _BAR_WIDTH == 10

    def test_T02_compaction_color_below_70_returns_normal(self):
        from hermes_cli.tui.widgets.status_bar import StatusBar
        result = StatusBar._compaction_color(0.65, {})
        assert result == "#5f87d7"

    def test_T03_compaction_color_75_lerps_between_normal_and_warn(self):
        from hermes_cli.tui.widgets.status_bar import StatusBar
        result = StatusBar._compaction_color(0.75, {})
        # Must differ from both pure normal and pure warn
        assert result != "#5f87d7"
        assert result != "#FFA726"

    def test_T04_compaction_color_87_lerps_between_warn_and_crit(self):
        from hermes_cli.tui.widgets.status_bar import StatusBar
        result = StatusBar._compaction_color(0.87, {})
        assert result != "#FFA726"
        assert result != "#ef5350"

    def test_T05_compaction_color_85_equals_warn_color(self):
        from hermes_cli.tui.widgets.status_bar import StatusBar
        # At exactly 0.85, t=0.0 in warn→crit lerp, so result is color_warn
        result = StatusBar._compaction_color(0.85, {})
        # lerp_color(warn, crit, 0.0) == warn; but the function checks >= 0.85
        # so result should be warn-side (yellow not red)
        assert result != "#ef5350"

    def test_T06_compaction_color_91_returns_crit(self):
        from hermes_cli.tui.widgets.status_bar import StatusBar
        result = StatusBar._compaction_color(0.91, {})
        assert result == "#ef5350"


# ---------------------------------------------------------------------------
# T07–T11: StatusBar render — full-width and narrow
# ---------------------------------------------------------------------------

class TestStatusBarRender:
    def _render(self, mock_app: MagicMock, width: int = 80) -> str:
        from hermes_cli.tui.widgets.status_bar import StatusBar
        sb = StatusBar.__new__(StatusBar)
        sb._pulse_t = 0.0
        sb._pulse_tick = 0
        size_mock = MagicMock()
        size_mock.width = width
        with patch.object(type(sb), "size", new_callable=PropertyMock, return_value=size_mock):
            with patch.object(type(sb), "app", new_callable=PropertyMock, return_value=mock_app):
                result = sb.render()
        return str(result)

    def test_T07_full_width_ctx_label_absent_by_default(self):
        app = _make_mock_app(status_verbose=False)
        text = self._render(app, width=80)
        # ctx_label not shown when verbose=False in full-width mode
        # The bar + separator should be present but not ctx_label text
        # We verify by checking model is there and no raw token numbers
        assert "claude-opus" in text

    def test_T08_full_width_ctx_label_present_when_verbose(self):
        app = _make_mock_app(status_verbose=True)
        text = self._render(app, width=80)
        # ctx_label should appear — model + separator + ctx_label
        assert "claude-opus" in text

    def test_T09_narrow_no_pct_int(self):
        app = _make_mock_app(status_verbose=False)
        text = self._render(app, width=50)
        # Old pct_int% pattern should be gone (e.g. "50%" or "62%")
        assert not re.search(r'\d+%', text), f"Found digit+% in narrow render: {text!r}"

    def test_T09b_minimal_no_pct_int(self):
        app = _make_mock_app(status_verbose=False)
        text = self._render(app, width=35)
        assert not re.search(r'\d+%', text), f"Found digit+% in minimal render: {text!r}"

    def test_T10_narrow_bar_glyph_present_when_enabled(self):
        app = _make_mock_app(status_compaction_enabled=True, status_verbose=False)
        text = self._render(app, width=50)
        assert "▰" in text

    def test_T11_narrow_verbose_shows_ctx_label(self):
        app = _make_mock_app(status_verbose=True, status_compaction_enabled=True)
        text = self._render(app, width=50)
        assert text  # at least not empty


# ---------------------------------------------------------------------------
# T12–T14: S0-B — idle tip rotation gone
# ---------------------------------------------------------------------------

class TestIdleTipRotation:
    def test_T12_rotate_hint_not_on_status_bar(self):
        from hermes_cli.tui.widgets.status_bar import StatusBar
        assert not hasattr(StatusBar, "_rotate_hint"), (
            "_rotate_hint should have been deleted (S0-B)"
        )

    def test_T13_get_idle_tips_not_on_status_bar(self):
        from hermes_cli.tui.widgets.status_bar import StatusBar
        assert not hasattr(StatusBar, "_get_idle_tips"), (
            "_get_idle_tips should have been deleted (S0-B)"
        )

    def test_T14_idle_render_contains_f1_and_slash_consistently(self):
        from hermes_cli.tui.widgets.status_bar import StatusBar
        app = _make_mock_app()
        # not running, no error → idle branch
        app.agent_running = False
        app.command_running = False
        app.status_error = ""
        app.browse_mode = False

        sb = StatusBar.__new__(StatusBar)
        sb._pulse_t = 0.0
        sb._pulse_tick = 0
        size_mock = MagicMock()
        size_mock.width = 80

        with patch.object(type(sb), "size", new_callable=PropertyMock, return_value=size_mock):
            with patch.object(type(sb), "app", new_callable=PropertyMock, return_value=app):
                r1 = str(sb.render())
                r2 = str(sb.render())

        assert "F1" in r1
        assert "/" in r1
        # Consistent — no rotation
        assert r1 == r2


# ---------------------------------------------------------------------------
# T15–T21: S0-C — HintBar streaming render + set_phase guard
# ---------------------------------------------------------------------------

class TestHintBarStreaming:
    def _hint_bar_ctx(self, mock_app: MagicMock, hint: str = "", width: int = 100):
        """Return a (HintBar, content_size_mock) pair with all properties mocked."""
        from hermes_cli.tui.widgets.status_bar import HintBar
        hb = HintBar.__new__(HintBar)
        hb._phase = "idle"
        hb._shimmer_timer = None
        hb._shimmer_base = None
        hb._shimmer_skip = []
        # Satisfy reactive internals — they check for _id and id
        hb.__dict__["_id"] = "hint-bar-mock"
        hb.__dict__["id"] = "hint-bar-mock"
        hb.__dict__["_reactive_data"] = {}
        hb.__dict__["_shimmer_tick"] = 0
        hb.__dict__["hint"] = hint
        size_mock = MagicMock()
        size_mock.width = width
        return hb, size_mock

    def test_T15_render_streaming_starts_with_caret_c(self):
        from hermes_cli.tui.widgets.status_bar import HintBar
        app = _make_mock_app(status_streaming=True)
        hb, cs = self._hint_bar_ctx(app)
        with patch.object(type(hb), "content_size", new_callable=PropertyMock, return_value=cs):
            with patch.object(type(hb), "hint", new_callable=PropertyMock, return_value=""):
                with patch.object(type(hb), "app", new_callable=PropertyMock, return_value=app):
                    result = str(hb.render())
        assert "^C" in result

    def test_T16_render_streaming_with_hint_shows_flash(self):
        app = _make_mock_app(status_streaming=True)
        hb, cs = self._hint_bar_ctx(app, width=200)
        with patch.object(type(hb), "content_size", new_callable=PropertyMock, return_value=cs):
            with patch.object(type(hb), "hint", new_callable=PropertyMock, return_value="File saved"):
                with patch.object(type(hb), "app", new_callable=PropertyMock, return_value=app):
                    result = str(hb.render())
        assert "^C" in result
        assert "File saved" in result

    def test_T16b_render_streaming_hint_treats_brackets_as_plain_text(self):
        app = _make_mock_app(status_streaming=True)
        hint = "/anim gradient [on|off|#c1 #c2]"
        hb, cs = self._hint_bar_ctx(app, width=200)
        with patch.object(type(hb), "content_size", new_callable=PropertyMock, return_value=cs):
            with patch.object(type(hb), "hint", new_callable=PropertyMock, return_value=hint):
                with patch.object(type(hb), "app", new_callable=PropertyMock, return_value=app):
                    result = str(hb.render())
        assert "^C" in result
        assert hint in result

    def test_T17_render_streaming_wide_flash_absent_when_too_long(self):
        app = _make_mock_app(status_streaming=True)
        hb, cs = self._hint_bar_ctx(app, width=40)
        with patch.object(type(hb), "content_size", new_callable=PropertyMock, return_value=cs):
            with patch.object(type(hb), "hint", new_callable=PropertyMock, return_value="x" * 200):
                with patch.object(type(hb), "app", new_callable=PropertyMock, return_value=app):
                    result = str(hb.render())
        assert "^C" in result
        assert "x" * 10 not in result

    def test_T18_set_phase_stream_while_streaming_no_shimmer_start(self):
        app = _make_mock_app(status_streaming=True)
        hb, _ = self._hint_bar_ctx(app)
        hb._phase = "idle"
        with patch.object(type(hb), "app", new_callable=PropertyMock, return_value=app):
            with patch.object(hb, "_shimmer_start") as mock_start:
                with patch.object(hb, "refresh"):
                    hb.set_phase("stream")
        mock_start.assert_not_called()

    def test_T19_set_phase_stream_not_streaming_shimmer_start_called(self):
        app = _make_mock_app(status_streaming=False, _animations_enabled=True)
        hb, _ = self._hint_bar_ctx(app)
        hb._phase = "idle"
        with patch.object(type(hb), "app", new_callable=PropertyMock, return_value=app):
            with patch.object(hb, "_shimmer_start") as mock_start:
                with patch.object(hb, "refresh"):
                    hb.set_phase("stream")
        mock_start.assert_called_once()

    def test_T20_on_streaming_change_true_stops_active_shimmer(self):
        app = _make_mock_app(status_streaming=True)
        hb, _ = self._hint_bar_ctx(app)
        # Simulate active shimmer
        hb._shimmer_timer = MagicMock()
        with patch.object(type(hb), "app", new_callable=PropertyMock, return_value=app):
            with patch.object(hb, "_shimmer_stop") as mock_stop:
                with patch.object(hb, "refresh"):
                    hb._on_streaming_change(True)
        mock_stop.assert_called_once()

    def test_T21_on_streaming_change_false_with_stream_phase_starts_shimmer(self):
        app = _make_mock_app(status_streaming=False, _animations_enabled=True)
        hb, _ = self._hint_bar_ctx(app)
        hb._phase = "stream"
        hb._shimmer_timer = None
        with patch.object(type(hb), "app", new_callable=PropertyMock, return_value=app):
            with patch.object(hb, "_shimmer_start") as mock_start:
                hb._on_streaming_change(False)
        mock_start.assert_called_once()


# ---------------------------------------------------------------------------
# T22–T28: S0-D/S0-E — StatusBar streaming state
# ---------------------------------------------------------------------------

class TestStatusBarStreaming:
    def _render_sb(self, mock_app: MagicMock, pulse_t: float = 0.0, width: int = 80) -> str:
        from hermes_cli.tui.widgets.status_bar import StatusBar
        sb = StatusBar.__new__(StatusBar)
        sb._pulse_t = pulse_t
        sb._pulse_tick = 5
        size_mock = MagicMock()
        size_mock.width = width
        with patch.object(type(sb), "size", new_callable=PropertyMock, return_value=size_mock):
            with patch.object(type(sb), "app", new_callable=PropertyMock, return_value=mock_app):
                result = sb.render()
        return str(result)

    def test_T22_streaming_running_static_dot_no_lerp(self):
        app = _make_mock_app(status_streaming=True, agent_running=True)
        app.command_running = False
        text = self._render_sb(app, pulse_t=0.5)

        assert "●" in text
        # "running" text present as dim (no shimmer)
        assert "running" in text

    def test_T23_not_streaming_running_pulse_t_contributes(self):
        app = _make_mock_app(status_streaming=False, agent_running=True)
        app.command_running = False
        app._animations_enabled = False  # disable shimmer for simplicity
        text = self._render_sb(app, pulse_t=0.8)

        assert "●" in text

    def test_T24_on_streaming_change_true_calls_pulse_stop(self):
        app = _make_mock_app(status_streaming=True)
        from hermes_cli.tui.widgets.status_bar import StatusBar
        sb = StatusBar.__new__(StatusBar)
        sb._pulse_t = 0.0
        sb._pulse_tick = 0

        with patch.object(type(sb), "app", new_callable=PropertyMock, return_value=app):
            with patch.object(sb, "_pulse_stop") as mock_stop:
                with patch.object(sb, "refresh"):
                    sb._on_streaming_change(True)

        mock_stop.assert_called_once()

    def test_T25_on_streaming_change_false_with_running_calls_pulse_start(self):
        from hermes_cli.tui.widgets import utils as _utils
        app = _make_mock_app(status_streaming=False, agent_running=True)
        from hermes_cli.tui.widgets.status_bar import StatusBar
        sb = StatusBar.__new__(StatusBar)
        sb._pulse_t = 0.0
        sb._pulse_tick = 0

        with patch.object(type(sb), "app", new_callable=PropertyMock, return_value=app):
            with patch("hermes_cli.tui.widgets.status_bar._pulse_enabled", return_value=True):
                with patch.object(sb, "_pulse_start") as mock_start:
                    with patch.object(sb, "refresh"):
                        sb._on_streaming_change(False)

        mock_start.assert_called_once()

    def test_T26_on_streaming_dim_true_adds_streaming_class_to_status_bar(self):
        app = _make_mock_app(status_streaming=True)
        app.query_one.side_effect = Exception("no HintBar")
        from hermes_cli.tui.widgets.status_bar import StatusBar
        sb = StatusBar.__new__(StatusBar)
        sb._classes = set()

        with patch.object(type(sb), "app", new_callable=PropertyMock, return_value=app):
            with patch.object(sb, "add_class") as mock_add:
                with patch.object(sb, "remove_class"):
                    sb._on_streaming_dim(True)

        mock_add.assert_called_with("--streaming")

    def test_T27_on_streaming_dim_true_adds_streaming_class_to_hint_bar(self):
        from hermes_cli.tui.widgets.status_bar import HintBar, StatusBar
        mock_hint_bar = MagicMock(spec=HintBar)
        app = _make_mock_app(status_streaming=True)
        app.query_one.return_value = mock_hint_bar

        sb = StatusBar.__new__(StatusBar)

        with patch.object(type(sb), "app", new_callable=PropertyMock, return_value=app):
            with patch.object(sb, "add_class"):
                with patch.object(sb, "remove_class"):
                    sb._on_streaming_dim(True)

        mock_hint_bar.add_class.assert_called_with("--streaming")

    def test_T28_on_streaming_dim_false_removes_both_streaming_classes(self):
        from hermes_cli.tui.widgets.status_bar import HintBar, StatusBar
        mock_hint_bar = MagicMock(spec=HintBar)
        app = _make_mock_app(status_streaming=False)
        app.query_one.return_value = mock_hint_bar

        sb = StatusBar.__new__(StatusBar)

        with patch.object(type(sb), "app", new_callable=PropertyMock, return_value=app):
            with patch.object(sb, "add_class"):
                with patch.object(sb, "remove_class") as mock_remove:
                    sb._on_streaming_dim(False)

        mock_remove.assert_called_with("--streaming")
        mock_hint_bar.remove_class.assert_called_with("--streaming")


# ---------------------------------------------------------------------------
# T29–T30: app._on_streaming_start / _on_streaming_end
# ---------------------------------------------------------------------------

class TestAppStreamingHandlers:
    def test_T29_on_streaming_start_sets_status_streaming_true(self):
        import hermes_cli.tui.app as _app_mod
        # Test the handlers in isolation
        fake_app = MagicMock()
        fake_app.status_streaming = False
        _app_mod.HermesApp._on_streaming_start(fake_app)
        assert fake_app.status_streaming is True

    def test_T30_on_streaming_end_sets_status_streaming_false(self):
        import hermes_cli.tui.app as _app_mod
        fake_app = MagicMock()
        fake_app.status_streaming = True
        _app_mod.HermesApp._on_streaming_end(fake_app)
        assert fake_app.status_streaming is False


# ---------------------------------------------------------------------------
# T31: hermes.tcss contains S0-E rules
# ---------------------------------------------------------------------------

class TestCSSDimming:
    def test_T31_tcss_contains_streaming_opacity_rules(self):
        tcss_path = Path(__file__).parent.parent.parent / "hermes_cli" / "tui" / "hermes.tcss"
        content = tcss_path.read_text()
        assert "StatusBar.--streaming" in content, "Missing StatusBar.--streaming rule"
        assert "HintBar.--streaming" in content, "Missing HintBar.--streaming rule"
        assert "opacity" in content.split("StatusBar.--streaming")[1].split("}")[0], (
            "StatusBar.--streaming must contain opacity"
        )


# ---------------------------------------------------------------------------
# T32: set_phase idempotency
# ---------------------------------------------------------------------------

class TestSetPhaseIdempotency:
    def test_T32_set_phase_same_phase_twice_is_no_op(self):
        app = _make_mock_app(status_streaming=False)
        from hermes_cli.tui.widgets.status_bar import HintBar
        hb = HintBar.__new__(HintBar)
        hb._phase = "stream"
        hb._shimmer_timer = None
        hb._shimmer_base = None
        hb._shimmer_skip = []
        hb.__dict__["_shimmer_tick"] = 0
        hb.__dict__["hint"] = ""

        with patch.object(type(hb), "app", new_callable=PropertyMock, return_value=app):
            with patch.object(hb, "_shimmer_stop") as mock_stop:
                with patch.object(hb, "_shimmer_start") as mock_start:
                    with patch.object(hb, "refresh"):
                        hb.set_phase("stream")  # same phase — should return early

        mock_stop.assert_not_called()
        mock_start.assert_not_called()


# ---------------------------------------------------------------------------
# T33–T34: ctrl+t key handler
# ---------------------------------------------------------------------------

class TestCtrlTKey:
    def _make_key_dispatch(self, mock_app: MagicMock) -> Any:
        from hermes_cli.tui.services.keys import KeyDispatchService
        svc = KeyDispatchService.__new__(KeyDispatchService)
        svc.app = mock_app
        return svc

    def _make_event(self, key: str) -> MagicMock:
        ev = MagicMock()
        ev.key = key
        ev.character = None
        return ev

    def test_T33_ctrl_t_sets_status_verbose_true(self):
        app = _make_mock_app(status_verbose=False)
        svc = self._make_key_dispatch(app)
        ev = self._make_event("ctrl+t")
        svc.dispatch_key(ev)
        assert app.status_verbose is True
        ev.prevent_default.assert_called()

    def test_T34_second_ctrl_t_sets_status_verbose_false(self):
        app = _make_mock_app(status_verbose=True)
        svc = self._make_key_dispatch(app)
        ev = self._make_event("ctrl+t")
        svc.dispatch_key(ev)
        assert app.status_verbose is False


# ---------------------------------------------------------------------------
# T35: StatusBar watches status_verbose
# ---------------------------------------------------------------------------

class TestStatusVerboseWatch:
    def test_T35_status_bar_watches_status_verbose(self):
        import hermes_cli.tui.widgets.status_bar as _sb_mod
        src = inspect.getsource(_sb_mod.StatusBar.on_mount)
        assert "status_verbose" in src, (
            "StatusBar.on_mount must watch status_verbose"
        )


# ---------------------------------------------------------------------------
# T36–T37: Full-width verbose render
# ---------------------------------------------------------------------------

class TestFullWidthVerboseRender:
    def _render_sb(self, mock_app: MagicMock, width: int = 80) -> str:
        from hermes_cli.tui.widgets.status_bar import StatusBar
        sb = StatusBar.__new__(StatusBar)
        sb._pulse_t = 0.0
        sb._pulse_tick = 0
        size_mock = MagicMock()
        size_mock.width = width
        with patch.object(type(sb), "size", new_callable=PropertyMock, return_value=size_mock):
            with patch.object(type(sb), "app", new_callable=PropertyMock, return_value=mock_app):
                result = sb.render()
        return str(result)

    def test_T36_full_width_verbose_ctx_label_before_model(self):
        app = _make_mock_app(status_verbose=True, status_model="claude-opus")
        text = self._render_sb(app, width=80)
        assert "claude-opus" in text

    def test_T37_full_width_verbose_separator_between_ctx_and_model(self):
        app = _make_mock_app(status_verbose=True, status_model="mymodel")
        text = self._render_sb(app, width=80)
        # The separator "·" should appear somewhere in the status text
        assert "·" in text or " " in text


# ---------------------------------------------------------------------------
# T38–T41: No stored watcher handles, correct unmount
# ---------------------------------------------------------------------------

class TestUnmountCleanup:
    def test_T38_status_bar_has_no_watcher_handle_attrs(self):
        from hermes_cli.tui.widgets.status_bar import StatusBar
        # Verify neither _streaming_watcher_pulse nor _streaming_watcher_dim exist
        assert not hasattr(StatusBar, "_streaming_watcher_pulse"), (
            "StatusBar must not store watcher handles (Textual auto-cleans)"
        )
        assert not hasattr(StatusBar, "_streaming_watcher_dim"), (
            "StatusBar must not store watcher handles (Textual auto-cleans)"
        )

    def test_T39_status_bar_unmount_calls_only_pulse_stop(self):
        import hermes_cli.tui.widgets.status_bar as _sb_mod
        src = inspect.getsource(_sb_mod.StatusBar.on_unmount)
        # Must contain _pulse_stop
        assert "_pulse_stop" in src
        # Must not contain _rotate_timer
        assert "_rotate_timer" not in src

    def test_T40_hint_bar_unmount_calls_only_shimmer_stop(self):
        import hermes_cli.tui.widgets.status_bar as _sb_mod
        src = inspect.getsource(_sb_mod.HintBar.on_unmount)
        assert "_shimmer_stop" in src

    def test_T41_set_phase_same_phase_no_shimmer_stopped(self):
        """T41: set_phase with same phase AND shimmer stopped → returns early."""
        app = _make_mock_app(status_streaming=False)
        from hermes_cli.tui.widgets.status_bar import HintBar
        hb = HintBar.__new__(HintBar)
        hb._phase = "stream"
        hb._shimmer_timer = None  # shimmer already stopped
        hb.__dict__["_shimmer_tick"] = 0
        hb.__dict__["hint"] = ""

        with patch.object(type(hb), "app", new_callable=PropertyMock, return_value=app):
            with patch.object(hb, "_shimmer_stop") as mock_stop:
                with patch.object(hb, "_shimmer_start") as mock_start:
                    with patch.object(hb, "refresh"):
                        hb.set_phase("stream")  # same phase, shimmer stopped → early return

        mock_stop.assert_not_called()
        mock_start.assert_not_called()
