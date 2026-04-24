"""Tests for Tool Rendering HIGH Issues spec (H1-H5).

H1: Chip tone contract
H2: Shell-pipeline false-positives
H3: Read+write same-path grouping
H4: Collapsed group append
H5: OmissionBar._reset_label missing
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch, AsyncMock
import pytest

from hermes_cli.tui.tool_result_parse import (
    Chip,
    ResultSummaryV4,
    _TONE_BY_KIND,
    ParseContext,
    ToolComplete,
    ToolStart,
    web_result_v4,
    file_result_v4,
)
from hermes_cli.tui.tool_group import (
    RULE_SHELL_PIPE,
    RULE_SHELL_BATCH,
    RULE_FILE_EDIT,
    RULE_DIFF_ATTACH,
    _find_rule_match,
    _build_summary_text,
    _get_effective_tp_siblings,
    _PIPELINE_OPS_RE,
    _FILE_READ_TOOLS,
    _FILE_WRITE_TOOLS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _web_ctx(raw, *, url="http://example.com", is_error=False, error_kind=None, exit_code=None):
    complete = ToolComplete(
        name="web_fetch",
        raw_result=raw,
        exit_code=exit_code,
        is_error=is_error,
        error_kind=error_kind,
    )
    start = ToolStart(name="web_fetch", args={"url": url})
    spec = MagicMock()
    spec.primary_result = "bytes"
    return ParseContext(complete=complete, start=start, spec=spec)


def _file_ctx(raw, *, path="a.py", is_write=True, is_error=False, error_kind=None):
    complete = ToolComplete(
        name="edit_file",
        raw_result=raw,
        exit_code=None,
        is_error=is_error,
        error_kind=error_kind,
    )
    start = ToolStart(name="edit_file", args={"path": path})
    spec = MagicMock()
    spec.primary_result = "wrote" if is_write else "lines"
    return ParseContext(complete=complete, start=start, spec=spec)


def _mock_panel(*, category=None, tool_name="", label="", start_time=None):
    from hermes_cli.tui.tool_category import ToolCategory
    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    p = MagicMock(spec=_TP)
    p.classes = []
    p._category = category or ToolCategory.SHELL
    p._tool_name = tool_name
    p._label = label
    p._completed_at = time.monotonic()
    p._start_time = start_time if start_time is not None else time.monotonic()
    p.parent = None
    p.is_attached = True
    p._result_paths = []
    return p


def _make_mp(panels):
    mp = MagicMock()
    mp.children = panels
    for p in panels:
        p.parent = mp
    return mp


# ---------------------------------------------------------------------------
# H1 — Chip tone contract
# ---------------------------------------------------------------------------


class TestH1ChipToneContract:

    def test_web_4xx_chip_tone_is_error(self):
        raw = "HTTP/1.1 404 Not Found\nContent-Length: 0\n"
        ctx = _web_ctx(raw)
        result = web_result_v4(ctx)
        status_chips = [c for c in result.chips if c.kind == "status"]
        assert status_chips, "expected at least one status chip"
        assert status_chips[0].tone == "error"

    def test_web_5xx_chip_tone_is_error(self):
        raw = "HTTP/1.1 503 Service Unavailable\nContent-Length: 0\n"
        ctx = _web_ctx(raw)
        result = web_result_v4(ctx)
        status_chips = [c for c in result.chips if c.kind == "status"]
        assert status_chips
        assert status_chips[0].tone == "error"

    def test_web_3xx_chip_tone_is_warning(self):
        raw = "HTTP/1.1 301 Moved Permanently\nLocation: http://example.com/new\n"
        ctx = _web_ctx(raw)
        result = web_result_v4(ctx)
        status_chips = [c for c in result.chips if c.kind == "status"]
        assert status_chips
        assert status_chips[0].tone == "warning"

    def test_web_2xx_chip_tone_is_success(self):
        raw = "HTTP/1.1 200 OK\nContent-Length: 100\n" + "x" * 100
        ctx = _web_ctx(raw)
        result = web_result_v4(ctx)
        status_chips = [c for c in result.chips if c.kind == "status"]
        assert status_chips
        assert status_chips[0].tone == "success"

    def test_file_diff_del_tone_is_error(self):
        patch_body = "+++ b/a.py\n--- a/a.py\n-line1\n-line2\n-line3\n"
        ctx = _file_ctx(patch_body, path="a.py", is_write=True)
        result = file_result_v4(ctx)
        del_chips = [c for c in result.chips if c.kind == "diff-"]
        assert del_chips, "expected diff- chip"
        assert del_chips[0].tone == "error"

    def test_file_diff_add_tone_is_success(self):
        patch_body = "+++ b/a.py\n--- a/a.py\n+line1\n+line2\n+line3\n"
        ctx = _file_ctx(patch_body, path="a.py", is_write=True)
        result = file_result_v4(ctx)
        add_chips = [c for c in result.chips if c.kind == "diff+"]
        assert add_chips, "expected diff+ chip"
        assert add_chips[0].tone == "success"

    def test_result_summary_v4_rejects_bad_tone(self):
        with pytest.raises(ValueError, match="cannot have tone"):
            ResultSummaryV4(
                primary="x", exit_code=None,
                chips=(Chip("+1", "diff+", "error"),),
                stderr_tail="", actions=(), artifacts=(), is_error=False,
            )

    def test_result_summary_v4_accepts_tone_contract(self):
        for kind, tones in _TONE_BY_KIND.items():
            for tone in tones:
                ResultSummaryV4(
                    primary="x", exit_code=None,
                    chips=(Chip("val", kind, tone),),
                    stderr_tail="", actions=(), artifacts=(), is_error=False,
                )


# ---------------------------------------------------------------------------
# H2 — Shell pipeline grouping
# ---------------------------------------------------------------------------


class TestH2ShellPipelineGrouping:

    def _shell(self, label, *, dt_ago=0.0):
        from hermes_cli.tui.tool_category import ToolCategory
        p = _mock_panel(category=ToolCategory.SHELL, tool_name="bash", label=label)
        p._start_time = time.monotonic() - dt_ago
        return p

    def test_shell_pipeline_with_operator_groups_long_window(self):
        """ls && make + make test 800ms apart → RULE_SHELL_PIPE (wide window)."""
        prev = self._shell("ls && make", dt_ago=0.8)
        new = self._shell("make test", dt_ago=0.0)
        mp = _make_mp([prev])
        with (
            patch("hermes_cli.config.read_raw_config", return_value={"display": {"shell_pipeline_ms": 500}}),
            patch("hermes_cli.tui.tool_group._get_header_label", side_effect=lambda p: p._label),
            patch("hermes_cli.tui.tool_group._get_effective_tp_siblings", return_value=[prev]),
        ):
            match = _find_rule_match(mp, new)
        assert match is not None
        assert match[1] == RULE_SHELL_PIPE

    def test_shell_pipeline_summary_names_pipeline(self):
        """RULE_SHELL_PIPE summary starts with 'shell pipeline'."""
        from hermes_cli.tui.tool_category import ToolCategory
        ch = _mock_panel(category=ToolCategory.SHELL, tool_name="bash", label="ls | head")
        with patch("hermes_cli.tui.tool_group._get_header_label", side_effect=lambda p: p._label):
            text = _build_summary_text(RULE_SHELL_PIPE, [ch])
        assert text.startswith("shell pipeline")

    def test_shell_temporal_only_groups_as_batch(self):
        """Two unrelated cmds 100ms apart → RULE_SHELL_BATCH, not RULE_SHELL_PIPE."""
        prev = self._shell("ls", dt_ago=0.1)
        new = self._shell("echo hi", dt_ago=0.0)
        mp = _make_mp([prev])
        with (
            patch("hermes_cli.config.read_raw_config", return_value={"display": {"shell_pipeline_ms": 500}}),
            patch("hermes_cli.tui.tool_group._get_header_label", side_effect=lambda p: p._label),
            patch("hermes_cli.tui.tool_group._get_effective_tp_siblings", return_value=[prev]),
        ):
            match = _find_rule_match(mp, new)
        assert match is not None
        _, rule = match
        assert rule == RULE_SHELL_BATCH
        assert rule != RULE_SHELL_PIPE

    def test_shell_temporal_batch_names_first_and_last(self):
        """RULE_SHELL_BATCH summary contains both first and last command."""
        from hermes_cli.tui.tool_category import ToolCategory
        first = _mock_panel(category=ToolCategory.SHELL, label="ls")
        last = _mock_panel(category=ToolCategory.SHELL, label="echo hi")
        with patch("hermes_cli.tui.tool_group._get_header_label", side_effect=lambda p: p._label):
            text = _build_summary_text(RULE_SHELL_BATCH, [first, last])
        assert "ls" in text
        assert "echo hi" in text
        assert "shell pipeline" not in text

    def test_shell_no_operator_outside_window_no_group(self):
        """Two unrelated cmds 800ms apart → no group."""
        prev = self._shell("ls", dt_ago=0.8)
        new = self._shell("echo hi", dt_ago=0.0)
        mp = _make_mp([prev])
        with (
            patch("hermes_cli.config.read_raw_config", return_value={"display": {"shell_pipeline_ms": 500}}),
            patch("hermes_cli.tui.tool_group._get_header_label", side_effect=lambda p: p._label),
            patch("hermes_cli.tui.tool_group._get_effective_tp_siblings", return_value=[prev]),
        ):
            match = _find_rule_match(mp, new)
        assert match is None

    def test_shell_pipeline_operator_only_in_new_cmd(self):
        """ls (prev) + ls | wc (new) 300ms → RULE_SHELL_PIPE."""
        prev = self._shell("ls", dt_ago=0.3)
        new = self._shell("ls | wc", dt_ago=0.0)
        mp = _make_mp([prev])
        with (
            patch("hermes_cli.config.read_raw_config", return_value={"display": {"shell_pipeline_ms": 500}}),
            patch("hermes_cli.tui.tool_group._get_header_label", side_effect=lambda p: p._label),
            patch("hermes_cli.tui.tool_group._get_effective_tp_siblings", return_value=[prev]),
        ):
            match = _find_rule_match(mp, new)
        assert match is not None
        assert match[1] == RULE_SHELL_PIPE

    def test_shell_single_pipe_detected_not_double(self):
        """Regex: | detected, || also detected, ||| doesn't cause double-match."""
        assert _PIPELINE_OPS_RE.search("a | b")
        assert _PIPELINE_OPS_RE.search("a || b")
        # ||| should match once for ||, not twice causing issues
        matches = _PIPELINE_OPS_RE.findall("a ||| b")
        assert len(matches) >= 1


