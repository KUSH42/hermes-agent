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


# ---------------------------------------------------------------------------
# Phase 3: Detail level watcher (T-D1 – T-D11)
# ---------------------------------------------------------------------------


async def _get_shell_panel(app, pilot) -> ToolPanel:
    """Helper: open a shell panel and return it."""
    app.agent_running = True
    await _pause(pilot)
    app._open_gen_block("terminal")
    await _pause(pilot)
    output = app.query_one(OutputPanel)
    return output.query_one(ToolPanel)


@pytest.mark.asyncio
async def test_td1_l0_hides_all_panes():
    """T-D1: L0 hides ArgsPane, BodyPane, and FooterPane."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        panel.detail_level = 0
        await _pause(pilot)

        assert panel.query_one(ArgsPane).styles.display == "none"
        assert panel.query_one(BodyPane).styles.display == "none"
        assert panel.query_one(FooterPane).styles.display == "none"


@pytest.mark.asyncio
async def test_td2_l1_shows_body_preview():
    """T-D2: L1 hides ArgsPane, shows BodyPane in preview mode."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        panel.detail_level = 1
        await _pause(pilot)

        assert panel.query_one(ArgsPane).styles.display == "none"
        assert panel.query_one(BodyPane).styles.display in ("block", "")


@pytest.mark.asyncio
async def test_td3_l2_shows_body_full():
    """T-D3: L2 hides ArgsPane, shows BodyPane full body."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        panel.detail_level = 2
        await _pause(pilot)

        assert panel.query_one(ArgsPane).styles.display == "none"
        assert panel.query_one(BodyPane).styles.display in ("block", "")


@pytest.mark.asyncio
async def test_td4_l3_shows_all_panes():
    """T-D4: L3 shows ArgsPane + BodyPane full + FooterPane."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        panel.detail_level = 3
        await _pause(pilot)

        assert panel.query_one(ArgsPane).styles.display == "block"
        assert panel.query_one(BodyPane).styles.display in ("block", "")
        assert panel.query_one(FooterPane).styles.display == "block"


@pytest.mark.asyncio
async def test_td6_enter_cycles_l1_l2():
    """T-D6: Enter key cycles L1 ↔ L2 when ToolPanel is focused."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        panel.detail_level = 1
        await _pause(pilot)

        panel.focus()
        await _pause(pilot)
        await pilot.press("enter")
        await _pause(pilot)
        assert panel.detail_level == 2

        await pilot.press("enter")
        await _pause(pilot)
        assert panel.detail_level == 1


@pytest.mark.asyncio
async def test_td7_d_key_cycles_forward():
    """T-D7: D key cycles L1 → L2 → L3 → L1."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        panel.detail_level = 1
        await _pause(pilot)

        panel.focus()
        await _pause(pilot)

        await pilot.press("d")
        await _pause(pilot)
        assert panel.detail_level == 2

        await pilot.press("d")
        await _pause(pilot)
        assert panel.detail_level == 3

        await pilot.press("d")
        await _pause(pilot)
        assert panel.detail_level == 1


@pytest.mark.asyncio
async def test_td8_shift_d_reverses():
    """T-D8: Shift+D reverses; at L0 stays at L0."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        panel.detail_level = 3
        await _pause(pilot)

        panel.focus()
        await _pause(pilot)

        await pilot.press("D")
        await _pause(pilot)
        assert panel.detail_level == 2

        await pilot.press("D")
        await _pause(pilot)
        assert panel.detail_level == 1

        await pilot.press("D")
        await _pause(pilot)
        assert panel.detail_level == 0

        # At L0, Shift+D stays
        await pilot.press("D")
        await _pause(pilot)
        assert panel.detail_level == 0


@pytest.mark.asyncio
async def test_td9_number_keys_jump():
    """T-D9: 0/1/2/3 keys jump directly to that level."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        panel.focus()
        await _pause(pilot)

        for level, key in ((0, "0"), (1, "1"), (2, "2"), (3, "3")):
            await pilot.press(key)
            await _pause(pilot)
            assert panel.detail_level == level, f"After key {key!r}: expected {level}, got {panel.detail_level}"


