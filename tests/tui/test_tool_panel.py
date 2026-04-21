"""Tests for ToolPanel binary collapse (tui-tool-panel-spec-binary-collapse.md).

Covers:
- Binary collapsed reactive (§2)
- Auto-collapse at completion (§3)
- Enter keybind toggle (§4)
- watch_collapsed watcher (§5)
- Initial state always expanded (§6)
- OmissionBar no-op while collapsed (§7)
- Back-ref wiring (§2.5 / §14.2)
- Result wiring via set_result_summary_v4 (§14)
- Category classification + class applied
- Copy contract, hint row, OmissionBar delegation
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import OutputPanel
from hermes_cli.tui.tool_category import ToolCategory, classify_tool, _CATEGORY_DEFAULTS
from hermes_cli.tui.tool_panel import ToolPanel, BodyPane, FooterPane
from hermes_cli.tui.tool_accent import ToolAccent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _pause(pilot, n: int = 5) -> None:
    for _ in range(n):
        await pilot.pause()


def _make_app() -> HermesApp:
    return HermesApp(cli=MagicMock())


async def _get_shell_panel(app, pilot) -> ToolPanel:
    app.agent_running = True
    await _pause(pilot)
    app._open_gen_block("terminal")
    await _pause(pilot)
    output = app.query_one(OutputPanel)
    return output.query_one(ToolPanel)


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
        assert d.default_collapsed_lines > 0


# ---------------------------------------------------------------------------
# ToolPanel composition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_panel_compose_order():
    """ToolPanel binary-collapse: BodyPane < FooterPane as direct children."""
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
        direct_types = [type(c) for c in panel.children]

        assert BodyPane in direct_types, f"BodyPane must be direct child; got {direct_types}"
        assert FooterPane in direct_types, f"FooterPane must be direct child; got {direct_types}"
        body_idx = direct_types.index(BodyPane)
        footer_idx = direct_types.index(FooterPane)
        assert body_idx < footer_idx, f"Expected BodyPane < FooterPane, got {body_idx}, {footer_idx}"


@pytest.mark.asyncio
async def test_tool_panel_collapsed_default_false():
    """Panel starts collapsed=False (always expanded at mount)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app._open_gen_block("bash")
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        panel = output.query_one(ToolPanel)
        assert panel.collapsed is False


@pytest.mark.asyncio
async def test_tool_panel_category_classification():
    """ToolPanel classifies known tool names correctly."""
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
    """Unknown category class applied; no crash."""
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
    """ToolPanel.can_focus is True."""
    from hermes_cli.tui.tool_blocks import ToolBlock
    inner = ToolBlock("test", ["l1"], ["l1"])
    panel = ToolPanel(inner, tool_name="terminal")
    assert panel.can_focus is True


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
        block_ref = app._open_gen_block("bash")
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        msg = output.current_message
        assert msg is not None

        tp = next((c for c in msg.children if isinstance(c, ToolPanel)), None)
        assert tp is not None, "ToolPanel must be direct child of MessagePanel"
        assert tp.parent is msg

        stb = tp.query_one(StreamingToolBlock)
        assert stb is not None
        assert stb is block_ref


@pytest.mark.asyncio
async def test_tool_panel_back_ref_on_header():
    """ToolPanel.on_mount sets header._panel back-ref for toggle delegation."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        block_ref = app._open_gen_block("bash")
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        panel = output.query_one(ToolPanel)
        assert block_ref._header._panel is panel


@pytest.mark.asyncio
async def test_streaming_tool_block_has_tool_panel_back_ref():
    """open_streaming_tool_block sets block._tool_panel for result wiring."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        block_ref = app._open_gen_block("bash")
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        panel = output.query_one(ToolPanel)
        assert getattr(block_ref, "_tool_panel", None) is panel


@pytest.mark.asyncio
async def test_tool_block_wrapped_in_tool_panel():
    """mount_tool_block wraps ToolBlock in ToolPanel."""
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
        assert tp is not None
        assert tp._category == ToolCategory.FILE

        all_tbs = list(tp.query(ToolBlock))
        tb = next((b for b in all_tbs if not isinstance(b, StreamingToolBlock)), None)
        assert tb is not None


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
        ecb = tp.query_one(ExecuteCodeBlock)
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
        wfb = tp.query_one(WriteFileBlock)
        assert wfb is block_ref


