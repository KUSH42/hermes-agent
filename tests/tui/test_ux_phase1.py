"""Phase 1 UX improvements — tests.

A1: Error kind distinct icons
A3: Silent failure fallbacks
B1: Secondary args in microcopy slot
C1: Unified open_primary action
C2: j/k scroll in body
F1: Color + text status indicators
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# A1 — _error_kind_display
# ---------------------------------------------------------------------------

class TestErrorKindDisplay:
    def test_timeout_nerdfont_returns_timer_icon_and_var(self):
        from hermes_cli.tui.tool_result_parse import _error_kind_display
        icon, label, var = _error_kind_display("timeout", "timeout", "nerdfont")
        assert icon == "\U000f0513"
        assert label == "timeout"
        assert var == "error-timeout"

    def test_exit_emoji_returns_icon_and_critical_var(self):
        from hermes_cli.tui.tool_result_parse import _error_kind_display
        icon, label, var = _error_kind_display("exit", "exit 1", "emoji")
        assert icon == "💢"
        assert label == "exit 1"
        assert var == "error-critical"

    def test_signal_ascii_returns_k_marker(self):
        from hermes_cli.tui.tool_result_parse import _error_kind_display
        icon, label, var = _error_kind_display("signal", "signal 9", "ascii")
        assert icon == "[K]"
        assert var == "error-critical"

    def test_auth_returns_auth_var(self):
        from hermes_cli.tui.tool_result_parse import _error_kind_display
        icon, label, var = _error_kind_display("auth", "auth error", "ascii")
        assert icon == "[A]"
        assert var == "error-auth"

    def test_unknown_kind_falls_back_to_network(self):
        from hermes_cli.tui.tool_result_parse import _error_kind_display
        icon, label, var = _error_kind_display("zz_unknown", "mystery", "ascii")
        assert icon == "[W]"
        assert var == "error-network"

    def test_network_kind_returns_network_var(self):
        from hermes_cli.tui.tool_result_parse import _error_kind_display
        icon, label, var = _error_kind_display("network", "connection refused", "ascii")
        assert icon == "[W]"
        assert label == "connection refused"
        assert var == "error-network"

    def test_label_passthrough(self):
        from hermes_cli.tui.tool_result_parse import _error_kind_display
        _, label, _ = _error_kind_display("timeout", "my custom detail", "ascii")
        assert label == "my custom detail"


# ---------------------------------------------------------------------------
# A3 — Silent failure fallbacks
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_tool_icon_uses_ascii_fallback_on_error():
    """_refresh_tool_icon falls back to ASCII when get_tool_icon raises."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import ToolHeader

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolHeader(label="bash", line_count=5, tool_name="bash")

    async with _App().run_test() as pilot:
        header = pilot.app.query_one(ToolHeader)
        with patch("agent.display.get_tool_icon", side_effect=Exception("fail")):
            header._refresh_tool_icon()
        # Should be non-empty — ASCII fallback or "?"
        assert header._tool_icon != ""


@pytest.mark.asyncio
async def test_render_fallback_when_v4_returns_none():
    """render() produces non-empty Text when _render_v4 returns None."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import ToolHeader
    from rich.text import Text

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolHeader(label="bash", line_count=5, tool_name="bash")

    async with _App().run_test() as pilot:
        header = pilot.app.query_one(ToolHeader)
        with patch.object(header, "_render_v4", return_value=None):
            result = header.render()
        assert isinstance(result, Text)
        assert result.plain != ""


def test_body_pane_renderer_falls_back_to_plain_on_error():
    """BodyPane uses PlainBodyRenderer when BodyRenderer.for_category raises."""
    from hermes_cli.tui.tool_panel import BodyPane
    from hermes_cli.tui.body_renderers.streaming import PlainBodyRenderer
    from hermes_cli.tui.tool_category import ToolCategory

    with patch("hermes_cli.tui.body_renderers.streaming.StreamingBodyRenderer.for_category", side_effect=RuntimeError("fail")):
        pane = BodyPane(block=None, category=ToolCategory.SHELL)
    assert isinstance(pane._renderer, PlainBodyRenderer), (
        f"Expected PlainBodyRenderer fallback, got {type(pane._renderer)}"
    )


@pytest.mark.asyncio
async def test_diff_path_none_no_crash():
    """inject_diff with no +++ line leaves _diff_file_path=None; no exception."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    class _App(App):
        def compose(self) -> ComposeResult:
            yield StreamingToolBlock(label="diff", tool_name="bash")

    async with _App().run_test() as pilot:
        stb = pilot.app.query_one(StreamingToolBlock)
        # Diff content with no +++ line → path extraction yields None
        stb.inject_diff(["--- a/foo.py", "-old line", "+new line"], None)
        assert stb._diff_file_path is None
        # Header renders without crash
        result = stb._header.render()
        from rich.text import Text
        assert isinstance(result, Text)