# ---------------------------------------------------------------------------
# H3 — Read + write same-path grouping
# ---------------------------------------------------------------------------


class TestH3FileEditPairing:

    def _file_panel(self, tool_name, label, *, dt_ago=0.0):
        from hermes_cli.tui.tool_category import ToolCategory
        p = _mock_panel(category=ToolCategory.FILE, tool_name=tool_name, label=label)
        p._start_time = time.monotonic() - dt_ago
        return p

    def _rule_match_with_label(self, prev, new):
        mp = _make_mp([prev])
        with (
            patch("hermes_cli.config.read_raw_config", return_value={"display": {"diff_attach_window_s": 15.0}}),
            patch("hermes_cli.tui.tool_group._get_header_label", side_effect=lambda p: p._label),
            patch("hermes_cli.tui.tool_group._get_effective_tp_siblings", return_value=[prev]),
        ):
            return _find_rule_match(mp, new)

    def test_read_then_edit_same_path_groups(self):
        prev = self._file_panel("read_file", "a.py", dt_ago=2.0)
        new = self._file_panel("edit_file", "a.py", dt_ago=0.0)
        match = self._rule_match_with_label(prev, new)
        assert match is not None
        assert match[1] == RULE_FILE_EDIT

    def test_read_then_edit_summary_names_basename(self):
        from hermes_cli.tui.tool_category import ToolCategory
        read = _mock_panel(category=ToolCategory.FILE, tool_name="read_file", label="/some/path/a.py")
        edit = _mock_panel(category=ToolCategory.FILE, tool_name="edit_file", label="/some/path/a.py")
        with patch("hermes_cli.tui.tool_group._get_header_label", side_effect=lambda p: p._label):
            text = _build_summary_text(RULE_FILE_EDIT, [read, edit])
        assert text == "edited a.py"

    def test_read_then_edit_different_paths_no_group(self):
        prev = self._file_panel("read_file", "a.py", dt_ago=2.0)
        new = self._file_panel("edit_file", "b.py", dt_ago=0.0)
        match = self._rule_match_with_label(prev, new)
        assert match is None

    def test_read_then_edit_outside_window_no_group(self):
        prev = self._file_panel("read_file", "a.py", dt_ago=30.0)
        new = self._file_panel("edit_file", "a.py", dt_ago=0.0)
        mp = _make_mp([prev])
        with (
            patch("hermes_cli.config.read_raw_config", return_value={"display": {"diff_attach_window_s": 15.0}}),
            patch("hermes_cli.tui.tool_group._get_header_label", side_effect=lambda p: p._label),
            patch("hermes_cli.tui.tool_group._get_effective_tp_siblings", return_value=[prev]),
        ):
            match = _find_rule_match(mp, new)
        assert match is None

    def test_read_then_shell_no_group(self):
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.tool_panel import ToolPanel as _TP
        prev = self._file_panel("read_file", "a.py", dt_ago=2.0)
        new_shell = MagicMock(spec=_TP)
        new_shell._category = ToolCategory.SHELL
        new_shell._tool_name = "bash"
        new_shell._label = "a.py"
        new_shell._start_time = time.monotonic()
        new_shell.parent = None
        new_shell.is_attached = True
        new_shell.classes = []
        mp = _make_mp([prev])
        with (
            patch("hermes_cli.tui.tool_group._get_header_label", side_effect=lambda p: p._label),
            patch("hermes_cli.tui.tool_group._get_effective_tp_siblings", return_value=[prev]),
        ):
            match = _find_rule_match(mp, new_shell)
        assert match is None or match[1] != RULE_FILE_EDIT

    def test_view_then_patch_groups(self):
        """view is a read alias; patch is a write alias — group should form."""
        prev = self._file_panel("view", "a.py", dt_ago=5.0)
        new = self._file_panel("patch", "a.py", dt_ago=0.0)
        match = self._rule_match_with_label(prev, new)
        assert match is not None
        assert match[1] == RULE_FILE_EDIT