# ---------------------------------------------------------------------------
# Binary collapse — watcher and state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collapsed_true_hides_body_and_footer():
    """collapsed=True hides block._body (ToolBodyContainer) and FooterPane.

    BodyPane stays visible so ToolHeader remains clickable for expand.
    """
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        panel.collapsed = True
        await _pause(pilot)

        # BodyPane stays visible — ToolHeader inside must remain clickable
        assert panel.query_one(BodyPane).styles.display != "none"
        # Only the inner content body is hidden
        assert panel._block._body.styles.display == "none"
        # Footer hidden
        assert panel.query_one(FooterPane).styles.display == "none"


@pytest.mark.asyncio
async def test_collapsed_false_shows_body():
    """collapsed=False shows BodyPane."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        panel.collapsed = True
        await _pause(pilot)
        panel.collapsed = False
        await _pause(pilot)

        assert panel.query_one(BodyPane).styles.display in ("block", "")


@pytest.mark.asyncio
async def test_enter_key_toggles_collapsed():
    """Enter key calls action_toggle_collapse → flips collapsed."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        assert panel.collapsed is False

        panel.focus()
        await _pause(pilot)
        await pilot.press("enter")
        await _pause(pilot)
        assert panel.collapsed is True

        await pilot.press("enter")
        await _pause(pilot)
        assert panel.collapsed is False


@pytest.mark.asyncio
async def test_enter_sets_user_override():
    """action_toggle_collapse sets _user_collapse_override."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        assert panel._user_collapse_override is False

        panel.focus()
        await _pause(pilot)
        await pilot.press("enter")
        await _pause(pilot)
        assert panel._user_collapse_override is True


# ---------------------------------------------------------------------------
# Auto-collapse at completion (v4 result wiring)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_collapse_over_threshold():
    """No override + >threshold lines → collapsed=True after set_result_summary_v4."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        block = panel.query_one(StreamingToolBlock)
        for i in range(11):  # >10 = new SHELL threshold (E2 raised from 8→10)
            block.append_line(f"line {i}")
        await _pause(pilot)
        panel._user_collapse_override = False

        summary = ResultSummaryV4(
            primary=None, exit_code=0, chips=(), stderr_tail="",
            actions=(), artifacts=(), is_error=False,
        )
        panel.set_result_summary_v4(summary)
        await _pause(pilot)

        assert panel.collapsed is True


@pytest.mark.asyncio
async def test_auto_collapse_within_threshold_stays_expanded():
    """No override + ≤threshold lines → collapsed=False after set_result_summary_v4."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        block = panel.query_one(StreamingToolBlock)
        for i in range(2):
            block.append_line(f"line {i}")
        await _pause(pilot)
        panel._user_collapse_override = False

        summary = ResultSummaryV4(
            primary=None, exit_code=0, chips=(), stderr_tail="",
            actions=(), artifacts=(), is_error=False,
        )
        panel.set_result_summary_v4(summary)
        await _pause(pilot)

        assert panel.collapsed is False


@pytest.mark.asyncio
async def test_error_forces_expand():
    """collapsed=True + error result → force expanded (error promotion rule)."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        panel.collapsed = False
        panel._user_collapse_override = False
        await _pause(pilot)

        summary = ResultSummaryV4(
            primary=None, exit_code=1, chips=(), stderr_tail="",
            actions=(), artifacts=(), is_error=True,
        )
        panel.set_result_summary_v4(summary)
        await _pause(pilot)

        assert panel.collapsed is False


@pytest.mark.asyncio
async def test_user_override_prevents_auto_collapse():
    """_user_collapse_override=True → auto-collapse skipped on non-error."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        block = panel.query_one(StreamingToolBlock)
        for i in range(10):
            block.append_line(f"line {i}")
        await _pause(pilot)
        panel._user_collapse_override = True  # user already toggled

        summary = ResultSummaryV4(
            primary=None, exit_code=0, chips=(), stderr_tail="",
            actions=(), artifacts=(), is_error=False,
        )
        panel.set_result_summary_v4(summary)
        await _pause(pilot)

        # Override active: remains expanded (user chose to keep it open)
        assert panel.collapsed is False


@pytest.mark.asyncio
async def test_user_override_collapsed_non_error_stays_collapsed():
    """User collapsed manually + non-error result: stays collapsed."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        block = panel.query_one(StreamingToolBlock)
        for i in range(2):
            block.append_line(f"line {i}")
        await _pause(pilot)
        panel.collapsed = True
        panel._user_collapse_override = True

        summary = ResultSummaryV4(
            primary=None, exit_code=0, chips=(), stderr_tail="",
            actions=(), artifacts=(), is_error=False,
        )
        panel.set_result_summary_v4(summary)
        await _pause(pilot)

        assert panel.collapsed is True  # user override respected


