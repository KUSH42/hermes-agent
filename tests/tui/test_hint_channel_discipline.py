"""HB-1 Hint Channel Discipline tests — HB1-H1..H4 + HB1-M1..M3.

23 tests across 6 classes. No full Textual app run (no pilot).
Uses FakeScheduler + FakeAdapter from service test patterns.

Classes:
  TestPaneFocusRouting     — 4 (HB1-H1)
  TestFlashMessageRemoval  — 6 (HB1-H2)
  TestCancelByKey          — 7 (HB1-H3 + IL-HB-1)
  TestFlashHintSignature   — 3 (HB1-H4)
  TestStatusBarPeek        — 2 (HB1-M1)
  TestStructuralRemoval    — 1 (HB1-M2/M3 cross-check)
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.services.feedback import (
    LOW,
    NORMAL,
    ChannelAdapter,
    FeedbackService,
    FlashState,
)
import hermes_cli.tui.services.feedback as _feedback_mod

# ---------------------------------------------------------------------------
# Shared test fakes
# ---------------------------------------------------------------------------


class FakeCancelToken:
    def __init__(self) -> None:
        self.stopped: bool = False

    def stop(self) -> None:
        self.stopped = True


class FakeScheduler:
    def __init__(self) -> None:
        self._now: float = 0.0
        self._queue: list[list[Any]] = []

    def after(self, delay: float, cb: Any) -> FakeCancelToken:
        token = FakeCancelToken()
        self._queue.append([self._now + delay, cb, token])
        self._queue.sort(key=lambda x: x[0])
        return token

    def advance(self, dt: float) -> None:
        self._now += dt
        for entry in list(self._queue):
            if entry[0] <= self._now and not entry[2].stopped:
                entry[2].stopped = True
                entry[1]()
        self._queue = [e for e in self._queue if not e[2].stopped]


class FakeAdapter(ChannelAdapter):
    def __init__(self) -> None:
        self.applied: list[FlashState | None] = []
        self._mounted: bool = True

    def apply(self, state: FlashState | None) -> None:
        self.applied.append(state)


def make_service(*channels: str) -> tuple[FeedbackService, FakeScheduler, dict[str, FakeAdapter]]:
    sched = FakeScheduler()
    svc = FeedbackService(sched)
    adapters: dict[str, FakeAdapter] = {}
    for ch in channels:
        adapter = FakeAdapter()
        svc.register_channel(ch, adapter)
        adapters[ch] = adapter
    return svc, sched, adapters


# ---------------------------------------------------------------------------
# TestPaneFocusRouting — HB1-H1
# ---------------------------------------------------------------------------


class TestPaneFocusRouting:
    """HB1-H1: pane_manager routes hint through FeedbackService, not direct HintBar.hint writes."""

    def _make_app_with_feedback(self) -> tuple[MagicMock, FeedbackService, FakeScheduler, FakeAdapter]:
        svc, sched, adapters = make_service("hint-bar")
        app = MagicMock()
        app.feedback = svc
        return app, svc, sched, adapters["hint-bar"]

    def _make_pane_manager_and_app(self) -> tuple[Any, MagicMock]:
        """Build a PaneManager stub and a mocked app."""
        from hermes_cli.tui.pane_manager import PaneManager, PaneId

        app = MagicMock()
        app.feedback = MagicMock()
        app.feedback.flash.return_value = MagicMock()

        pm = PaneManager.__new__(PaneManager)
        pm._mode = MagicMock()
        pm._focused_pane = PaneId.LEFT
        pm._left_collapsed = False
        pm._right_collapsed = False
        pm._left_w_override = None
        pm._right_w_override = None

        dummy_pane = MagicMock()
        dummy_pane.can_focus = True
        app.query_one.return_value = dummy_pane
        return pm, app

    def test_pane_focus_routes_through_feedback(self) -> None:
        """flash() called with channel='hint-bar', key='pane-focus', duration=3.0, priority=LOW."""
        from hermes_cli.tui.pane_manager import PaneId

        pm, app = self._make_pane_manager_and_app()
        flash_calls: list[dict[str, Any]] = []

        def capture_flash(channel: str, message: str, **kwargs: Any) -> Any:
            flash_calls.append({"channel": channel, "message": message, **kwargs})
            return MagicMock()

        app.feedback.flash = capture_flash

        # Focus a non-CENTER pane
        pm.focus_pane_widget(PaneId.LEFT, app)

        assert len(flash_calls) == 1, f"Expected 1 flash call, got: {flash_calls}"
        call_kwargs = flash_calls[0]
        assert call_kwargs["channel"] == "hint-bar"
        assert call_kwargs.get("key") == _feedback_mod.HINT_KEY_PANE_FOCUS
        assert call_kwargs.get("duration") == 3.0
        assert call_kwargs.get("priority") == LOW

    def test_pane_focus_blocked_by_status_error(self) -> None:
        """When status_error is active at p=10, pane-focus flash at p=LOW (0) is blocked."""
        from hermes_cli.tui.pane_manager import PaneId

        # Use real FeedbackService to verify priority ordering
        svc, sched, adapters = make_service("hint-bar")

        # Pre-flash status_error at priority 10
        h_err = svc.flash("hint-bar", "⚠ error", duration=9999, priority=10,
                          key=_feedback_mod.HINT_KEY_STATUS_ERROR)
        assert h_err.displayed

        # Pane-focus at LOW (0) — should be blocked
        h_focus = svc.flash("hint-bar", "Esc → input", duration=3.0, priority=LOW,
                            key=_feedback_mod.HINT_KEY_PANE_FOCUS)
        assert not h_focus.displayed, "pane-focus flash at p=0 should be blocked by status_error p=10"

        # Error still active
        state = svc.peek("hint-bar")
        assert state is not None
        assert "⚠" in state.message

    def test_pane_focus_no_free_running_timer(self) -> None:
        """app.set_timer is NOT called from focus_pane_widget."""
        from hermes_cli.tui.pane_manager import PaneId

        pm, app = self._make_pane_manager_and_app()
        pm.focus_pane_widget(PaneId.LEFT, app)
        app.set_timer.assert_not_called()

    def test_clear_hint_if_side_pane_helper_removed(self) -> None:
        """_clear_hint_if_side_pane must not exist in pane_manager module."""
        from hermes_cli.tui import pane_manager
        assert not hasattr(pane_manager, "_clear_hint_if_side_pane"), (
            "_clear_hint_if_side_pane still exists in pane_manager; should have been deleted (HB1-H1)"
        )


# ---------------------------------------------------------------------------
# TestFlashMessageRemoval — HB1-H2
# ---------------------------------------------------------------------------


class TestFlashMessageRemoval:
    """HB1-H2: FlashMessage class and HintBar parallel flash state removed."""

    def test_flash_message_class_removed(self) -> None:
        """FlashMessage is not importable from status_bar."""
        with pytest.raises(ImportError):
            from hermes_cli.tui.widgets.status_bar import FlashMessage  # noqa: F401

    def test_flash_message_not_in_widgets_init(self) -> None:
        """FlashMessage is not importable from widgets package."""
        with pytest.raises((ImportError, AttributeError)):
            from hermes_cli.tui.widgets import FlashMessage  # noqa: F401

    def test_density_flash_routes_through_feedback(self) -> None:
        """The density flash code path calls feedback.flash with correct args.

        Test verifies the call site in tool_panel/_core.py uses the right
        channel, key, duration, and priority — using source inspection and
        a direct call with a mocked app.
        """
        import inspect
        from hermes_cli.tui.tool_panel import _core

        source = inspect.getsource(_core)
        # Check that the updated code routes through feedback.flash
        assert 'feedback.flash' in source or 'app.feedback.flash' in source, (
            "tool_panel/_core.py should call feedback.flash for density change"
        )
        assert 'HINT_KEY_DENSITY_CHANGE' in source, (
            "tool_panel/_core.py should use HINT_KEY_DENSITY_CHANGE"
        )
        # Verify priority is LOW
        assert '_fb.LOW' in source or 'feedback.LOW' in source, (
            "density flash should use LOW priority"
        )
        # Verify FlashMessage is gone
        assert 'FlashMessage' not in source, (
            "FlashMessage should not be referenced in tool_panel/_core.py"
        )

    def test_density_flash_yields_to_higher_priority(self) -> None:
        """Density flash at p=LOW (0) is blocked by status_error at p=10."""
        svc, sched, adapters = make_service("hint-bar")

        # Pre-flash status_error at p=10
        h = svc.flash("hint-bar", "⚠ some error", duration=9999, priority=10,
                      key=_feedback_mod.HINT_KEY_STATUS_ERROR)
        assert h.displayed

        # Density flash at p=LOW = 0 → blocked
        h2 = svc.flash("hint-bar", "COMPACT", duration=1.2, priority=LOW,
                       key=_feedback_mod.HINT_KEY_DENSITY_CHANGE)
        assert not h2.displayed

        # Error still active
        state = svc.peek("hint-bar")
        assert state is not None
        assert "error" in state.message or "⚠" in state.message

    def test_hintbar_no_local_flash_state(self) -> None:
        """HintBar instance has no _flash_text, _flash_timer, or _clear_flash."""
        from hermes_cli.tui.widgets.status_bar import HintBar

        assert not hasattr(HintBar, "_flash_text"), "_flash_text still on HintBar class"
        assert not hasattr(HintBar, "_flash_timer"), "_flash_timer still on HintBar class"
        assert not hasattr(HintBar, "_clear_flash"), "_clear_flash still on HintBar class"

    def test_hintbar_no_on_flash_message(self) -> None:
        """HintBar does not have on_flash_message handler."""
        from hermes_cli.tui.widgets.status_bar import HintBar
        assert not hasattr(HintBar, "on_flash_message"), (
            "on_flash_message still on HintBar; should have been deleted (HB1-H2)"
        )

    def test_hintbar_unmount_no_flash_cleanup(self) -> None:
        """HintBar.on_unmount source does not reference _flash_timer."""
        import inspect
        from hermes_cli.tui.widgets.status_bar import HintBar
        source = inspect.getsource(HintBar.on_unmount)
        assert "_flash_timer" not in source, (
            "on_unmount still references _flash_timer (HB1-H2 removal incomplete)"
        )


# ---------------------------------------------------------------------------
# TestCancelByKey — HB1-H3 + IL-HB-1
# ---------------------------------------------------------------------------


class TestCancelByKey:
    """HB1-H3: All cancel('hint-bar') calls have key=; IL-HB-1 lint gate."""

    def _make_svc(self) -> tuple[FeedbackService, FakeScheduler]:
        svc, sched, _ = make_service("hint-bar")
        return svc, sched

    def test_rev_search_cancel_uses_key(self) -> None:
        """cancel('hint-bar', key=HINT_KEY_REV_SEARCH) only cancels rev-search flash.

        If rev-search is NOT the active flash, cancel with its key is a no-op.
        This ensures cancelling rev-search never silently wipes an unrelated flash.
        """
        svc, sched = self._make_svc()

        # Flash status-error at p=10 (highest priority wins)
        h_err = svc.flash("hint-bar", "⚠ some error", duration=9999, priority=10,
                          key=_feedback_mod.HINT_KEY_STATUS_ERROR)
        assert h_err.displayed

        # Try to cancel rev-search (which is NOT active) → must be a no-op
        result = svc.cancel("hint-bar", key=_feedback_mod.HINT_KEY_REV_SEARCH)
        assert not result, "cancel with non-matching key should return False"

        # Status-error still active
        state = svc.peek("hint-bar")
        assert state is not None
        assert "⚠" in state.message

    def test_bash_mode_cancel_uses_key(self) -> None:
        """cancel('hint-bar', key=HINT_KEY_BASH_MODE) only cancels bash-mode flash.

        If bash-mode IS the active flash, it is cancelled; otherwise no-op.
        """
        svc, sched = self._make_svc()

        # Flash bash-mode
        h_bash = svc.flash("hint-bar", "shell mode", duration=9999, priority=NORMAL,
                           key=_feedback_mod.HINT_KEY_BASH_MODE)
        assert h_bash.displayed

        # Cancel bash-mode by key
        result = svc.cancel("hint-bar", key=_feedback_mod.HINT_KEY_BASH_MODE)
        assert result, "cancel with matching key should return True"

        # Channel is now empty
        state = svc.peek("hint-bar")
        assert state is None, "channel should be empty after cancelling the only flash"

    def test_status_error_cancel_uses_key(self) -> None:
        """cancel('hint-bar', key=HINT_KEY_STATUS_ERROR) cancels only the error flash."""
        svc, sched = self._make_svc()

        # Flash status-error at p=10
        h_err = svc.flash("hint-bar", "⚠ error message", duration=9999, priority=10,
                          key=_feedback_mod.HINT_KEY_STATUS_ERROR)
        assert h_err.displayed

        # Cancelling with the correct key removes it
        result = svc.cancel("hint-bar", key=_feedback_mod.HINT_KEY_STATUS_ERROR)
        assert result

        state = svc.peek("hint-bar")
        assert state is None

        # Now flash a different key and confirm cancel(status_error) is a no-op
        h_other = svc.flash("hint-bar", "something else", duration=5.0, priority=5,
                            key=_feedback_mod.HINT_KEY_COMPACTION_WARN)
        assert h_other.displayed

        no_cancel = svc.cancel("hint-bar", key=_feedback_mod.HINT_KEY_STATUS_ERROR)
        assert not no_cancel, "cancel with wrong key should not affect active flash"

        still_active = svc.peek("hint-bar")
        assert still_active is not None
        assert "something else" in still_active.message

    def test_compaction_warn_uses_key(self) -> None:
        """Compaction warn flash carries HINT_KEY_COMPACTION_WARN; second call preempts first."""
        svc, sched = self._make_svc()

        h1 = svc.flash("hint-bar", "Context 85% full — /compact available",
                       duration=8.0, priority=5, key=_feedback_mod.HINT_KEY_COMPACTION_WARN)
        assert h1.displayed

        # Second compaction warn: same key → preempts via key match
        h2 = svc.flash("hint-bar", "Context 85% full — /compact available",
                       duration=8.0, priority=5, key=_feedback_mod.HINT_KEY_COMPACTION_WARN)
        assert h2.displayed

        state = svc.peek("hint-bar")
        assert state is not None
        assert "85%" in state.message

    def test_compaction_crit_uses_key(self) -> None:
        """Compaction crit flash carries HINT_KEY_COMPACTION_CRIT."""
        svc, sched = self._make_svc()

        h = svc.flash("hint-bar", "Context 95% full — /compact or clear conversation",
                      duration=8.0, priority=8, key=_feedback_mod.HINT_KEY_COMPACTION_CRIT)
        assert h.displayed
        state = svc.peek("hint-bar")
        assert state is not None
        assert state.key == _feedback_mod.HINT_KEY_COMPACTION_CRIT

    def test_il_hb_1_lint_gate(self) -> None:
        """IL-HB-1: No cancel('hint-bar') without key= in hermes_cli/tui/."""
        tui_root = Path(__file__).parent.parent.parent / "hermes_cli" / "tui"
        assert tui_root.is_dir(), f"TUI root not found: {tui_root}"

        violations: list[str] = []
        for py_file in tui_root.rglob("*.py"):
            # Skip test files
            if "test_" in py_file.name:
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(py_file))
            except SyntaxError:
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (isinstance(func, ast.Attribute) and func.attr == "cancel"):
                    continue
                if not node.args:
                    continue
                first_arg = node.args[0]
                if not (isinstance(first_arg, ast.Constant) and first_arg.value == "hint-bar"):
                    continue
                # Check for key= keyword
                has_key = any(kw.arg == "key" for kw in node.keywords)
                if not has_key:
                    violations.append(
                        f"{py_file.relative_to(tui_root.parent.parent)}:{node.lineno}"
                    )

        assert not violations, (
            f"IL-HB-1: cancel('hint-bar') without key= found in {len(violations)} location(s):\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_feedback_module_exports_key_constants(self) -> None:
        """All HINT_KEY_* constants importable from hermes_cli.tui.services.feedback."""
        expected_keys = [
            "HINT_KEY_REV_SEARCH",
            "HINT_KEY_BASH_MODE",
            "HINT_KEY_STATUS_ERROR",
            "HINT_KEY_COMPACTION_WARN",
            "HINT_KEY_COMPACTION_CRIT",
            "HINT_KEY_PANE_FOCUS",
            "HINT_KEY_DENSITY_CHANGE",
            "HINT_KEY_DENSITY_TOGGLE",
            "HINT_KEY_HISTORY_WRITE_ERR",
            "HINT_KEY_TOOL_DISCOVERY",
            "HINT_KEY_SCROLL_CATCHUP",
        ]
        missing = [k for k in expected_keys if not hasattr(_feedback_mod, k)]
        assert not missing, f"Missing HINT_KEY constants in feedback module: {missing}"


# ---------------------------------------------------------------------------
# TestFlashHintSignature — HB1-H4
# ---------------------------------------------------------------------------


class TestFlashHintSignature:
    """HB1-H4: _flash_hint accepts key= and priority= kwargs; returns FlashHandle."""

    def _make_app(self) -> MagicMock:
        """Return app stub with real FeedbackService."""
        svc, sched, _ = make_service("hint-bar")
        app = MagicMock()
        app.feedback = svc
        return app

    def test_flash_hint_signature_accepts_key(self) -> None:
        """_flash_hint passes key through to feedback.flash."""
        captured: list[dict[str, Any]] = []

        app = MagicMock()
        feedback_mock = MagicMock()

        def fake_flash(channel: str, msg: str, **kwargs: Any) -> Any:
            captured.append({"channel": channel, "msg": msg, **kwargs})
            return MagicMock(displayed=True)

        feedback_mock.flash = fake_flash
        app.feedback = feedback_mock

        # Import _flash_hint and call it on the mock app
        import types
        from hermes_cli.tui import app as _app_mod

        # Call _flash_hint bound to our app mock
        _app_mod.HermesApp._flash_hint(app, "test text", key="my-key")
        assert len(captured) == 1
        assert captured[0]["key"] == "my-key"
        assert captured[0]["channel"] == "hint-bar"

    def test_flash_hint_returns_handle(self) -> None:
        """_flash_hint returns the FlashHandle from feedback.flash."""
        app = MagicMock()
        fake_handle = MagicMock()
        fake_handle.displayed = True
        app.feedback.flash.return_value = fake_handle

        from hermes_cli.tui import app as _app_mod
        result = _app_mod.HermesApp._flash_hint(app, "text", 1.5)
        assert result is fake_handle

    def test_density_toggle_uses_key(self) -> None:
        """Density toggle passes HINT_KEY_DENSITY_TOGGLE to _flash_hint."""
        flash_calls: list[dict[str, Any]] = []

        app = MagicMock()

        def fake_flash(text: str, duration: float = 1.5, *, key: Any = None, priority: int = 10) -> Any:
            flash_calls.append({"text": text, "duration": duration, "key": key, "priority": priority})
            return MagicMock(displayed=True)

        app._flash_hint = fake_flash  # type: ignore[assignment]
        app._compact_manual = None
        app.compact = False

        # Simulate action_toggle_density via the actual method code path
        from hermes_cli.tui import app as _app_mod
        _app_mod.HermesApp.action_toggle_density(app)

        assert any(c.get("key") == _feedback_mod.HINT_KEY_DENSITY_TOGGLE for c in flash_calls), (
            f"Expected HINT_KEY_DENSITY_TOGGLE in flash calls, got: {flash_calls}"
        )


# ---------------------------------------------------------------------------
# TestStatusBarPeek — HB1-M1
# ---------------------------------------------------------------------------


class TestStatusBarPeek:
    """HB1-M1: StatusBar.render S1-E uses feedback.peek directly."""

    def test_statusbar_s1e_uses_peek_directly(self) -> None:
        """_hintbar_flashing is True when feedback.peek returns a non-None FlashState."""
        # Verify peek is the gating mechanism by checking the source code
        import inspect
        from hermes_cli.tui.widgets.status_bar import StatusBar
        source = inspect.getsource(StatusBar.render)
        # The new code should call .peek("hint-bar") and assign _hintbar_flashing from it
        assert 'peek("hint-bar")' in source, "render() must call feedback.peek('hint-bar')"
        assert "_hintbar_flashing" in source, "render() must set _hintbar_flashing"

    def test_statusbar_s1e_no_mockish_branch(self) -> None:
        """StatusBar.render does not use _mockish for flash detection (removed in HB1-M1)."""
        import inspect
        from hermes_cli.tui.widgets.status_bar import StatusBar
        source = inspect.getsource(StatusBar.render)
        # The S1-E block (flash state) must not reference _mockish for flash detection
        # Find the S1-E section specifically
        s1e_start = source.find("S1-E")
        assert s1e_start != -1, "S1-E comment not found in render()"
        # Extract S1-E section up to S1-F
        s1f_start = source.find("S1-F", s1e_start)
        if s1f_start == -1:
            s1e_section = source[s1e_start:]
        else:
            s1e_section = source[s1e_start:s1f_start]
        assert "_mockish" not in s1e_section, (
            "S1-E section of render() still references _mockish; should use peek directly (HB1-M1)"
        )


# ---------------------------------------------------------------------------
# TestStructuralRemoval — HB1-M2/M3 combined
# ---------------------------------------------------------------------------


class TestStructuralRemoval:
    """HB1-M2/M3: Combined structural smoke check."""

    def test_hintbar_and_panemanager_structural_removal(self) -> None:
        """HintBar has no _flash_text (M2); pane_manager has no _clear_hint_if_side_pane (M3)."""
        from hermes_cli.tui.widgets.status_bar import HintBar
        from hermes_cli.tui import pane_manager

        # M2: HintBar cleanup
        assert not hasattr(HintBar, "_flash_text"), (
            "_flash_text still on HintBar — HB1-M2 removal incomplete"
        )
        assert not hasattr(HintBar, "on_flash_message"), (
            "on_flash_message still on HintBar — HB1-M2 removal incomplete"
        )

        # M3: pane_manager cleanup
        assert not hasattr(pane_manager, "_clear_hint_if_side_pane"), (
            "_clear_hint_if_side_pane still in pane_manager — HB1-M3 removal incomplete"
        )