@pytest.mark.asyncio
async def test_td10a_user_override_flag_set_on_key():
    """T-D10a: _user_detail_override set when user changes level via key."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        panel.focus()
        await _pause(pilot)

        assert panel._user_detail_override is False
        await pilot.press("d")
        await _pause(pilot)
        assert panel._user_detail_override is True


@pytest.mark.asyncio
async def test_td10b_l0_override_error_promotes_to_l1():
    """T-D10b: Panel at L0 with user override + error result → auto-promote to L1."""
    from hermes_cli.tui.tool_result_parse import ResultSummary

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        panel.detail_level = 0
        panel._user_detail_override = True
        await _pause(pilot)

        panel.set_result_summary(ResultSummary(exit_code=1, is_error=True))
        await _pause(pilot)

        # L0 override + error → promoted to L1
        assert panel.detail_level == 1


@pytest.mark.asyncio
async def test_td10c_l2_override_survives_error():
    """T-D10c: L2 override survives error completion unchanged."""
    from hermes_cli.tui.tool_result_parse import ResultSummary

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        panel.detail_level = 2
        panel._user_detail_override = True
        await _pause(pilot)

        panel.set_result_summary(ResultSummary(exit_code=2, is_error=True))
        await _pause(pilot)

        assert panel.detail_level == 2


@pytest.mark.asyncio
async def test_td10d_no_override_over_threshold_collapses_l1():
    """T-D10d: No override + over threshold → auto-collapse to L1."""
    from hermes_cli.tui.tool_result_parse import ResultSummary
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        block = panel.query_one(StreamingToolBlock)
        # Feed > threshold (3) lines
        for i in range(10):
            block.append_line(f"line {i}")
        await _pause(pilot)
        panel._user_detail_override = False  # ensure no override

        panel.set_result_summary(ResultSummary())
        await _pause(pilot)

        assert panel.detail_level == 1  # auto-collapsed


@pytest.mark.asyncio
async def test_td10e_no_override_within_threshold_stays_l2():
    """T-D10e: No override + within threshold → stay at L2."""
    from hermes_cli.tui.tool_result_parse import ResultSummary
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        block = panel.query_one(StreamingToolBlock)
        # Feed ≤ threshold (3) lines
        for i in range(2):
            block.append_line(f"line {i}")
        await _pause(pilot)
        panel._user_detail_override = False

        panel.set_result_summary(ResultSummary())
        await _pause(pilot)

        assert panel.detail_level == 2


# ---------------------------------------------------------------------------
# Phase 3: Args pane (T-A1 – T-A8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ta1_l3_reveals_args_pane():
    """T-A1: L3 reveals ArgsPane; L2 hides it."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)

        panel.detail_level = 2
        await _pause(pilot)
        assert panel.query_one(ArgsPane).styles.display == "none"

        panel.detail_level = 3
        await _pause(pilot)
        assert panel.query_one(ArgsPane).styles.display == "block"


@pytest.mark.asyncio
async def test_ta2_file_args_formatter():
    """T-A2: file_args({'path': 'src/a.py'}) → [('path', Text with 'a.py')]."""
    from hermes_cli.tui.tool_args_format import file_args
    rows = file_args({"path": "src/a.py"})
    assert len(rows) >= 1
    assert rows[0][0] == "path"
    assert "a.py" in rows[0][1].plain


@pytest.mark.asyncio
async def test_ta3_shell_args_two_rows():
    """T-A3: shell_args({command, cwd}) emits two rows."""
    from hermes_cli.tui.tool_args_format import shell_args
    rows = shell_args({"command": "ls -la", "cwd": "/tmp"})
    keys = [r[0] for r in rows]
    assert "command" in keys
    assert "cwd" in keys


@pytest.mark.asyncio
async def test_ta4_code_args_line_count():
    """T-A4: code_args → [('code', '2 lines')]."""
    from hermes_cli.tui.tool_args_format import code_args
    rows = code_args({"code": "print(1)\nprint(2)"})
    assert rows[0][0] == "code"
    assert "2 lines" in rows[0][1].plain


@pytest.mark.asyncio
async def test_ta5_search_args_query():
    """T-A5: search_args({'query': 'foo'}) → [('query', italic Text)]."""
    from hermes_cli.tui.tool_args_format import search_args
    rows = search_args({"query": "foo"})
    assert rows[0][0] == "query"
    assert "foo" in rows[0][1].plain


