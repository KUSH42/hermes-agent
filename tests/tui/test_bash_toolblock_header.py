"""BASHHDR-1 / BASHHDR-2 — Bash tool block header completeness.

Spec: 2026-05-09-bash-toolblock-header-completeness-spec.md

All tests mount StreamingToolBlock directly (no ToolPanel wrapper), so
_header_lifted=False and ToolHeader is children[0] in the block's own DOM.
"""
from __future__ import annotations

import sys
import pytest
from unittest.mock import patch

from textual.app import App, ComposeResult

from hermes_cli.tui.tool_blocks import StreamingToolBlock, ToolHeader


# ---------------------------------------------------------------------------
# Minimal host app — mounts a single bare STB (no ToolPanel, _header_lifted=False)
# ---------------------------------------------------------------------------

class _BashApp(App):
    """Host app that composes a single bash StreamingToolBlock directly."""

    def compose(self) -> ComposeResult:
        yield StreamingToolBlock("output", tool_name="bash")


# ---------------------------------------------------------------------------
# TestBashHeader — BASHHDR-1 (6 tests)
# ---------------------------------------------------------------------------

class TestBashHeader:

    @pytest.mark.asyncio
    async def test_bash_render_header_spec_flag(self):
        """spec_for("bash").render_header must be True — suppression guard cannot fire."""
        from hermes_cli.tui.tool_category import spec_for
        assert spec_for("bash").render_header is True

    @pytest.mark.asyncio
    async def test_bash_header_present_started(self):
        """STARTED state: ToolHeader is first child with non-zero height."""
        async with _BashApp().run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.pause()

            block = pilot.app.query_one(StreamingToolBlock)
            assert len(block.children) >= 1
            assert isinstance(block.children[0], ToolHeader), (
                f"Expected ToolHeader as children[0], got {type(block.children[0]).__name__}"
            )
            assert block._header.styles.height.value > 0

    @pytest.mark.asyncio
    async def test_bash_header_present_streaming_with_body(self):
        """STREAMING state with body line: ToolHeader still first child, non-zero height."""
        async with _BashApp().run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.pause()

            block = pilot.app.query_one(StreamingToolBlock)
            block.append_line("timeout: 15 / cwd: /tmp")
            await pilot.pause()
            await pilot.pause()

            assert isinstance(block.children[0], ToolHeader), (
                f"Expected ToolHeader as children[0], got {type(block.children[0]).__name__}"
            )
            assert block._header.styles.height.value > 0

    @pytest.mark.asyncio
    async def test_bash_header_present_done(self):
        """DONE state: ToolHeader is first child with non-zero height."""
        async with _BashApp().run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.pause()

            block = pilot.app.query_one(StreamingToolBlock)
            block.complete(duration="0.1s", is_error=False)
            await pilot.pause()
            await pilot.pause()

            assert isinstance(block.children[0], ToolHeader), (
                f"Expected ToolHeader as children[0], got {type(block.children[0]).__name__}"
            )
            assert block._header.styles.height.value > 0

    @pytest.mark.asyncio
    async def test_bash_header_present_error(self):
        """ERROR state: ToolHeader is first child with non-zero height."""
        async with _BashApp().run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.pause()

            block = pilot.app.query_one(StreamingToolBlock)
            block.complete(duration="0.1s", is_error=True)
            await pilot.pause()
            await pilot.pause()

            assert isinstance(block.children[0], ToolHeader), (
                f"Expected ToolHeader as children[0], got {type(block.children[0]).__name__}"
            )
            assert block._header.styles.height.value > 0

    @pytest.mark.asyncio
    async def test_bash_icon_is_shell_ascii_fallback(self):
        """Fallback icon for bash is "$" (SHELL ascii_fallback) when agent.display absent.

        Poisons sys.modules["agent.display"] = None so `from agent.display import ...`
        raises ImportError, exercising the outer except guard in _refresh_tool_icon().
        """
        async with _BashApp().run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.pause()

            block = pilot.app.query_one(StreamingToolBlock)
            header = block._header

            # Setting to None poisons the import; Python raises ImportError on
            # `from agent.display import ...` even if the module file exists.
            with patch.dict(sys.modules, {"agent.display": None}):
                header._tool_icon = ""
                header._refresh_tool_icon()

            assert header._tool_icon == "$", (
                f"Expected SHELL ascii_fallback '$', got {header._tool_icon!r}"
            )


# ---------------------------------------------------------------------------
# TestBashMountOrder — BASHHDR-2 (1 test)
# ---------------------------------------------------------------------------

class TestBashMountOrder:

    @pytest.mark.asyncio
    async def test_header_mounted_before_body(self):
        """Non-lifted StreamingToolBlock: ToolHeader is children[0] right after on_mount."""
        async with _BashApp().run_test(size=(80, 24)) as pilot:
            # Single pause — check mount order right after on_mount resolves.
            await pilot.pause()

            block = pilot.app.query_one(StreamingToolBlock)
            assert len(block.children) >= 1, "block has no children after mount"
            assert isinstance(block.children[0], ToolHeader), (
                f"Expected ToolHeader as children[0], got {type(block.children[0]).__name__}"
            )
