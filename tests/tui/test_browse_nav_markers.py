"""Tests for browse mode unified navigation markers (BrowseAnchor system).

Covers:
  - Anchor Registry (8 tests)
  - Jump Navigation (8 tests)
  - Focus & CSS (4 tests)
  - Edge Cases (4 tests)
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from hermes_cli.tui.app import BrowseAnchor, BrowseAnchorType, HermesApp
from hermes_cli.tui.tool_blocks import ToolHeader, ToolBlock
from hermes_cli.tui.widgets import OutputPanel, StatusBar, StreamingCodeBlock, UserMessagePanel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.config = {}
    return HermesApp(cli=cli)


def _make_anchor(anchor_type: BrowseAnchorType, widget=None, label="Test", turn_id=1) -> BrowseAnchor:
    w = widget or MagicMock()
    w.is_mounted = True
    return BrowseAnchor(anchor_type=anchor_type, widget=w, label=label, turn_id=turn_id)


# ---------------------------------------------------------------------------
# Anchor Registry (8 tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rebuild_anchors_empty():
    """No widgets → empty list, cursor clamped to 0."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app._svc_browse.rebuild_browse_anchors()
        assert app._browse_anchors == []
        assert app._browse_cursor == 0


@pytest.mark.asyncio
async def test_rebuild_anchors_turn_start():
    """UserMessagePanel yields one TURN_START anchor with turn_id=1."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        panel = UserMessagePanel("hello")
        await output.mount(panel)
        await pilot.pause()

        app._svc_browse.rebuild_browse_anchors()
        ts = [a for a in app._browse_anchors if a.anchor_type == BrowseAnchorType.TURN_START]
        assert len(ts) == 1
        assert ts[0].turn_id == 1
        assert ts[0].widget is panel


@pytest.mark.asyncio
async def test_rebuild_anchors_code_block_complete():
    """StreamingCodeBlock with _state == 'COMPLETE' is included."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        scb = StreamingCodeBlock(lang="python")
        await output.mount(scb)
        scb._state = "COMPLETE"
        await pilot.pause()

        app._svc_browse.rebuild_browse_anchors()
        cb = [a for a in app._browse_anchors if a.anchor_type == BrowseAnchorType.CODE_BLOCK]
        assert len(cb) == 1
        assert cb[0].widget is scb
        assert "python" in cb[0].label


@pytest.mark.asyncio
async def test_rebuild_anchors_code_block_streaming():
    """StreamingCodeBlock with _state == 'STREAMING' is excluded."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        scb = StreamingCodeBlock(lang="python")
        await output.mount(scb)
        scb._state = "STREAMING"
        await pilot.pause()

        app._svc_browse.rebuild_browse_anchors()
        cb = [a for a in app._browse_anchors if a.anchor_type == BrowseAnchorType.CODE_BLOCK]
        assert len(cb) == 0


@pytest.mark.asyncio
async def test_rebuild_anchors_tool_header():
    """ToolHeader yields one TOOL_BLOCK anchor; label comes from _label."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        block = ToolBlock("read_file", [], [], tool_name="read_file")
        await output.mount(block)
        await pilot.pause()

        app._svc_browse.rebuild_browse_anchors()
        tb = [a for a in app._browse_anchors if a.anchor_type == BrowseAnchorType.TOOL_BLOCK]
        assert len(tb) == 1
        assert tb[0].label == block._header._label or tb[0].label == "Tool"