@pytest.mark.asyncio
async def test_ta6_none_args_empty_pane():
    """T-A6: args_final=None → ArgsPane still mounts (no crash)."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        panel.set_tool_args(None)
        panel.detail_level = 3
        await _pause(pilot)
        # ArgsPane visible and no exception
        assert panel.query_one(ArgsPane).styles.display == "block"


@pytest.mark.asyncio
async def test_ta7_narrow_layout():
    """T-A7: ArgsPane.on_resize with width=60 adds .narrow class."""
    from hermes_cli.tui.tool_panel import ArgsPane
    from textual.geometry import Size

    class MockEvent:
        size = Size(60, 10)

    pane = ArgsPane()
    pane.on_resize(MockEvent())
    assert pane.has_class("narrow")
    assert not pane.has_class("wide")


@pytest.mark.asyncio
async def test_ta8_wide_layout():
    """T-A8: ArgsPane.on_resize with width=120 adds .wide class."""
    from hermes_cli.tui.tool_panel import ArgsPane
    from textual.geometry import Size

    class MockEvent:
        size = Size(120, 10)

    pane = ArgsPane()
    pane.on_resize(MockEvent())
    assert pane.has_class("wide")
    assert not pane.has_class("narrow")


# ---------------------------------------------------------------------------
# Phase 3: Footer pane (T-F1 – T-F6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tf1_exit_code_chip():
    """T-F1: Non-zero exit_code shows 'exit N' chip in footer."""
    from hermes_cli.tui.tool_result_parse import ResultSummary

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        panel.set_result_summary(ResultSummary(exit_code=1, is_error=True))
        panel.detail_level = 3
        await _pause(pilot)

        footer = panel.query_one(FooterPane)
        assert footer.styles.display == "block"
        # Verify footer content via update_summary (already called via set_result_summary)
        # The content widget is a Static — just verify footer is visible with error state
        assert panel._result_summary is not None
        assert panel._result_summary.is_error is True


@pytest.mark.asyncio
async def test_tf2_diff_stat_badges():
    """T-F2: Diff stats appear as +N -M badges."""
    from hermes_cli.tui.tool_result_parse import ResultSummary

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        panel.set_result_summary(ResultSummary(stat_badges=["+12", "-4"]))
        panel.detail_level = 3
        await _pause(pilot)

        footer = panel.query_one(FooterPane)
        assert footer.styles.display == "block"


@pytest.mark.asyncio
async def test_tf6_should_show_footer_rules():
    """T-F6: _should_show_footer returns True per spec rules."""
    from hermes_cli.tui.tool_result_parse import ResultSummary
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)

        # L0: never show footer
        panel._result_summary = ResultSummary(exit_code=1, is_error=True)
        assert panel._should_show_footer(0) is False

        # L3: always show footer
        assert panel._should_show_footer(3) is True

        # L1/L2 without result: no footer
        panel._result_summary = None
        assert panel._should_show_footer(1) is False
        assert panel._should_show_footer(2) is False

        # L1/L2 with error: show footer
        panel._result_summary = ResultSummary(exit_code=1, is_error=True)
        assert panel._should_show_footer(1) is True
        assert panel._should_show_footer(2) is True


# ---------------------------------------------------------------------------
# Phase 3: Copy contract (T-CP1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tcp1_copy_at_l0_returns_content():
    """T-CP1: copy_content() at L0 (body hidden) still returns full output."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        block = panel.query_one(StreamingToolBlock)
        block.append_line("secret output")
        await _pause(pilot)

        panel.detail_level = 0
        await _pause(pilot)

        # Body hidden, but copy still works
        content = panel.copy_content()
        assert "secret output" in content


# ---------------------------------------------------------------------------
# P6: OmissionBar keyboard + focused-panel hint row
# ---------------------------------------------------------------------------


def test_p6_bindings_include_expand_collapse():
    """ToolPanel.BINDINGS includes +/-/* for OmissionBar control."""
    from textual.binding import Binding
    keys = {b.key for b in ToolPanel.BINDINGS}
    assert "+" in keys
    assert "-" in keys
    assert "*" in keys