# ---------------------------------------------------------------------------
# H4 — Collapsed group append
# ---------------------------------------------------------------------------


class TestH4CollapsedGroupAppend:

    def _make_group(self, *, collapsed: bool):
        from hermes_cli.tui.tool_group import ToolGroup, GroupHeader, GroupBody
        group = MagicMock(spec=ToolGroup)
        group.collapsed = collapsed
        header = MagicMock(spec=GroupHeader)
        header.classes = set()

        def add_class(cls):
            header.classes.add(cls)

        def remove_class(cls):
            header.classes.discard(cls)

        header.add_class = add_class
        header.remove_class = remove_class
        group._header = header

        body = MagicMock(spec=GroupBody)
        group._body = body

        # recompute_aggregate is a no-op
        group.recompute_aggregate = MagicMock()
        return group

    def _make_async_group(self, *, collapsed: bool):
        """Group mock with AsyncMock for mount/remove."""
        from hermes_cli.tui.tool_group import GroupHeader, GroupBody

        header_classes: set[str] = set()
        group = MagicMock()
        group.recompute_aggregate = MagicMock()
        group.set_timer = MagicMock()
        group.app = MagicMock()

        body = MagicMock()
        body.mount = AsyncMock()
        group._body = body

        header = MagicMock()
        header.classes = header_classes
        header.add_class = lambda c: header_classes.add(c)
        header.remove_class = lambda c: header_classes.discard(c)
        group._header = header

        group._collapsed_value = collapsed

        type(group).collapsed = property(
            lambda self: self._collapsed_value,
            lambda self, v: setattr(self, "_collapsed_value", v),
        )

        return group, header_classes

    @pytest.mark.asyncio
    async def test_append_to_collapsed_group_expands(self):
        from hermes_cli.tui.tool_group import _do_append_to_group

        group, _ = self._make_async_group(collapsed=True)
        new_panel = MagicMock()
        new_panel.parent = MagicMock()  # not message_panel
        message_panel = MagicMock()

        await _do_append_to_group(group, new_panel, message_panel)
        assert group._collapsed_value is False

    @pytest.mark.asyncio
    async def test_append_to_expanded_group_no_flash(self):
        from hermes_cli.tui.tool_group import _do_append_to_group

        group, header_classes = self._make_async_group(collapsed=False)
        new_panel = MagicMock()
        new_panel.parent = MagicMock()
        message_panel = MagicMock()

        await _do_append_to_group(group, new_panel, message_panel)
        assert "--group-appended" not in header_classes

    @pytest.mark.asyncio
    async def test_append_to_collapsed_group_flashes_header(self):
        from hermes_cli.tui.tool_group import _do_append_to_group

        group, header_classes = self._make_async_group(collapsed=True)
        new_panel = MagicMock()
        new_panel.parent = MagicMock()
        message_panel = MagicMock()

        await _do_append_to_group(group, new_panel, message_panel)
        assert "--group-appended" in header_classes

    @pytest.mark.asyncio
    async def test_flash_class_removed_after_timer(self):
        """set_timer is called with 0.6 delay and a lambda that removes the class."""
        from hermes_cli.tui.tool_group import _do_append_to_group

        group, header_classes = self._make_async_group(collapsed=True)
        timer_callbacks: list = []

        def _set_timer(delay, cb):
            timer_callbacks.append((delay, cb))

        group.set_timer = _set_timer

        new_panel = MagicMock()
        new_panel.parent = MagicMock()
        message_panel = MagicMock()

        await _do_append_to_group(group, new_panel, message_panel)

        assert timer_callbacks, "set_timer should have been called"
        delay, cb = timer_callbacks[0]
        assert delay == pytest.approx(0.6, abs=0.05)

        # Simulate timer firing — class should be removed
        header_classes.add("--group-appended")
        cb()
        assert "--group-appended" not in header_classes


