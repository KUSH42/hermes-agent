"""Phase 4 Phase 2 tests — B1/B2/B3/C1/D2/E1/H1."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_spec(name: str = "mcp__myserver__tool", provenance: str | None = None, category_val: str = "mcp"):
    from hermes_cli.tui.tool_category import ToolSpec, ToolCategory
    cat_map = {
        "mcp": ToolCategory.MCP,
        "shell": ToolCategory.SHELL,
        "file": ToolCategory.FILE,
        "unknown": ToolCategory.UNKNOWN,
    }
    cat = cat_map.get(category_val, ToolCategory.UNKNOWN)
    return ToolSpec(name=name, category=cat, primary_arg=None, primary_result="none", provenance=provenance)


def _make_parse_ctx(raw: str = "", is_error: bool = True, error_kind: str | None = None, name: str = "mcp__s__t", provenance: str | None = None):
    from hermes_cli.tui.tool_result_parse import ParseContext, ToolStart, ToolComplete
    start = ToolStart(name=name, args={})
    complete = ToolComplete(name=name, raw_result=raw, is_error=is_error, error_kind=error_kind)
    spec = _make_spec(name=name, provenance=provenance)
    return ParseContext(complete=complete, start=start, spec=spec)


# ---------------------------------------------------------------------------
# B1 — Error-kind icon in tool icon slot
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_error_kind_timeout_shows_clock_icon():
    """B1: _error_kind="timeout" with _tool_icon_error renders [T] in ascii mode."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    class _App(App):
        def compose(self) -> ComposeResult:
            yield StreamingToolBlock(label="mytool", tool_name="mytool")

    with patch("agent.display.get_tool_icon_mode", return_value="ascii"):
        async with _App().run_test() as pilot:
            block = pilot.app.query_one(StreamingToolBlock)
            header = block._header
            header._tool_icon = "\uf489"  # original category icon
            header._tool_icon_error = True
            header._error_kind = "timeout"
            header._is_complete = True

            from hermes_cli.tui.tool_result_parse import _error_kind_display
            ek_icon, _, _ = _error_kind_display("timeout", "", "ascii")
            assert ek_icon == "[T]"

            await pilot.pause(0.05)
            from rich.text import Text
            rendered = header._render_v4()
            plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
            assert "[T]" in plain


@pytest.mark.asyncio
async def test_error_kind_exit_shows_exit_icon():
    """B1: _error_kind="exit" with _tool_icon_error renders [X] in ascii mode."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    class _App(App):
        def compose(self) -> ComposeResult:
            yield StreamingToolBlock(label="mytool", tool_name="mytool")

    with patch("agent.display.get_tool_icon_mode", return_value="ascii"):
        async with _App().run_test() as pilot:
            block = pilot.app.query_one(StreamingToolBlock)
            header = block._header
            header._tool_icon = "\uf489"
            header._tool_icon_error = True
            header._error_kind = "exit"
            header._is_complete = True

            from hermes_cli.tui.tool_result_parse import _error_kind_display
            ek_icon, _, _ = _error_kind_display("exit", "", "ascii")
            assert ek_icon == "[X]"

            await pilot.pause(0.05)
            rendered = header._render_v4()
            plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
            assert "[X]" in plain


@pytest.mark.asyncio
async def test_success_keeps_category_icon():
    """B1: no error → category icon stays in icon slot (not overridden)."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    class _App(App):
        def compose(self) -> ComposeResult:
            yield StreamingToolBlock(label="mytool", tool_name="mytool")

    async with _App().run_test() as pilot:
        block = pilot.app.query_one(StreamingToolBlock)
        header = block._header
        header._tool_icon = "[MY]"
        header._tool_icon_error = False
        header._error_kind = None
        header._is_complete = True

        await pilot.pause(0.05)
        rendered = header._render_v4()
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        assert "[MY]" in plain