# ---------------------------------------------------------------------------
# B1 — Secondary args in microcopy slot
# ---------------------------------------------------------------------------

def test_secondary_args_text_file_write():
    from hermes_cli.tui.tool_blocks import _secondary_args_text
    from hermes_cli.tui.tool_category import ToolCategory
    text = _secondary_args_text(ToolCategory.FILE, {"content": "hello\nworld"})
    assert "chars" in text
    assert "lines" in text


def test_secondary_args_text_file_read_with_offset():
    from hermes_cli.tui.tool_blocks import _secondary_args_text
    from hermes_cli.tui.tool_category import ToolCategory
    text = _secondary_args_text(ToolCategory.FILE, {"offset": 10, "limit": 50})
    assert "offset: 10" in text
    assert "limit: 50" in text


def test_secondary_args_text_shell_no_extras():
    from hermes_cli.tui.tool_blocks import _secondary_args_text
    from hermes_cli.tui.tool_category import ToolCategory
    text = _secondary_args_text(ToolCategory.SHELL, {"command": "ls"})
    assert text == ""


def test_secondary_args_text_shell_with_env():
    from hermes_cli.tui.tool_blocks import _secondary_args_text
    from hermes_cli.tui.tool_category import ToolCategory
    text = _secondary_args_text(ToolCategory.SHELL, {"command": "ls", "env": {"FOO": "bar"}})
    assert "env:" in text
    assert "FOO" in text


def test_secondary_args_text_search_with_glob():
    from hermes_cli.tui.tool_blocks import _secondary_args_text
    from hermes_cli.tui.tool_category import ToolCategory
    text = _secondary_args_text(ToolCategory.SEARCH, {"query": "foo", "glob": "*.py"})
    assert "glob: *.py" in text


def test_secondary_args_text_agent_truncated():
    from hermes_cli.tui.tool_blocks import _secondary_args_text
    from hermes_cli.tui.tool_category import ToolCategory
    long_task = "x" * 100
    text = _secondary_args_text(ToolCategory.AGENT, {"task": long_task})
    assert text.endswith("…")
    assert len(text) <= 82


@pytest.mark.asyncio
async def test_secondary_args_persists_after_complete():
    """After complete(), secondary args text is restored in microcopy slot."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_category import ToolCategory, ToolSpec, TOOL_REGISTRY

    tool_name = "write_file_test_b1"
    spec = ToolSpec(
        name=tool_name,
        category=ToolCategory.FILE,
        primary_result="diff",
        streaming=False,
    )
    TOOL_REGISTRY[tool_name] = spec

    try:
        class _App(App):
            def compose(self) -> ComposeResult:
                yield StreamingToolBlock(
                    label="test.py",
                    tool_name=tool_name,
                    tool_input={"content": "hello\nworld\n"},
                )

        async with _App().run_test() as pilot:
            stb = pilot.app.query_one(StreamingToolBlock)
            await pilot.pause(0.1)
            # After mount, secondary args should be visible
            mc = stb._microcopy_widget
            assert mc is not None
            # Complete the block
            stb.complete("0.1s")
            await pilot.pause(0.1)
            # Secondary args restored — body.clear_microcopy() should have put it back
            assert stb._body._secondary_text != ""
    finally:
        TOOL_REGISTRY.pop(tool_name, None)


# ---------------------------------------------------------------------------
# C1 — Unified open_primary action
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_action_open_primary_opens_header_path():
    """action_open_primary opens header path when path-clickable."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel

    class _App(App):
        def compose(self) -> ComposeResult:
            block = StreamingToolBlock(label="/tmp/test.py", tool_name="read_file")
            block._header.set_path("/tmp/test.py")
            yield ToolPanel(block=block, tool_name="read_file")

    opened_paths = []

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        pilot.app._open_path_action = lambda *a, **kw: opened_paths.append(a[1])
        panel.action_open_primary()
        assert len(opened_paths) == 1
        assert opened_paths[0] == "/tmp/test.py"