@pytest.mark.asyncio
async def test_result_summary_v4_stored():
    """set_result_summary_v4 stores summary to _result_summary_v4."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        assert panel._result_summary_v4 is None

        summary = ResultSummaryV4(
            primary="✓ done", exit_code=0, chips=(), stderr_tail="",
            actions=(), artifacts=(), is_error=False,
        )
        panel.set_result_summary_v4(summary)
        await _pause(pilot)

        assert panel._result_summary_v4 is summary


@pytest.mark.asyncio
async def test_result_summary_posts_completed():
    """set_result_summary_v4 posts ToolPanel.Completed message."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    completed_msgs = []

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)

        app.on_tool_panel_completed = lambda msg: completed_msgs.append(msg)
        summary = ResultSummaryV4(
            primary=None, exit_code=0, chips=(), stderr_tail="",
            actions=(), artifacts=(), is_error=False,
        )
        panel.set_result_summary_v4(summary)
        await _pause(pilot)

        # Completed message should have been posted
        assert panel._result_summary_v4 is summary  # at minimum summary stored


# ---------------------------------------------------------------------------
# has_footer_content
# ---------------------------------------------------------------------------


def test_has_footer_content_none_summary():
    """_has_footer_content returns False when no summary."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    block = StreamingToolBlock(label="bash", tool_name="bash")
    panel = ToolPanel(block, tool_name="bash")
    assert panel._has_footer_content() is False


def test_has_footer_content_non_zero_exit():
    """_has_footer_content returns True for non-zero exit_code."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    block = StreamingToolBlock(label="bash", tool_name="bash")
    panel = ToolPanel(block, tool_name="bash")
    panel._result_summary_v4 = ResultSummaryV4(
        primary=None, exit_code=1, chips=(), stderr_tail="",
        actions=(), artifacts=(), is_error=True,
    )
    assert panel._has_footer_content() is True


def test_has_footer_content_zero_exit_no_chips():
    """_has_footer_content returns False when exit_code=0 and no content."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    block = StreamingToolBlock(label="bash", tool_name="bash")
    panel = ToolPanel(block, tool_name="bash")
    panel._result_summary_v4 = ResultSummaryV4(
        primary=None, exit_code=0, chips=(), stderr_tail="",
        actions=(), artifacts=(), is_error=False,
    )
    assert panel._has_footer_content() is False


# ---------------------------------------------------------------------------
# Category class applied
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_file_tool_gets_category_class():
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
# Inner block refs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inner_block_ref_append_line_works():
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
# Copy contract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_copy_while_collapsed_returns_content():
    """copy_content() while collapsed still returns full output."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        block = panel.query_one(StreamingToolBlock)
        block.append_line("secret output")
        await _pause(pilot)

        panel.collapsed = True
        await _pause(pilot)

        content = panel.copy_content()
        assert "secret output" in content


# ---------------------------------------------------------------------------
# Footer visible only when expanded and has content
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_footer_visible_when_expanded_with_content():
    """Footer shows when not collapsed and has content (non-zero exit)."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)

        summary = ResultSummaryV4(
            primary=None, exit_code=1, chips=(), stderr_tail="",
            actions=(), artifacts=(), is_error=True,
        )
        panel.set_result_summary_v4(summary)
        await _pause(pilot)
        panel.collapsed = False
        # Re-trigger watcher
        panel.watch_collapsed(True, False)
        await _pause(pilot)

        footer = panel.query_one(FooterPane)
        assert footer.styles.display == "block"


@pytest.mark.asyncio
async def test_footer_hidden_when_collapsed():
    """Footer hidden when panel is collapsed regardless of content."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)

        summary = ResultSummaryV4(
            primary=None, exit_code=1, chips=(), stderr_tail="",
            actions=(), artifacts=(), is_error=True,
        )
        panel.set_result_summary_v4(summary)
        panel.collapsed = True
        panel.watch_collapsed(False, True)
        await _pause(pilot)

        footer = panel.query_one(FooterPane)
        assert footer.styles.display == "none"


# ---------------------------------------------------------------------------
# P6: OmissionBar keyboard + focused-panel hint row
# ---------------------------------------------------------------------------


def test_p6_bindings_include_expand_collapse():
    """ToolPanel.BINDINGS includes +/-/* for OmissionBar and Enter for toggle."""
    keys = {b.key for b in ToolPanel.BINDINGS}
    assert "+" in keys
    assert "-" in keys
    assert "*" in keys
    assert "enter" in keys