# ---------------------------------------------------------------------------
# B2 — Suppress {N}L tail when primary hero set
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_line_count_suppressed_when_primary_hero_set():
    """B2: 42L not shown in header when _primary_hero is set."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    class _App(App):
        def compose(self) -> ComposeResult:
            yield StreamingToolBlock(label="mytool", tool_name="mytool")

    async with _App().run_test() as pilot:
        block = pilot.app.query_one(StreamingToolBlock)
        header = block._header
        header._line_count = 42
        header._primary_hero = "✓ 42 lines"
        header._is_complete = True
        header._spinner_char = None
        header._stats = None

        await pilot.pause(0.05)
        rendered = header._render_v4()
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        assert "42L" not in plain


@pytest.mark.asyncio
async def test_line_count_shown_when_no_hero():
    """B2: 42L shown when _primary_hero is None."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    class _App(App):
        def compose(self) -> ComposeResult:
            yield StreamingToolBlock(label="mytool", tool_name="mytool")

    async with _App().run_test() as pilot:
        block = pilot.app.query_one(StreamingToolBlock)
        header = block._header
        header._line_count = 42
        header._primary_hero = None
        header._is_complete = True
        header._spinner_char = None
        header._stats = None

        await pilot.pause(0.05)
        rendered = header._render_v4()
        plain = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        assert "42L" in plain


# ---------------------------------------------------------------------------
# B3 — MCP streaming microcopy fallback
# ---------------------------------------------------------------------------

def test_mcp_microcopy_registered_provenance():
    """B3: spec with provenance='mcp:github' → 'github' in microcopy."""
    from hermes_cli.tui.streaming_microcopy import microcopy_line, StreamingState

    spec = _make_spec(name="github__search_repos", provenance="mcp:github", category_val="mcp")
    state = StreamingState(lines_received=0, bytes_received=0, elapsed_s=0.5)
    result = microcopy_line(spec, state)
    text = result.plain if hasattr(result, "plain") else str(result)
    assert "github" in text


def test_mcp_microcopy_unregistered_fallback():
    """B3: provenance=None, name with __ → last segment used, not '?'."""
    from hermes_cli.tui.streaming_microcopy import microcopy_line, StreamingState

    spec = _make_spec(name="mcp__myserver__tool", provenance=None, category_val="mcp")
    state = StreamingState(lines_received=0, bytes_received=0, elapsed_s=0.5)
    result = microcopy_line(spec, state)
    text = result.plain if hasattr(result, "plain") else str(result)
    assert "?" not in text
    assert ("tool" in text or "myserver" in text)


def test_mcp_microcopy_bare_name_fallback():
    """B3: provenance=None, name has no __ → bare name used."""
    from hermes_cli.tui.streaming_microcopy import microcopy_line, StreamingState

    spec = _make_spec(name="some_tool", provenance=None, category_val="mcp")
    state = StreamingState(lines_received=0, bytes_received=0, elapsed_s=0.5)
    result = microcopy_line(spec, state)
    text = result.plain if hasattr(result, "plain") else str(result)
    assert "some_tool" in text


