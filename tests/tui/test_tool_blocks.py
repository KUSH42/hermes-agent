"""Tests for ToolBlock widgets and browse mode.

Steps covered:
  1 — ToolBlock widgets (4 tests)
  3 — mount_tool_block (2 tests)
  4 — cli.py _on_tool_complete refactor (2 tests)
  5 — browse reactives (3 tests)
  6 — browse keybindings (6 tests)
  7 — StatusBar browse layout (4 tests)
  8 — Integration (3 tests)
  9 — Click-to-toggle (7 tests, SPEC-D)
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from agent.display import capture_local_edit_snapshot
from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.tool_blocks import COLLAPSE_THRESHOLD, ToolBlock, ToolBodyContainer, ToolHeader
from hermes_cli.tui.widgets import CopyableRichLog


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.agent = None
    return HermesApp(cli=cli)


def _make_block(n_lines: int, label: str = "diff") -> ToolBlock:
    lines = [f"line {i}" for i in range(n_lines)]
    plain = [f"plain {i}" for i in range(n_lines)]
    return ToolBlock(label, lines, plain)


# ---------------------------------------------------------------------------
# Step 1 — ToolBlock widget unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_expand_small_block():
    """Blocks with ≤ COLLAPSE_THRESHOLD lines are auto-expanded, no affordances."""
    block = _make_block(COLLAPSE_THRESHOLD)
    assert block._header.collapsed is False
    assert block._header._has_affordances is False


@pytest.mark.asyncio
async def test_collapse_default_large_block():
    """Blocks with > COLLAPSE_THRESHOLD lines start collapsed with affordances."""
    block = _make_block(COLLAPSE_THRESHOLD + 1)
    assert block._header.collapsed is True
    assert block._header._has_affordances is True


@pytest.mark.asyncio
async def test_toggle_adds_removes_expanded_class():
    """toggle() adds 'expanded' class to body on open, removes on close."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        plain = [f"P{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        block = app.query_one(ToolBlock)
        assert not block._body.has_class("expanded")

        block.toggle()
        await pilot.pause()
        assert block._body.has_class("expanded")

        block.toggle()
        await pilot.pause()
        assert not block._body.has_class("expanded")


@pytest.mark.asyncio
async def test_copy_content_returns_plain_text():
    """copy_content() returns plain lines joined by newlines."""
    plain = ["first line", "second line", "third line", "fourth line"]
    lines = ["  ┊ " + p for p in plain]
    block = ToolBlock("diff", lines, plain)
    assert block.copy_content() == "first line\nsecond line\nthird line\nfourth line"


@pytest.mark.asyncio
async def test_diff_block_header_shows_add_delete_counts():
    """Diff blocks show +N / -N header counts instead of raw rendered-line total."""
    lines = [
        "review diff",
        "@@ -1,2 +1,2 @@",
        "   1 - old",
        "   1 + new",
        "   2 + newer",
    ]
    block = ToolBlock("diff", lines, lines)
    rendered = str(block._header.render())
    assert "+2" in rendered
    assert "-1" in rendered
    assert "5L" not in rendered


@pytest.mark.asyncio
async def test_diff_block_body_has_trailing_blank_line():
    """Expanded diff body ends with a blank separator line for visual spacing."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [
            "review diff",
            "@@ -1,1 +1,1 @@",
            "   1 - old",
            "   1 + new",
        ]
        app.mount_tool_block("diff", lines, lines)
        await pilot.pause()

        block = app.query_one(ToolBlock)
        block.toggle()
        await pilot.pause()

        log = block._body.query_one(CopyableRichLog)
        assert len(log.lines) == len(lines) + 1
        assert "".join(segment.text for segment in log.lines[-1]) == ""


@pytest.mark.asyncio
async def test_toggle_is_noop_on_small_block():
    """toggle() is a no-op for blocks with ≤ COLLAPSE_THRESHOLD lines."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(COLLAPSE_THRESHOLD)]
        plain = [f"P{i}" for i in range(COLLAPSE_THRESHOLD)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        block = app.query_one(ToolBlock)
        # Small block auto-expands — body is expanded, no affordances
        assert block._body.has_class("expanded")
        assert not block._header._has_affordances

        # toggle() should be a no-op
        block.toggle()
        await pilot.pause()
        assert block._body.has_class("expanded")  # still expanded


# ---------------------------------------------------------------------------
# Step 3 — mount_tool_block
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mount_tool_block_appears_in_dom():
    """mount_tool_block() mounts a ToolBlock with the correct label."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"line {i}" for i in range(5)]
        plain = [f"plain {i}" for i in range(5)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        blocks = list(app.query(ToolBlock))
        assert len(blocks) == 1
        assert blocks[0]._label == "diff"
        assert blocks[0]._header._line_count == 5


@pytest.mark.asyncio
async def test_mount_tool_block_resolves_header_icon_from_tool_name():
    """ToolBlock header resolves icon from originating tool name."""
    app = _make_app()
    with patch("agent.display.get_tool_icon", return_value="X"):
        async with app.run_test(size=(80, 24)) as pilot:
            lines = [f"line {i}" for i in range(5)]
            plain = [f"plain {i}" for i in range(5)]
            app.mount_tool_block("diff", lines, plain, tool_name="write_file")
            await pilot.pause()

            block = app.query_one(ToolBlock)
            assert block._header._tool_icon == "X"
            assert "X" in str(block._header.render())


@pytest.mark.asyncio
async def test_mount_tool_block_empty_lines_no_mount():
    """mount_tool_block() with empty lines list does not mount any ToolBlock."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.mount_tool_block("diff", [], [])
        await pilot.pause()

        assert list(app.query(ToolBlock)) == []


@pytest.mark.asyncio
async def test_open_streaming_tool_block_resolves_header_icon_from_tool_name():
    """Streaming tool headers resolve icon from tool name."""
    app = _make_app()
    with patch("agent.display.get_tool_icon", return_value="T"):
        async with app.run_test(size=(80, 24)) as pilot:
            app.open_streaming_tool_block("tool-1", "bash -lc ls", "terminal")
            await pilot.pause()

            block = app.query_one(ToolBlock)
            assert block._header._tool_icon == "T"


# ---------------------------------------------------------------------------
# Step 4 — cli.py _on_tool_complete refactor
# ---------------------------------------------------------------------------

def _make_cli_obj():
    """Minimal HermesCLI instance via __new__ — no real __init__ overhead."""
    from cli import HermesCLI
    cli_obj = HermesCLI.__new__(HermesCLI)
    cli_obj.tool_progress_mode = "normal"
    cli_obj._code_highlight_enabled = False
    cli_obj._pending_edit_snapshots = {}
    cli_obj._active_stream_tool_ids = set()
    cli_obj._stream_start_times = {}
    cli_obj._stream_callback_tokens = {}
    cli_obj._pending_gen_queue = []
    return cli_obj


def test_on_tool_complete_tui_calls_mount_tool_block():
    """When TUI is active, _on_tool_complete calls mount_tool_block (not _cprint) for diffs."""
    import cli as cli_module

    mock_tui = MagicMock()
    cli_obj = _make_cli_obj()

    fake_lines = ["  ┊ -old", "  ┊ +new"]

    def fake_render(diff, *, print_fn=None, prefix=""):
        if print_fn:
            for line in fake_lines:
                print_fn(line)
        return True

    with patch.object(cli_module, "_hermes_app", mock_tui), \
         patch("agent.display.extract_edit_diff", return_value="rawdiff"), \
         patch("agent.display.render_captured_diff_preview", side_effect=fake_render), \
         patch("hermes_cli.tui.widgets._strip_ansi", side_effect=lambda x: x):
        cli_obj._on_tool_complete("id1", "write_file", {}, '{"success": true}')

    # First call_from_thread is mount_tool_block
    assert mock_tui.call_from_thread.call_count >= 1
    first_call = mock_tui.call_from_thread.call_args_list[0]
    assert first_call[0][0] == mock_tui.mount_tool_block
    assert first_call[0][1] == "diff"
    assert first_call[0][2] == fake_lines


def test_on_tool_complete_pt_mode_calls_cprint():
    """When TUI is absent (_hermes_app=None), _cprint is called per line."""
    import cli as cli_module

    cli_obj = _make_cli_obj()

    printed: list[str] = []
    fake_lines = ["  ┊ -old", "  ┊ +new"]

    def fake_render(tool_name, result, *, function_args=None, snapshot=None, print_fn=None, prefix=""):
        if print_fn:
            for line in fake_lines:
                print_fn(line)
        return True

    with patch.object(cli_module, "_hermes_app", None), \
         patch.object(cli_module, "_cprint", side_effect=printed.append), \
         patch("agent.display.render_edit_diff_with_delta", side_effect=fake_render):
        cli_obj._on_tool_complete("id2", "write_file", {}, '{"success": true}')

    assert printed == fake_lines


def test_on_tool_complete_execute_code_tui_passes_rerender_callback():
    """execute_code previews mounted in the TUI should carry a rerender callback."""
    import cli as cli_module

    mock_tui = MagicMock()
    cli_obj = _make_cli_obj()
    cli_obj.tool_progress_mode = "verbose"
    cli_obj._code_highlight_enabled = True

    with patch.object(cli_module, "_hermes_app", mock_tui):
        cli_obj._on_tool_complete(
            "id3",
            "execute_code",
            {"code": "print('hello')"},
            '{"success": true}',
        )

    mount_calls = [
        call for call in mock_tui.call_from_thread.call_args_list
        if call[0] and call[0][0] == mock_tui.mount_tool_block
    ]
    assert mount_calls, "Expected mount_tool_block call for execute_code preview"
    args = mount_calls[0][0]
    assert args[1] == "code"
    assert callable(args[4])


def test_on_tool_complete_diff_tui_passes_rerender_callback():
    """Diff previews mounted in the TUI should carry a rerender callback."""
    import cli as cli_module

    mock_tui = MagicMock()
    cli_obj = _make_cli_obj()

    fake_lines = ["  ┊ -old", "  ┊ +new"]

    def fake_render(diff, *, print_fn=None, prefix=""):
        if print_fn:
            for line in fake_lines:
                print_fn(line)
        return True

    with patch.object(cli_module, "_hermes_app", mock_tui), \
         patch("agent.display.extract_edit_diff", return_value="rawdiff"), \
         patch("agent.display.render_captured_diff_preview", side_effect=fake_render), \
         patch("hermes_cli.tui.widgets._strip_ansi", side_effect=lambda x: x):
        cli_obj._on_tool_complete("id-diff", "write_file", {}, '{"success": true}')

    mount_calls = [
        call for call in mock_tui.call_from_thread.call_args_list
        if call[0] and call[0][0] == mock_tui.mount_tool_block
    ]
    assert mount_calls
    args = mount_calls[0][0]
    assert args[1] == "diff"
    assert callable(args[4])


def test_on_tool_complete_patch_mode_tui_mounts_diff_from_snapshot(tmp_path):
    """V4A patch previews mount a diff ToolBlock even when tool result omits diff text."""
    import cli as cli_module

    mock_tui = MagicMock()
    cli_obj = _make_cli_obj()
    target = tmp_path / "note.txt"
    target.write_text("old\n", encoding="utf-8")
    function_args = {
        "mode": "patch",
        "patch": f"*** Begin Patch\n*** Update File: {target}\n@@\n-old\n+new\n*** End Patch\n",
    }
    cli_obj._pending_edit_snapshots["id-patch"] = capture_local_edit_snapshot("patch", function_args)
    target.write_text("new\n", encoding="utf-8")

    with patch.object(cli_module, "_hermes_app", mock_tui), \
         patch("hermes_cli.tui.widgets._strip_ansi", side_effect=lambda x: x):
        cli_obj._on_tool_complete("id-patch", "patch", function_args, '{"success": true}')

    mount_calls = [
        call for call in mock_tui.call_from_thread.call_args_list
        if call[0] and call[0][0] == mock_tui.mount_tool_block
    ]
    assert mount_calls, "Expected mount_tool_block call for V4A patch diff preview"
    args = mount_calls[0][0]
    assert args[1] == "diff"
    assert any("old" in line for line in args[3])
    assert any("new" in line for line in args[3])


def test_on_tool_complete_read_file_tui_passes_rerender_callback():
    """read_file previews mounted in the TUI should carry a rerender callback."""
    import cli as cli_module

    mock_tui = MagicMock()
    cli_obj = _make_cli_obj()
    cli_obj.tool_progress_mode = "verbose"
    cli_obj._code_highlight_enabled = True

    result = '{"content": "def hello():\\n    return 1\\n"}'

    with patch.object(cli_module, "_hermes_app", mock_tui):
        cli_obj._on_tool_complete(
            "id-read",
            "read_file",
            {"path": "hello.py"},
            result,
        )

    mount_calls = [
        call for call in mock_tui.call_from_thread.call_args_list
        if call[0] and call[0][0] == mock_tui.mount_tool_block
    ]
    assert mount_calls
    args = mount_calls[0][0]
    assert args[1] == "code"
    assert callable(args[4])


def test_on_tool_complete_terminal_preview_tui_passes_rerender_callback():
    """terminal file previews mounted in the TUI should carry a rerender callback."""
    import cli as cli_module

    mock_tui = MagicMock()
    cli_obj = _make_cli_obj()
    cli_obj.tool_progress_mode = "verbose"
    cli_obj._code_highlight_enabled = True

    result = '{"output": "def hello():\\n    return 1\\n"}'

    with patch.object(cli_module, "_hermes_app", mock_tui):
        cli_obj._on_tool_complete(
            "id-terminal",
            "terminal",
            {"command": "cat hello.py"},
            result,
        )

    mount_calls = [
        call for call in mock_tui.call_from_thread.call_args_list
        if call[0] and call[0][0] == mock_tui.mount_tool_block
    ]
    assert mount_calls
    args = mount_calls[0][0]
    assert args[1] == "output"
    assert callable(args[4])


# ---------------------------------------------------------------------------
# Step 5 — browse reactives
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_browse_mode_stays_false_with_no_headers():
    """Entering browse mode with no ToolHeaders is a no-op — browse_mode stays False."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert list(app.query(ToolHeader)) == []
        app.browse_mode = True
        await pilot.pause()
        assert app.browse_mode is False


@pytest.mark.asyncio
async def test_enter_browse_sets_focused_on_index0():
    """Entering browse mode sets .focused on the first ToolHeader."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        # Mount a large block so there is something to browse
        lines = [f"L{i}" for i in range(5)]
        plain = [f"P{i}" for i in range(5)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        app.browse_mode = True
        await pilot.pause()

        headers = list(app.query(ToolHeader))
        assert headers[0].has_class("focused")


@pytest.mark.asyncio
async def test_browse_index_change_moves_focus():
    """Changing browse_index moves the .focused class to the correct header."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(3):
            lines = [f"L{i}" for i in range(5)]
            plain = [f"P{i}" for i in range(5)]
            app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        app.browse_mode = True
        await pilot.pause()

        headers = list(app.query(ToolHeader))
        assert headers[0].has_class("focused")
        assert not headers[1].has_class("focused")

        app.browse_index = 1
        await pilot.pause()

        assert not headers[0].has_class("focused")
        assert headers[1].has_class("focused")


# ---------------------------------------------------------------------------
# Step 6 — browse keybindings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_browse_tab_cycles_forward():
    """Tab key increments browse_index, wrapping at the end."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(3):
            lines = [f"L{i}" for i in range(5)]
            plain = [f"P{i}" for i in range(5)]
            app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        app.browse_mode = True
        app.browse_index = 0
        await pilot.pause()

        await pilot.press("tab")
        await pilot.pause()
        assert app.browse_index == 1

        await pilot.press("tab")
        await pilot.pause()
        assert app.browse_index == 2

        # Wrap around
        await pilot.press("tab")
        await pilot.pause()
        assert app.browse_index == 0


@pytest.mark.asyncio
async def test_browse_shift_tab_cycles_backward():
    """Shift+Tab decrements browse_index, wrapping at the start."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(3):
            lines = [f"L{i}" for i in range(5)]
            plain = [f"P{i}" for i in range(5)]
            app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        app.browse_mode = True
        app.browse_index = 0
        await pilot.pause()

        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.browse_index == 2


@pytest.mark.asyncio
async def test_browse_enter_toggles_block():
    """Enter key in browse mode calls toggle() on the focused block."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(5)]
        plain = [f"P{i}" for i in range(5)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        app.browse_mode = True
        app.browse_index = 0
        await pilot.pause()

        block = app.query_one(ToolBlock)
        assert not block._body.has_class("expanded")

        await pilot.press("enter")
        await pilot.pause()
        assert block._body.has_class("expanded")


@pytest.mark.asyncio
async def test_browse_c_triggers_flash_copy():
    """c key in browse mode calls flash_copy() on the focused header."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(5)]
        plain = [f"P{i}" for i in range(5)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        app.browse_mode = True
        app.browse_index = 0
        await pilot.pause()

        header = app.query_one(ToolHeader)
        assert not header._copy_flash

        await pilot.press("c")
        await pilot.pause()
        assert header._copy_flash


@pytest.mark.asyncio
async def test_browse_escape_exits():
    """Escape key exits browse mode and clears .focused classes."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(5)]
        plain = [f"P{i}" for i in range(5)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        app.browse_mode = True
        await pilot.pause()
        assert app.browse_mode is True

        await pilot.press("escape")
        await pilot.pause()
        assert app.browse_mode is False
        header = app.query_one(ToolHeader)
        assert not header.has_class("focused")


@pytest.mark.asyncio
async def test_browse_a_expands_all():
    """'a' key in browse mode expands all blocks that have affordances."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(3):
            lines = [f"L{i}" for i in range(5)]
            plain = [f"P{i}" for i in range(5)]
            app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        app.browse_mode = True
        await pilot.pause()

        blocks = list(app.query(ToolBlock))
        assert all(not b._body.has_class("expanded") for b in blocks)

        await pilot.press("a")
        await pilot.pause()
        assert all(b._body.has_class("expanded") for b in blocks)
        assert app.browse_mode is True  # stays in browse mode


@pytest.mark.asyncio
async def test_browse_A_collapses_all():
    """'A' (shift+a) key in browse mode collapses all expanded blocks."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(3):
            lines = [f"L{i}" for i in range(5)]
            plain = [f"P{i}" for i in range(5)]
            app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        app.browse_mode = True
        await pilot.pause()

        # First expand all
        blocks = list(app.query(ToolBlock))
        for b in blocks:
            b.toggle()
        await pilot.pause()
        assert all(b._body.has_class("expanded") for b in blocks)

        await pilot.press("A")
        await pilot.pause()
        assert all(not b._body.has_class("expanded") for b in blocks)
        assert app.browse_mode is True  # stays in browse mode


@pytest.mark.asyncio
async def test_browse_uses_increments_on_entry():
    """_browse_uses increments each time browse mode is entered."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(5)]
        plain = [f"P{i}" for i in range(5)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        assert app._browse_uses == 0
        app.browse_mode = True
        await pilot.pause()
        assert app._browse_uses == 1

        app.browse_mode = False
        await pilot.pause()
        app.browse_mode = True
        await pilot.pause()
        assert app._browse_uses == 2


@pytest.mark.asyncio
async def test_browse_printable_key_exits_and_inserts():
    """A printable key (not a/A/c/enter) in browse mode exits browse mode."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(5)]
        plain = [f"P{i}" for i in range(5)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        app.browse_mode = True
        await pilot.pause()
        assert app.browse_mode is True

        await pilot.press("q")
        await pilot.pause()
        assert app.browse_mode is False


# ---------------------------------------------------------------------------
# Step 7 — StatusBar browse layout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_statusbar_browse_full_width():
    """StatusBar at ≥60 width shows full browse hint."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(5)]
        plain = [f"P{i}" for i in range(5)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        app.browse_mode = True
        app.browse_index = 0
        await pilot.pause()

        from hermes_cli.tui.widgets import StatusBar
        bar = app.query_one(StatusBar)
        rendered = bar.render()
        plain_text = rendered.plain
        assert "BROWSE" in plain_text
        assert "1/1" in plain_text
        assert "Tab" in plain_text
        assert "Enter" in plain_text
        assert "expand-all" in plain_text
        assert "Esc exit" in plain_text


@pytest.mark.asyncio
async def test_statusbar_browse_compact_width():
    """StatusBar at 40–59 width shows compact browse hint."""
    app = _make_app()
    async with app.run_test(size=(50, 24)) as pilot:
        lines = [f"L{i}" for i in range(5)]
        plain = [f"P{i}" for i in range(5)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        app.browse_mode = True
        app.browse_index = 0
        await pilot.pause()

        from hermes_cli.tui.widgets import StatusBar
        bar = app.query_one(StatusBar)
        rendered = bar.render()
        plain_text = rendered.plain
        assert "BROWSE" in plain_text
        assert "Tab" in plain_text
        # Full hint should not appear at compact width
        assert "Enter" not in plain_text


@pytest.mark.asyncio
async def test_statusbar_browse_minimal_width():
    """StatusBar at <40 width shows minimal browse (index only)."""
    app = _make_app()
    async with app.run_test(size=(30, 24)) as pilot:
        lines = [f"L{i}" for i in range(5)]
        plain = [f"P{i}" for i in range(5)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        app.browse_mode = True
        app.browse_index = 0
        await pilot.pause()

        from hermes_cli.tui.widgets import StatusBar
        bar = app.query_one(StatusBar)
        rendered = bar.render()
        plain_text = rendered.plain
        assert "BROWSE" in plain_text
        assert "Tab" not in plain_text


@pytest.mark.asyncio
async def test_statusbar_normal_mode_when_not_browsing():
    """StatusBar shows normal layout when browse_mode is False."""
    app = _make_app()
    app.status_model = "claude-test"
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.browse_mode is False

        from hermes_cli.tui.widgets import StatusBar
        bar = app.query_one(StatusBar)
        rendered = bar.render()
        plain_text = rendered.plain
        assert "BROWSE" not in plain_text
        assert "claude-test" in plain_text


# ---------------------------------------------------------------------------
# Step 8 — Integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_integration_tab_cycles_three_blocks():
    """Mount 3 blocks, enter browse, Tab through all 3, verify index cycles."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(3):
            lines = [f"L{i}" for i in range(5)]
            plain = [f"P{i}" for i in range(5)]
            app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        app.browse_mode = True
        app.browse_index = 0
        await pilot.pause()

        headers = list(app.query(ToolHeader))
        assert len(headers) == 3
        assert headers[0].has_class("focused")

        await pilot.press("tab")
        await pilot.pause()
        assert app.browse_index == 1
        assert headers[1].has_class("focused")

        await pilot.press("tab")
        await pilot.pause()
        assert app.browse_index == 2
        assert headers[2].has_class("focused")

        # Wrap around
        await pilot.press("tab")
        await pilot.pause()
        assert app.browse_index == 0
        assert headers[0].has_class("focused")


@pytest.mark.asyncio
async def test_integration_enter_expand_c_flash():
    """Enter expands focused block; c triggers flash_copy on focused header."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(5)]
        plain = [f"P{i}" for i in range(5)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        app.browse_mode = True
        app.browse_index = 0
        await pilot.pause()

        block = app.query_one(ToolBlock)
        header = app.query_one(ToolHeader)

        assert not block._body.has_class("expanded")
        await pilot.press("enter")
        await pilot.pause()
        assert block._body.has_class("expanded")

        assert not header._copy_flash
        await pilot.press("c")
        await pilot.pause()
        assert header._copy_flash


@pytest.mark.asyncio
async def test_integration_exit_clears_all_focused():
    """Exiting browse mode clears .focused on all ToolHeaders."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        for _ in range(2):
            lines = [f"L{i}" for i in range(5)]
            plain = [f"P{i}" for i in range(5)]
            app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        app.browse_mode = True
        await pilot.pause()

        headers = list(app.query(ToolHeader))
        assert any(h.has_class("focused") for h in headers)

        app.browse_mode = False
        await pilot.pause()

        assert not any(h.has_class("focused") for h in headers)


# ---------------------------------------------------------------------------
# Step 9 — Click-to-toggle (SPEC-D)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_click_left_toggles_expanded():
    """Left-click on ToolHeader with affordances toggles block from collapsed to expanded."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        plain = [f"P{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        block = app.query_one(ToolBlock)
        assert block._header.collapsed is True
        assert not block._body.has_class("expanded")

        await pilot.click(block._header)
        await pilot.pause()

        assert block._header.collapsed is False
        assert block._body.has_class("expanded")


@pytest.mark.asyncio
async def test_click_left_toggles_back_to_collapsed():
    """Second left-click on ToolHeader toggles block back to collapsed."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        plain = [f"P{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        block = app.query_one(ToolBlock)
        # First click — expand
        await pilot.click(block._header)
        await pilot.pause()
        assert block._header.collapsed is False

        # Second click — collapse
        await pilot.click(block._header)
        await pilot.pause()
        assert block._header.collapsed is True
        assert not block._body.has_class("expanded")


@pytest.mark.asyncio
async def test_click_while_streaming_is_ignored():
    """Left-click while streaming (_spinner_char is not None) leaves block unchanged."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        plain = [f"P{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        block = app.query_one(ToolBlock)
        header = block._header
        # Simulate streaming state
        header._spinner_char = "◐"
        original_collapsed = header.collapsed

        await pilot.click(header)
        await pilot.pause()

        assert header.collapsed == original_collapsed


@pytest.mark.asyncio
async def test_click_no_affordances_is_ignored():
    """Left-click on no-affordance header (_has_affordances=False) leaves block unchanged."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        # Small block: ≤ COLLAPSE_THRESHOLD lines — no affordances
        lines = [f"L{i}" for i in range(COLLAPSE_THRESHOLD)]
        plain = [f"P{i}" for i in range(COLLAPSE_THRESHOLD)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        block = app.query_one(ToolBlock)
        header = block._header
        assert header._has_affordances is False
        assert header.collapsed is False  # auto-expanded

        await pilot.click(header)
        await pilot.pause()

        # Should remain expanded — click was a no-op
        assert header.collapsed is False
        assert block._body.has_class("expanded")


@pytest.mark.asyncio
async def test_right_click_does_not_toggle():
    """Right-click on ToolHeader does not toggle the block (bubbles to HermesApp)."""
    from unittest.mock import patch as _patch
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        plain = [f"P{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        block = app.query_one(ToolBlock)
        header = block._header
        original_collapsed = header.collapsed

        await pilot.click(header, button=3)
        await pilot.pause()

        assert header.collapsed == original_collapsed


@pytest.mark.asyncio
async def test_click_calls_toggle_exactly_once():
    """Left-click on ToolHeader calls parent.toggle() exactly once."""
    from unittest.mock import patch as _patch
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        plain = [f"P{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        block = app.query_one(ToolBlock)
        toggle_calls = []
        original_toggle = block.toggle

        def mock_toggle():
            toggle_calls.append(1)
            original_toggle()

        with _patch.object(block, "toggle", side_effect=mock_toggle):
            await pilot.click(block._header)
            await pilot.pause()

        assert len(toggle_calls) == 1


def test_toolheader_hover_css_rule_present():
    """ToolHeader:hover CSS rule with background accent is present in hermes.tcss."""
    import os
    tcss_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "hermes_cli", "tui", "hermes.tcss"
    )
    with open(os.path.abspath(tcss_path)) as f:
        content = f.read()
    assert "ToolHeader:hover" in content
    assert "background: $accent 8%" in content