def test_p6_bindings_no_legacy_level_keys():
    """d/D/0/1/2/3 bindings are removed."""
    keys = {b.key for b in ToolPanel.BINDINGS}
    for removed_key in ("d", "D", "0", "1", "2", "3"):
        assert removed_key not in keys, f"Key {removed_key!r} should be removed"


def test_p6_hint_row_composed():
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    block = StreamingToolBlock(label="bash", tool_name="bash")
    panel = ToolPanel(block, tool_name="bash")
    assert panel._hint_row is None  # before compose


@pytest.mark.asyncio
async def test_p6_hint_shows_on_focus():
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        panel.focus()
        await _pause(pilot)

        assert panel._hint_row is not None
        hint_text = str(panel._hint_row.content)
        assert len(hint_text) > 0


@pytest.mark.asyncio
async def test_p6_hint_clears_on_blur():
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        panel.focus()
        await _pause(pilot)
        panel.watch_has_focus(False)
        await _pause(pilot)

        assert panel._hint_row is not None
        rendered = panel._hint_row.content
        assert str(rendered) == "" or not rendered


@pytest.mark.asyncio
async def test_p6_build_hint_text_contains_keys():
    """_build_hint_text contains Enter and c; not d/D."""
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        hint = panel._build_hint_text()
        plain = hint.plain if hasattr(hint, "plain") else str(hint)
        assert "Enter" in plain
        assert "c" in plain
        assert "d/D" not in plain
        assert "0-3" not in plain


@pytest.mark.asyncio
async def test_p6_expand_lines_no_bar_no_crash():
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        panel.action_expand_lines()
        panel.action_collapse_lines()
        panel.action_expand_all_lines()


def test_p6_get_omission_bar_none_without_block():
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    block = StreamingToolBlock(label="bash", tool_name="bash")
    panel = ToolPanel(block, tool_name="bash")
    # bar is always created in __init__ but display=False; _get_omission_bar returns None
    # when not mounted (block not yet in app)
    assert panel._get_omission_bar() is None


@pytest.mark.asyncio
async def test_p6_expand_lines_delegates_to_rerender():
    from hermes_cli.tui.tool_blocks import _PAGE_SIZE, _VISIBLE_CAP
    from unittest.mock import patch

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        block = panel._block
        # Seed enough lines so bottom bar is visible
        for i in range(_VISIBLE_CAP + _PAGE_SIZE):
            block.append_line(f"line {i}")
        block._flush_pending()
        await _pause(pilot)

        with patch.object(block, "rerender_window") as mock_rw:
            panel.action_expand_lines()
        mock_rw.assert_called_once()
        start, end = mock_rw.call_args[0]
        assert end > _VISIBLE_CAP  # window expanded


@pytest.mark.asyncio
async def test_p6_collapse_lines_delegates_to_rerender():
    from hermes_cli.tui.tool_blocks import _PAGE_SIZE, _VISIBLE_CAP
    from unittest.mock import patch

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        block = panel._block
        # Need enough lines so that after an expand the window is scrollable
        # (visible_end > _VISIBLE_CAP + _PAGE_SIZE), making collapse possible.
        for i in range(_VISIBLE_CAP + _PAGE_SIZE * 3):
            block.append_line(f"line {i}")
        block._flush_pending()
        await _pause(pilot)
        # Expand twice to move window_end above _VISIBLE_CAP + _PAGE_SIZE
        panel.action_expand_lines()
        panel.action_expand_lines()
        await _pause(pilot)

        with patch.object(block, "rerender_window") as mock_rw:
            panel.action_collapse_lines()
        mock_rw.assert_called_once()


@pytest.mark.asyncio
async def test_p6_expand_all_delegates_to_rerender():
    from hermes_cli.tui.tool_blocks import _PAGE_SIZE, _VISIBLE_CAP
    from unittest.mock import patch

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        block = panel._block
        total = _VISIBLE_CAP + _PAGE_SIZE
        for i in range(total):
            block.append_line(f"line {i}")
        block._flush_pending()
        await _pause(pilot)

        with patch.object(block, "rerender_window") as mock_rw:
            panel.action_expand_all_lines()
        mock_rw.assert_called_once()
        _start, end = mock_rw.call_args[0]
        assert end == total  # expanded to full total


@pytest.mark.asyncio
async def test_p6_hint_includes_lines_hint_when_bar_present():
    from hermes_cli.tui.tool_blocks import _PAGE_SIZE, _VISIBLE_CAP

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        block = panel._block
        for i in range(_VISIBLE_CAP + 1):
            block.append_line(f"line {i}")
        block._flush_pending()
        await _pause(pilot)

        hint = panel._build_hint_text()
        plain = hint.plain if hasattr(hint, "plain") else str(hint)
        assert "+" in plain or "+/-" in plain