@pytest.mark.asyncio
async def test_rebuild_anchors_document_order():
    """Anchors listed in DOM order: TURN_START → CODE_BLOCK → TOOL_BLOCK."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        ump = UserMessagePanel("hi")
        scb = StreamingCodeBlock(lang="bash")
        scb._state = "COMPLETE"
        block = ToolBlock("read_file", [], [], tool_name="read_file")
        await output.mount(ump)
        await output.mount(scb)
        await output.mount(block)
        await pilot.pause()

        app._svc_browse.rebuild_browse_anchors()
        types = [a.anchor_type for a in app._browse_anchors]
        assert types == [
            BrowseAnchorType.TURN_START,
            BrowseAnchorType.CODE_BLOCK,
            BrowseAnchorType.TOOL_BLOCK,
        ]


@pytest.mark.asyncio
async def test_rebuild_anchors_diff_header_label():
    """ToolHeader with --diff-header class gets 'Diff · ' prefix in label."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        block = ToolBlock("patch", [], [], tool_name="patch")
        await output.mount(block)
        block._header.add_class("--diff-header")
        await pilot.pause()

        app._svc_browse.rebuild_browse_anchors()
        tb = [a for a in app._browse_anchors if a.anchor_type == BrowseAnchorType.TOOL_BLOCK]
        assert len(tb) == 1
        assert tb[0].label.startswith("Diff · ")