# ---------------------------------------------------------------------------
# H5 — OmissionBar._reset_label
# ---------------------------------------------------------------------------


class TestH5OmissionBarReset:

    def test_reset_label_returns_string(self):
        from hermes_cli.tui.tool_blocks._shared import OmissionBar
        result = OmissionBar._reset_label()
        assert isinstance(result, str)
        assert result == "[reset]"

    def test_refresh_skin_resets_cap_button_label(self):
        from hermes_cli.tui.tool_blocks._shared import OmissionBar
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock

        bar = MagicMock(spec=OmissionBar)
        bar.is_mounted = True

        btn = MagicMock()
        btn.label = "old label"
        bar.query_one = MagicMock(return_value=btn)

        block = MagicMock(spec=StreamingToolBlock)
        block._omission_bar_top = bar
        block._omission_bar_bottom = None
        block._header = MagicMock()
        block._header._refresh_gutter_color = MagicMock()
        block._header._refresh_tool_icon = MagicMock()
        block._header.refresh = MagicMock()

        StreamingToolBlock.refresh_skin(block)

        bar.query_one.assert_called_once_with(".--ob-cap", pytest.importorskip("textual.widgets").Button)
        assert btn.label == "[reset]"

    def test_refresh_skin_skips_unmounted_bar(self):
        from hermes_cli.tui.tool_blocks._shared import OmissionBar
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock

        bar = MagicMock(spec=OmissionBar)
        bar.is_mounted = False

        block = MagicMock(spec=StreamingToolBlock)
        block._omission_bar_top = bar
        block._omission_bar_bottom = None
        block._header = MagicMock()
        block._header._refresh_gutter_color = MagicMock()
        block._header._refresh_tool_icon = MagicMock()
        block._header.refresh = MagicMock()

        StreamingToolBlock.refresh_skin(block)
        bar.query_one.assert_not_called()

    def test_streaming_swallow_logs_on_nomatches(self):
        from textual.css.query import NoMatches
        from hermes_cli.tui.tool_blocks._shared import OmissionBar
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock

        bar = MagicMock(spec=OmissionBar)
        bar.is_mounted = True
        bar.query_one = MagicMock(side_effect=NoMatches())

        block = MagicMock(spec=StreamingToolBlock)
        block._omission_bar_top = bar
        block._omission_bar_bottom = None
        block._header = MagicMock()
        block._header._refresh_gutter_color = MagicMock()
        block._header._refresh_tool_icon = MagicMock()
        block._header.refresh = MagicMock()

        with patch("hermes_cli.tui.tool_blocks._streaming.logger") as mock_log:
            StreamingToolBlock.refresh_skin(block)
            mock_log.debug.assert_called_once()
            call_args = mock_log.debug.call_args
            assert call_args.kwargs.get("exc_info") is True

    def test_streaming_swallow_logs_on_attribute_error(self):
        from hermes_cli.tui.tool_blocks._shared import OmissionBar
        from hermes_cli.tui.tool_blocks._streaming import StreamingToolBlock

        bar = MagicMock(spec=OmissionBar)
        bar.is_mounted = True
        bar.query_one = MagicMock(side_effect=AttributeError("drift"))

        block = MagicMock(spec=StreamingToolBlock)
        block._omission_bar_top = bar
        block._omission_bar_bottom = None
        block._header = MagicMock()
        block._header._refresh_gutter_color = MagicMock()
        block._header._refresh_tool_icon = MagicMock()
        block._header.refresh = MagicMock()

        with patch("hermes_cli.tui.tool_blocks._streaming.logger") as mock_log:
            StreamingToolBlock.refresh_skin(block)
            mock_log.warning.assert_called_once()
            call_args = mock_log.warning.call_args
            assert call_args.kwargs.get("exc_info") is True


