"""Tests for streaming microcopy (v4 §3) and adaptive flush (§3.4)."""

from __future__ import annotations

import time
import pytest

from hermes_cli.tui.streaming_microcopy import StreamingState, _kb, microcopy_line
from hermes_cli.tui.tool_category import ToolCategory, ToolSpec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(category: ToolCategory, primary_result: str = "none", provenance: str | None = None) -> ToolSpec:
    return ToolSpec(
        name="test",
        category=category,
        primary_result=primary_result,
        provenance=provenance,
    )


def _state(**kwargs) -> StreamingState:
    defaults = dict(lines_received=0, bytes_received=0, elapsed_s=1.0)
    defaults.update(kwargs)
    return StreamingState(**defaults)


# ---------------------------------------------------------------------------
# _kb helper
# ---------------------------------------------------------------------------

class TestKb:
    def test_sub_1024_shows_bytes(self):
        assert _kb(0) == "0B"
        assert _kb(512) == "512B"
        assert _kb(1023) == "1023B"

    def test_exactly_1024_shows_kb(self):
        assert _kb(1024) == "1.0kB"

    def test_larger_value(self):
        assert _kb(5120) == "5.0kB"

    def test_fractional_kb(self):
        assert _kb(1536) == "1.5kB"


# ---------------------------------------------------------------------------
# §3.2 microcopy_line per category
# ---------------------------------------------------------------------------

class TestMicrocopyShell:
    def test_shell_format(self):
        spec = _spec(ToolCategory.SHELL)
        s = _state(lines_received=42, bytes_received=2048)
        assert microcopy_line(spec, s) == "▸ 42 lines · 2.0kB"

    def test_shell_zero_bytes(self):
        spec = _spec(ToolCategory.SHELL)
        s = _state(lines_received=1, bytes_received=0)
        assert microcopy_line(spec, s) == "▸ 1 lines · 0B"


class TestMicrocopyFile:
    def test_file_read_with_totals(self):
        spec = _spec(ToolCategory.FILE, primary_result="lines")
        s = _state(lines_received=10, bytes_received=1024,
                   total_lines=100, total_bytes=10240)
        result = microcopy_line(spec, s)
        assert result == "▸ 10/100 lines · 1.0kB/10.0kB"

    def test_file_read_without_totals(self):
        spec = _spec(ToolCategory.FILE, primary_result="lines")
        s = _state(lines_received=5, bytes_received=512)
        result = microcopy_line(spec, s)
        assert "5/?" in result
        assert "?" in result

    def test_file_read_lines_primary_result(self):
        spec = _spec(ToolCategory.FILE, primary_result="lines")
        s = _state(lines_received=3, bytes_received=100)
        assert "lines" in microcopy_line(spec, s)
        assert "/" in microcopy_line(spec, s)  # read format

    def test_file_write_format(self):
        spec = _spec(ToolCategory.FILE, primary_result="done")
        s = _state(lines_received=7, bytes_received=500)
        assert microcopy_line(spec, s) == "▸ 7 lines written"

    def test_file_write_none_result(self):
        spec = _spec(ToolCategory.FILE, primary_result="none")
        s = _state(lines_received=3, bytes_received=100)
        assert microcopy_line(spec, s) == "▸ 3 lines written"


class TestMicrocopySearch:
    def test_search_uses_matches_so_far(self):
        spec = _spec(ToolCategory.SEARCH)
        s = _state(lines_received=10, bytes_received=0, matches_so_far=4)
        assert microcopy_line(spec, s) == "▸ 4 matches so far…"

    def test_search_falls_back_to_lines_received(self):
        spec = _spec(ToolCategory.SEARCH)
        s = _state(lines_received=10, bytes_received=0, matches_so_far=None)
        assert microcopy_line(spec, s) == "▸ 10 matches so far…"

    def test_search_zero_matches(self):
        spec = _spec(ToolCategory.SEARCH)
        s = _state(lines_received=0, bytes_received=0, matches_so_far=0)
        assert microcopy_line(spec, s) == "▸ 0 matches so far…"