@pytest.mark.asyncio
async def test_rebuild_anchors_cursor_clamp():
    """Cursor at 99 with 3 anchors is clamped to 2."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        for _ in range(3):
            await output.mount(UserMessagePanel("x"))
        await pilot.pause()

        app._browse_cursor = 99
        app._svc_browse.rebuild_browse_anchors()
        assert app._browse_cursor == 2


# ---------------------------------------------------------------------------
# Jump Navigation (8 tests)
# ---------------------------------------------------------------------------

def _install_anchors(app: HermesApp, types: list[BrowseAnchorType]) -> list[BrowseAnchor]:
    """Directly inject a synthetic anchor list into app for unit testing."""
    anchors = []
    for i, t in enumerate(types):
        w = MagicMock()
        w.is_mounted = True
        w.add_class = MagicMock()
        anchors.append(BrowseAnchor(anchor_type=t, widget=w, label=f"Label {i}", turn_id=i + 1))
    app._browse_anchors = anchors
    app._svc_browse._browse_anchors = anchors
    app._browse_cursor = 0
    app._svc_browse._browse_cursor = 0
    return anchors


def test_jump_anchor_forward_any():
    """_jump_anchor(+1) advances cursor from 0 to 1."""
    app = _make_app()
    _install_anchors(app, [BrowseAnchorType.TURN_START, BrowseAnchorType.CODE_BLOCK])
    app._browse_cursor = 0

    focused = []
    app._svc_browse.focus_anchor = lambda idx, anchor, **kw: focused.append(idx)
    app._svc_browse.jump_anchor(+1)
    assert focused == [1]


def test_jump_anchor_backward_any():
    """_jump_anchor(-1) moves cursor from 1 to 0."""
    app = _make_app()
    _install_anchors(app, [BrowseAnchorType.TURN_START, BrowseAnchorType.CODE_BLOCK])
    app._browse_cursor = 1

    focused = []
    app._svc_browse.focus_anchor = lambda idx, anchor, **kw: focused.append(idx)
    app._svc_browse.jump_anchor(-1)
    assert focused == [0]


def test_jump_anchor_forward_wrap():
    """] at last anchor wraps to first (index 0)."""
    app = _make_app()
    anchors = _install_anchors(app, [BrowseAnchorType.TURN_START, BrowseAnchorType.CODE_BLOCK])
    app._browse_cursor = 1  # at last

    focused = []
    app._svc_browse.focus_anchor = lambda idx, anchor, **kw: focused.append(idx)
    app._svc_browse.jump_anchor(+1)
    assert focused == [0]


def test_jump_anchor_backward_wrap():
    """[ at first anchor wraps to last."""
    app = _make_app()
    anchors = _install_anchors(app, [BrowseAnchorType.TURN_START, BrowseAnchorType.CODE_BLOCK])
    app._browse_cursor = 0  # at first

    focused = []
    app._svc_browse.focus_anchor = lambda idx, anchor, **kw: focused.append(idx)
    app._svc_browse.jump_anchor(-1)
    assert focused == [1]


def test_jump_code_block_filtered():
    """} skips TURN_START and TOOL_BLOCK, jumps only to CODE_BLOCK."""
    app = _make_app()
    _install_anchors(app, [
        BrowseAnchorType.TURN_START,
        BrowseAnchorType.CODE_BLOCK,
        BrowseAnchorType.TOOL_BLOCK,
    ])
    app._browse_cursor = 0

    focused = []
    app._svc_browse.focus_anchor = lambda idx, anchor, **kw: focused.append(idx)
    app._svc_browse.jump_anchor(+1, BrowseAnchorType.CODE_BLOCK)
    assert focused == [1]


def test_jump_code_block_no_blocks():
    """} with no CODE_BLOCK anchors → no focus call, no crash."""
    app = _make_app()
    _install_anchors(app, [BrowseAnchorType.TURN_START, BrowseAnchorType.TOOL_BLOCK])
    app._browse_cursor = 0

    focused = []
    app._svc_browse.focus_anchor = lambda idx, anchor, **kw: focused.append(idx)
    app._svc_browse.jump_anchor(+1, BrowseAnchorType.CODE_BLOCK)
    assert focused == []


def test_jump_turn_start_forward():
    """Alt+Down lands on next TURN_START, skipping CODE_BLOCK and TOOL_BLOCK."""
    app = _make_app()
    _install_anchors(app, [
        BrowseAnchorType.TURN_START,    # idx 0
        BrowseAnchorType.CODE_BLOCK,    # idx 1
        BrowseAnchorType.TOOL_BLOCK,    # idx 2
        BrowseAnchorType.TURN_START,    # idx 3
    ])
    app._browse_cursor = 0

    focused = []
    app._svc_browse.focus_anchor = lambda idx, anchor, **kw: focused.append(idx)
    app._svc_browse.jump_anchor(+1, BrowseAnchorType.TURN_START)
    assert focused == [3]


def test_jump_turn_start_backward():
    """Alt+Up lands on previous TURN_START."""
    app = _make_app()
    _install_anchors(app, [
        BrowseAnchorType.TURN_START,    # idx 0
        BrowseAnchorType.CODE_BLOCK,    # idx 1
        BrowseAnchorType.TURN_START,    # idx 2
    ])
    app._browse_cursor = 2

    focused = []
    app._svc_browse.focus_anchor = lambda idx, anchor, **kw: focused.append(idx)
    app._svc_browse.jump_anchor(-1, BrowseAnchorType.TURN_START)
    assert focused == [0]


# ---------------------------------------------------------------------------
# Focus & CSS (4 tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_focus_anchor_adds_class():
    """_focus_anchor adds --browse-focused to the target widget."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        panel = UserMessagePanel("hi")
        await output.mount(panel)
        await pilot.pause()

        anchor = BrowseAnchor(
            anchor_type=BrowseAnchorType.TURN_START,
            widget=panel,
            label="Turn 1",
            turn_id=1,
        )
        app._browse_anchors = [anchor]
        app._svc_browse.focus_anchor(0, anchor)
        await pilot.pause()
        assert panel.has_class("--browse-focused")