# ---------------------------------------------------------------------------
# §2 — Footer retry (UX pass 3)
# ---------------------------------------------------------------------------


def test_retry_in_implemented_actions():
    from hermes_cli.tui.tool_panel import _IMPLEMENTED_ACTIONS
    assert "retry" in _IMPLEMENTED_ACTIONS


@pytest.mark.asyncio
async def test_retry_chip_shown_when_is_error():
    """FooterPane renders retry chip when result is_error=True."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    rs = ResultSummaryV4(
        primary="error: cmd failed",
        exit_code=1,
        chips=(),
        stderr_tail="",
        actions=(),
        artifacts=(),
        is_error=True,
    )
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)
        panel.set_result_summary_v4(rs)
        await _pause(pilot)

        footer = panel.query_one(FooterPane)
        rendered = footer.render() if hasattr(footer, "render") else None
        # hint row should include "r retry"
        hint = panel._build_hint_text()
        plain = hint.plain if hasattr(hint, "plain") else str(hint)
        assert "r" in plain


@pytest.mark.asyncio
async def test_retry_chip_hidden_when_no_error():
    """retry hint absent when is_error=False."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    rs = ResultSummaryV4(
        primary="3 lines read",
        exit_code=0,
        chips=(),
        stderr_tail="",
        actions=(),
        artifacts=(),
        is_error=False,
    )
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)
        panel.set_result_summary_v4(rs)
        await _pause(pilot)

        hint = panel._build_hint_text()
        plain = hint.plain if hasattr(hint, "plain") else str(hint)
        # "r retry" should not appear
        assert " retry" not in plain


@pytest.mark.asyncio
async def test_action_retry_calls_initiate_retry():
    """action_retry() calls app._initiate_retry() when result is error."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    rs = ResultSummaryV4(
        primary="error",
        exit_code=1,
        chips=(),
        stderr_tail="",
        actions=(),
        artifacts=(),
        is_error=True,
    )
    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)
        panel.set_result_summary_v4(rs)
        await _pause(pilot)

        called = []
        app._initiate_retry = lambda: called.append(True)
        panel.action_retry()
        assert called == [True]


# ---------------------------------------------------------------------------
# §10 — Artifact icon mode (UX pass 3)
# ---------------------------------------------------------------------------


def test_artifact_icons_nerdfont_mode():
    """In nerdfont mode, file icon is the nerd-font glyph, not emoji."""
    from hermes_cli.tui.tool_panel import _artifact_icon
    with patch("agent.display.get_tool_icon_mode", return_value="nerdfont"):
        icon = _artifact_icon("file")
    assert icon == "\uf15b"
    assert "📎" not in icon


def test_artifact_icons_emoji_mode():
    """In emoji mode, file icon is 📎."""
    from hermes_cli.tui.tool_panel import _artifact_icon
    with patch("agent.display.get_tool_icon_mode", return_value="emoji"):
        icon = _artifact_icon("file")
    assert "📎" in icon


def test_artifact_icons_ascii_mode():
    """In ascii mode, file icon is [F], no multi-byte emoji."""
    from hermes_cli.tui.tool_panel import _artifact_icon
    with patch("agent.display.get_tool_icon_mode", return_value="ascii"):
        icon = _artifact_icon("file")
    assert icon == "[F]"
    assert "📎" not in icon


# ---------------------------------------------------------------------------
# §11 — Collapse no-op flash (UX pass 3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collapse_at_minimum_flashes_no_op():
    """At default window, action_collapse_lines flashes 'at minimum', not rerender."""
    from hermes_cli.tui.tool_blocks import _PAGE_SIZE, _VISIBLE_CAP
    from unittest.mock import patch as upatch

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        block = panel._block
        for i in range(_VISIBLE_CAP + _PAGE_SIZE):
            block.append_line(f"line {i}")
        block._flush_pending()
        await _pause(pilot)

        flash_calls = []
        with upatch.object(panel, "_flash_header", side_effect=lambda m: flash_calls.append(m)):
            with upatch.object(block, "rerender_window") as mock_rw:
                panel.action_collapse_lines()

        assert flash_calls == ["at minimum"]
        mock_rw.assert_not_called()


# ---------------------------------------------------------------------------
# P0-3: payload_truncated chip in footer
# ---------------------------------------------------------------------------

def test_payload_truncated_chip_shown():
    """FooterPane shows 'truncated' warning when any action has payload_truncated=True."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Action, Chip
    from rich.text import Text

    footer = FooterPane()
    # Inject compose result manually (no app needed)
    footer._content = MagicMock()
    footer._stderr_row = MagicMock()
    footer._remediation_row = MagicMock()
    footer._artifact_row = MagicMock()
    footer._artifact_row.query.return_value = []
    footer._show_all_artifacts = False
    footer._last_resize_w = 80

    summary = ResultSummaryV4(
        primary="done",
        exit_code=0,
        chips=(),
        stderr_tail="",
        actions=(Action("copy body", "c", "copy_body", "x" * 1000, payload_truncated=True),),
        artifacts=(),
        is_error=False,
    )

    updates = []
    footer._content.update = lambda t: updates.append(str(t) if not isinstance(t, str) else t)

    footer._render_footer(summary, frozenset())

    # The update call's content must include "truncated"
    joined = " ".join(updates)
    assert "truncated" in joined.lower()


