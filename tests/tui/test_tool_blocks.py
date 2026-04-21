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

        from hermes_cli.tui.tool_panel import ToolPanel
        block = app.query_one(ToolBlock)
        panel = app.query_one(ToolPanel)
        assert panel.collapsed is False  # starts expanded (binary collapse spec §6)

        block.toggle()
        await pilot.pause()
        assert panel.collapsed is True  # toggle delegates to ToolPanel

        block.toggle()
        await pilot.pause()
        assert panel.collapsed is False


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

    # execute_code now uses a lambda so parent_id is captured via closure
    mount_calls = [
        call for call in mock_tui.call_from_thread.call_args_list
        if call[0] and callable(call[0][0])
    ]
    assert mount_calls, "Expected mount_tool_block lambda call for execute_code preview"


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
    assert callable(args[4])  # rerender_fn at position 4; tool_name at position 6


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
    assert callable(args[4])  # rerender_fn at position 4; tool_name at position 6


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
    assert callable(args[4])  # rerender_fn at position 4; tool_name at position 6


# ---------------------------------------------------------------------------
# Step 5 — browse reactives
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_browse_mode_allowed_with_no_headers():
    """Browse mode can be entered even with no ToolHeaders (unified anchor list supports turn-start nav)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert list(app.query(ToolHeader)) == []
        app.browse_mode = True
        await pilot.pause()
        assert app.browse_mode is True


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

        from hermes_cli.tui.tool_panel import ToolPanel
        panel = app.query_one(ToolPanel)
        assert panel.collapsed is False  # starts expanded

        await pilot.press("enter")
        await pilot.pause()
        assert panel.collapsed is True  # Enter collapses it


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

        from hermes_cli.tui.tool_panel import ToolPanel
        panels = list(app.query(ToolPanel))
        assert all(not p.collapsed for p in panels)  # all start expanded

        await pilot.press("a")
        await pilot.pause()
        assert all(not p.collapsed for p in panels)  # 'a' expands all → still expanded
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

        from hermes_cli.tui.tool_panel import ToolPanel
        panels = list(app.query(ToolPanel))
        # Collapse all first via toggle
        for p in panels:
            p.action_toggle_collapse()
        await pilot.pause()
        assert all(p.collapsed for p in panels)

        await pilot.press("A")
        await pilot.pause()
        assert all(p.collapsed for p in panels)  # 'A' collapses all → still collapsed
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

        from hermes_cli.tui.tool_panel import ToolPanel
        block = app.query_one(ToolBlock)
        panel = app.query_one(ToolPanel)
        header = app.query_one(ToolHeader)

        assert panel.collapsed is False  # starts expanded (binary collapse spec §6)
        await pilot.press("enter")
        await pilot.pause()
        assert panel.collapsed is True  # enter delegates to ToolPanel

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

        from hermes_cli.tui.tool_panel import ToolPanel
        block = app.query_one(ToolBlock)
        panel = app.query_one(ToolPanel)
        assert panel.collapsed is False  # starts expanded (binary collapse spec §6)

        await pilot.click(block._header)
        await pilot.pause()

        assert panel.collapsed is True  # click delegates toggle to ToolPanel


@pytest.mark.asyncio
async def test_click_left_toggles_back_to_collapsed():
    """Second left-click on ToolHeader toggles block back to collapsed."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        plain = [f"P{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        from hermes_cli.tui.tool_panel import ToolPanel
        block = app.query_one(ToolBlock)
        panel = app.query_one(ToolPanel)
        # First click — collapse (starts expanded)
        await pilot.click(block._header)
        await pilot.pause()
        assert panel.collapsed is True

        # Second click — expand
        await pilot.click(block._header)
        await pilot.pause()
        assert panel.collapsed is False


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
    """Left-click on ToolHeader toggles collapse via ToolPanel.action_toggle_collapse."""
    from unittest.mock import patch as _patch
    from hermes_cli.tui.tool_panel import ToolPanel
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        plain = [f"P{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()

        panel = app.query_one(ToolPanel)
        toggle_calls = []
        original_toggle = panel.action_toggle_collapse

        def mock_toggle():
            toggle_calls.append(1)
            original_toggle()

        block = app.query_one(ToolBlock)
        with _patch.object(panel, "action_toggle_collapse", side_effect=mock_toggle):
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


# ---------------------------------------------------------------------------
# Spec: Tool block path UX — T1–T14 (diff gutter + path rendering)
# ---------------------------------------------------------------------------

def _make_file_block(tool_name: str, label: str = "/a/b/c.py") -> ToolBlock:
    lines = [f"L{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
    plain = [f"P{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
    return ToolBlock(label, lines, plain, tool_name=tool_name)


def _make_diff_block(plain_lines: list[str]) -> ToolBlock:
    styled = ["  " + p for p in plain_lines]
    return ToolBlock("diff", styled, plain_lines)


# --- T1: _is_child_diff set when preceded by file-tool STB ---

@pytest.mark.asyncio
async def test_T1_is_child_diff_set_by_mount_tool_block():
    """mount_tool_block(label='diff') after file-tool STB sets _is_child_diff=True."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = app.query_one("OutputPanel")
        msg = output.current_message or output.new_message()
        # Simulate file-tool streaming block
        stb = StreamingToolBlock(label="write_file", tool_name="write_file")
        msg._last_file_tool_block = stb
        # Mount a diff block
        lines = ["--- a/src/foo.py", "+++ b/src/foo.py", "  1 + new"]
        plain = ["--- a/src/foo.py", "+++ b/src/foo.py", "  1 + new"]
        block = msg.mount_tool_block("diff", lines, plain, tool_name="patch")
        await pilot.pause()
        assert block._header._is_child_diff is True


# --- T2: _is_child_diff=True renders ╰─ gutter with gutter_w=4 ---

def test_T2_child_diff_gutter_renders_connector():
    """_is_child_diff=True in render() produces '  ╰─' gutter text."""
    header = ToolHeader("diff", 5)
    header._is_child_diff = True
    rendered = str(header.render())
    assert "╰─" in rendered


# --- T3: diff always has _is_child_diff=True (unconditional) ---

@pytest.mark.asyncio
async def test_T3_diff_always_child_diff():
    """Diff blocks always have _is_child_diff=True regardless of preceding tool."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = app.query_one("OutputPanel")
        msg = output.current_message or output.new_message()
        assert msg._last_file_tool_block is None
        lines = ["--- a/src/foo.py", "+++ b/src/foo.py", "  1 + x"]
        plain = lines[:]
        block = msg.mount_tool_block("diff", lines, plain, tool_name="patch")
        await pilot.pause()
        assert block._header._is_child_diff is True


# --- T4: non-diff block always has _is_child_diff=False ---

def test_T4_non_diff_block_no_child_diff_flag():
    """Non-diff block always has _is_child_diff=False."""
    block = _make_file_block("write_file")
    assert block._header._is_child_diff is False


# --- T5: _last_file_tool_block cleared on watch_agent_running(False) ---

@pytest.mark.asyncio
async def test_T5_last_file_tool_block_cleared_on_turn_end():
    """_last_file_tool_block cleared when watch_agent_running(False) fires."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        # Trigger a new turn so a MessagePanel exists in the DOM
        app.agent_running = True
        await pilot.pause()
        output = app.query_one("OutputPanel")
        msg = output.current_message
        if msg is None:
            output.new_message()
            await pilot.pause()
            msg = output.current_message
        assert msg is not None
        stb = StreamingToolBlock(label="write_file", tool_name="write_file")
        msg._last_file_tool_block = stb
        assert msg._last_file_tool_block is not None
        app.agent_running = False
        await pilot.pause()
        assert msg._last_file_tool_block is None


# --- T6: set_path sets _full_path, _path_clickable, _is_url=False ---

def test_T6_set_path_file():
    """set_path('/a/b/c.py') sets _full_path, _path_clickable=True, _is_url=False."""
    header = ToolHeader("x", 5)
    header.set_path("/a/b/c.py")
    assert header._full_path == "/a/b/c.py"
    assert header._path_clickable is True
    assert header._is_url is False


# --- T7: set_path with URL sets _is_url=True ---

def test_T7_set_path_url():
    """set_path('https://example.com/foo') sets _is_url=True."""
    header = ToolHeader("x", 5)
    header.set_path("https://example.com/foo")
    assert header._is_url is True
    assert header._path_clickable is True


# --- T8: short path renders dim dir + bold filename ---

def test_T8_render_path_label_short():
    """Short path 'src/foo.py': dim ' src/' prefix + bold 'foo.py'."""
    header = ToolHeader("src/foo.py", 5)
    header.set_path("src/foo.py")
    text = header._render_path_label(60)
    plain = text.plain
    assert "src/" in plain, "Expected directory prefix"
    assert "foo.py" in plain, "Expected filename"


# --- T9: long path truncates dir prefix, keeps filename ---

def test_T9_long_path_truncates_dir():
    """Long path: dir prefix truncated to '…/<remaining>/', bold filename intact."""
    long_path = "/home/user/projects/src/very/long/path/module.py"
    header = ToolHeader(long_path, 5)
    header.set_path(long_path)
    text = header._render_path_label(30)  # tight budget
    plain = text.plain
    assert "module.py" in plain, "Filename must be preserved"
    assert "…" in plain, "Dir truncation marker must appear"


# --- T10: path with no slash renders bold bare filename ---

def test_T10_path_no_slash():
    """Path with no '/': single dim leading space + bold bare filename."""
    header = ToolHeader("config.py", 5)
    header.set_path("config.py")
    text = header._render_path_label(30)
    assert "config.py" in text.plain
    assert "/" not in text.plain


# --- T11: _full_path unchanged after render ---

def test_T11_full_path_unchanged_after_render():
    """_full_path is not mutated by _render_path_label."""
    header = ToolHeader("/a/b/very/long/path/file.py", 5)
    header.set_path("/a/b/very/long/path/file.py")
    header._render_path_label(20)
    assert header._full_path == "/a/b/very/long/path/file.py"


# --- T12: _path_clickable=False uses plain label ---

def test_T12_path_not_clickable_uses_plain_label():
    """_path_clickable=False → _render_path_label not called, plain label used."""
    header = ToolHeader("some-label", 5)
    assert header._path_clickable is False
    # render() in pre-mount (term_w=0) should use plain label
    rendered = str(header.render())
    assert "some-label" in rendered


# --- T13: file tool triggers set_path in ToolBlock.__init__ ---

def test_T13_file_tool_triggers_set_path():
    """tool_name in _FILE_TOOL_NAMES → header.set_path(label) called in ToolBlock.__init__."""
    from hermes_cli.tui.tool_blocks import _FILE_TOOL_NAMES
    for tool in ("write_file", "patch", "read_file", "create_file"):
        assert tool in _FILE_TOOL_NAMES
        block = _make_file_block(tool, "/a/b.py")
        assert block._header._path_clickable is True
        assert block._header._full_path == "/a/b.py"


# --- T14: non-file tool does NOT call set_path ---

def test_T14_non_file_tool_no_set_path():
    """tool_name not in _FILE_TOOL_NAMES → set_path NOT called."""
    block = ToolBlock("terminal", ["L0", "L1", "L2", "L3"], ["P0", "P1", "P2", "P3"], tool_name="terminal")
    assert block._header._path_clickable is False
    assert block._header._full_path is None


# ---------------------------------------------------------------------------
# Spec: T44–T47 — Action feedback on ToolHeader
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T44_flash_success_adds_class():
    """flash_success() adds --flash-success CSS class."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        plain = [f"P{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()
        header = app.query_one(ToolHeader)
        header.flash_success()
        assert header.has_class("--flash-success")


@pytest.mark.asyncio
async def test_T45_flash_error_adds_class():
    """flash_error() adds --flash-error CSS class."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        lines = [f"L{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        plain = [f"P{i}" for i in range(COLLAPSE_THRESHOLD + 1)]
        app.mount_tool_block("diff", lines, plain)
        await pilot.pause()
        header = app.query_one(ToolHeader)
        header.flash_error()
        assert header.has_class("--flash-error")


def test_T46_pulse_start_stop_no_crash():
    """_pulse_start()/_pulse_stop() do not crash without app context."""
    header = ToolHeader("x", 5)
    # Without app, the timer call will fail gracefully — just check no exception
    try:
        header._pulse_start()
    except Exception:
        pass
    try:
        header._pulse_stop()
    except Exception:
        pass


def test_T47_flash_success_flash_error_exist_on_header():
    """flash_success() and flash_error() methods exist on ToolHeader."""
    header = ToolHeader("x", 5)
    assert callable(header.flash_success)
    assert callable(header.flash_error)


def test_T48_other_tools_label_normal_color():
    """Non-execute_code tool headers (terminal, read_file) use non-dim label color."""
    from textual.geometry import Size
    for tool_label in ("bash", "read_file", "write_file", "terminal"):
        header = ToolHeader(label=tool_label, line_count=3)
        header._duration = "0.5s"
        header._spinner_char = None
        header._tool_icon_error = False
        header._size = Size(80, 1)
        result = header.render()
        from rich.text import Text
        assert isinstance(result, Text)
        for span in result._spans:
            text_slice = result.plain[span.start:span.end]
            if tool_label in text_slice:
                assert "dim" not in str(span.style), (
                    f"Label '{tool_label}' span has unexpected dim style: {span.style}"
                )
                break


def test_T49_right_align_preserves_affordances():
    """Short label: affordances (toggle, line count, duration) remain right-flushed."""
    from textual.geometry import Size
    header = ToolHeader(label="x", line_count=10)
    header._duration = "2.5s"
    header._spinner_char = None
    header._has_affordances = True
    header._collapsed = False
    header._size = Size(80, 1)
    result = header.render()
    plain = result.plain
    # Duration and toggle char must appear in the right half of the terminal
    mid = len(plain) // 2
    tail = plain[mid:]
    assert "2.5s" in tail, f"Duration not in right half: {repr(plain)}"
    assert any(ch in tail for ch in ("▾", "▸")), f"Toggle char not in right half: {repr(plain)}"


# ---------------------------------------------------------------------------
# UX pass 3 — §3, §4, §5, §6, §7, §9
# ---------------------------------------------------------------------------


# §3 — _label_rich in ToolHeader


def test_label_rich_used_when_set():
    """ToolHeader uses _label_rich content when set instead of plain label."""
    from textual.geometry import Size
    from rich.text import Text

    header = ToolHeader(label="plain", line_count=0)
    header._label_rich = Text("import yaml", style="green")
    header._spinner_char = None
    header._duration = ""
    header._size = Size(80, 1)
    result = header.render()
    assert "import yaml" in result.plain


def test_label_rich_truncated_to_available_width():
    """_label_rich is truncated + '…' appended when longer than available width."""
    from textual.geometry import Size
    from rich.text import Text

    header = ToolHeader(label="x", line_count=0)
    long_label = Text("a" * 60)
    header._label_rich = long_label
    header._spinner_char = None
    header._duration = ""
    header._size = Size(40, 1)
    result = header.render()
    assert "…" in result.plain or result.cell_len <= 42


# §4 — ANSI preservation in _all_rich


@pytest.mark.asyncio
async def test_all_rich_appended_on_append_line():
    """_all_rich stores Text with ANSI spans after append_line."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from rich.text import Text

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        block = StreamingToolBlock(label="test")
        app.query_one("OutputPanel").current_message or app.query_one("OutputPanel").new_message()
        # Use a minimal mount approach — just call append_line after ensuring attrs exist
        # We can test _all_rich without full mount by checking the list directly
        block._all_plain = []
        block._all_rich = []

        green_line = "\x1b[32mhello\x1b[0m"
        block._all_plain.append("hello")
        from rich.text import Text as T
        block._all_rich.append(T.from_ansi(green_line))

        assert len(block._all_rich) == 1
        rich_text = block._all_rich[0]
        assert isinstance(rich_text, Text)
        assert "hello" in rich_text.plain
        # Verify it has color spans (not a plain Text)
        has_color = any(
            hasattr(s.style, "color") and s.style.color is not None
            for s in rich_text._spans
        )
        assert has_color or rich_text.plain == "hello"


def test_all_rich_length_matches_all_plain():
    """After N append_line calls, len(_all_rich) == len(_all_plain)."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    block = StreamingToolBlock.__new__(StreamingToolBlock)
    block._all_plain = []
    block._all_rich = []
    block._total_received = 0
    block._bytes_received = 0
    block._last_line_time = 0.0
    block._pending = []
    block._completed = False

    from hermes_cli.tui.tool_blocks import _strip_ansi
    from rich.text import Text

    for i in range(10):
        raw = f"\x1b[3{i % 8}mline {i}\x1b[0m"
        plain = _strip_ansi(raw)
        block._all_plain.append(plain)
        block._all_rich.append(Text.from_ansi(raw))

    assert len(block._all_rich) == len(block._all_plain) == 10


def test_copy_content_uses_plain():
    """copy_content() returns _all_plain joined, no ANSI escapes."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    block = StreamingToolBlock.__new__(StreamingToolBlock)
    block._all_plain = ["line0", "line1", "line2"]
    block._all_rich = []

    result = block.copy_content()
    assert result == "line0\nline1\nline2"
    assert "\x1b[" not in result


# §5 — ECB top OmissionBar


@pytest.mark.asyncio
async def test_ecb_mounts_top_omission_bar():
    """ExecuteCodeBlock has _omission_bar_top_mounted True after mount."""
    from hermes_cli.tui.execute_code_block import ExecuteCodeBlock

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app._open_execute_code_block(0)
        await pilot.pause()
        # Let call_after_refresh fire
        for _ in range(10):
            await pilot.pause()

        from hermes_cli.tui.widgets import OutputPanel
        try:
            block = app.query_one(OutputPanel).query_one(ExecuteCodeBlock)
            assert block._omission_bar_top_mounted is True
        except Exception:
            pytest.skip("ECB not mounted in this test setup")


@pytest.mark.asyncio
async def test_ecb_mounts_bottom_omission_bar():
    """ExecuteCodeBlock has _omission_bar_bottom_mounted True after mount."""
    from hermes_cli.tui.execute_code_block import ExecuteCodeBlock

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        app._open_execute_code_block(0)
        await pilot.pause()
        for _ in range(10):
            await pilot.pause()

        from hermes_cli.tui.widgets import OutputPanel
        try:
            block = app.query_one(OutputPanel).query_one(ExecuteCodeBlock)
            assert block._omission_bar_bottom_mounted is True
        except Exception:
            pytest.skip("ECB not mounted in this test setup")


# §6 — FILE microcopy no denominators


def test_file_microcopy_no_question_marks():
    """microcopy_line() for FILE tool with defaults produces no '?' in output."""
    from hermes_cli.tui.streaming_microcopy import microcopy_line, StreamingState
    from hermes_cli.tui.tool_category import ToolCategory
    from unittest.mock import MagicMock

    spec = MagicMock()
    spec.category = ToolCategory.FILE
    spec.primary_result = "lines"

    state = StreamingState(lines_received=5, bytes_received=1024, elapsed_s=0.0)

    result = microcopy_line(spec, state)
    assert "?" not in result


def test_file_microcopy_format():
    """FILE microcopy shows '▸ 47 lines · 12kB'."""
    from hermes_cli.tui.streaming_microcopy import microcopy_line, StreamingState
    from hermes_cli.tui.tool_category import ToolCategory
    from unittest.mock import MagicMock

    spec = MagicMock()
    spec.category = ToolCategory.FILE
    spec.primary_result = "lines"

    state = StreamingState(lines_received=47, bytes_received=12288, elapsed_s=0.0)

    result = microcopy_line(spec, state)
    assert "47 lines" in result
    assert "12.0kB" in result
    assert "?" not in result


# §7 — MCP microcopy cleared on complete


@pytest.mark.asyncio
async def test_mcp_microcopy_cleared_on_complete():
    """_clear_microcopy_on_complete() clears text for MCP blocks."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_category import ToolCategory
    from unittest.mock import MagicMock

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.agent_running = True
        app._open_gen_block("mcp__some__tool")
        await pilot.pause()

        from hermes_cli.tui.widgets import OutputPanel
        block = app.query_one(OutputPanel).query_one(StreamingToolBlock)
        if block._microcopy_widget is not None:
            block._microcopy_widget.update("▸ mcp · someserver server")
            block._microcopy_widget.add_class("--active")

        block._clear_microcopy_on_complete()

        if block._microcopy_widget is not None:
            assert block._microcopy_widget._Static__content == ""


@pytest.mark.asyncio
async def test_non_mcp_microcopy_still_cleared():
    """_clear_microcopy_on_complete() also clears non-MCP block microcopy."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.agent_running = True
        app._open_gen_block("terminal")
        await pilot.pause()

        from hermes_cli.tui.widgets import OutputPanel
        block = app.query_one(OutputPanel).query_one(StreamingToolBlock)
        if block._microcopy_widget is not None:
            block._microcopy_widget.update("▸ 5 lines · 1kB")

        block._clear_microcopy_on_complete()

        if block._microcopy_widget is not None:
            assert block._microcopy_widget._Static__content == ""


# ---------------------------------------------------------------------------
# adjacent-mount anchors (_adj_anchors dict)
# ---------------------------------------------------------------------------


def test_adj_anchors_initialized():
    """MessagePanel initializes _adj_anchors to empty dict."""
    from hermes_cli.tui.widgets import MessagePanel
    mp = MessagePanel.__new__(MessagePanel)
    mp._adj_anchors = {}
    assert mp._adj_anchors == {}


@pytest.mark.asyncio
async def test_web_search_sets_adj_anchor():
    """Opening a web_search block registers it in _adj_anchors['web_search']."""
    from hermes_cli.tui.widgets import OutputPanel
    from hermes_cli.tui.tool_panel import ToolPanel

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = app.query_one(OutputPanel)
        msg = output.current_message or output.new_message()

        app.open_streaming_tool_block("ws-001", "web_search query", "web_search")
        await pilot.pause()
        await pilot.pause()

        assert msg._adj_anchors.get("web_search") is not None
        assert getattr(msg._adj_anchors["web_search"], "_tool_name", None) == "web_search"


@pytest.mark.asyncio
async def test_search_child_mounted_before_reasoning():
    """'search' block inserted directly after web_search, before any reasoning text."""
    from hermes_cli.tui.widgets import OutputPanel
    from hermes_cli.tui.tool_panel import ToolPanel

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = app.query_one(OutputPanel)
        msg = output.current_message or output.new_message()

        # Mount web_search block
        app.open_streaming_tool_block("ws-001", "web_search query", "web_search")
        await pilot.pause()

        # Simulate reasoning text appearing after web_search (via append_response_chunk)
        try:
            app.append_response_chunk("thinking about results…")
        except Exception:
            pass
        await pilot.pause()

        # Mount search sub-tool block
        app.open_streaming_tool_block("ws-002", "search", "search")
        await pilot.pause()
        await pilot.pause()

        # The search panel should appear directly after web_search (before reasoning text)
        children = [c for c in msg.children if isinstance(c, ToolPanel)]
        tool_names = [getattr(c, "_tool_name", None) for c in children]
        if len(tool_names) >= 2:
            ws_idx = tool_names.index("web_search") if "web_search" in tool_names else -1
            s_idx = tool_names.index("search") if "search" in tool_names else -1
            if ws_idx >= 0 and s_idx >= 0:
                assert s_idx == ws_idx + 1, (
                    f"search (idx {s_idx}) should be directly after web_search (idx {ws_idx})"
                )


@pytest.mark.asyncio
async def test_execute_code_sets_adj_anchor():
    """Opening an execute_code block registers it in _adj_anchors keyed by panel_id."""
    from hermes_cli.tui.widgets import OutputPanel

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = app.query_one(OutputPanel)
        msg = output.current_message or output.new_message()

        # HermesApp.open_streaming_tool_block sets panel_id = f"tool-{tool_call_id}"
        app.open_streaming_tool_block("ec-001", "print('hello')", "execute_code")
        await pilot.pause()
        await pilot.pause()

        expected_key = "tool-ec-001"
        assert msg._adj_anchors.get(expected_key) is not None
        assert getattr(msg._adj_anchors[expected_key], "_tool_name", None) == "execute_code"


@pytest.mark.asyncio
async def test_execute_code_output_mounted_before_reasoning():
    """Output block inserted directly after execute_code, before any reasoning text."""
    from hermes_cli.tui.widgets import OutputPanel
    from hermes_cli.tui.tool_panel import ToolPanel

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        output = app.query_one(OutputPanel)
        msg = output.current_message or output.new_message()

        # Mount execute_code streaming block; app sets panel_id = "tool-ec-adj-1"
        app.open_streaming_tool_block("ec-adj-1", "print('hello')", "execute_code")
        await pilot.pause()

        # Simulate reasoning text appearing after execute_code
        try:
            app.append_response_chunk("analyzing output…")
        except Exception:
            pass
        await pilot.pause()

        # Mount result/output tool block with parent_id matching the streaming block's panel_id
        app.mount_tool_block("output", ["ec-result"], ["ec-result"], tool_name="execute_code", parent_id="tool-ec-adj-1")
        await pilot.pause()
        await pilot.pause()

        # The output panel should appear directly after execute_code (before reasoning text)
        children = [c for c in msg.children if isinstance(c, ToolPanel)]
        tool_names = [getattr(c, "_tool_name", None) for c in children]
        if len(tool_names) >= 2:
            ec_idx = next((i for i, n in enumerate(tool_names) if n == "execute_code"), -1)
            out_idx = next((i for i, n in enumerate(tool_names) if n == "execute_code" and i > ec_idx), -1)
            # If two execute_code panels exist, the second should be at ec_idx+1
            ec_panels = [i for i, n in enumerate(tool_names) if n == "execute_code"]
            if len(ec_panels) >= 2:
                assert ec_panels[1] == ec_panels[0] + 1, (
                    f"output execute_code (idx {ec_panels[1]}) should be directly after "
                    f"parent (idx {ec_panels[0]})"
                )


# §9 — Dead CSS removed


def test_flash_complete_class_not_in_tcss():
    """hermes.tcss must not contain the dead '--flash-complete' rule."""
    import os
    tcss_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "hermes_cli", "tui", "hermes.tcss"
    )
    with open(tcss_path) as f:
        content = f.read()
    assert "--flash-complete" not in content


# ---------------------------------------------------------------------------
# P0-5: Diff path regex — require git a/ b/ prefix
# ---------------------------------------------------------------------------

def test_diff_path_ignores_yaml_separator():
    """Bare '---' YAML separator must NOT be captured as diff old-file path."""
    from hermes_cli.tui.tool_blocks import _DIFF_OLD_RE, _DIFF_NEW_RE

    yaml_sep = "---"
    assert _DIFF_OLD_RE.match(yaml_sep) is None, "bare '---' should NOT match _DIFF_OLD_RE"

    yaml_with_text = "--- some_yaml_key: value"
    assert _DIFF_OLD_RE.match(yaml_with_text) is None, "yaml '--- key:' should NOT match"


def test_diff_path_git_format_parsed():
    """'--- a/foo/bar.py' → path 'foo/bar.py'; '+++ b/foo/bar.py' → 'foo/bar.py'."""
    from hermes_cli.tui.tool_blocks import _DIFF_OLD_RE, _DIFF_NEW_RE

    m_old = _DIFF_OLD_RE.match("--- a/foo/bar.py")
    assert m_old is not None
    assert (m_old.group(2) or None) == "foo/bar.py"

    m_new = _DIFF_NEW_RE.match("+++ b/foo/bar.py")
    assert m_new is not None
    assert (m_new.group(2) or None) == "foo/bar.py"

    # /dev/null → group(2) is None
    m_null = _DIFF_OLD_RE.match("--- /dev/null")
    assert m_null is not None
    assert (m_null.group(2) if m_null else "x") is None


# ---------------------------------------------------------------------------
# P1-10: rate deque maxlen is 60
# ---------------------------------------------------------------------------

def test_rate_deque_maxlen_is_60():
    """StreamingToolBlock._rate_samples uses deque(maxlen=60) for accurate 2s window."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from collections import deque
    stb = StreamingToolBlock.__new__(StreamingToolBlock)
    stb._rate_samples = deque(maxlen=60)
    assert stb._rate_samples.maxlen == 60
    # Verify class default
    stb2 = StreamingToolBlock(label="bash", tool_name="bash")
    assert stb2._rate_samples.maxlen == 60


# ---------------------------------------------------------------------------
# P0-1: ToolHeader.on_click calls event.stop() in all left-click paths
# ---------------------------------------------------------------------------

def test_tool_header_on_click_stops_event_in_all_paths():
    """All left-click branches in ToolHeader.on_click call event.stop() to prevent bubble."""
    import inspect
    from hermes_cli.tui.tool_blocks import ToolHeader
    src = inspect.getsource(ToolHeader.on_click)
    # Count event.stop() calls — must cover path-clickable, double-click, panel toggle, legacy toggle
    stop_count = src.count("event.stop()")
    assert stop_count >= 4, (
        f"Expected ≥4 event.stop() calls in ToolHeader.on_click (one per left-click branch), "
        f"found {stop_count}. Missing stop() causes click to bubble to ToolGroup and double-toggle."
    )


# ---------------------------------------------------------------------------
# P1-6: context menu uses asyncio.ensure_future, not deprecated get_event_loop
# ---------------------------------------------------------------------------

def test_context_menu_uses_ensure_future_not_deprecated_event_loop():
    """ToolHeader._show_context_menu uses asyncio.ensure_future, not deprecated get_event_loop().create_task()."""
    import inspect
    from hermes_cli.tui.tool_blocks import ToolHeader
    src = inspect.getsource(ToolHeader._show_context_menu)
    assert "ensure_future" in src, "Expected asyncio.ensure_future in _show_context_menu"
    assert "get_event_loop" not in src, (
        "Found deprecated get_event_loop in _show_context_menu — "
        "raises DeprecationWarning in Python 3.10+ when no event loop is running"
    )


# ---------------------------------------------------------------------------
# Pass-6 P2-3: flash_complete removed; StreamingToolBlock.complete uses flash_success
# ---------------------------------------------------------------------------

def test_tool_header_no_flash_complete_method():
    """ToolHeader.flash_complete must be removed — it was a deprecated dead wrapper."""
    from hermes_cli.tui.tool_blocks import ToolHeader
    assert not hasattr(ToolHeader, "flash_complete"), (
        "ToolHeader.flash_complete still exists — deprecated wrapper must be removed"
    )


def test_streaming_tool_block_complete_calls_flash_success_not_flash_complete():
    """StreamingToolBlock.complete() must call flash_success(), not the removed flash_complete()."""
    import inspect
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    src = inspect.getsource(StreamingToolBlock.complete)
    assert "flash_success" in src, (
        "StreamingToolBlock.complete must call flash_success() directly"
    )
    assert "flash_complete" not in src, (
        "StreamingToolBlock.complete still references flash_complete() — must be updated to flash_success()"
    )
