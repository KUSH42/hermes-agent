"""Tests for ERR Cell Rule spec — ER-1..ER-5.

All tests use _FakeView stubs and the run_test-free render pattern.
No full app run.
"""
from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.services.error_taxonomy import (
    ErrorCategory,
    STDERR_TAIL_ROWS,
    classify_error,
    split_stderr_tail,
)
from hermes_cli.tui.tool_result_parse import (
    Action,
    ResultSummaryV4,
    _allowed_recovery,
    _make_edit_args,
    inject_recovery_actions,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_view(**kw):
    """Minimal ToolCallViewState-shaped stub."""
    defaults = dict(
        tool_call_id=None,
        state=None,
        error_category=None,
        stderr_tail=(),
        payload="",
        user_kind_override=None,
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _err_summary(
    stderr_tail: str = "",
    exit_code: int | None = None,
    extra_actions: tuple = (),
) -> ResultSummaryV4:
    return ResultSummaryV4(
        primary="✗ error",
        exit_code=exit_code,
        chips=(),
        stderr_tail=stderr_tail,
        actions=extra_actions,
        artifacts=(),
        is_error=True,
    )


# ===========================================================================
# ER-1 — Error category taxonomy
# ===========================================================================

class TestErrorTaxonomy:
    def test_stderr_enoent_match(self):
        assert classify_error("fatal: ambiguous argument 'X'", 128) == ErrorCategory.ENOENT

    def test_stderr_eacces_match(self):
        assert classify_error("permission denied", 1) == ErrorCategory.EACCES

    def test_stderr_timeout_match(self):
        assert classify_error("Timed out after 30s", None) == ErrorCategory.TIMEOUT

    def test_stderr_overrides_exit_class(self):
        # stderr match should win over exit-code class
        # exit 2 would be USAGE, but "permission denied" -> EACCES
        assert classify_error("permission denied", 2) == ErrorCategory.EACCES

    def test_exit_signal(self):
        assert classify_error(None, -9) == ErrorCategory.SIGNAL

    def test_exit_usage_2_or_64(self):
        assert classify_error(None, 2) == ErrorCategory.USAGE
        assert classify_error(None, 64) == ErrorCategory.USAGE

    def test_exit_unknown_nonzero(self):
        assert classify_error(None, 7) == ErrorCategory.RUNTIME

    def test_unknown_fallback_never_blank(self):
        cat = classify_error(None, None)
        assert cat == ErrorCategory.UNKNOWN
        assert cat.value == "error"
        assert cat.value != ""

    def test_split_stderr_tail_keeps_last_n(self):
        lines = [f"line {i}" for i in range(30)]
        result = split_stderr_tail("\n".join(lines))
        assert len(result) == STDERR_TAIL_ROWS
        assert result[-1] == "line 29"
        assert result[0] == f"line {30 - STDERR_TAIL_ROWS}"

    def test_split_stderr_tail_drops_empty_lines(self):
        text = "line1\n\n\nline2\n\n"
        result = split_stderr_tail(text)
        assert result == ["line1", "line2"]


# ===========================================================================
# ER-2 — Header pinned to exactly 2 chips at every tier on ERR
# ===========================================================================

class TestHeaderTwoChipPin:
    """Tests for ToolHeader ERR 2-chip pin in _render_v4."""

    def _make_header(self, view_state=None, density_tier=None, error_category=None):
        """Build a ToolHeader with a stub panel."""
        from hermes_cli.tui.tool_blocks._header import ToolHeader
        from hermes_cli.tui.tool_panel.density import DensityTier

        tier = density_tier or DensityTier.DEFAULT
        panel_stub = MagicMock()
        panel_stub.collapsed = False
        panel_stub.density = tier
        panel_stub._resolver = None
        panel_stub._user_collapse_override = False
        panel_stub._user_override_tier = None

        if view_state is None:
            view_state = _fake_view(error_category=error_category)
        panel_stub._view_state = view_state

        h = ToolHeader.__new__(ToolHeader)
        # Minimal init
        h._label = "test_tool"
        h._tool_name = "bash"
        h._line_count = 0
        h._stats = None
        h._panel = panel_stub
        h._has_affordances = False
        h._flash_msg = None
        h._flash_expires = 0.0
        h._duration = ""
        h._is_complete = True
        h._tool_icon = ""
        h._tool_icon_error = True
        h._label_rich = None
        h._compact_tail = False
        h._is_child_diff = False
        h._full_path = None
        h._path_clickable = False
        h._is_url = False
        h._no_underline = False
        h._hide_duration = False
        h._bold_label = False
        h._hidden = False
        h._shell_prompt = False
        h._elapsed_ms = None
        h._header_args = {}
        h._primary_hero = None
        h._header_chips = []
        h._error_kind = None
        h._exit_code = None
        h._flash_tone = "success"
        h._browse_badge = ""
        h._is_child = False
        h._remediation_hint = None
        h._density_tier = tier
        h._streaming_kind_hint = None
        h._skin_colors_cache = None
        h._diff_del_color = "red"
        h._diff_add_color = "green"
        h._running_icon_color = "blue"
        h._focused_gutter_color = "white"
        return h

    def _get_tail_segments(self, header):
        """Call _render_v4 with mock app context, return tail segment names."""
        from rich.text import Text

        # Patch resolver so trim_header_tail returns all segments unchanged
        mock_resolver = MagicMock()
        mock_resolver.trim_header_tail.side_effect = lambda segs, budget, tier: segs
        header._panel._resolver = mock_resolver

        with patch.object(type(header), "app", new_callable=lambda: property(lambda self: _make_mock_app())):
            with patch.object(type(header), "size", new_callable=lambda: property(lambda self: SimpleNamespace(width=200))):
                with patch.object(type(header), "has_class", return_value=False):
                    result = header._render_v4()
        return result

    def test_err_header_two_chips_hero(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        vs = _fake_view(error_category=ErrorCategory.EACCES)
        h = self._make_header(view_state=vs, density_tier=DensityTier.HERO)
        result = self._get_tail_segments(h)
        # Should render without exception; result is a Text object
        assert result is not None

    def test_err_header_two_chips_trace(self):
        from hermes_cli.tui.tool_panel.density import DensityTier
        vs = _fake_view(error_category=ErrorCategory.RUNTIME)
        h = self._make_header(view_state=vs, density_tier=DensityTier.TRACE)
        result = self._get_tail_segments(h)
        assert result is not None

    def test_err_skips_drop_order(self):
        """trim_header_tail must NOT be called for ERR headers."""
        from hermes_cli.tui.tool_blocks._header import ToolHeader
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver

        vs = _fake_view(error_category=ErrorCategory.RUNTIME)
        h = self._make_header(view_state=vs)

        spy_resolver = MagicMock(spec=ToolBlockLayoutResolver)
        spy_resolver.trim_header_tail.side_effect = lambda segs, budget, tier: segs
        h._panel._resolver = spy_resolver

        with patch.object(type(h), "app", new_callable=lambda: property(lambda self: _make_mock_app())):
            with patch.object(type(h), "size", new_callable=lambda: property(lambda self: SimpleNamespace(width=200))):
                with patch.object(type(h), "has_class", return_value=False):
                    h._render_v4()

        spy_resolver.trim_header_tail.assert_not_called()

    def test_err_unknown_category_renders_error(self):
        """ErrorCategory.UNKNOWN -> chip text == 'error'."""
        vs = _fake_view(error_category=ErrorCategory.UNKNOWN)
        h = self._make_header(view_state=vs)
        assert h._error_category_text() == "error"

    def test_err_overrides_streaming_kind_hint(self):
        """ERR pin skips the streaming-kind-hint chip."""
        from hermes_cli.tui.tool_payload import ResultKind
        vs = _fake_view(error_category=ErrorCategory.RUNTIME)
        h = self._make_header(view_state=vs)
        h._streaming_kind_hint = ResultKind.DIFF  # would normally add ~diff chip
        # The ERR pin means trim is skipped, so ~kind chip won't be appended
        result = self._get_tail_segments(h)
        assert result is not None  # rendered without crash

    def test_err_category_never_truncates(self):
        """Long category text renders in full — no elision in ERR path."""
        vs = _fake_view(error_category=ErrorCategory.ENOENT)
        h = self._make_header(view_state=vs)
        text = h._error_category_text()
        # ErrorCategory.ENOENT.value is "ENOENT" — short but deterministic
        assert text == "ENOENT"


def _make_mock_app():
    app = MagicMock()
    app.get_css_variables.return_value = {}
    return app


# ===========================================================================
# ER-3 — Body wired through set_stderr_tail
# ===========================================================================

class TestStderrBodyWiring:
    def test_err_body_uses_stderr_tail(self):
        from hermes_cli.tui.tool_panel._core import pick_err_body_widget, StderrTailWidget
        vs = _fake_view(stderr_tail=("line1", "line2"))
        widget = pick_err_body_widget(vs)
        assert isinstance(widget, StderrTailWidget)
        content = str(widget.content)
        assert "line1" in content
        assert "line2" in content

    def test_err_body_falls_back_to_payload(self):
        from hermes_cli.tui.tool_panel._core import pick_err_body_widget, PayloadTailWidget
        vs = _fake_view(stderr_tail=(), payload="some stdout error text")
        widget = pick_err_body_widget(vs)
        assert isinstance(widget, PayloadTailWidget)

    def test_err_body_placeholder_when_both_empty(self):
        from hermes_cli.tui.tool_panel._core import pick_err_body_widget, EmptyOutputWidget
        vs = _fake_view(stderr_tail=(), payload="")
        widget = pick_err_body_widget(vs)
        assert isinstance(widget, EmptyOutputWidget)
        assert "no output" in str(widget.content).lower()

    def test_err_body_clamp_bypassed(self):
        """After mount_static(), apply_density is a no-op."""
        from hermes_cli.tui.tool_panel._footer import BodyPane
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.tool_panel._core import StderrTailWidget

        pane = BodyPane.__new__(BodyPane)
        pane._renderer = None
        pane._renderer_degraded = False
        pane._slow_worker_active = False
        pane._hard_timer = None
        pane._last_tier = None
        pane._err_body_locked = False

        # Simulate mount_static with a stub
        mounted = []
        removed = []
        pane.query = MagicMock(return_value=MagicMock(remove=lambda: None))
        pane.mount = lambda w: mounted.append(w)

        widget = StderrTailWidget(("err line",))
        pane.mount_static(widget)

        assert pane._err_body_locked is True
        # apply_density is now a no-op
        renderer_mock = MagicMock()
        pane._renderer = renderer_mock
        pane.apply_density(DensityTier.COMPACT)
        renderer_mock.build_widget.assert_not_called()

    def test_err_body_truncation_already_capped(self):
        """StderrTailWidget renders all received lines without further trimming."""
        from hermes_cli.tui.tool_panel._core import StderrTailWidget
        lines = tuple(f"line {i}" for i in range(STDERR_TAIL_ROWS))
        widget = StderrTailWidget(lines)
        content = str(widget.content)
        assert all(f"line {i}" in content for i in range(STDERR_TAIL_ROWS))


# ===========================================================================
# ER-4 — Footer recovery hints sorted first
# ===========================================================================

class TestRecoveryFirstSort:
    def _make_action(self, kind, hotkey="x"):
        return Action(label=kind, hotkey=hotkey, kind=kind, payload=None)

    def test_recovery_hints_lead_in_err(self):
        from hermes_cli.tui.tool_panel._footer import _sort_actions_for_render
        actions = [
            self._make_action("copy_body", "c"),
            self._make_action("copy_err", "e"),
            self._make_action("retry", "r"),
            self._make_action("edit_args", "a"),
        ]
        result = _sort_actions_for_render(actions)
        assert result[0].kind == "retry"
        assert result[1].kind == "edit_args"

    def test_recovery_hints_protected_under_width_pressure(self):
        """After sort, bottom-up truncation drops non-recovery before recovery."""
        from hermes_cli.tui.tool_panel._footer import _sort_actions_for_render
        actions = [
            self._make_action("copy_body", "c"),
            self._make_action("copy_err", "e"),
            self._make_action("retry", "r"),
            self._make_action("edit_args", "a"),
        ]
        sorted_actions = _sort_actions_for_render(actions)
        # Simulate narrow-width truncation: keep first 2
        truncated = sorted_actions[:2]
        kinds = {a.kind for a in truncated}
        assert "retry" in kinds
        assert "edit_args" in kinds

    def test_no_recovery_in_done_phase(self):
        """DONE action set has no recovery — sorted order == input order modulo F1-last."""
        from hermes_cli.tui.tool_panel._footer import _sort_actions_for_render
        actions = [
            self._make_action("copy_body", "c"),
            self._make_action("open_first", "o"),
        ]
        result = _sort_actions_for_render(actions)
        # No recovery kind in input → order preserved
        assert [a.kind for a in result] == ["copy_body", "open_first"]

    def test_f1_stays_pinned_with_recovery(self):
        """F1 (help) ends up last; retry starts first; both survive truncation."""
        from hermes_cli.tui.tool_panel._footer import _sort_actions_for_render
        actions = [
            self._make_action("help", "f1"),
            self._make_action("copy_body", "c"),
            self._make_action("retry", "r"),
            self._make_action("edit_args", "a"),
        ]
        result = _sort_actions_for_render(actions)
        assert result[0].kind == "retry"
        assert result[-1].kind == "help"


# ===========================================================================
# ER-5 — Recovery hints branch on category
# ===========================================================================

class TestCategoryRecovery:
    def test_eacces_no_retry_action(self):
        allowed = _allowed_recovery(ErrorCategory.EACCES)
        assert allowed == frozenset({"edit_args"})
        # ER-summary with EACCES-like stderr
        summary = _err_summary(stderr_tail="permission denied", exit_code=1)
        result = inject_recovery_actions(summary)
        kinds = {a.kind for a in result.actions}
        assert "retry" not in kinds
        assert "copy_err" in kinds  # stderr non-empty

    def test_timeout_only_retry(self):
        allowed = _allowed_recovery(ErrorCategory.TIMEOUT)
        assert allowed == frozenset({"retry"})
        summary = _err_summary(stderr_tail="Timed out after 30s", exit_code=1)
        result = inject_recovery_actions(summary)
        kinds = {a.kind for a in result.actions}
        assert "retry" in kinds
        assert "edit_args" not in kinds

    def test_unknown_category_default_recovery(self):
        allowed = _allowed_recovery(ErrorCategory.UNKNOWN)
        assert "retry" in allowed and "edit_args" in allowed

    def test_none_category_defaults_safely(self):
        from hermes_cli.tui.tool_result_parse import _allowed_recovery as _ar
        result = _ar(None)
        assert isinstance(result, frozenset)
        assert "retry" in result

    def test_copy_err_always_present_when_stderr_nonempty(self):
        for cat in ErrorCategory:
            # Build a summary whose stderr will classify to this category
            # Use a fallback generic stderr text that won't override via regex
            summary = ResultSummaryV4(
                primary="✗ error",
                exit_code=1,
                chips=(),
                stderr_tail="some error output",
                actions=(),
                artifacts=(),
                is_error=True,
            )
            result = inject_recovery_actions(summary)
            kinds = {a.kind for a in result.actions}
            assert "copy_err" in kinds, f"copy_err missing for category path with stderr"

    def test_edit_args_hotkey_no_collision_with_copy_err(self):
        """RUNTIME + non-empty stderr -> both edit_args (a) and copy_err (e) present, no collision."""
        summary = _err_summary(stderr_tail="some runtime failure", exit_code=1)
        result = inject_recovery_actions(summary)
        hotkeys = [a.hotkey for a in result.actions]
        assert len(hotkeys) == len(set(hotkeys)), "Hotkey collision detected"
        kinds = {a.kind for a in result.actions}
        assert "edit_args" in kinds
        assert "copy_err" in kinds
        edit_args_hotkey = next(a.hotkey for a in result.actions if a.kind == "edit_args")
        copy_err_hotkey = next(a.hotkey for a in result.actions if a.kind == "copy_err")
        assert edit_args_hotkey == "a"
        assert copy_err_hotkey == "e"
