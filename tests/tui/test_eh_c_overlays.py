"""EH-C compliance tests for hermes_cli/tui/overlays/ exception handling."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import pytest


# ---------------------------------------------------------------------------
# TestAdapters — EH-C-01..06
# ---------------------------------------------------------------------------

class TestAdapters:
    """Tests for _adapters.py exception-handling fixes."""

    def _make_state(self, deadline: float = 0.0, remaining: float = 30.0) -> SimpleNamespace:
        state = SimpleNamespace(
            deadline=deadline,
            remaining=remaining,
            response_queue=MagicMock(),
            choices=["yes", "no"],
            selected=0,
            question="test?",
            user_text="hello",
            has_checkpoint=False,
        )
        state.response_queue.put = MagicMock()
        return state

    def test_adapters_on_resolve_queue_put_error(self) -> None:
        """EH-C-01: queue.put failure logs at debug with exc_info."""
        from hermes_cli.tui.overlays._adapters import _make_on_resolve

        state = self._make_state()
        state.response_queue.put.side_effect = RuntimeError("queue full")
        app = MagicMock()
        cb = _make_on_resolve("clarify_state", app, state)

        with patch("hermes_cli.tui.overlays._adapters._log") as mock_log:
            cb("some_value")
            mock_log.debug.assert_called_once()
            call = mock_log.debug.call_args
            assert call.kwargs.get("exc_info") is True

    def test_adapters_on_resolve_setattr_error(self) -> None:
        """EH-C-02: setattr app reactive failure logs at debug with exc_info."""
        from hermes_cli.tui.overlays._adapters import _make_on_resolve

        state = self._make_state()
        app = MagicMock()
        # Make setattr raise
        type(app).__setattr__ = MagicMock(side_effect=AttributeError("frozen"))

        cb = _make_on_resolve("clarify_state", app, state)

        with patch("hermes_cli.tui.overlays._adapters._log") as mock_log:
            cb("some_value")
            calls = mock_log.debug.call_args_list
            assert any(c.kwargs.get("exc_info") is True for c in calls)

    def test_adapters_adopt_deadline_error(self) -> None:
        """EH-C-03: malformed deadline logs at debug with exc_info."""
        from hermes_cli.tui.overlays._adapters import _adopt_state_deadline
        from hermes_cli.tui.overlays.interrupt import InterruptKind, InterruptPayload

        p = InterruptPayload(kind=InterruptKind.CLARIFY, countdown_s=30.0)
        state = SimpleNamespace(deadline="not-a-float", remaining=30.0)

        with patch("hermes_cli.tui.overlays._adapters._log") as mock_log:
            result = _adopt_state_deadline(p, state)
            mock_log.debug.assert_called_once()
            assert mock_log.debug.call_args.kwargs.get("exc_info") is True
        assert result is p  # payload returned unchanged

    def test_adapters_resolve_undo_queue_error(self) -> None:
        """EH-C-04: undo queue.put failure logs at debug."""
        from hermes_cli.tui.overlays._adapters import make_undo_payload

        state = SimpleNamespace(
            deadline=0.0,
            remaining=30.0,
            response_queue=MagicMock(),
            user_text="old msg",
            has_checkpoint=False,
        )
        state.response_queue.put.side_effect = RuntimeError("broken queue")
        app = MagicMock()
        payload = make_undo_payload(app, state)

        with patch("hermes_cli.tui.overlays._adapters._log") as mock_log:
            payload.on_resolve("y")
            calls = mock_log.debug.call_args_list
            assert any(
                "undo" in (c.args[0] if c.args else "").lower()
                and c.kwargs.get("exc_info") is True
                for c in calls
            )

    def test_adapters_resolve_undo_clear_accepted_error(self) -> None:
        """EH-C-05: undo accepted path clear failure logs at debug."""
        from hermes_cli.tui.overlays._adapters import make_undo_payload

        state = SimpleNamespace(
            deadline=0.0,
            remaining=30.0,
            response_queue=MagicMock(),
            user_text="old msg",
            has_checkpoint=False,
        )
        app = MagicMock()
        # Make attribute assignment raise
        type(app).__setattr__ = MagicMock(side_effect=AttributeError("frozen"))
        payload = make_undo_payload(app, state)

        with patch("hermes_cli.tui.overlays._adapters._log") as mock_log:
            payload.on_resolve("y")
            calls = mock_log.debug.call_args_list
            assert any(
                "accepted" in (c.args[0] if c.args else "").lower()
                and c.kwargs.get("exc_info") is True
                for c in calls
            )

    def test_adapters_resolve_undo_clear_cancel_error(self) -> None:
        """EH-C-06: undo cancel path clear failure logs at debug."""
        from hermes_cli.tui.overlays._adapters import make_undo_payload

        state = SimpleNamespace(
            deadline=0.0,
            remaining=30.0,
            response_queue=MagicMock(),
            user_text="old msg",
            has_checkpoint=False,
        )
        app = MagicMock()
        type(app).__setattr__ = MagicMock(side_effect=AttributeError("frozen"))
        payload = make_undo_payload(app, state)

        with patch("hermes_cli.tui.overlays._adapters._log") as mock_log:
            payload.on_resolve("n")
            calls = mock_log.debug.call_args_list
            assert any(
                "cancel" in (c.args[0] if c.args else "").lower()
                and c.kwargs.get("exc_info") is True
                for c in calls
            )


# ---------------------------------------------------------------------------
# TestConfigOverlay — EH-C-11,12,14,16,18,21
# ---------------------------------------------------------------------------

class TestConfigOverlay:
    """Tests for config.py exception-handling fixes."""

    def _make_overlay_with_app(self):
        """Return (overlay, app_mock) — app is patched by overriding property on isolated subclass."""
        from hermes_cli.tui.overlays.config import ConfigOverlay
        from textual.css.query import NoMatches

        app_mock = MagicMock()

        # Fresh subclass per call; override app with plain property to avoid Textual tree walk
        class _Isolated(ConfigOverlay):
            pass

        _Isolated.app = property(lambda self: app_mock)  # type: ignore[method-assign]

        overlay = _Isolated.__new__(_Isolated)
        overlay._yolo_previous_mode = "manual"
        overlay._reasoning_current_level = "medium"
        overlay._snap_css_vars = {}
        overlay._snap_component_vars = {}
        overlay._snap_skin_name = "default"
        overlay._current_skin = "default"
        overlay._current_syntax = "monokai"
        overlay._skin_names = []
        overlay._syntax_schemes = []
        overlay.query_one = MagicMock(side_effect=NoMatches(""))

        return overlay, app_mock

    def test_config_skin_preview_load_error(self) -> None:
        """EH-C-11: skin preview load failure logs at debug with exc_info."""
        overlay, app_mock = self._make_overlay_with_app()
        tm = MagicMock()
        tm.load_skin.side_effect = ValueError("bad skin")
        app_mock._theme_manager = tm

        event = MagicMock()
        event.option_list = MagicMock()
        event.option_list.id = "co-skin-list"
        event.option = MagicMock()
        event.option.id = "co-skin-opt-aurora"

        with patch("hermes_cli.tui.overlays.config._log") as mock_log:
            overlay.on_option_list_option_highlighted(event)
            mock_log.debug.assert_called_once()
            assert mock_log.debug.call_args.kwargs.get("exc_info") is True

    def test_config_confirm_model_apply_error(self) -> None:
        """EH-C-12: model apply failure logs at warning with exc_info."""
        overlay, app_mock = self._make_overlay_with_app()
        # Make the inner model application raise so the outer except fires
        app_mock.query_one.side_effect = RuntimeError("HermesInput not found")

        with patch("hermes_cli.tui.overlays.config._log") as mock_log, \
             patch("hermes_cli.tui.overlays.config._dismiss_overlay_and_focus_input"):
            overlay._confirm_model("claude-3-5-haiku")
            mock_log.warning.assert_called_once()
            assert mock_log.warning.call_args.kwargs.get("exc_info") is True

    def test_config_confirm_verbose_save_error(self) -> None:
        """EH-C-14: verbose config save failure logs at warning with exc_info."""
        overlay, _app = self._make_overlay_with_app()

        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config", return_value={}), \
             patch("hermes_cli.tui.overlays.config._cfg_save_config", side_effect=OSError("disk full")), \
             patch("hermes_cli.tui.overlays.config._dismiss_overlay_and_focus_input"), \
             patch("hermes_cli.tui.overlays.config._log") as mock_log:
            overlay._confirm_verbose("all")
            mock_log.warning.assert_called_once()
            call = mock_log.warning.call_args
            assert call.kwargs.get("exc_info") is True
            assert "verbose" in call.args[0].lower()

    def test_config_confirm_skin_save_error(self) -> None:
        """EH-C-16: skin config save failure logs at warning with exc_info."""
        overlay, _app = self._make_overlay_with_app()

        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config", return_value={}), \
             patch("hermes_cli.tui.overlays.config._cfg_save_config", side_effect=OSError("disk full")), \
             patch("hermes_cli.tui.overlays.config._log") as mock_log:
            overlay._confirm_skin("aurora")
            mock_log.warning.assert_called_once()
            call = mock_log.warning.call_args
            assert call.kwargs.get("exc_info") is True
            assert "skin" in call.args[0].lower()

    def test_config_confirm_syntax_save_error(self) -> None:
        """EH-C-18: syntax theme config save failure logs at warning with exc_info."""
        overlay, _app = self._make_overlay_with_app()

        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config", return_value={}), \
             patch("hermes_cli.tui.overlays.config._cfg_save_config", side_effect=OSError("disk full")), \
             patch("hermes_cli.tui.overlays.config._log") as mock_log:
            overlay._confirm_syntax("dracula")
            mock_log.warning.assert_called_once()
            call = mock_log.warning.call_args
            assert call.kwargs.get("exc_info") is True
            assert "syntax" in call.args[0].lower()

    def test_config_set_yolo_save_error(self) -> None:
        """EH-C-21: YOLO config save failure logs at warning with exc_info."""
        overlay, _app = self._make_overlay_with_app()

        with patch("hermes_cli.tui.overlays.config._cfg_read_raw_config", return_value={}), \
             patch("hermes_cli.tui.overlays.config._cfg_save_config", side_effect=OSError("disk full")), \
             patch("hermes_cli.tui.overlays.config._dismiss_overlay_and_focus_input"), \
             patch("hermes_cli.tui.overlays.config._log") as mock_log:
            overlay._set_yolo(True)
            warning_calls = mock_log.warning.call_args_list
            assert len(warning_calls) >= 1
            assert warning_calls[0].kwargs.get("exc_info") is True


# ---------------------------------------------------------------------------
# TestInterruptOverlay — EH-C-28,30,36,38
# ---------------------------------------------------------------------------

class TestInterruptOverlay:
    """Tests for interrupt.py exception-handling fixes."""

    def _make_overlay(self):
        """Return (overlay, app_mock) with app and is_mounted patched on isolated subclass."""
        from hermes_cli.tui.overlays.interrupt import InterruptOverlay
        from textual.css.query import NoMatches

        app_mock = MagicMock()

        class _Isolated(InterruptOverlay):
            app = property(lambda self: app_mock)  # type: ignore[assignment]
            is_mounted = property(lambda self: True)  # type: ignore[assignment]

        overlay = _Isolated.__new__(_Isolated)
        # Satisfy Textual reactive checks
        overlay.__dict__["_id"] = "test-overlay"

        overlay._queue = []
        overlay._current_payload = None
        overlay._countdown_timer = None
        overlay._dismiss_timer = None
        overlay._unmasked = False
        overlay._merge_strategy = "squash"
        overlay._ns_base = "current"
        overlay._enter_blocked_until = 0.0
        overlay._confirm_destructive_id = None
        overlay._confirm_destructive_timer = None

        overlay.query_one = MagicMock(side_effect=NoMatches(""))
        overlay.add_class = MagicMock()
        overlay.remove_class = MagicMock()
        # Override display as plain instance attr (bypass Textual reactive)
        _Isolated.display = property(  # type: ignore[method-assign]
            lambda self: False, lambda self, v: None
        )
        overlay.set_interval = MagicMock(side_effect=RuntimeError("not mounted"))
        overlay._refresh_countdown_display = MagicMock()
        overlay._stop_countdown_timer = MagicMock()
        overlay._stop_dismiss_timer = MagicMock()
        overlay._clear_destructive_confirm = MagicMock()

        return overlay, app_mock

    def test_interrupt_activate_countdown_timer_error(self) -> None:
        """EH-C-28: set_interval failure logs at debug with exc_info."""
        from hermes_cli.tui.overlays.interrupt import (
            InterruptKind,
            InterruptPayload,
            _COUNTDOWN_ALLOWED,
        )

        overlay, _app = self._make_overlay()
        overlay._render_current = MagicMock()
        overlay.call_after_refresh = MagicMock(side_effect=RuntimeError("not mounted"))
        overlay.has_class = MagicMock(return_value=False)

        payload = InterruptPayload(
            kind=InterruptKind.CLARIFY,
            countdown_s=30.0,
        )
        assert payload.kind in _COUNTDOWN_ALLOWED

        with patch("hermes_cli.tui.overlays.interrupt._log") as mock_log:
            overlay._activate(payload)
            mock_log.debug.assert_called_once()
            assert mock_log.debug.call_args.kwargs.get("exc_info") is True
        assert overlay._countdown_timer is None

    def test_interrupt_teardown_on_resolve_error(self) -> None:
        """EH-C-30: on_resolve callback failure logs at warning with exc_info."""
        from hermes_cli.tui.overlays.interrupt import (
            InterruptKind,
            InterruptPayload,
        )

        overlay, _app = self._make_overlay()
        on_resolve = MagicMock(side_effect=RuntimeError("callback exploded"))
        payload = InterruptPayload(
            kind=InterruptKind.CLARIFY,
            on_resolve=on_resolve,
        )
        overlay._current_payload = payload

        with patch("hermes_cli.tui.overlays.interrupt._log") as mock_log:
            overlay._teardown_current(resolve=True, value="y")
            mock_log.warning.assert_called_once()
            call = mock_log.warning.call_args
            assert call.kwargs.get("exc_info") is True
            assert "on_resolve" in call.args[0].lower()

    def test_interrupt_drain_queue_on_resolve_error(self) -> None:
        """EH-C-36: drain_queue on_resolve failure logs at warning with exc_info."""
        from hermes_cli.tui.overlays.interrupt import (
            InterruptKind,
            InterruptPayload,
        )

        overlay, _app = self._make_overlay()
        on_resolve = MagicMock(side_effect=RuntimeError("resolve exploded"))
        queued = InterruptPayload(
            kind=InterruptKind.CLARIFY,
            on_resolve=on_resolve,
        )
        overlay._queue = [queued]
        overlay.dismiss_current = MagicMock()

        with patch("hermes_cli.tui.overlays.interrupt._log") as mock_log:
            overlay.action_drain_queue()
            warning_calls = mock_log.warning.call_args_list
            assert len(warning_calls) >= 1
            assert warning_calls[0].kwargs.get("exc_info") is True

    def test_interrupt_run_merge_error(self) -> None:
        """EH-C-38: run_merge failure logs at warning with exc_info."""
        from hermes_cli.tui.overlays.interrupt import (
            InterruptKind,
            InterruptPayload,
        )

        overlay, app_mock = self._make_overlay()
        app_mock._svc_sessions.run_merge.side_effect = RuntimeError("merge failed")

        payload = InterruptPayload(
            kind=InterruptKind.MERGE_CONFIRM,
            session_id="sess-1",
        )

        with patch("hermes_cli.tui.overlays.interrupt._log") as mock_log:
            overlay._run_merge(payload, close_on_success=True)
            mock_log.warning.assert_called_once()
            call = mock_log.warning.call_args
            assert call.kwargs.get("exc_info") is True
            assert "merge" in call.args[0].lower()


# ---------------------------------------------------------------------------
# TestReferenceOverlay — EH-C-39,40
# ---------------------------------------------------------------------------

class TestReferenceOverlay:
    """Tests for reference.py exception-handling fixes."""

    def test_reference_build_stats_rate_limit_error(self) -> None:
        """EH-C-39: get_rate_limit_state failure logs at debug with exc_info."""
        from hermes_cli.tui.overlays.reference import UsageOverlay

        overlay = UsageOverlay.__new__(UsageOverlay)
        agent = MagicMock()
        agent.get_rate_limit_state.side_effect = RuntimeError("rate limit service down")
        agent.model = "claude-3-5-sonnet"

        compressor = None
        cost_result = MagicMock()
        cost_result.amount_usd = None
        cost_result.status = "unknown"

        with patch("hermes_cli.tui.overlays.reference._log") as mock_log:
            result = overlay._build_stats(
                inp=100,
                cr=50,
                cw=10,
                out=200,
                total=360,
                calls=3,
                cost_result=cost_result,
                compressor=compressor,
                agent=agent,
            )
            mock_log.debug.assert_called_once()
            call = mock_log.debug.call_args
            assert call.kwargs.get("exc_info") is True
            assert "rate" in call.args[0].lower()
        assert isinstance(result, str)

    def test_reference_switch_tab_error(self) -> None:
        """EH-C-40: workspace tab switch failure logs at debug with exc_info."""
        from hermes_cli.tui.overlays.reference import WorkspaceOverlay

        overlay = WorkspaceOverlay.__new__(WorkspaceOverlay)
        overlay.query_one = MagicMock(side_effect=RuntimeError("switcher broken"))

        with patch("hermes_cli.tui.overlays.reference._log") as mock_log:
            overlay._switch_tab("ws-git-pane")
            mock_log.debug.assert_called_once()
            call = mock_log.debug.call_args
            assert call.kwargs.get("exc_info") is True
            assert "tab" in call.args[0].lower() or "switch" in call.args[0].lower()


# ---------------------------------------------------------------------------
# TestSkillPicker — EH-C-43
# ---------------------------------------------------------------------------

class TestSkillPicker:
    """Tests for skill_picker.py exception-handling fixes."""

    def test_skill_picker_load_candidates_error(self) -> None:
        """EH-C-43: _load_candidates failure logs at debug with exc_info."""
        from hermes_cli.tui.overlays.skill_picker import SkillPickerOverlay

        app_mock = MagicMock()
        app_mock.query_one.side_effect = RuntimeError("HermesInput not found")

        class _Isolated(SkillPickerOverlay):
            pass

        _Isolated.app = property(lambda self: app_mock)  # type: ignore[method-assign]

        overlay = _Isolated.__new__(_Isolated)
        overlay._candidates = []
        overlay._filter = ""

        with patch("hermes_cli.tui.overlays.skill_picker._log") as mock_log:
            overlay._load_candidates()
            mock_log.debug.assert_called_once()
            call = mock_log.debug.call_args
            assert call.kwargs.get("exc_info") is True
            assert "candidate" in call.args[0].lower() or "skill" in call.args[0].lower()
        assert overlay._candidates == []