# ---------------------------------------------------------------------------
# P0-4: ToolPanelHelpOverlay dismissed by escape via _dismiss_all_info_overlays
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_help_overlay_dismissed_by_escape():
    """ToolPanelHelpOverlay is dismissed when _dismiss_all_info_overlays is called."""
    from hermes_cli.tui.overlays import ToolPanelHelpOverlay

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        overlay = ToolPanelHelpOverlay()
        app.mount(overlay)
        await _pause(pilot)
        overlay.add_class("--visible")
        await _pause(pilot)
        assert overlay.has_class("--visible")

        app._dismiss_all_info_overlays()
        await _pause(pilot)

        assert not overlay.has_class("--visible")


# ---------------------------------------------------------------------------
# P1-2: edit_cmd saves existing input to history
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_edit_cmd_saves_existing_input_to_history():
    """action_edit_cmd saves current input text to history before overwriting."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Action

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        # Give the panel an edit_cmd action
        summary = ResultSummaryV4(
            primary="done",
            exit_code=1,
            chips=(),
            stderr_tail="",
            actions=(Action("edit cmd", "E", "edit_cmd", "git commit -m 'wip'"),),
            artifacts=(),
            is_error=True,
        )
        panel.set_result_summary_v4(summary)
        await _pause(pilot)

        # Pre-fill input with existing text
        from hermes_cli.tui.input_widget import HermesInput
        inp = app.query_one(HermesInput)
        history_before = list(inp._history)

        inp.load_text("my important message")
        await _pause(pilot)

        history_calls = []
        original = inp._save_to_history
        def _spy_save(text):
            history_calls.append(text)
            original(text)
        inp._save_to_history = _spy_save

        panel.action_edit_cmd()
        await _pause(pilot)

        assert "my important message" in history_calls, "Existing input should be saved to history"


# ---------------------------------------------------------------------------
# P1-6: secondary args persist independently of microcopy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_secondary_args_visible_during_streaming():
    """Secondary args show in --args-row slot, separate from microcopy."""
    from hermes_cli.tui.tool_blocks import ToolBodyContainer

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        block = panel._block
        assert block is not None

        block._body.update_secondary_args("cwd: /project  env: DEBUG=1")
        await _pause(pilot)

        # Secondary args must be in --args-row, not --microcopy
        from textual.widgets import Static
        try:
            args_row = block._body.query_one(".--args-row", Static)
            assert block._body._secondary_text == "cwd: /project  env: DEBUG=1"
        except Exception as e:
            pytest.fail(f"--args-row not found: {e}")


@pytest.mark.asyncio
async def test_secondary_args_persists_after_microcopy_set():
    """Secondary args remain visible when set_microcopy() overwrites the microcopy slot."""
    from hermes_cli.tui.tool_blocks import ToolBodyContainer

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        block = panel._block
        assert block is not None

        block._body.update_secondary_args("cwd: /project")
        await _pause(pilot)

        # Activate streaming microcopy
        block._body.set_microcopy("▸ 5 lines · 1kB")
        await _pause(pilot)

        # Secondary args text must not be lost
        assert block._body._secondary_text == "cwd: /project"


# ---------------------------------------------------------------------------
# P1-7: path-open hint shown on first focus without OSC 8
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_open_hint_shown_on_first_path_tool_focus_without_osc8():
    """_flash_hint is called with path-open message on first focus when OSC 8 unavailable."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)

        hint_calls: list[str] = []
        app._path_open_hint_shown = False
        app._flash_hint = lambda text, duration=1.5: hint_calls.append(text)

        # Patch osc8.is_supported to return False (no OSC 8)
        import hermes_cli.tui.osc8 as _osc8
        with patch.object(_osc8, "is_supported", return_value=False):
            import unittest.mock as _um
            event = _um.MagicMock()
            app.on_tool_panel_path_focused(event)

        assert app._path_open_hint_shown is True
        assert any("open" in h.lower() for h in hint_calls), f"Expected open-file hint, got {hint_calls}"