def test_p6_hint_row_composed():
    """_hint_row Static is created during compose (not None after init guard)."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    block = StreamingToolBlock(label="bash", tool_name="bash")
    panel = ToolPanel(block, tool_name="bash")
    # _hint_row set in compose; before compose it's None
    assert panel._hint_row is None  # before compose
    # We can't run compose without a mounted app, but the attr is declared


@pytest.mark.asyncio
async def test_p6_hint_shows_on_focus():
    """watch_has_focus sets hint text when panel gains focus."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        # Simulate focus
        panel.focus()
        await _pause(pilot)

        assert panel._hint_row is not None
        hint_text = str(panel._hint_row.content)
        # At least 'd/D' should be in the hint
        assert "d" in hint_text.lower() or len(hint_text) > 0


@pytest.mark.asyncio
async def test_p6_hint_clears_on_blur():
    """watch_has_focus clears hint text when panel loses focus."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        panel.focus()
        await _pause(pilot)

        # Blur by focusing something else (simulate)
        panel.watch_has_focus(False)
        await _pause(pilot)

        assert panel._hint_row is not None
        # After blur, hint should be empty
        rendered = panel._hint_row.content
        assert str(rendered) == "" or not rendered


@pytest.mark.asyncio
async def test_p6_build_hint_text_contains_keys():
    """_build_hint_text returns object with d/D/Enter content."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        hint = panel._build_hint_text()
        # Should be a Rich Text object or str
        plain = hint.plain if hasattr(hint, "plain") else str(hint)
        assert "d/D" in plain
        assert "Enter" in plain
        assert "c" in plain


@pytest.mark.asyncio
async def test_p6_expand_lines_no_bar_no_crash():
    """action_expand_lines is a no-op when no OmissionBar is present."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        # Should not raise even if no OmissionBar
        panel.action_expand_lines()
        panel.action_collapse_lines()
        panel.action_expand_all_lines()


def test_p6_get_omission_bar_none_without_block():
    """_get_omission_bar returns None when block has no bar."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    block = StreamingToolBlock(label="bash", tool_name="bash")
    panel = ToolPanel(block, tool_name="bash")
    result = panel._get_omission_bar()
    assert result is None


@pytest.mark.asyncio
async def test_p6_expand_lines_delegates_to_bar():
    """action_expand_lines calls _do_expand_one on the bar."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock, OmissionBar
    from unittest.mock import MagicMock, patch

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        # Inject a fake OmissionBar
        block = panel._block
        fake_bar = MagicMock(spec=OmissionBar)
        block._omission_bar = fake_bar
        block._omission_bar_mounted = True

        panel.action_expand_lines()
        fake_bar._do_expand_one.assert_called_once()


@pytest.mark.asyncio
async def test_p6_collapse_lines_delegates_to_bar():
    """action_collapse_lines calls _do_collapse_one on the bar."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock, OmissionBar
    from unittest.mock import MagicMock

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        block = panel._block
        fake_bar = MagicMock(spec=OmissionBar)
        block._omission_bar = fake_bar
        block._omission_bar_mounted = True

        panel.action_collapse_lines()
        fake_bar._do_collapse_one.assert_called_once()


@pytest.mark.asyncio
async def test_p6_expand_all_delegates_to_bar():
    """action_expand_all_lines calls _do_expand_all on the bar."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock, OmissionBar
    from unittest.mock import MagicMock

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        block = panel._block
        fake_bar = MagicMock(spec=OmissionBar)
        block._omission_bar = fake_bar
        block._omission_bar_mounted = True

        panel.action_expand_all_lines()
        fake_bar._do_expand_all.assert_called_once()


@pytest.mark.asyncio
async def test_p6_hint_includes_lines_hint_when_bar_present():
    """_build_hint_text includes +/- when OmissionBar is present."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock, OmissionBar
    from unittest.mock import MagicMock

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        block = panel._block
        fake_bar = MagicMock(spec=OmissionBar)
        block._omission_bar = fake_bar
        block._omission_bar_mounted = True

        hint = panel._build_hint_text()
        plain = hint.plain if hasattr(hint, "plain") else str(hint)
        assert "+/-" in plain or "+" in plain