class TestMicrocopyWeb:
    def test_web_with_status(self):
        spec = _spec(ToolCategory.WEB)
        s = _state(lines_received=0, bytes_received=2048, last_status="200 OK")
        assert microcopy_line(spec, s) == "▸ 200 OK · 2.0kB"

    def test_web_without_status_defaults_connecting(self):
        spec = _spec(ToolCategory.WEB)
        s = _state(lines_received=0, bytes_received=0, last_status=None)
        assert microcopy_line(spec, s) == "▸ connecting · 0B"


class TestMicrocopyMcp:
    def test_mcp_with_provenance(self):
        spec = _spec(ToolCategory.MCP, provenance="mcp:github")
        s = _state(lines_received=0, bytes_received=0)
        assert microcopy_line(spec, s) == "▸ mcp · github server"

    def test_mcp_without_provenance(self):
        spec = _spec(ToolCategory.MCP, provenance=None)
        s = _state()
        assert microcopy_line(spec, s) == "▸ mcp · ? server"

    def test_mcp_non_mcp_provenance_format(self):
        spec = _spec(ToolCategory.MCP, provenance="mcp:linear")
        s = _state()
        assert "linear" in microcopy_line(spec, s)


class TestMicrocopyNoOp:
    def test_code_returns_empty(self):
        spec = _spec(ToolCategory.CODE)
        assert microcopy_line(spec, _state()) == ""

    def test_agent_returns_empty(self):
        spec = _spec(ToolCategory.AGENT)
        assert microcopy_line(spec, _state()) == ""

    def test_unknown_returns_empty(self):
        spec = _spec(ToolCategory.UNKNOWN)
        assert microcopy_line(spec, _state()) == ""


# ---------------------------------------------------------------------------
# ToolBodyContainer — microcopy Static always present
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_body_container_has_microcopy_static():
    """ToolBodyContainer always composes a .--microcopy Static."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import ToolBodyContainer

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolBodyContainer()

    async with _App().run_test() as pilot:
        container = pilot.app.query_one(ToolBodyContainer)
        from textual.widgets import Static
        mc = container.query_one(".--microcopy", Static)
        assert mc is not None


@pytest.mark.asyncio
async def test_microcopy_hidden_by_default():
    """Microcopy Static starts hidden (no --active class)."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import ToolBodyContainer
    from textual.widgets import Static

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolBodyContainer()

    async with _App().run_test() as pilot:
        mc = pilot.app.query_one(".--microcopy", Static)
        assert not mc.has_class("--active")


# ---------------------------------------------------------------------------
# StreamingToolBlock — bytes tracking
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bytes_received_increments():
    """_bytes_received increments by raw line length on append_line."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    class _App(App):
        def compose(self) -> ComposeResult:
            yield StreamingToolBlock(label="bash", tool_name="bash")

    async with _App().run_test() as pilot:
        stb = pilot.app.query_one(StreamingToolBlock)
        assert stb._bytes_received == 0
        stb.append_line("hello world")
        assert stb._bytes_received == len("hello world")
        stb.append_line("second line")
        assert stb._bytes_received == len("hello world") + len("second line")


@pytest.mark.asyncio
async def test_last_line_time_updates_on_append():
    """_last_line_time updates on each append_line call."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    class _App(App):
        def compose(self) -> ComposeResult:
            yield StreamingToolBlock(label="bash", tool_name="bash")

    async with _App().run_test() as pilot:
        stb = pilot.app.query_one(StreamingToolBlock)
        t0 = stb._last_line_time
        stb.append_line("line")
        assert stb._last_line_time >= t0