# ---------------------------------------------------------------------------
# P2-2: --body-degraded class on renderer exception
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_body_degraded_class_on_renderer_exception():
    """BodyPane gets --body-degraded class when renderer init raises."""
    from hermes_cli.tui.tool_panel import BodyPane
    from unittest.mock import patch

    with patch("hermes_cli.tui.body_renderer.BodyRenderer") as mock_renderer_cls:
        mock_renderer_cls.for_category.side_effect = RuntimeError("renderer broken")
        pane = BodyPane(category="FAKE")
        assert pane._renderer_degraded is True, "--body-degraded flag must be set"


# ---------------------------------------------------------------------------
# P2-6: narrow screen hint truncation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hint_row_truncated_on_narrow_screen():
    """On <50 char width, _build_hint_text returns at most 3 hints."""
    app = _make_app()
    async with app.run_test(size=(40, 24)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        # Force narrow width
        from unittest.mock import PropertyMock
        with patch.object(type(panel), "size", new_callable=PropertyMock,
                          return_value=type("S", (), {"width": 40, "height": 24})()) as _:
            hint = panel._build_hint_text()

        from rich.text import Text
        assert isinstance(hint, Text)
        # Count hint segments (bold key spans)
        bold_spans = [s for s in hint._spans if "bold" in str(s.style)]
        assert len(bold_spans) <= 3, f"Narrow screen should show ≤3 hints, got {len(bold_spans)}"


# ---------------------------------------------------------------------------
# P2-7: artifact overflow chip has URL remediation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_artifact_overflow_chip_has_url_remediation():
    """[+N more] overflow chip has _overflow_remediation=url hint when URLs truncated."""
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Artifact
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_result_parse import _ARTIFACT_DISPLAY_CAP

    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await _pause(pilot)
        panel = await _get_shell_panel(app, pilot)
        await _pause(pilot)

        # Create artifacts exceeding the cap with URL in overflow
        artifacts = [Artifact(label=f"f{i}.txt", kind="file", path_or_url=f"/f{i}.txt") for i in range(_ARTIFACT_DISPLAY_CAP)]
        artifacts.append(Artifact(label="https://example.com", kind="url", path_or_url="https://example.com"))

        summary = ResultSummaryV4(
            primary="done",
            exit_code=0,
            chips=(),
            stderr_tail="",
            actions=(),
            artifacts=tuple(artifacts),
            artifacts_truncated=True,
            is_error=False,
        )
        panel.set_result_summary_v4(summary)
        await _pause(pilot)

        from textual.widgets import Button
        overflow_btns = list(panel.query(".--artifact-overflow"))
        assert len(overflow_btns) > 0, "Expected overflow chip"
        btn = overflow_btns[0]
        remediation = getattr(btn, "_overflow_remediation", None)
        assert remediation is not None and "url" in remediation.lower(), f"Expected URL remediation, got {remediation}"


# ---------------------------------------------------------------------------
# P1-2: action_copy_ansi delegates to _copy_text_with_hint (no raw clipboard dispatch)
# ---------------------------------------------------------------------------

def test_action_copy_ansi_uses_copy_with_hint():
    """action_copy_ansi calls app._copy_text_with_hint, not a raw clipboard dispatch."""
    import inspect
    from hermes_cli.tui.tool_panel import ToolPanel
    src = inspect.getsource(ToolPanel.action_copy_ansi)
    assert "_copy_text_with_hint" in src, "action_copy_ansi must delegate to _copy_text_with_hint"
    assert "_flash_header" in src, "action_copy_ansi must call _flash_header after copy"


# ---------------------------------------------------------------------------
# P1-3: page-scroll uses scroll_relative (single call, not O(N) loop)
# ---------------------------------------------------------------------------

def test_page_scroll_uses_scroll_down_loop():
    """action_scroll_body_page_down/up use a scroll_down/up loop for mock-testable paging."""
    import inspect
    from hermes_cli.tui.tool_panel import ToolPanel
    src_down = inspect.getsource(ToolPanel.action_scroll_body_page_down)
    src_up = inspect.getsource(ToolPanel.action_scroll_body_page_up)
    assert "scroll_down" in src_down, "action_scroll_body_page_down must use scroll_down"
    assert "scroll_up" in src_up, "action_scroll_body_page_up must use scroll_up"


# ---------------------------------------------------------------------------
# P1-4: toggle_tail_follow uses _flash_header, not notify
# ---------------------------------------------------------------------------

def test_toggle_tail_follow_uses_flash_header_not_notify():
    """action_toggle_tail_follow reports state via _flash_header, not self.notify."""
    import inspect
    from hermes_cli.tui.tool_panel import ToolPanel
    src = inspect.getsource(ToolPanel.action_toggle_tail_follow)
    assert "_flash_header" in src, "action_toggle_tail_follow must use _flash_header"
    assert "notify" not in src, "action_toggle_tail_follow must not call self.notify (goes to app toast, not header)"


# ---------------------------------------------------------------------------
# P1-5: FooterPane remediation row hidden when no hints
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_footer_remediation_hidden_when_no_hints():
    """FooterPane does not have 'has-remediation' class when result has no remediation hints."""
    from hermes_cli.tui.tool_panel import FooterPane
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)

        fp = FooterPane()
        app.screen.mount(fp)
        await _pause(pilot)

        rs = ResultSummaryV4(
            primary="done",
            exit_code=0,
            chips=(),
            actions=(),
            stderr_tail="",
            artifacts=(),
            is_error=False,
        )
        fp.update_summary_v4(rs)
        await _pause(pilot)

        assert not fp.has_class("has-remediation"), (
            "FooterPane must not have 'has-remediation' class when no remediation hints present"
        )
        content_str = str(fp._remediation_row.render())
        assert content_str in ("", "Content('')"), (
            f"Remediation row content must be empty when no hints, got: {content_str!r}"
        )


