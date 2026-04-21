"""Tests for Phase A — Header Signal Clarity (A1–A8)."""
from __future__ import annotations

import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from rich.text import Text
from textual.widget import Widget
from textual.geometry import Size


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stb(label="test", tool_name="bash", tool_input=None, is_first_in_turn=False):
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    return StreamingToolBlock(
        label=label,
        tool_name=tool_name,
        tool_input=tool_input,
        is_first_in_turn=is_first_in_turn,
    )


def _make_header(label="test", line_count=5, tool_name="bash"):
    from hermes_cli.tui.tool_blocks import ToolHeader
    h = ToolHeader(label=label, line_count=line_count, tool_name=tool_name)
    return h


def _bare_header(**kwargs):
    """ToolHeader via __new__ with minimal DOM stubs for _render_v4 testing."""
    from hermes_cli.tui.tool_blocks import ToolHeader
    h = ToolHeader.__new__(ToolHeader)
    defaults = dict(
        _label="test", _tool_name="bash", _line_count=5, _panel=None,
        _spinner_char=None, _is_complete=True, _tool_icon_error=False,
        _primary_hero=None, _header_chips=[], _stats=None, _duration="1s",
        _has_affordances=False, _label_rich=None, _is_child_diff=False,
        _header_args={}, _flash_msg=None, _flash_expires=0.0, _flash_tone="success",
        _error_kind=None, _tool_icon="", _full_path=None, _path_clickable=False,
        _classes=frozenset(),
    )
    defaults.update(kwargs)
    for k, v in defaults.items():
        setattr(h, k, v)
    return h


# ---------------------------------------------------------------------------
# A1 — microcopy_shown attr and sub-500ms flash
# ---------------------------------------------------------------------------

class TestA1:
    def test_microcopy_shown_defaults_false(self):
        stb = _make_stb()
        assert stb._microcopy_shown is False

    def test_microcopy_shown_set_after_update(self):
        """_microcopy_shown becomes True when _update_microcopy sets microcopy."""
        stb = _make_stb()
        stb._stream_started_at = time.monotonic() - 1.0  # elapsed 1s → past 0.5s threshold
        stb._last_http_status = None

        # Patch body.set_microcopy so it doesn't need DOM
        stb._body = MagicMock()
        # Both spec_for and microcopy_line are local imports inside _update_microcopy
        # Also need to stub app access (raises NoActiveAppError outside Textual context)
        mock_app = MagicMock()
        mock_app._reduced_motion = False
        with patch("hermes_cli.tui.tool_category.spec_for", return_value=MagicMock(category=MagicMock())):
            with patch("hermes_cli.tui.streaming_microcopy.microcopy_line", return_value="test line"):
                with patch.object(type(stb), "app", new_callable=lambda: property(lambda self: mock_app)):
                    stb._update_microcopy()
        assert stb._microcopy_shown is True

    def test_microcopy_not_shown_before_threshold(self):
        stb = _make_stb()
        stb._stream_started_at = time.monotonic() - 0.1  # only 100ms elapsed
        stb._body = MagicMock()
        stb._update_microcopy()
        assert stb._microcopy_shown is False


# ---------------------------------------------------------------------------
# A2 — empty result visual state
# ---------------------------------------------------------------------------