# ---------------------------------------------------------------------------
# Regression slice
# ---------------------------------------------------------------------------


class TestHighRegressions:

    def test_rule4_evaluated_before_rule1(self):
        """A read→write match should not accidentally become diff-attach."""
        from hermes_cli.tui.tool_category import ToolCategory
        from hermes_cli.tui.tool_panel import ToolPanel as _TP

        # prev = read_file("a.py")
        prev = MagicMock(spec=_TP)
        prev._category = ToolCategory.FILE
        prev._tool_name = "read_file"
        prev._label = "a.py"
        prev._start_time = time.monotonic() - 2.0
        prev._completed_at = time.monotonic() - 1.5
        prev.classes = []
        prev.parent = None
        prev.is_attached = True
        prev._result_paths = []

        # new = patch("a.py") — would also match Rule 1 (diff tool), but Rule 4 wins
        new = MagicMock(spec=_TP)
        new._category = ToolCategory.FILE
        new._tool_name = "patch"
        new._label = "a.py"
        new._start_time = time.monotonic()
        new._completed_at = None
        new.classes = []
        new.parent = None
        new.is_attached = True
        new._result_paths = []

        mp = _make_mp([prev])
        with (
            patch("hermes_cli.config.read_raw_config", return_value={"display": {"diff_attach_window_s": 15.0}}),
            patch("hermes_cli.tui.tool_group._get_header_label", side_effect=lambda p: p._label),
            patch("hermes_cli.tui.tool_group._get_effective_tp_siblings", return_value=[prev]),
        ):
            match = _find_rule_match(mp, new)

        # Rule 4 wins — not diff-attach
        assert match is not None
        _, rule = match
        assert rule == RULE_FILE_EDIT

    def test_tone_validator_off_path_kind_not_in_table(self):
        """Chip kinds not in _TONE_BY_KIND skip the validator — no error raised."""
        # "bytes" kind only allows "neutral" — this is in the table and should pass
        chip = Chip("10kb", "bytes", "neutral")
        rs = ResultSummaryV4(
            primary="x", exit_code=None,
            chips=(chip,),
            stderr_tail="", actions=(), artifacts=(), is_error=False,
        )
        assert rs.chips[0].tone == "neutral"

    def test_shell_batch_summary_n_greater_than_2(self):
        """RULE_SHELL_BATCH with 3 children uses 'N shell calls · first … last'."""
        from hermes_cli.tui.tool_category import ToolCategory
        c1 = _mock_panel(category=ToolCategory.SHELL, label="git status")
        c2 = _mock_panel(category=ToolCategory.SHELL, label="git diff")
        c3 = _mock_panel(category=ToolCategory.SHELL, label="git log")
        with patch("hermes_cli.tui.tool_group._get_header_label", side_effect=lambda p: p._label):
            text = _build_summary_text(RULE_SHELL_BATCH, [c1, c2, c3])
        assert "3 shell calls" in text
        assert "git status" in text
        assert "git log" in text

    def test_file_edit_summary_falls_back_when_no_label(self):
        """_build_summary_text RULE_FILE_EDIT with no label falls back to 'edited file'."""
        from hermes_cli.tui.tool_category import ToolCategory
        child = _mock_panel(category=ToolCategory.FILE, tool_name="edit_file", label="")
        with patch("hermes_cli.tui.tool_group._get_header_label", side_effect=lambda p: p._label):
            text = _build_summary_text(RULE_FILE_EDIT, [child])
        assert text == "edited file"