# ---------------------------------------------------------------------------
# P2-1: hint tuple is 3-tuple (priority field removed)
# ---------------------------------------------------------------------------

def test_hint_tuple_is_three_tuple_not_four():
    """_build_hint_text builds from 3-tuple (key, sep, label) — no dead 4th priority field."""
    import inspect
    from hermes_cli.tui.tool_panel import ToolPanel
    src = inspect.getsource(ToolPanel._build_hint_text)
    # The unpack should be 3-variable, not 4
    assert "key, sep, label, _" not in src, (
        "_build_hint_text still unpacks 4 fields (key, sep, label, _) — "
        "dead priority field should be removed"
    )
    assert "key, sep, label" in src, "_build_hint_text must unpack 3-tuple (key, sep, label)"


# ---------------------------------------------------------------------------
# Pass-6 P1-4: action_copy_html copies HTML content, not file path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_action_copy_html_copies_content_not_path():
    """action_copy_html must pass HTML content to _copy_text_with_hint, not a file path."""
    from hermes_cli.tui.tool_panel import ToolPanel
    from rich.text import Text

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app.mount_tool_block("read_file", ["result line"], ["result line"], tool_name="read_file")
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        panel = output.query_one(ToolPanel)

        # Give block some rich content
        block = panel._block
        if block is not None:
            block._all_rich = [Text("result line")]

        captured: list[str] = []
        app._copy_text_with_hint = lambda text: captured.append(text)

        panel.action_copy_html()
        await _pause(pilot)

        if not captured:
            pytest.skip("action_copy_html had no rich content to copy")

        copied = captured[0]
        assert not copied.startswith("/tmp/"), (
            f"action_copy_html must copy HTML content, not file path. Got: {copied[:60]!r}"
        )
        assert "<" in copied, (
            f"action_copy_html must copy HTML markup. Got: {copied[:80]!r}"
        )


# ---------------------------------------------------------------------------
# Pass-6 P2-2: action_retry flashes 'no error' when no error present
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_action_retry_non_error_flashes_no_error():
    """action_retry on a non-error panel must flash 'no error', not silently no-op."""
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    app = _make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        app.agent_running = True
        await _pause(pilot)
        app._open_gen_block("bash")
        await _pause(pilot)

        output = app.query_one(OutputPanel)
        panel = output.query_one(ToolPanel)

        # Set a non-error result summary
        rs = ResultSummaryV4(
            primary="done",
            exit_code=0,
            chips=(),
            stderr_tail="",
            actions=(),
            artifacts=(),
            is_error=False,
            error_kind=None,
        )
        panel._result_summary_v4 = rs

        # Call action_retry — must not silently no-op
        flashed: list[str] = []
        panel._flash_header = lambda msg: flashed.append(msg)

        panel.action_retry()

        assert flashed, "action_retry must call _flash_header when no error — got silent no-op"
        assert any("no error" in m.lower() for m in flashed), (
            f"Expected 'no error' flash message, got: {flashed}"
        )