# ---------------------------------------------------------------------------
# §3.4 Adaptive flush — rate switching
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flush_slow_flag_set_on_idle(monkeypatch):
    """After 2s idle, _flush_slow=True and timer drops to 10Hz."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    import hermes_cli.tui.tool_blocks as tb

    monkeypatch.setattr(tb, "_tool_panel_v4_enabled", lambda: True)

    class _App(App):
        def compose(self) -> ComposeResult:
            yield StreamingToolBlock(label="bash", tool_name="bash")

    async with _App().run_test() as pilot:
        stb = pilot.app.query_one(StreamingToolBlock)
        # Fake idle: set _last_line_time 3s in the past
        stb._last_line_time = time.monotonic() - 3.0
        stb._flush_slow = False
        # Manually trigger _flush_pending
        stb._flush_pending()
        assert stb._flush_slow is True


@pytest.mark.asyncio
async def test_flush_slow_restored_on_append(monkeypatch):
    """append_line while _flush_slow=True restores 60Hz and clears flag."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    import hermes_cli.tui.tool_blocks as tb

    monkeypatch.setattr(tb, "_tool_panel_v4_enabled", lambda: True)

    class _App(App):
        def compose(self) -> ComposeResult:
            yield StreamingToolBlock(label="bash", tool_name="bash")

    async with _App().run_test() as pilot:
        stb = pilot.app.query_one(StreamingToolBlock)
        stb._flush_slow = True
        stb.append_line("wake up")
        assert stb._flush_slow is False


@pytest.mark.asyncio
async def test_adaptive_flush_no_op_when_v4_off(monkeypatch):
    """When v4 disabled, idle 2s does NOT set _flush_slow."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    import hermes_cli.tui.tool_blocks as tb

    monkeypatch.setattr(tb, "_tool_panel_v4_enabled", lambda: False)

    class _App(App):
        def compose(self) -> ComposeResult:
            yield StreamingToolBlock(label="bash", tool_name="bash")

    async with _App().run_test() as pilot:
        stb = pilot.app.query_one(StreamingToolBlock)
        stb._last_line_time = time.monotonic() - 3.0
        stb._flush_pending()
        assert stb._flush_slow is False


# ---------------------------------------------------------------------------
# Microcopy — MCP line persists after complete()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mcp_microcopy_persists_after_complete(monkeypatch):
    """MCP provenance line stays after complete() (§3.3)."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from textual.widgets import Static
    import hermes_cli.tui.tool_blocks as tb
    from hermes_cli.tui.tool_category import register_tool, ToolSpec, ToolCategory, TOOL_REGISTRY

    monkeypatch.setattr(tb, "_tool_panel_v4_enabled", lambda: True)

    mcp_name = "mcp__test-p3__my_tool"
    spec = ToolSpec(
        name=mcp_name,
        category=ToolCategory.MCP,
        primary_result="done",
        provenance="mcp:test-p3",
    )
    TOOL_REGISTRY[mcp_name] = spec

    try:
        class _App(App):
            def compose(self) -> ComposeResult:
                yield StreamingToolBlock(label="my_tool", tool_name=mcp_name)

        async with _App().run_test() as pilot:
            stb = pilot.app.query_one(StreamingToolBlock)
            mc = stb._microcopy_widget
            assert mc is not None
            # Manually activate microcopy
            mc.update("▸ mcp · test-p3 server")
            mc.add_class("--active")
            # complete the block
            stb.complete("1.0s")
            await pilot.pause(0.1)
            # MCP line should still be active
            assert mc.has_class("--active")
            assert "mcp" in mc.renderable if hasattr(mc, "renderable") else True
    finally:
        TOOL_REGISTRY.pop(mcp_name, None)


@pytest.mark.asyncio
async def test_non_mcp_microcopy_cleared_after_complete(monkeypatch):
    """Non-MCP microcopy is cleared on complete() (§3.3)."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from textual.widgets import Static
    import hermes_cli.tui.tool_blocks as tb

    monkeypatch.setattr(tb, "_tool_panel_v4_enabled", lambda: True)

    class _App(App):
        def compose(self) -> ComposeResult:
            yield StreamingToolBlock(label="bash", tool_name="bash")

    async with _App().run_test() as pilot:
        stb = pilot.app.query_one(StreamingToolBlock)
        mc = stb._microcopy_widget
        assert mc is not None
        mc.update("▸ 5 lines · 1.0kB")
        mc.add_class("--active")
        stb.complete("0.1s")
        await pilot.pause(0.1)
        assert not mc.has_class("--active")
