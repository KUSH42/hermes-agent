"""Phase 1 tests for ToolPanel shell widget (tui-tool-panel-v2-spec.md §12.1).

Phase 1 tests cover:
- ToolPanel composition contract (Header/Args/Body/Footer slots)
- ToolCategory classification
- detail_level default
- can_focus behaviour
- Wrapping of StreamingToolBlock, ToolBlock, ExecuteCodeBlock, WriteFileBlock
  via open_streaming_tool_block / mount_tool_block / _open_execute_code_block /
  _open_write_file_block
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import OutputPanel
from hermes_cli.tui.tool_category import ToolCategory, classify_tool, _CATEGORY_DEFAULTS
from hermes_cli.tui.tool_panel import ToolPanel, ArgsPane, BodyPane, FooterPane


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _pause(pilot, n: int = 5) -> None:
    for _ in range(n):
        await pilot.pause()


def _make_app() -> HermesApp:
    return HermesApp(cli=MagicMock())


# ---------------------------------------------------------------------------
# ToolCategory unit tests (no app needed)
# ---------------------------------------------------------------------------


def test_classify_tool_file():
    for name in ("read_file", "write_file", "create_file", "edit_file",
                 "str_replace_editor", "patch", "view"):
        assert classify_tool(name) == ToolCategory.FILE, name


def test_classify_tool_shell():
    for name in ("terminal", "bash"):
        assert classify_tool(name) == ToolCategory.SHELL, name


def test_classify_tool_code():
    assert classify_tool("execute_code") == ToolCategory.CODE


def test_classify_tool_search():
    for name in ("web_search", "grep", "glob"):
        assert classify_tool(name) == ToolCategory.SEARCH, name


def test_classify_tool_web():
    for name in ("web_extract", "fetch", "http"):
        assert classify_tool(name) == ToolCategory.WEB, name


def test_classify_tool_agent():
    for name in ("think", "plan", "delegate"):
        assert classify_tool(name) == ToolCategory.AGENT, name


def test_classify_tool_unknown():
    assert classify_tool("nonexistent_tool") == ToolCategory.UNKNOWN
    assert classify_tool("") == ToolCategory.UNKNOWN


def test_category_defaults_all_categories():
    for cat in ToolCategory:
        assert cat in _CATEGORY_DEFAULTS, f"Missing defaults for {cat}"
        d = _CATEGORY_DEFAULTS[cat]
        assert d.accent_var
        assert d.ascii_fallback
        assert 0 <= d.default_detail <= 3
        assert d.default_collapsed_lines > 0


# ---------------------------------------------------------------------------
# ToolPanel composition (T-C1, T-C2, T-C3, T-C4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_panel_compose_order():
    """T-C1: ToolPanel composes ArgsPane → BodyPane → FooterPane."""
    from hermes_cli.tui.tool_blocks import ToolBlock

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app.mount_tool_block("terminal", ["line1", "line2", "line3", "line4"],
                             ["line1", "line2", "line3", "line4"],
                             tool_name="terminal")
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        panel = output.query_one(ToolPanel)
        children = list(panel.children)
        types = [type(c) for c in children]

        assert ArgsPane in types
        assert BodyPane in types
        assert FooterPane in types
        args_idx = types.index(ArgsPane)
        body_idx = types.index(BodyPane)
        footer_idx = types.index(FooterPane)
        assert args_idx < body_idx < footer_idx, (
            f"Expected ArgsPane < BodyPane < FooterPane, got {args_idx}, {body_idx}, {footer_idx}"
        )


@pytest.mark.asyncio
async def test_tool_panel_detail_level_default():
    """T-C2: detail_level defaults to 2 (L2 = full body) in Phase 1."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app._open_gen_block("bash")
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        panel = output.query_one(ToolPanel)
        assert panel.detail_level == 2


@pytest.mark.asyncio
async def test_tool_panel_category_classification():
    """T-C3: ToolPanel classifies known tool names correctly."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app._open_gen_block("terminal")
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        panel = output.query_one(ToolPanel)
        assert panel._category == ToolCategory.SHELL
        assert panel.has_class("category-shell")


@pytest.mark.asyncio
async def test_tool_panel_unknown_category_fallback():
    """T-C3b: Unknown category uses TextRenderer placeholder; no crash."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app._open_gen_block("unknown_custom_tool")
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        panel = output.query_one(ToolPanel)
        assert panel._category == ToolCategory.UNKNOWN
        assert panel.has_class("category-unknown")


@pytest.mark.asyncio
async def test_tool_panel_can_focus():
    """T-C4: ToolPanel.can_focus is True."""
    from hermes_cli.tui.tool_blocks import ToolBlock
    inner = ToolBlock("test", ["l1"], ["l1"])
    panel = ToolPanel(inner, tool_name="terminal")
    assert panel.can_focus is True


