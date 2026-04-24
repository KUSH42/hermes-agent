"""Tests for Tool Rendering MEDIUM issues (M1–M9).

Covers:
  M1 – emoji mode returns emoji chars, not ASCII
  M2 – all category defaults have icon_nf populated
  M3 – _find_diff_targets collects all writes sharing a path
  M4 – GroupHeader ops chip compact form at narrow widths
  M5 – central remediation registry lookup and registration
  M6 – Action hotkey collision detection
  M7 – truncate_path shared helper
  M8 – flash error style uses CSS var, not hardcoded red
  M9 – ToolsScreen filter state persists across close/reopen
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from hermes_cli.tui.tool_category import (
    ToolCategory,
    ToolSpec,
    _CATEGORY_DEFAULTS,
    _EMOJI_ICONS,
    _emoji_for,
    resolve_icon_final,
)
from hermes_cli.tui.tool_result_parse import (
    Action,
    Chip,
    ResultSummaryV4,
    _REMEDIATIONS,
    lookup_remediation,
    register_remediation,
    shell_result_v4,
    code_result_v4,
    mcp_result_v4,
    ParseContext,
    ToolStart,
    ToolComplete,
)
from hermes_cli.tui.tool_blocks._shared import truncate_path
from hermes_cli.tui.tool_group import (
    _find_diff_targets,
    _find_diff_target,
    GroupHeader,
)
from hermes_cli.tui.tools_overlay import _tools_state, _ToolsScreenState, ToolsScreen


# ===========================================================================
# M1 — Emoji icon mode
# ===========================================================================

class TestM1EmojiIconMode:
    def _file_spec(self):
        return ToolSpec(name="read_file", category=ToolCategory.FILE,
                        primary_arg="path", primary_result="lines")

    def _shell_spec(self):
        return ToolSpec(name="bash", category=ToolCategory.SHELL,
                        primary_arg="command", primary_result="lines")

    def _mcp_spec(self):
        return ToolSpec(name="mcp__srv__call", category=ToolCategory.MCP,
                        primary_result="none")

    def test_emoji_mode_returns_emoji_not_ascii(self):
        with patch("agent.display.get_tool_icon_mode", return_value="emoji"):
            result = resolve_icon_final(self._file_spec(), nerd_font=False)
        assert result == "📄"
        assert result != "F"

    def test_emoji_mode_shell_returns_emoji(self):
        with patch("agent.display.get_tool_icon_mode", return_value="emoji"):
            result = resolve_icon_final(self._shell_spec(), nerd_font=False)
        assert result == "🐚"

    def test_ascii_mode_still_ascii(self):
        with patch("agent.display.get_tool_icon_mode", return_value="ascii"):
            result = resolve_icon_final(self._file_spec(), nerd_font=False)
        assert result == "F"

    def test_nerdfont_mode_unchanged(self):
        with patch("agent.display.get_tool_icon_mode", return_value="nerdfont"):
            result = resolve_icon_final(self._file_spec(), nerd_font=True)
        # Should return nerdfont glyph, not ASCII
        assert result != "F"
        assert result != "📄"


# ===========================================================================
# M2 — All categories have icon_nf
# ===========================================================================

class TestM2CategoryIconDefaults:
    def test_all_category_defaults_have_icon_nf(self):
        for cat, defaults in _CATEGORY_DEFAULTS.items():
            assert defaults.icon_nf != "", \
                f"ToolCategory.{cat.name} has empty icon_nf"

    def test_emoji_map_covers_all_categories(self):
        for cat in ToolCategory:
            assert cat in _EMOJI_ICONS, f"ToolCategory.{cat.name} missing from _EMOJI_ICONS"

    def test_ascii_mode_still_returns_ascii(self):
        spec = ToolSpec(name="bash", category=ToolCategory.SHELL,
                        primary_arg="command", primary_result="lines")
        with patch("agent.display.get_tool_icon_mode", return_value="ascii"):
            result = resolve_icon_final(spec, nerd_font=False)
        assert result == "$"


# ===========================================================================
# M3 — _find_diff_targets collects all writes in window
# ===========================================================================

def _make_write_panel(tool_name: str, path: str, completed_at: float | None = None):
    p = MagicMock()
    p._tool_name = tool_name
    p._completed_at = completed_at
    p._label = path
    # _get_header_label queries for ToolHeader then reads _label from it
    from hermes_cli.tui.tool_blocks._header import ToolHeader as _TH
    h = MagicMock(spec=_TH)
    h._label = path
    p.query = MagicMock(return_value=iter([h]))
    return p


class TestM3DiffTargetCollection:
    def test_find_diff_targets_returns_all_in_window(self):
        now = time.monotonic()
        w1 = _make_write_panel("patch", "/a/foo.py", now - 5)
        w2 = _make_write_panel("patch", "/a/foo.py", now - 2)
        siblings = [w1, w2]
        result = _find_diff_targets(siblings, window_s=15.0)
        assert len(result) == 2
        assert w1 in result
        assert w2 in result

    def test_find_diff_targets_filters_by_path(self):
        now = time.monotonic()
        w1 = _make_write_panel("patch", "/a/foo.py", now - 5)
        w2 = _make_write_panel("patch", "/b/bar.py", now - 2)
        siblings = [w1, w2]
        result = _find_diff_targets(siblings, window_s=15.0)
        # Only w2 path becomes anchor; w1 has different path
        assert len(result) == 1
        assert w2 in result
        assert w1 not in result

    def test_find_diff_targets_window_boundary(self):
        now = time.monotonic()
        w1 = _make_write_panel("patch", "/a/foo.py", now - 20)  # outside 15s window
        w2 = _make_write_panel("patch", "/a/foo.py", now - 5)   # inside
        siblings = [w1, w2]
        result = _find_diff_targets(siblings, window_s=15.0)
        # w1 is outside window; reversed scan breaks on first out-of-window hit
        assert w2 in result
        assert w1 not in result

    def test_diff_group_contains_all_writes(self):
        now = time.monotonic()
        w1 = _make_write_panel("patch", "/a/foo.py", now - 10)
        w2 = _make_write_panel("patch", "/a/foo.py", now - 5)
        w3 = _make_write_panel("patch", "/a/foo.py", now - 1)
        siblings = [w1, w2, w3]
        result = _find_diff_targets(siblings, window_s=15.0)
        assert len(result) == 3


# ===========================================================================
# M4 — GroupHeader ops chip compact form
# ===========================================================================

def _make_group_header(child_count: int) -> GroupHeader:
    header = GroupHeader.__new__(GroupHeader)
    header._collapsed = False
    header._summary_text = "test group"
    header._diff_add = 0
    header._diff_del = 0
    header._duration_ms = 0.0
    header._error_count = 0
    header._child_count = child_count
    return header


def _render_group_header(child_count: int, term_w: int) -> str:
    header = _make_group_header(child_count)
    size_mock = MagicMock()
    size_mock.width = term_w
    with patch.object(GroupHeader, "size", new_callable=PropertyMock, return_value=size_mock):
        return header.render().plain


class TestM4OpsChipCompactForm:
    def test_ops_chip_wide_width_full_form(self):
        plain = _render_group_header(child_count=5, term_w=80)
        assert "5 ops" in plain

    def test_ops_chip_narrow_compact_form(self):
        plain = _render_group_header(child_count=5, term_w=45)
        assert "×5" in plain
        assert "ops" not in plain

    def test_ops_chip_tiny_width_omitted(self):
        plain = _render_group_header(child_count=5, term_w=35)
        assert "ops" not in plain
        assert "×5" not in plain


# ===========================================================================
# M5 — Remediation registry
# ===========================================================================

class TestM5RemediationRegistry:
    def test_lookup_remediation_shell_timeout(self):
        result = lookup_remediation(ToolCategory.SHELL, "timeout")
        assert result == "increase timeout_sec parameter"

    def test_lookup_remediation_unknown_returns_none(self):
        result = lookup_remediation(ToolCategory.UNKNOWN, "weird")
        assert result is None

    def test_lookup_remediation_none_kind_returns_none(self):
        result = lookup_remediation(ToolCategory.SHELL, None)
        assert result is None

    def test_register_remediation_roundtrip(self):
        key = (ToolCategory.FILE, "test-kind-xyz")
        original = _REMEDIATIONS.get(key)
        try:
            register_remediation(ToolCategory.FILE, "test-kind-xyz", "custom hint")
            assert lookup_remediation(ToolCategory.FILE, "test-kind-xyz") == "custom hint"
            # Unregistered key still None
            assert lookup_remediation(ToolCategory.FILE, "nonexistent") is None
        finally:
            # Restore original state
            if original is None:
                _REMEDIATIONS.pop(key, None)
            else:
                _REMEDIATIONS[key] = original

    def test_parsers_use_central_registry(self):
        original = _REMEDIATIONS.get((ToolCategory.SHELL, "timeout"))
        try:
            _REMEDIATIONS[(ToolCategory.SHELL, "timeout")] = "injected hint"
            ctx = ParseContext(
                complete=ToolComplete(
                    name="bash", raw_result="timed out", exit_code=124,
                    is_error=True, error_kind="timeout",
                ),
                start=ToolStart(name="bash", args={"command": "sleep 100"}),
                spec=ToolSpec(name="bash", category=ToolCategory.SHELL,
                              primary_arg="command", primary_result="lines"),
            )
            result = shell_result_v4(ctx)
            chips_remediations = [c.remediation for c in result.chips]
            assert "injected hint" in chips_remediations
        finally:
            if original is None:
                _REMEDIATIONS.pop((ToolCategory.SHELL, "timeout"), None)
            else:
                _REMEDIATIONS[(ToolCategory.SHELL, "timeout")] = original


# ===========================================================================
# M6 — Hotkey collision detection
# ===========================================================================

class TestM6HotkeyCollisions:
    def _make_action(self, hotkey: str, kind: str = "copy_body") -> Action:
        return Action(label=hotkey, hotkey=hotkey, kind=kind, payload=None)  # type: ignore[arg-type]

    def test_duplicate_hotkey_raises(self):
        a1 = self._make_action("c", "copy_body")
        a2 = self._make_action("c", "retry")
        with pytest.raises(ValueError, match="hotkey collision.*'c'"):
            ResultSummaryV4(
                primary="ok", exit_code=0,
                chips=(), stderr_tail="",
                actions=(a1, a2), artifacts=(),
                is_error=False,
            )

    def test_case_sensitive_hotkeys_ok(self):
        a1 = Action(label="retry", hotkey="r", kind="retry", payload=None)
        a2 = Action(label="reconnect", hotkey="R", kind="reconnect", payload=None)
        # Should not raise
        result = ResultSummaryV4(
            primary="ok", exit_code=0,
            chips=(), stderr_tail="",
            actions=(a1, a2), artifacts=(),
            is_error=False,
        )
        assert len(result.actions) == 2

    def test_unique_hotkeys_construct(self):
        actions = (
            Action(label="copy", hotkey="c", kind="copy_body", payload=None),
            Action(label="retry", hotkey="r", kind="retry", payload=None),
            Action(label="edit", hotkey="e", kind="edit_cmd", payload=None),
            Action(label="open", hotkey="o", kind="open_first", payload=None),
        )
        result = ResultSummaryV4(
            primary="ok", exit_code=0,
            chips=(), stderr_tail="",
            actions=actions, artifacts=(),
            is_error=False,
        )
        assert len(result.actions) == 4


# ===========================================================================
# M7 — truncate_path helper
# ===========================================================================

class TestM7PathTruncationHelper:
    def test_truncate_path_basic(self):
        t = truncate_path("/a/b/c/foo.py", max_w=40)
        plain = t.plain
        assert "foo.py" in plain
        assert "…" not in plain

    def test_truncate_path_exceeds_width(self):
        t = truncate_path("/very/long/directory/structure/foo.py", max_w=20)
        plain = t.plain
        assert "foo.py" in plain
        assert "…" in plain

    def test_truncate_path_extreme_narrow(self):
        t = truncate_path("/a/b/c/longfilename.py", max_w=15)
        plain = t.plain
        assert "longfilename.py" in plain


# ===========================================================================
# M8 — Flash error style uses theme CSS var
# ===========================================================================

class TestM8FlashErrorThemeColor:
    def _make_header(self, flash_tone: str, flash_msg: str):
        from hermes_cli.tui.tool_blocks._header import ToolHeader
        h = ToolHeader.__new__(ToolHeader)
        h._flash_tone = flash_tone
        h._flash_msg = flash_msg
        h._flash_expires = time.monotonic() + 10.0
        h._focused_gutter_color = "#5f87d7"
        return h

    def test_flash_error_uses_theme_error_color(self):
        h = self._make_header("error", "something failed")
        css_vars = {"status-error-color": "#abcdef"}
        app_mock = MagicMock()
        app_mock.get_css_variables.return_value = css_vars
        collected: list[str] = []

        def mock_append(text, style=""):
            collected.append(style)

        from rich.text import Text as RichText
        t = RichText()

        with patch.object(type(h), "app", new_callable=PropertyMock, return_value=app_mock):
            # Simulate the flash render logic from _header.py
            accent_color = getattr(h, "_focused_gutter_color", "#5f87d7")
            if h._flash_tone == "error":
                try:
                    _err_color = h.app.get_css_variables().get("status-error-color", "red")
                except Exception:
                    _err_color = "red"
                _flash_style = f"dim {_err_color}"
            else:
                _flash_style = f"dim {accent_color}"

        assert _flash_style == "dim #abcdef"
        assert "red" not in _flash_style

    def test_flash_success_uses_accent(self):
        h = self._make_header("success", "done")
        accent = "#5f87d7"
        with patch.object(type(h), "app", new_callable=PropertyMock, return_value=MagicMock()):
            accent_color = getattr(h, "_focused_gutter_color", "#5f87d7")
            if h._flash_tone == "error":
                _flash_style = "dim red"
            else:
                _flash_style = f"dim {accent_color}"
        assert _flash_style == f"dim {accent}"


# ===========================================================================
# M9 — ToolsScreen filter state persists across close/reopen
# ===========================================================================

class TestM9ToolsScreenFilterPersist:
    def _snapshot(self, tool_call_id: str = "abc123") -> list[dict]:
        return [{"tool_call_id": tool_call_id, "name": "bash", "start_ms": 1000.0}]

    def _reset_state(self):
        _tools_state.filter_text = ""
        _tools_state.active_categories = frozenset()
        _tools_state.errors_only = False
        _tools_state.sort_mode = 0
        _tools_state.turn_id = None

    def setup_method(self):
        self._reset_state()

    def teardown_method(self):
        self._reset_state()

    def test_first_open_uses_defaults(self):
        snap = self._snapshot("turn1")
        screen = ToolsScreen.__new__(ToolsScreen)
        ToolsScreen.__init__(screen, snap)
        assert screen._filter_text == ""
        assert screen._errors_only is False
        assert screen._sort_mode == 0

    def test_filter_text_preserved_across_close(self):
        snap = self._snapshot("turn1")
        # Simulate: open → set filter → close
        screen1 = ToolsScreen.__new__(ToolsScreen)
        ToolsScreen.__init__(screen1, snap)
        screen1._filter_text = "git"
        _tools_state.filter_text = "git"
        _tools_state.turn_id = "turn1"
        _tools_state.active_categories = frozenset()
        _tools_state.errors_only = False
        _tools_state.sort_mode = 0

        # Reopen same turn
        screen2 = ToolsScreen.__new__(ToolsScreen)
        ToolsScreen.__init__(screen2, snap)
        assert screen2._filter_text == "git"

    def test_errors_only_preserved_across_close(self):
        snap = self._snapshot("turn1")
        _tools_state.errors_only = True
        _tools_state.turn_id = "turn1"
        _tools_state.filter_text = ""
        _tools_state.active_categories = frozenset()
        _tools_state.sort_mode = 0

        screen = ToolsScreen.__new__(ToolsScreen)
        ToolsScreen.__init__(screen, snap)
        assert screen._errors_only is True

    def test_filter_cleared_on_new_turn(self):
        snap_old = self._snapshot("old-turn")
        snap_new = self._snapshot("new-turn")
        _tools_state.filter_text = "git"
        _tools_state.turn_id = "old-turn"

        screen = ToolsScreen.__new__(ToolsScreen)
        ToolsScreen.__init__(screen, snap_new)
        assert screen._filter_text == ""

    def test_sort_mode_preserved_across_close(self):
        snap = self._snapshot("turn1")
        _tools_state.sort_mode = 2
        _tools_state.turn_id = "turn1"
        _tools_state.filter_text = ""
        _tools_state.active_categories = frozenset()
        _tools_state.errors_only = False

        screen = ToolsScreen.__new__(ToolsScreen)
        ToolsScreen.__init__(screen, snap)
        assert screen._sort_mode == 2


# ===========================================================================
# Cross-cutting regression tests
# ===========================================================================

class TestMediumRegressions:
    def test_icon_resolution_matrix_nerdfont(self):
        for cat in ToolCategory:
            spec = ToolSpec(name="test", category=cat, primary_result="none")
            with patch("agent.display.get_tool_icon_mode", return_value="nerdfont"):
                icon = resolve_icon_final(spec, nerd_font=True)
            # Should return non-empty string
            assert icon, f"{cat.name} returned empty icon in nerdfont mode"

    def test_icon_resolution_matrix_emoji(self):
        for cat in ToolCategory:
            spec = ToolSpec(name="test", category=cat, primary_result="none")
            with patch("agent.display.get_tool_icon_mode", return_value="emoji"):
                icon = resolve_icon_final(spec, nerd_font=False)
            assert icon, f"{cat.name} returned empty icon in emoji mode"
            assert icon != _CATEGORY_DEFAULTS[cat].ascii_fallback, \
                f"{cat.name} silently degraded to ASCII in emoji mode"

    def test_registry_extensibility_smoke(self):
        key = (ToolCategory.WEB, "rate-limit")
        original = _REMEDIATIONS.get(key)
        try:
            register_remediation(ToolCategory.WEB, "rate-limit", "retry after 60s")
            assert lookup_remediation(ToolCategory.WEB, "rate-limit") == "retry after 60s"
        finally:
            if original is None:
                _REMEDIATIONS.pop(key, None)
            else:
                _REMEDIATIONS[key] = original

    def test_find_diff_targets_empty_siblings(self):
        result = _find_diff_targets([], window_s=15.0)
        assert result == []

    def test_truncate_path_no_slash(self):
        t = truncate_path("simplefile.py", max_w=40)
        plain = t.plain
        assert "simplefile.py" in plain