@pytest.mark.asyncio
async def test_action_open_primary_falls_back_to_artifact():
    """action_open_primary falls back to artifact when header not path-clickable."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Artifact

    class _App(App):
        def compose(self) -> ComposeResult:
            block = StreamingToolBlock(label="bash", tool_name="bash")
            yield ToolPanel(block=block, tool_name="bash")

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        summary = ResultSummaryV4(
            primary="✓ done", exit_code=0, chips=(), stderr_tail="",
            actions=(), is_error=False,
            artifacts=(Artifact(label="test.py", path_or_url="/tmp/test.py", kind="file"),),
        )
        panel.set_result_summary(summary)
        # No path on header — should fall back to artifact
        with patch("hermes_cli.tui.tool_panel.safe_open_url") as mock_open:
            panel.action_open_primary()
        assert mock_open.called
        assert "/tmp/test.py" in mock_open.call_args[0][1]


@pytest.mark.asyncio
async def test_action_open_primary_noop_when_no_path_no_artifact():
    """action_open_primary is a no-op when neither header path nor artifacts present."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(block=StreamingToolBlock(label="bash", tool_name="bash"), tool_name="bash")

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        with patch("hermes_cli.tui.tool_panel.safe_open_url") as mock_open:
            panel.action_open_primary()
        assert not mock_open.called


# ---------------------------------------------------------------------------
# C2 — j/k scroll
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_action_scroll_body_down_calls_scroll_down():
    """action_scroll_body_down calls scroll_down on CopyableRichLog."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.widgets import CopyableRichLog

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(block=StreamingToolBlock(label="bash", tool_name="bash"), tool_name="bash")

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        panel.collapsed = False
        log = panel.query_one(CopyableRichLog)
        called = []
        log.scroll_down = lambda animate=True: called.append("down")
        panel.action_scroll_body_down()
        assert "down" in called


@pytest.mark.asyncio
async def test_action_scroll_body_up_calls_scroll_up():
    """action_scroll_body_up calls scroll_up on CopyableRichLog."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.widgets import CopyableRichLog

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(block=StreamingToolBlock(label="bash", tool_name="bash"), tool_name="bash")

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        panel.collapsed = False
        log = panel.query_one(CopyableRichLog)
        called = []
        log.scroll_up = lambda animate=True: called.append("up")
        panel.action_scroll_body_up()
        assert "up" in called


# ---------------------------------------------------------------------------
# F1 — Color + text status indicators
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_accessible_mode_error_prefix():
    """In accessible mode, error state shows [!] prefix."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import ToolHeader
    from rich.text import Text

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolHeader(label="bash", line_count=5, tool_name="bash")

    with patch.dict(os.environ, {"HERMES_ACCESSIBLE": "1"}):
        async with _App().run_test() as pilot:
            header = pilot.app.query_one(ToolHeader)
            header._is_complete = True
            header._tool_icon_error = True
            result = header.render()
            assert isinstance(result, Text)
            assert "[!]" in result.plain


@pytest.mark.asyncio
async def test_accessible_mode_complete_prefix():
    """In accessible mode, complete state shows [✓] prefix."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import ToolHeader
    from rich.text import Text

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolHeader(label="bash", line_count=5, tool_name="bash")

    with patch.dict(os.environ, {"HERMES_ACCESSIBLE": "1"}):
        async with _App().run_test() as pilot:
            header = pilot.app.query_one(ToolHeader)
            header._is_complete = True
            header._tool_icon_error = False
            result = header.render()
            assert isinstance(result, Text)
            assert "[✓]" in result.plain


@pytest.mark.asyncio
async def test_normal_mode_no_accessible_prefix():
    """Without accessible mode, no [>]/[+]/[!] prefix in header."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import ToolHeader
    from rich.text import Text

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolHeader(label="bash", line_count=5, tool_name="bash")

    env_without = {k: v for k, v in os.environ.items() if k != "HERMES_ACCESSIBLE"}
    with patch.dict(os.environ, env_without, clear=True):
        async with _App().run_test() as pilot:
            header = pilot.app.query_one(ToolHeader)
            header._is_complete = True
            header._tool_icon_error = False
            with patch.object(header, "_accessible_mode", return_value=False):
                result = header.render()
            assert isinstance(result, Text)
            assert "[✓]" not in result.plain
            assert "[!]" not in result.plain