# ---------------------------------------------------------------------------
# ArgsPane and FooterPane hidden in Phase 1 (T-D1 subset)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_args_pane_hidden_phase1():
    """ArgsPane display:none in Phase 1 (detail_level pinned to 2)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app._open_gen_block("bash")
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        panel = output.query_one(ToolPanel)
        args = panel.query_one(ArgsPane)
        assert args.styles.display == "none"


@pytest.mark.asyncio
async def test_footer_pane_hidden_phase1():
    """FooterPane display:none in Phase 1."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app._open_gen_block("bash")
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        panel = output.query_one(ToolPanel)
        footer = panel.query_one(FooterPane)
        assert footer.styles.display == "none"


# ---------------------------------------------------------------------------
# Wrapping of all block types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streaming_tool_block_wrapped_in_tool_panel():
    """open_streaming_tool_block wraps STB in ToolPanel; STB inside BodyPane."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        # Use _open_gen_block which returns the inner block ref
        block_ref = app._open_gen_block("bash")
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        msg = output.current_message
        assert msg is not None

        tp = next((c for c in msg.children if isinstance(c, ToolPanel)), None)
        assert tp is not None, "ToolPanel must be direct child of MessagePanel"
        assert tp.parent is msg

        stb = tp.query_one(StreamingToolBlock)
        assert stb is not None, "STB must be inside ToolPanel"
        assert stb is block_ref, "block_ref must point to inner STB"


@pytest.mark.asyncio
async def test_tool_block_wrapped_in_tool_panel():
    """mount_tool_block wraps ToolBlock in ToolPanel; static ToolBlock inside BodyPane."""
    from hermes_cli.tui.tool_blocks import ToolBlock, StreamingToolBlock

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app.mount_tool_block(
            "read_file", ["l1", "l2", "l3", "l4"], ["l1", "l2", "l3", "l4"],
            tool_name="read_file"
        )
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        msg = output.current_message
        tp = next((c for c in msg.children if isinstance(c, ToolPanel)), None)
        assert tp is not None, "ToolPanel must be direct child of MessagePanel"
        assert tp._category == ToolCategory.FILE

        # Static ToolBlock should be inside ToolPanel (not a streaming subclass)
        all_tbs = list(tp.query(ToolBlock))
        tb = next((b for b in all_tbs if not isinstance(b, StreamingToolBlock)), None)
        assert tb is not None, "Static ToolBlock must be inside ToolPanel"


@pytest.mark.asyncio
async def test_execute_code_block_wrapped_in_tool_panel():
    """_open_execute_code_block wraps ECB in ToolPanel with CODE category."""
    from hermes_cli.tui.execute_code_block import ExecuteCodeBlock

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        output.new_message()
        await _pause(pilot)

        block_ref = app._open_execute_code_block(idx=0)
        await _pause(pilot)

        tp = output.query_one(ToolPanel)
        assert tp is not None
        assert tp._category == ToolCategory.CODE
        assert tp.has_class("category-code")

        ecb = tp.query_one(ExecuteCodeBlock)
        assert ecb is not None
        assert ecb is block_ref


@pytest.mark.asyncio
async def test_write_file_block_wrapped_in_tool_panel():
    """_open_write_file_block wraps WFB in ToolPanel with FILE category."""
    from hermes_cli.tui.write_file_block import WriteFileBlock

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        output = app.query_one(OutputPanel)
        output.new_message()
        await _pause(pilot)

        block_ref = app._open_write_file_block(idx=0, path="/tmp/test.py")
        await _pause(pilot)

        tp = output.query_one(ToolPanel)
        assert tp is not None
        assert tp._category == ToolCategory.FILE
        assert tp.has_class("category-file")

        wfb = tp.query_one(WriteFileBlock)
        assert wfb is not None
        assert wfb is block_ref


# ---------------------------------------------------------------------------
# Inner block refs still work after wrapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inner_block_ref_append_line_works():
    """Block ref from _open_gen_block still accepts append_line after wrapping."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        block = app._open_gen_block("bash")
        await _pause(pilot)

        block.append_line("hello world")
        await _pause(pilot)

        assert "hello world" in block._all_plain


@pytest.mark.asyncio
async def test_inner_block_ref_complete_works():
    """Block ref from _open_gen_block can be completed after wrapping."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        block = app._open_gen_block("bash")
        await _pause(pilot)

        block.complete("1.2s")
        await _pause(pilot)

        assert block._completed


# ---------------------------------------------------------------------------
# Category class applied
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_tool_gets_category_class():
    """read_file panel has category-file class."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app._open_gen_block("read_file")
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        panel = output.query_one(ToolPanel)
        assert panel.has_class("category-file")
        assert panel._category == ToolCategory.FILE


@pytest.mark.asyncio
async def test_shell_tool_gets_category_class():
    """terminal panel has category-shell class."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app._open_gen_block("terminal")
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        panel = output.query_one(ToolPanel)
        assert panel.has_class("category-shell")