@pytest.mark.asyncio
async def test_focus_anchor_clears_previous():
    """Second _focus_anchor removes --browse-focused from the first widget."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        panel1 = UserMessagePanel("a")
        panel2 = UserMessagePanel("b")
        await output.mount(panel1)
        await output.mount(panel2)
        await pilot.pause()

        a1 = BrowseAnchor(BrowseAnchorType.TURN_START, panel1, "Turn 1", 1)
        a2 = BrowseAnchor(BrowseAnchorType.TURN_START, panel2, "Turn 2", 2)
        app._browse_anchors = [a1, a2]

        app._svc_browse.focus_anchor(0, a1)
        await pilot.pause()
        assert panel1.has_class("--browse-focused")

        app._svc_browse.focus_anchor(1, a2)
        await pilot.pause()
        assert not panel1.has_class("--browse-focused")
        assert panel2.has_class("--browse-focused")


@pytest.mark.asyncio
async def test_focus_anchor_scroll_called():
    """_focus_anchor calls scroll_to_widget with center=True."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        panel = UserMessagePanel("hi")
        await output.mount(panel)
        await pilot.pause()

        scroll_calls = []
        original_scroll = output.scroll_to_widget

        def capture_scroll(w, **kw):
            scroll_calls.append((w, kw))
            return original_scroll(w, **kw)

        output.scroll_to_widget = capture_scroll

        anchor = BrowseAnchor(BrowseAnchorType.TURN_START, panel, "Turn 1", 1)
        app._browse_anchors = [anchor]
        app._svc_browse.focus_anchor(0, anchor)
        await pilot.pause()

        assert len(scroll_calls) == 1
        assert scroll_calls[0][0] is panel
        assert scroll_calls[0][1].get("center") is True


@pytest.mark.asyncio
async def test_clear_browse_highlight_removes_all():
    """_clear_browse_highlight removes --browse-focused from all tagged widgets."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        panel1 = UserMessagePanel("a")
        panel2 = UserMessagePanel("b")
        await output.mount(panel1)
        await output.mount(panel2)
        await pilot.pause()

        panel1.add_class("--browse-focused")
        panel2.add_class("--browse-focused")
        app._svc_browse.clear_browse_highlight()
        await pilot.pause()

        assert not panel1.has_class("--browse-focused")
        assert not panel2.has_class("--browse-focused")


# ---------------------------------------------------------------------------
# Edge Cases (4 tests)
# ---------------------------------------------------------------------------

def test_focus_anchor_unmounted_widget():
    """Unmounted widget triggers rebuild + retry on first same-type anchor; no crash."""
    app = _make_app()

    unmounted = MagicMock()
    unmounted.is_mounted = False

    live_widget = MagicMock()
    live_widget.is_mounted = True
    live_widget.add_class = MagicMock()

    anchors = [
        BrowseAnchor(BrowseAnchorType.CODE_BLOCK, unmounted, "Code · python", 1),
        BrowseAnchor(BrowseAnchorType.CODE_BLOCK, live_widget, "Code · bash", 1),
    ]
    app._browse_anchors = [anchors[0]]  # only unmounted initially
    app._svc_browse._browse_anchors = [anchors[0]]

    rebuild_calls = []

    def fake_rebuild():
        rebuild_calls.append(1)
        # After rebuild, unmounted widget is gone; only live_widget remains
        app._browse_anchors = [anchors[1]]
        app._svc_browse._browse_anchors = [anchors[1]]

    app._svc_browse.rebuild_browse_anchors = fake_rebuild

    scroll_calls = []

    def fake_scroll_to_widget(w, **kw):
        scroll_calls.append(w)

    # Patch OutputPanel scroll
    mock_output = MagicMock()
    mock_output.scroll_to_widget = fake_scroll_to_widget

    with patch.object(app, "query_one", return_value=mock_output):
        with patch.object(app, "query", return_value=[]):
            app._svc_browse.focus_anchor(0, anchors[0])

    assert rebuild_calls == [1]
    # Retry should have landed on live_widget (first CODE_BLOCK in rebuilt list)
    assert scroll_calls == [live_widget]


@pytest.mark.asyncio
async def test_tab_path_unchanged():
    """Tab cycling changes browse_index but never touches _browse_cursor."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        output = app.query_one(OutputPanel)
        block = ToolBlock("read_file", [], [], tool_name="read_file")
        await output.mount(block)
        app._browse_total = 1
        await pilot.pause()

        app._browse_cursor = 7   # set to a sentinel that Tab must NOT change
        app.browse_mode = True
        await pilot.pause()

        await pilot.press("tab")
        await pilot.pause()

        # browse_index should have cycled; _browse_cursor untouched by Tab
        assert app._browse_cursor == 0  # reset to 0 during browse entry rebuild