# ---------------------------------------------------------------------------
# C1 — J/K page-scroll and </> top/bottom bindings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_action_scroll_body_page_down_calls_multiple_scrolls():
    """C1: action_scroll_body_page_down calls scroll_down multiple times."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.widgets import CopyableRichLog

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(
                block=StreamingToolBlock(label="bash", tool_name="bash"),
                tool_name="bash",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        await pilot.pause(0.05)

        mock_log = MagicMock(spec=CopyableRichLog)
        with patch.object(panel._block._body, "query_one", return_value=mock_log):
            panel.action_scroll_body_page_down()

        assert mock_log.scroll_down.call_count >= 5


@pytest.mark.asyncio
async def test_action_scroll_body_page_up_calls_multiple_scrolls():
    """C1: action_scroll_body_page_up calls scroll_up multiple times."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.widgets import CopyableRichLog

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(
                block=StreamingToolBlock(label="bash", tool_name="bash"),
                tool_name="bash",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        await pilot.pause(0.05)

        mock_log = MagicMock(spec=CopyableRichLog)
        with patch.object(panel._block._body, "query_one", return_value=mock_log):
            panel.action_scroll_body_page_up()

        assert mock_log.scroll_up.call_count >= 5


@pytest.mark.asyncio
async def test_action_scroll_body_top_calls_scroll_home():
    """C1: action_scroll_body_top calls scroll_home."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.widgets import CopyableRichLog

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(
                block=StreamingToolBlock(label="bash", tool_name="bash"),
                tool_name="bash",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        await pilot.pause(0.05)

        mock_log = MagicMock(spec=CopyableRichLog)
        with patch.object(panel._block._body, "query_one", return_value=mock_log):
            panel.action_scroll_body_top()

        mock_log.scroll_home.assert_called_once_with(animate=False)


@pytest.mark.asyncio
async def test_action_scroll_body_bottom_calls_scroll_end():
    """C1: action_scroll_body_bottom calls scroll_end."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.widgets import CopyableRichLog

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(
                block=StreamingToolBlock(label="bash", tool_name="bash"),
                tool_name="bash",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        await pilot.pause(0.05)

        mock_log = MagicMock(spec=CopyableRichLog)
        with patch.object(panel._block._body, "query_one", return_value=mock_log):
            panel.action_scroll_body_bottom()

        mock_log.scroll_end.assert_called_once_with(animate=False)


# ---------------------------------------------------------------------------
# D2 — Artifact chips as clickable Buttons
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_artifact_buttons_mounted_after_summary():
    """D2: setting summary with 1 artifact mounts a Button with --artifact-chip class."""
    from textual.app import App, ComposeResult
    from textual.widgets import Button
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel, FooterPane
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Chip, Artifact

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(
                block=StreamingToolBlock(label="tool", tool_name="tool"),
                tool_name="tool",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        await pilot.pause(0.05)

        summary = ResultSummaryV4(
            primary="✓ done", exit_code=0,
            chips=(), stderr_tail="", actions=(),
            artifacts=(Artifact(label="myfile.txt", path_or_url="/tmp/myfile.txt", kind="file"),),
            is_error=False,
        )
        with patch("agent.display.get_tool_icon_mode", return_value="ascii"):
            panel.set_result_summary(summary)
        await pilot.pause(0.1)

        footer = panel._footer_pane
        assert footer is not None
        chips = list(footer.query(".--artifact-chip"))
        assert len(chips) >= 1
        assert isinstance(chips[0], Button)


@pytest.mark.asyncio
async def test_artifact_overflow_button_shows_more():
    """D2: 6 artifacts with truncation → --artifact-overflow button present."""
    from textual.app import App, ComposeResult
    from textual.widgets import Button
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel, FooterPane
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Chip, Artifact

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(
                block=StreamingToolBlock(label="tool", tool_name="tool"),
                tool_name="tool",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        await pilot.pause(0.05)

        artifacts = tuple(
            Artifact(label=f"file{i}.txt", path_or_url=f"/tmp/file{i}.txt", kind="file")
            for i in range(6)
        )
        summary = ResultSummaryV4(
            primary="✓ done", exit_code=0,
            chips=(), stderr_tail="", actions=(),
            artifacts=artifacts,
            is_error=False,
            artifacts_truncated=True,
        )
        with patch("agent.display.get_tool_icon_mode", return_value="ascii"):
            panel.set_result_summary(summary)
        await pilot.pause(0.1)

        footer = panel._footer_pane
        assert footer is not None
        overflows = list(footer.query(".--artifact-overflow"))
        assert len(overflows) >= 1


@pytest.mark.asyncio
async def test_artifact_chip_click_opens_path():
    """D2: clicking --artifact-chip button triggers subprocess.Popen with artifact path."""
    import subprocess as _sp
    from textual.app import App, ComposeResult
    from textual.widgets import Button
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel, FooterPane
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Chip, Artifact

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(
                block=StreamingToolBlock(label="tool", tool_name="tool"),
                tool_name="tool",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        await pilot.pause(0.05)

        summary = ResultSummaryV4(
            primary="✓ done", exit_code=0,
            chips=(), stderr_tail="", actions=(),
            artifacts=(Artifact(label="myfile.txt", path_or_url="/tmp/myfile.txt", kind="file"),),
            is_error=False,
        )
        with patch("agent.display.get_tool_icon_mode", return_value="ascii"):
            panel.set_result_summary(summary)
        await pilot.pause(0.1)

        footer = panel._footer_pane
        chips = list(footer.query(".--artifact-chip"))
        assert len(chips) >= 1

        with patch("hermes_cli.tui.tool_panel._footer.safe_open_url") as mock_open:
            chip_btn = chips[0]
            # Simulate on_button_pressed directly on FooterPane
            event = MagicMock()
            event.button = chip_btn
            event.button.classes = chip_btn.classes
            footer.on_button_pressed(event)

        mock_open.assert_called_once()
        assert "/tmp/myfile.txt" in mock_open.call_args[0][1]


# ---------------------------------------------------------------------------
# E1 — ToolPanel ? help overlay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_action_show_help_mounts_overlay():
    """E1: action_show_help() shows ToolPanelHelpOverlay (pre-mounted, toggled via --visible)."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.overlays import ToolPanelHelpOverlay

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanelHelpOverlay()
            yield ToolPanel(
                block=StreamingToolBlock(label="bash", tool_name="bash"),
                tool_name="bash",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        await pilot.pause(0.05)

        panel.action_show_help()
        await pilot.pause(0.1)

        overlay = pilot.app.query_one(ToolPanelHelpOverlay)
        assert overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_action_show_help_toggle_removes_existing():
    """E1: calling action_show_help() twice hides the overlay on second call."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.overlays import ToolPanelHelpOverlay

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanelHelpOverlay()
            yield ToolPanel(
                block=StreamingToolBlock(label="bash", tool_name="bash"),
                tool_name="bash",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        await pilot.pause(0.05)

        # First call: show
        panel.action_show_help()
        await pilot.pause(0.1)

        # Second call: should hide
        panel.action_show_help()
        await pilot.pause(0.1)

        overlay = pilot.app.query_one(ToolPanelHelpOverlay)
        assert not overlay.has_class("--visible")


@pytest.mark.asyncio
async def test_help_overlay_dismissed_by_escape():
    """E1: pressing escape on ToolPanelHelpOverlay removes --visible class."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.overlays import ToolPanelHelpOverlay

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanelHelpOverlay()
            yield ToolPanel(
                block=StreamingToolBlock(label="bash", tool_name="bash"),
                tool_name="bash",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        await pilot.pause(0.05)

        panel.action_show_help()
        await pilot.pause(0.1)

        overlay = pilot.app.query_one(ToolPanelHelpOverlay)
        assert overlay.has_class("--visible")

        # Simulate key event on overlay
        key_event = MagicMock()
        key_event.key = "escape"
        key_event.stop = MagicMock()
        overlay.on_key(key_event)
        await pilot.pause(0.1)

        # Overlay stays in DOM but --visible removed
        assert not overlay.has_class("--visible")


# ---------------------------------------------------------------------------
# H1 — MCP parse/signal/timeout remediation hints
# ---------------------------------------------------------------------------

def test_mcp_parse_error_has_remediation():
    """H1: mcp_result_v4 with error_kind='parse' has remediation on error chip."""
    from hermes_cli.tui.tool_result_parse import mcp_result_v4

    ctx = _make_parse_ctx(raw='{"error": "bad json"}', is_error=True, error_kind="parse", name="mcp__s__t")
    result = mcp_result_v4(ctx)
    error_chips = [c for c in result.chips if c.tone == "error"]
    assert len(error_chips) >= 1
    remediations = [c.remediation for c in error_chips if getattr(c, "remediation", None)]
    assert len(remediations) >= 1
    assert "json" in remediations[0] or "server" in remediations[0]


def test_mcp_signal_error_has_remediation():
    """H1: mcp_result_v4 with error_kind='signal' has remediation on error chip."""
    from hermes_cli.tui.tool_result_parse import mcp_result_v4

    ctx = _make_parse_ctx(raw="killed", is_error=True, error_kind="signal", name="mcp__s__t")
    result = mcp_result_v4(ctx)
    error_chips = [c for c in result.chips if c.tone == "error"]
    remediations = [c.remediation for c in error_chips if getattr(c, "remediation", None)]
    assert len(remediations) >= 1
    assert "crash" in remediations[0] or "log" in remediations[0]


def test_mcp_timeout_error_has_remediation():
    """H1: mcp_result_v4 with error_kind='timeout' has remediation on error chip."""
    from hermes_cli.tui.tool_result_parse import mcp_result_v4

    ctx = _make_parse_ctx(raw="timed out", is_error=True, error_kind="timeout", name="mcp__s__t")
    result = mcp_result_v4(ctx)
    error_chips = [c for c in result.chips if c.tone == "error"]
    remediations = [c.remediation for c in error_chips if getattr(c, "remediation", None)]
    assert len(remediations) >= 1
    assert "timeout" in remediations[0] or "load" in remediations[0]


def test_mcp_disconnect_still_has_remediation():
    """H1: mcp_result_v4 with error_kind='disconnect' still has existing remediation."""
    from hermes_cli.tui.tool_result_parse import mcp_result_v4

    ctx = _make_parse_ctx(raw="", is_error=True, error_kind="disconnect", name="mcp__s__t")
    result = mcp_result_v4(ctx)
    error_chips = [c for c in result.chips if c.tone == "error"]
    remediations = [c.remediation for c in error_chips if getattr(c, "remediation", None)]
    assert len(remediations) >= 1
    assert "restart" in remediations[0] or "log" in remediations[0]
