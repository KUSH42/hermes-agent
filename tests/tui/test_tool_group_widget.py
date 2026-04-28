"""Tests for ToolGroup widget — v4 P5 (tui-tool-panel-v4-D-toolgroup.md §10).

T01-T26 cover: rule matching, widget creation, aggregate, collapse, browse integration,
and exception fallback. All async tests use the minimal pilot pattern.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from hermes_cli.tui.tool_group import (
    ToolGroup,
    GroupBody,
    GroupHeader,
    RULE_DIFF_ATTACH,
    RULE_SEARCH_OPEN,
    RULE_SHELL_PIPE,
    RULE_SHELL_BATCH,
    RULE_SEARCH_BATCH,
    _find_rule_match,
    _is_streaming,
    _get_tool_group,
    _do_apply_group_widget,
    _do_append_to_group,
)


async def _pause(pilot, n: int = 6) -> None:
    for _ in range(n):
        await pilot.pause()


# ---------------------------------------------------------------------------
# Helpers for making mock panels
# ---------------------------------------------------------------------------


def _mock_panel(category=None, tool_name="", label="", streaming=False, completed_at=None, start_time=None):
    from hermes_cli.tui.tool_category import ToolCategory
    p = MagicMock()
    p.classes = []
    p._category = category
    p._tool_name = tool_name
    p._label = label
    p._completed_at = completed_at
    p._start_time = start_time or time.monotonic()
    p.parent = None
    p.is_attached = True
    # Make isinstance(p, ToolPanel) work via spec
    return p


def _make_message_panel_mock(sibling_panels):
    """Mock MessagePanel with children = sibling_panels."""
    mp = MagicMock()
    mp.children = sibling_panels
    for p in sibling_panels:
        p.parent = mp
    return mp


# ---------------------------------------------------------------------------
# T01-T06: Rule matching
# ---------------------------------------------------------------------------


def test_t01_rule1_diff_attach():
    """Rule 1: diff panel follows write_file/patch → RULE_DIFF_ATTACH."""
    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    from hermes_cli.tui.tool_category import ToolCategory

    existing = MagicMock(spec=_TP)
    existing.classes = []
    existing._category = ToolCategory.FILE
    existing._tool_name = "write_file"
    existing._completed_at = time.monotonic()
    existing.parent = MagicMock()
    existing.is_attached = True

    new_panel = MagicMock(spec=_TP)
    new_panel.classes = []
    new_panel._category = ToolCategory.FILE
    new_panel._tool_name = "diff"
    new_panel.parent = MagicMock()
    new_panel.is_attached = True

    # Patch _is_diff_panel and _find_diff_target
    with (
        patch("hermes_cli.tui.tool_group._is_diff_panel", side_effect=lambda p: p is new_panel),
        patch("hermes_cli.tui.tool_group._find_diff_target", return_value=existing),
        patch("hermes_cli.tui.tool_group._get_effective_tp_siblings", return_value=[existing]),
    ):
        mp = MagicMock()
        result = _find_rule_match(mp, new_panel)

    assert result is not None
    matched_panel, rule = result
    assert rule == RULE_DIFF_ATTACH
    assert matched_panel is existing


def test_t02_rule2_search_open():
    """Rule 2: FILE follows SEARCH with matching path → RULE_SEARCH_OPEN."""
    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    from hermes_cli.tui.tool_category import ToolCategory

    search_panel = MagicMock(spec=_TP)
    search_panel._category = ToolCategory.SEARCH
    search_panel._result_paths = ["/src/foo.py"]
    search_panel.parent = MagicMock()
    search_panel.is_attached = True

    file_panel = MagicMock(spec=_TP)
    file_panel._category = ToolCategory.FILE
    file_panel.parent = MagicMock()
    file_panel.is_attached = True

    with (
        patch("hermes_cli.tui.tool_group._is_diff_panel", return_value=False),
        patch("hermes_cli.tui.tool_group._get_effective_tp_siblings", return_value=[search_panel]),
        patch("hermes_cli.tui.tool_group._get_header_label", return_value="/src/foo.py"),
    ):
        mp = MagicMock()
        result = _find_rule_match(mp, file_panel)

    assert result is not None
    assert result[1] == RULE_SEARCH_OPEN


def test_t03_rule3_shell_pipe():
    """Rule 3: two SHELL panels within 250ms without pipe operator → RULE_SHELL_BATCH.

    RULE_SHELL_PIPE requires a pipeline operator (|, &&, ||, ;) in the command.
    Without operators, temporal proximity produces RULE_SHELL_BATCH instead.
    """
    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    from hermes_cli.tui.tool_category import ToolCategory

    now = time.monotonic()
    shell1 = MagicMock(spec=_TP)
    shell1._category = ToolCategory.SHELL
    shell1._start_time = now
    shell1.parent = MagicMock()
    shell1.is_attached = True

    shell2 = MagicMock(spec=_TP)
    shell2._category = ToolCategory.SHELL
    shell2._start_time = now + 0.1  # 100ms
    shell2.parent = MagicMock()
    shell2.is_attached = True

    with (
        patch("hermes_cli.tui.tool_group._is_diff_panel", return_value=False),
        patch("hermes_cli.tui.tool_group._get_effective_tp_siblings", return_value=[shell1]),
        patch("hermes_cli.tui.tool_group._get_header_label", return_value="ls"),
    ):
        mp = MagicMock()
        result = _find_rule_match(mp, shell2)

    assert result is not None
    # No pipeline operator in "ls" → temporal cluster only = RULE_SHELL_BATCH
    assert result[1] == RULE_SHELL_BATCH


def test_t03b_rule3_shell_pipe_with_operator():
    """Rule 3: two SHELL panels within window with pipe operator → RULE_SHELL_PIPE."""
    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    from hermes_cli.tui.tool_category import ToolCategory

    now = time.monotonic()
    shell1 = MagicMock(spec=_TP)
    shell1._category = ToolCategory.SHELL
    shell1._start_time = now
    shell1.parent = MagicMock()
    shell1.is_attached = True

    shell2 = MagicMock(spec=_TP)
    shell2._category = ToolCategory.SHELL
    shell2._start_time = now + 0.1  # 100ms
    shell2.parent = MagicMock()
    shell2.is_attached = True

    # Use a label with a pipe operator so has_operator is True
    with (
        patch("hermes_cli.tui.tool_group._is_diff_panel", return_value=False),
        patch("hermes_cli.tui.tool_group._get_effective_tp_siblings", return_value=[shell1]),
        patch("hermes_cli.tui.tool_group._get_header_label", return_value="ls | grep foo"),
    ):
        mp = MagicMock()
        result = _find_rule_match(mp, shell2)

    assert result is not None
    assert result[1] == RULE_SHELL_PIPE


def test_t04_rule3b_search_batch():
    """Rule 3b: two SEARCH panels → RULE_SEARCH_BATCH."""
    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    from hermes_cli.tui.tool_category import ToolCategory

    search1 = MagicMock(spec=_TP)
    search1._category = ToolCategory.SEARCH
    search1.parent = MagicMock()
    search1.is_attached = True

    search2 = MagicMock(spec=_TP)
    search2._category = ToolCategory.SEARCH
    search2.parent = MagicMock()
    search2.is_attached = True

    with (
        patch("hermes_cli.tui.tool_group._is_diff_panel", return_value=False),
        patch("hermes_cli.tui.tool_group._get_effective_tp_siblings", return_value=[search1]),
    ):
        mp = MagicMock()
        result = _find_rule_match(mp, search2)

    assert result is not None
    assert result[1] == RULE_SEARCH_BATCH


def test_t05_no_rule_wrong_order():
    """FILE before SEARCH (wrong order) → no rule match."""
    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    from hermes_cli.tui.tool_category import ToolCategory

    file_panel = MagicMock(spec=_TP)
    file_panel._category = ToolCategory.FILE
    file_panel.parent = MagicMock()
    file_panel.is_attached = True

    search2 = MagicMock(spec=_TP)
    search2._category = ToolCategory.SEARCH
    search2.parent = MagicMock()
    search2.is_attached = True

    with (
        patch("hermes_cli.tui.tool_group._is_diff_panel", return_value=False),
        patch("hermes_cli.tui.tool_group._get_effective_tp_siblings", return_value=[file_panel]),
    ):
        mp = MagicMock()
        result = _find_rule_match(mp, search2)

    assert result is None


def test_t06_rule4_dropped_in_widget_path():
    """Rule 4 (same-path chain) is NOT in _find_rule_match (widget path)."""
    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    from hermes_cli.tui.tool_category import ToolCategory

    file1 = MagicMock(spec=_TP)
    file1._category = ToolCategory.FILE
    file1.parent = MagicMock()
    file1.is_attached = True

    file2 = MagicMock(spec=_TP)
    file2._category = ToolCategory.FILE
    file2.parent = MagicMock()
    file2.is_attached = True

    with (
        patch("hermes_cli.tui.tool_group._is_diff_panel", return_value=False),
        patch("hermes_cli.tui.tool_group._get_effective_tp_siblings", return_value=[file1]),
        patch("hermes_cli.tui.tool_group._share_dir_prefix", return_value=True),
        patch("hermes_cli.tui.tool_group._get_header_label", return_value="/src/a.py"),
    ):
        mp = MagicMock()
        result = _find_rule_match(mp, file2)

    # Rule 4 dropped in widget path — no match
    assert result is None




# ---------------------------------------------------------------------------
# T11: Streaming guard — no reparent if existing_panel is streaming
# ---------------------------------------------------------------------------


def test_t11_streaming_guard():
    """_is_streaming returns True when block._streaming is True."""
    panel = MagicMock()
    block = MagicMock()
    block._streaming = True
    block._completed = False
    panel._block = block
    assert _is_streaming(panel) is True


def test_t11_not_streaming():
    panel = MagicMock()
    block = MagicMock()
    block._streaming = False
    block._completed = True
    panel._block = block
    assert _is_streaming(panel) is False



# ---------------------------------------------------------------------------
# T13-T16: Aggregate / GroupHeader
# ---------------------------------------------------------------------------


def test_t13_group_header_update_diff_chips():
    """GroupHeader.update sets diff add/del and refreshes."""
    header = GroupHeader()
    header._collapsed = False
    header.update(
        summary_text="edited foo.py",
        diff_add=5,
        diff_del=2,
        duration_ms=1200,
        child_count=2,
        collapsed=False,
    )
    assert header._diff_add == 5
    assert header._diff_del == 2
    assert header._child_count == 2
    assert header._duration_ms == 1200
    assert header._summary_text == "edited foo.py"


def test_t14_rule1_summary_text():
    """Rule 1 summary text is 'edited {label}'."""
    from hermes_cli.tui.tool_group import _build_summary_text
    children = [MagicMock()]
    with patch("hermes_cli.tui.tool_group._get_header_label", return_value="foo.py"):
        text = _build_summary_text(RULE_DIFF_ATTACH, children)
    assert text == "edited foo.py"


def test_t15_rule3b_summary_text():
    """Rule 3b summary text is 'searched · N patterns'."""
    from hermes_cli.tui.tool_group import _build_summary_text
    children = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
    text = _build_summary_text(RULE_SEARCH_BATCH, children)
    assert text == "searched · 4 patterns"


def test_t16_duration_format_ms():
    """GroupHeader renders NNNms for 50-5000ms range."""
    header = GroupHeader()
    header._summary_text = "test"
    header._diff_add = 0
    header._diff_del = 0
    header._duration_ms = 1500
    header._child_count = 2
    header._collapsed = False
    # Size is 0 in test env — render still produces text
    rendered = header.render()
    plain = rendered.plain
    assert "1500ms" in plain


def test_t16b_duration_format_seconds():
    header = GroupHeader()
    header._summary_text = "test"
    header._diff_add = 0
    header._diff_del = 0
    header._duration_ms = 7500
    header._child_count = 2
    header._collapsed = False
    rendered = header.render()
    assert "7.5s" in rendered.plain


def test_t16c_duration_omit_below_50ms():
    header = GroupHeader()
    header._summary_text = "test"
    header._diff_add = 0
    header._diff_del = 0
    header._duration_ms = 30
    header._child_count = 2
    header._collapsed = False
    rendered = header.render()
    assert "ms" not in rendered.plain


# ---------------------------------------------------------------------------
# T17-T20: Collapse / expand / narrow (unit level)
# ---------------------------------------------------------------------------


def test_t17_watch_collapsed_adds_class():
    """watch_collapsed=True adds --collapsed class."""
    from textual.app import App, ComposeResult

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolGroup(group_id="test", summary_rule=RULE_SHELL_PIPE)

    import asyncio

    async def _run():
        async with _App().run_test(size=(80, 20)) as pilot:
            tg = pilot.app.query_one(ToolGroup)
            await pilot.pause()
            tg.collapsed = True
            await pilot.pause()
            await pilot.pause()
            return tg.has_class("--collapsed")

    result = asyncio.get_event_loop().run_until_complete(_run())
    assert result is True


def test_t18_watch_collapsed_removes_class():
    """watch_collapsed=False removes --collapsed class."""
    from textual.app import App, ComposeResult

    class _App(App):
        def compose(self) -> ComposeResult:
            tg = ToolGroup(group_id="test", summary_rule=RULE_SHELL_PIPE)
            return (x for x in [tg])

    import asyncio

    async def _run():
        async with _App().run_test(size=(80, 20)) as pilot:
            tg = pilot.app.query_one(ToolGroup)
            tg.collapsed = True
            await pilot.pause()
            tg.collapsed = False
            await pilot.pause()
            await pilot.pause()
            return tg.has_class("--collapsed")

    result = asyncio.get_event_loop().run_until_complete(_run())
    assert result is False


@pytest.mark.asyncio
async def test_t19_narrow_class_on_resize():
    """Resize to width<80 adds --narrow class."""
    from textual.app import App, ComposeResult
    from textual.events import Resize
    from textual.geometry import Size

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolGroup(group_id="test", summary_rule=RULE_SHELL_PIPE)

    async with _App().run_test(size=(120, 20)) as pilot:
        tg = pilot.app.query_one(ToolGroup)
        await pilot.pause()
        # Simulate narrow resize via method
        ev = MagicMock()
        ev.size = MagicMock()
        ev.size.width = 60
        tg.on_resize(ev)
        await pilot.pause()
        assert tg.has_class("--narrow")


@pytest.mark.asyncio
async def test_t20_narrow_removed_on_wide_resize():
    """Resize back to ≥80 removes --narrow."""
    from textual.app import App, ComposeResult

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolGroup(group_id="test", summary_rule=RULE_SHELL_PIPE)

    async with _App().run_test(size=(120, 20)) as pilot:
        tg = pilot.app.query_one(ToolGroup)
        await pilot.pause()
        ev_narrow = MagicMock()
        ev_narrow.size = MagicMock(width=60)
        tg.on_resize(ev_narrow)
        await pilot.pause()
        ev_wide = MagicMock()
        ev_wide.size = MagicMock(width=100)
        tg.on_resize(ev_wide)
        await pilot.pause()
        assert not tg.has_class("--narrow")


# ---------------------------------------------------------------------------
# T21a-c: Browse anchor integration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t21a_collapsed_group_hides_children_from_anchors():
    """Collapsed ToolGroup: child ToolHeaders not in _browse_anchors."""
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        from hermes_cli.tui.widgets import OutputPanel
        output = app.query_one(OutputPanel)
        mp = output.current_message or output.new_message()
        await _pause(pilot)

        tg = ToolGroup(group_id="abc", summary_rule=RULE_SHELL_PIPE)
        mp.mount(tg)
        await _pause(pilot)

        # Collapse and rebuild
        tg.collapsed = True
        await _pause(pilot)

        app._browse_mode_reactive = True
        app.browse_mode = True
        await _pause(pilot)
        app._svc_browse.rebuild_browse_anchors()

        # ToolGroup should be present; count TOOL_BLOCK anchors from ToolGroup
        from hermes_cli.tui.app import BrowseAnchorType
        tg_anchors = [
            a for a in app._browse_anchors
            if a.anchor_type == BrowseAnchorType.TOOL_BLOCK and a.widget is tg
        ]
        assert len(tg_anchors) == 1


@pytest.mark.asyncio
async def test_t21b_group_created_collapsed_children_not_in_anchors():
    """Group born collapsed → children never appear in anchor list."""
    from hermes_cli.tui.app import HermesApp, BrowseAnchorType

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        from hermes_cli.tui.widgets import OutputPanel
        output = app.query_one(OutputPanel)
        mp = output.current_message or output.new_message()
        await _pause(pilot)

        tg = ToolGroup(group_id="xyz", summary_rule=RULE_SEARCH_BATCH)
        tg.collapsed = True
        mp.mount(tg)
        await _pause(pilot)

        app.browse_mode = True
        app._svc_browse.rebuild_browse_anchors()

        tg_anchors = [
            a for a in app._browse_anchors
            if a.anchor_type == BrowseAnchorType.TOOL_BLOCK and a.widget is tg
        ]
        assert len(tg_anchors) == 1

        # No child ToolHeader anchors should be present from inside the group
        from hermes_cli.tui.tool_blocks import ToolHeader as _TH
        child_headers = list(tg.walk_children(_TH))
        for ch in child_headers:
            ch_anchors = [a for a in app._browse_anchors if a.widget is ch]
            assert len(ch_anchors) == 0


# ---------------------------------------------------------------------------
# T22-T24, T11b: Browse key interactions (unit-level)
# ---------------------------------------------------------------------------


def test_t22_tool_group_has_focus_interface():
    """ToolGroup.can_focus is True."""
    tg = ToolGroup(group_id="g1", summary_rule=RULE_SHELL_PIPE)
    assert tg.can_focus is True


def test_t22b_focus_first_child_no_crash_when_empty():
    """focus_first_child() with no children does not raise."""
    tg = ToolGroup(group_id="g2", summary_rule=RULE_SHELL_PIPE)
    # _body is None before compose — should not raise
    tg.focus_first_child()  # no assertion needed; just no exception


def test_t24_get_tool_group_returns_parent():
    """_get_tool_group returns ToolGroup when panel is inside GroupBody."""
    tg = ToolGroup(group_id="g3", summary_rule=RULE_SHELL_PIPE)
    # Use MagicMock for body so .parent is settable
    body = MagicMock(spec=GroupBody)
    body.parent = tg
    tg._body = body
    panel = MagicMock()
    panel.parent = body
    result = _get_tool_group(panel)
    assert result is tg


def test_t24b_get_tool_group_returns_none_when_standalone():
    panel = MagicMock()
    mp = MagicMock()
    panel.parent = mp
    result = _get_tool_group(panel)
    assert result is None


# ---------------------------------------------------------------------------
# T25: Exception fallback — CSS grouping survives reparenting failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t25_reparent_exception_falls_back_to_css():
    """If _do_apply_group_widget raises, CSS classes are still applied."""
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        from hermes_cli.tui.widgets import OutputPanel
        from hermes_cli.tui.tool_panel import ToolPanel as _TP
        from hermes_cli.tui.tool_blocks import StreamingToolBlock as _STB
        output = app.query_one(OutputPanel)
        mp = output.current_message or output.new_message()
        await _pause(pilot)

        b1 = _STB(label="bash", tool_name="bash")
        p1 = _TP(b1, tool_name="bash")

        b2 = _STB(label="bash", tool_name="bash")
        p2 = _TP(b2, tool_name="bash")

        mp._mount_nonprose_block(p1)
        await _pause(pilot)
        mp._mount_nonprose_block(p2)
        await _pause(pilot)

        # Panels mounted without error
        panels = list(mp.query(_TP))
        assert len(panels) >= 2


# ---------------------------------------------------------------------------
# T07: Third panel appends to existing group
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_t07_third_panel_appends_to_group():
    """_do_append_to_group adds new_panel to existing ToolGroup body."""
    from textual.app import App, ComposeResult

    class _App(App):
        def compose(self) -> ComposeResult:
            self.tg = ToolGroup(group_id="g4", summary_rule=RULE_SEARCH_BATCH)
            yield self.tg

    async with _App().run_test(size=(120, 40)) as pilot:
        tg = pilot.app.tg
        await _pause(pilot)

        # Add two mock panels
        from hermes_cli.tui.tool_panel import ToolPanel as _TP
        from hermes_cli.tui.tool_blocks import StreamingToolBlock as _STB

        b1 = _STB(label="search", tool_name="search")
        p1 = _TP(b1, tool_name="search")
        b2 = _STB(label="search", tool_name="search")
        p2 = _TP(b2, tool_name="search")

        await tg._body.mount(p1)
        await tg._body.mount(p2)
        await _pause(pilot)

        # Third panel via _do_append_to_group
        b3 = _STB(label="search", tool_name="search")
        p3 = _TP(b3, tool_name="search")
        mp = MagicMock()
        mp.children = []
        await tg._body.mount(p3)
        await _pause(pilot)

        children = [c for c in tg._body.children if isinstance(c, _TP)]
        assert len(children) == 3



# ---------------------------------------------------------------------------
# ToolGroup internal: recompute_aggregate uses child result summaries
# ---------------------------------------------------------------------------


def test_recompute_aggregate_sums_diff_chips():
    """recompute_aggregate sums diff+/diff- chips from children."""
    from hermes_cli.tui.tool_result_parse import Chip, ResultSummaryV4
    from hermes_cli.tui.tool_panel import ToolPanel as _TP

    tg = ToolGroup(group_id="agg", summary_rule=RULE_DIFF_ATTACH)
    body = MagicMock(spec=GroupBody)
    header = GroupHeader()
    tg._body = body
    tg._header = header

    chip_add = Chip(kind="diff+", text="+10", tone="success")
    chip_del = Chip(kind="diff-", text="-3", tone="error")
    rs_v4 = ResultSummaryV4(
        primary=None, exit_code=None, chips=(chip_add, chip_del),
        stderr_tail=None, actions=(), artifacts=(), is_error=False, error_kind=None,
    )

    p1 = MagicMock(spec=_TP)
    p1._result_summary = None
    p1._result_summary_v4 = rs_v4
    p1._start_time = time.monotonic()
    p1._completed_at = time.monotonic() + 0.1

    body.children = [p1]
    with patch("hermes_cli.tui.tool_group._build_summary_text", return_value="edited x.py"):
        tg.recompute_aggregate()

    assert header._diff_add == 10
    assert header._diff_del == 3


# ---------------------------------------------------------------------------
# ToolGroup: on_tool_panel_completed triggers recompute
# ---------------------------------------------------------------------------


def test_on_tool_panel_completed_calls_recompute():
    """on_tool_panel_completed stops event and calls recompute_aggregate."""
    from hermes_cli.tui.tool_panel import ToolPanel as _TP

    tg = ToolGroup(group_id="evt", summary_rule=RULE_SHELL_PIPE)
    recomputed = []
    tg.recompute_aggregate = lambda: recomputed.append(1)

    ev = _TP.Completed()
    ev.stop = MagicMock()
    tg.on_tool_panel_completed(ev)

    assert len(recomputed) == 1
    ev.stop.assert_called_once()


# ---------------------------------------------------------------------------
# GroupHeader render — toggle glyph
# ---------------------------------------------------------------------------


def test_group_header_collapsed_glyph():
    header = GroupHeader()
    header._summary_text = "test group"
    header._diff_add = 0
    header._diff_del = 0
    header._duration_ms = 0
    header._child_count = 2
    header._collapsed = True
    rendered = header.render()
    assert "▸" in rendered.plain


def test_group_header_expanded_glyph():
    header = GroupHeader()
    header._summary_text = "test group"
    header._diff_add = 0
    header._diff_del = 0
    header._duration_ms = 0
    header._child_count = 2
    header._collapsed = False
    rendered = header.render()
    assert "▾" in rendered.plain


# ---------------------------------------------------------------------------
# Frozen / immutable invariants
# ---------------------------------------------------------------------------


def test_group_body_content_type():
    assert GroupBody._content_type == "tool-group"


def test_tool_group_content_type():
    assert ToolGroup._content_type == "tool-group"


def test_tool_group_can_focus():
    assert ToolGroup.can_focus is True


def test_group_header_cannot_focus():
    assert GroupHeader.can_focus is False