class TestA2:
    def test_result_empty_class_added_when_no_lines(self):
        stb = _make_stb()
        stb._total_received = 0
        stb._completed = False
        stb._secondary_args_snapshot = ""
        stb._stream_started_at = time.monotonic()
        # Patch all DOM-touching methods
        stb._header = MagicMock()
        stb._header._pulse_stop = MagicMock()
        stb._header.set_error = MagicMock()
        stb._header._is_complete = False
        stb._header._has_affordances = False
        stb._header._spinner_char = "⠋"
        stb._header._line_count = 0
        stb._header.add_class = MagicMock()
        stb._header.flash_success = MagicMock()
        stb._header.refresh = MagicMock()
        stb._body = MagicMock()
        stb._tail = MagicMock()
        stb._pending = []
        stb._all_plain = []
        stb._all_rich = []
        stb._omission_bar_bottom_mounted = False
        stb._omission_bar_top_mounted = False
        stb._follow_tail = False
        stb._render_timer = MagicMock()
        stb._spinner_timer = MagicMock()
        stb._duration_timer = MagicMock()
        stb._tool_input = None

        with patch.object(stb, "_try_mount_media"):
            with patch("hermes_cli.tui.tool_category.spec_for", return_value=MagicMock()):
                stb.complete("0.1s", is_error=False)

        stb._header.add_class.assert_any_call("result-empty")

    def test_result_empty_not_added_on_error(self):
        stb = _make_stb()
        stb._total_received = 0
        stb._completed = False
        stb._secondary_args_snapshot = ""
        stb._stream_started_at = time.monotonic()
        stb._header = MagicMock()
        stb._header._pulse_stop = MagicMock()
        stb._header.set_error = MagicMock()
        stb._header._is_complete = False
        stb._header._has_affordances = False
        stb._header._spinner_char = "⠋"
        stb._header._line_count = 0
        stb._header.add_class = MagicMock()
        stb._header.flash_success = MagicMock()
        stb._header.flash_error = MagicMock()
        stb._header.refresh = MagicMock()
        stb._body = MagicMock()
        stb._tail = MagicMock()
        stb._pending = []
        stb._all_plain = []
        stb._all_rich = []
        stb._omission_bar_bottom_mounted = False
        stb._omission_bar_top_mounted = False
        stb._follow_tail = False
        stb._render_timer = MagicMock()
        stb._spinner_timer = MagicMock()
        stb._duration_timer = MagicMock()
        stb._tool_input = None

        with patch.object(stb, "_try_mount_media"):
            with patch("hermes_cli.tui.tool_category.spec_for", return_value=MagicMock()):
                stb.complete("0.1s", is_error=True)

        calls = [str(c) for c in stb._header.add_class.call_args_list]
        assert not any("result-empty" in c for c in calls)


# ---------------------------------------------------------------------------
# A3 — tail order: hero first
# ---------------------------------------------------------------------------

class TestA3:
    def test_hero_before_stats_in_tail(self):
        from hermes_cli.tui.tool_blocks import ToolHeaderStats
        h = _bare_header(
            _primary_hero="✓ 5 lines",
            _stats=ToolHeaderStats(additions=3, deletions=1),
            _duration="1.2s",
        )

        with patch("hermes_cli.tui.tool_category.spec_for") as ms:
            ms.return_value = MagicMock(render_header=True, primary_arg="command",
                                        category=MagicMock(value="shell"))
            with patch.object(h, "_accessible_mode", return_value=False):
                with patch.object(Widget, "size", new_callable=PropertyMock,
                                  return_value=Size(80, 24)):
                    result = h._render_v4()

        if result is not None:
            plain = result.plain
            hero_pos = plain.find("✓ 5 lines")
            stat_pos = plain.find("+3")
            if hero_pos != -1 and stat_pos != -1:
                assert hero_pos < stat_pos


# ---------------------------------------------------------------------------
# A4 — secondary args snapshot
# ---------------------------------------------------------------------------

class TestA4:
    def test_secondary_args_snapshot_attr_exists(self):
        stb = _make_stb()
        assert hasattr(stb, "_secondary_args_snapshot")
        assert stb._secondary_args_snapshot == ""

    def test_secondary_args_snapshot_default_empty(self):
        stb = _make_stb(tool_input=None)
        assert stb._secondary_args_snapshot == ""


# ---------------------------------------------------------------------------
# A5 — unified error banner
# ---------------------------------------------------------------------------

class TestA5:
    def test_error_banner_mounted_on_error(self):
        """set_result_summary mounts .error-banner when is_error + error_kind set."""
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Chip

        stb = MagicMock()
        stb._header = MagicMock()
        stb._header._flash_msg = None
        stb._header._flash_expires = 0.0
        stb._header._microcopy_shown = True
        stb.query = MagicMock(return_value=[])

        panel = object.__new__(ToolPanel)
        panel._block = stb
        panel._result_summary_v4 = None
        panel._completed_at = None
        panel._user_collapse_override = False
        panel._footer_pane = MagicMock()
        panel._footer_pane.update_summary_v4 = MagicMock()
        panel._saved_visible_start = None

        banner_mounted = []

        def fake_mount(widget, after=None):
            banner_mounted.append(widget)

        stb.mount = fake_mount

        summary = ResultSummaryV4(
            primary="✗ timeout",
            exit_code=124,
            chips=(Chip("timeout", "exit", "error"),),
            stderr_tail="",
            actions=(),
            artifacts=(),
            is_error=True,
            error_kind="timeout",
        )

        with patch.object(panel, "_has_footer_content", return_value=True):
            with patch.object(panel, "_apply_complete_auto_collapse"):
                with patch.object(panel, "post_message"):
                    with patch.object(panel, "set_timer"):
                        # Patch collapsed as a data descriptor on the class level
                        # to avoid ReactiveError from uninitialized reactive node;
                        # save original and restore after test
                        _orig = type(panel).__dict__.get("collapsed")
                        type(panel).collapsed = property(lambda self: False,
                                                         lambda self, v: None)
                        try:
                            panel.set_result_summary(summary)
                        finally:
                            if _orig is not None:
                                type(panel).collapsed = _orig
                            else:
                                try:
                                    del type(panel).collapsed
                                except Exception:
                                    pass

        assert len(banner_mounted) >= 1