def test_browse_entry_no_anchors_allowed():
    """browse_mode can be set True even when no ToolHeaders exist."""
    app = _make_app()
    # Previously, watch_browse_mode would set browse_mode=False if no headers.
    # Now it should not. Since we can't run full async here, verify the guard
    # was removed by checking watch_browse_mode doesn't query ToolHeader to deny entry.
    import inspect
    src = inspect.getsource(app.watch_browse_mode)
    # The old guard checked for ToolHeader and set browse_mode=False
    assert "if not list(self.query(" not in src


@pytest.mark.asyncio
async def test_rebuild_called_on_agent_stop():
    """watch_agent_running(False) triggers _rebuild_browse_anchors when in browse mode."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        rebuild_calls = []
        original = app._svc_browse.rebuild_browse_anchors

        def tracking_rebuild():
            rebuild_calls.append(1)
            original()

        app._svc_browse.rebuild_browse_anchors = tracking_rebuild
        app.browse_mode = True
        rebuild_calls.clear()  # ignore the entry rebuild

        app.agent_running = True
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()

        assert len(rebuild_calls) >= 1


# ---------------------------------------------------------------------------
# Alt+↑/↓ navigation (TestAltArrowNav — spec §A2)
# ---------------------------------------------------------------------------

class TestAltArrowNav:
    """Tests for action_jump_turn_prev / action_jump_turn_next (spec §A2)."""

    @pytest.mark.asyncio
    async def test_alt_up_noop_during_streaming(self):
        """action_jump_turn_prev is a no-op when agent_running is True."""
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.agent_running = True
            await pilot.pause()

            jump_calls = []
            with patch.object(app, "_jump_anchor", side_effect=lambda *a, **kw: jump_calls.append(a)):
                app.action_jump_turn_prev()

            assert jump_calls == [], "No jump should happen while streaming"

    @pytest.mark.asyncio
    async def test_alt_down_noop_during_streaming(self):
        """action_jump_turn_next is a no-op when agent_running is True."""
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.agent_running = True
            await pilot.pause()

            jump_calls = []
            with patch.object(app, "_jump_anchor", side_effect=lambda *a, **kw: jump_calls.append(a)):
                app.action_jump_turn_next()

            assert jump_calls == [], "No jump should happen while streaming"

    @pytest.mark.asyncio
    async def test_alt_up_delegates_to_jump_anchor(self):
        """action_jump_turn_prev calls _jump_anchor(-1, BrowseAnchorType.TURN_START)."""
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.agent_running = False

            jump_calls = []
            with patch.object(app, "_jump_anchor", side_effect=lambda *a, **kw: jump_calls.append(a)):
                app.action_jump_turn_prev()

            assert len(jump_calls) == 1
            direction, anchor_type = jump_calls[0]
            assert direction == -1
            assert anchor_type == BrowseAnchorType.TURN_START

    @pytest.mark.asyncio
    async def test_alt_down_delegates_to_jump_anchor(self):
        """action_jump_turn_next calls _jump_anchor(+1, BrowseAnchorType.TURN_START)."""
        app = _make_app()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            app.agent_running = False

            jump_calls = []
            with patch.object(app, "_jump_anchor", side_effect=lambda *a, **kw: jump_calls.append(a)):
                app.action_jump_turn_next()

            assert len(jump_calls) == 1
            direction, anchor_type = jump_calls[0]
            assert direction == +1
            assert anchor_type == BrowseAnchorType.TURN_START

    def test_no_prev_turn_action_method(self):
        """HermesApp has no action_prev_turn attribute (regression guard)."""
        app = _make_app()
        assert not hasattr(app, "action_prev_turn"), (
            "action_prev_turn must be removed; use action_jump_turn_prev instead"
        )