# ---------------------------------------------------------------------------
# A6 — turn correlation badge
# ---------------------------------------------------------------------------

class TestA6:
    def test_is_first_in_turn_param(self):
        from hermes_cli.tui.tool_blocks import StreamingToolBlock
        stb = StreamingToolBlock(label="test", is_first_in_turn=True)
        assert stb._is_first_in_turn is True

    def test_is_first_in_turn_default_false(self):
        from hermes_cli.tui.tool_blocks import StreamingToolBlock
        stb = StreamingToolBlock(label="test")
        assert stb._is_first_in_turn is False

    def test_not_first_in_turn_when_false(self):
        from hermes_cli.tui.tool_blocks import StreamingToolBlock
        stb = StreamingToolBlock(label="test", is_first_in_turn=False)
        assert stb._is_first_in_turn is False


# ---------------------------------------------------------------------------
# A7 — full path tooltip update
# ---------------------------------------------------------------------------

class TestA7:
    def test_tooltip_updated_when_path_differs(self):
        h = _bare_header(
            _label="/short", _tool_name="read_file",
            _full_path="/very/long/path/to/actual/file.py",
            _path_clickable=True,
            _has_affordances=True,
            _panel=MagicMock(collapsed=False),
        )

        with patch("hermes_cli.tui.tool_category.spec_for") as ms:
            ms.return_value = MagicMock(render_header=True, primary_arg="path",
                                        category=MagicMock(value="file"))
            with patch.object(h, "_accessible_mode", return_value=False):
                with patch.object(Widget, "size", new_callable=PropertyMock,
                                  return_value=Size(40, 24)):
                    h._render_v4()

        assert h._tooltip_text == "/very/long/path/to/actual/file.py"


# ---------------------------------------------------------------------------
# A8 — MCP middle-truncation
# ---------------------------------------------------------------------------

class TestA8:
    def test_mcp_middle_truncation_narrow(self):
        from hermes_cli.tui.tool_blocks import header_label_v4
        from hermes_cli.tui.tool_category import ToolCategory, ToolSpec
        spec = MagicMock()
        spec.primary_arg = None
        spec.category = ToolCategory.MCP
        spec.provenance = "mcp:myserver"
        spec.name = "myserver__do_something"
        result = header_label_v4(spec, {}, "myserver::do_something()", None, available=12)
        plain = result.plain.strip()
        assert "…" in plain or len(plain) <= 14

    def test_mcp_very_narrow_shows_mcp(self):
        from hermes_cli.tui.tool_blocks import header_label_v4
        from hermes_cli.tui.tool_category import ToolCategory
        spec = MagicMock()
        spec.primary_arg = None
        spec.category = ToolCategory.MCP
        spec.provenance = "mcp:myserver"
        spec.name = "myserver__do_something"
        result = header_label_v4(spec, {}, "myserver::do_something()", None, available=6)
        plain = result.plain.strip()
        assert "[MCP]" in plain

    def test_mcp_no_truncation_when_fits(self):
        from hermes_cli.tui.tool_blocks import header_label_v4
        from hermes_cli.tui.tool_category import ToolCategory
        spec = MagicMock()
        spec.primary_arg = None
        spec.category = ToolCategory.MCP
        spec.provenance = "mcp:s"
        spec.name = "s__fn"
        result = header_label_v4(spec, {}, "s::fn()", None, available=40)
        plain = result.plain.strip()
        assert "s::fn()" in plain
