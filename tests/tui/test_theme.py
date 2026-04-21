"""Tests for theme/skin system — Step 6."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.completion_overlay import CompletionOverlay
from hermes_cli.tui.path_search import PathCandidate
from hermes_cli.tui.preview_panel import PreviewPanel
from hermes_cli.tui.tool_blocks import ToolBlock
from hermes_cli.tui.widgets import OutputPanel, StreamingCodeBlock


@pytest.mark.asyncio
async def test_apply_skin_injects_css_vars():
    """apply_skin stores vars that get_css_variables returns."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.apply_skin({"primary": "#FF0000", "background": "#000000"})
        await pilot.pause()
        css_vars = app.get_css_variables()
        assert css_vars["primary"] == "#FF0000"
        assert css_vars["background"] == "#000000"


@pytest.mark.asyncio
async def test_get_css_variables_includes_textual_defaults():
    """get_css_variables includes Textual's built-in theme variables."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        css_vars = app.get_css_variables()
        # Textual auto-generates variables like $primary, $background
        # Our override should merge, not replace
        assert isinstance(css_vars, dict)
        assert len(css_vars) > 0


@pytest.mark.asyncio
async def test_bad_skin_does_not_crash():
    """apply_skin with bad values logs warning but doesn't crash."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # This should not crash — invalid CSS values are handled gracefully
        app.apply_skin({"not-a-real-var": "invalid"})
        await pilot.pause()


@pytest.mark.asyncio
async def test_apply_skin_rehighlights_completed_historical_code_blocks():
    """Completed blocks should rebuild Syntax in place on skin change."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        app.apply_skin({"preview-syntax-theme": "monokai", "app-bg": "#1e1e1e"})
        await pilot.pause()

        msg = app.query_one(OutputPanel).new_message()
        block = StreamingCodeBlock(lang="")
        await msg.mount(block)
        await pilot.pause()

        block.append_line("public class HelloWorld {")
        block.append_line("    public static void main(String[] args) {")
        block.append_line('        System.out.println("hi");')
        block.append_line("    }")
        block.append_line("}")
        block.complete(app.get_css_variables())
        await asyncio.sleep(0.05)
        await pilot.pause()

        copy_before = block.copy_content()
        assert block._resolved_lang == "java"
        assert block._pygments_theme == "monokai"

        with patch.object(block._log, "clear", wraps=block._log.clear) as clear_spy:
            app.apply_skin({"preview-syntax-theme": "emacs", "app-bg": "#1e1e1e"})
            await pilot.pause()

        assert clear_spy.called
        assert block._resolved_lang == "java"
        assert block._pygments_theme == "emacs"
        assert block.copy_content() == copy_before


@pytest.mark.asyncio
async def test_apply_skin_updates_streaming_code_block_theme_without_state_change():
    """Streaming blocks keep streaming and finalize with the new theme."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()

        msg = app.query_one(OutputPanel).new_message()
        block = StreamingCodeBlock(lang="python", pygments_theme="monokai")
        await msg.mount(block)
        await pilot.pause()

        block.append_line("x = 1")
        app.apply_skin({"preview-syntax-theme": "emacs", "app-bg": "#1e1e1e"})
        await pilot.pause()

        assert block._state == "STREAMING"
        assert block._pygments_theme == "emacs"

        block.append_line("y = 2")
        block.complete(app.get_css_variables())
        await asyncio.sleep(0.05)
        await pilot.pause()

        assert block._state == "COMPLETE"
        assert block._pygments_theme == "emacs"
        assert block._resolved_lang == "python"


@pytest.mark.asyncio
async def test_apply_skin_rerenders_flushed_code_blocks():
    """Flushed blocks re-render with new theme (same as COMPLETE)."""
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()

        msg = app.query_one(OutputPanel).new_message()
        block = StreamingCodeBlock(lang="python", pygments_theme="monokai")
        await msg.mount(block)
        await pilot.pause()

        block.append_line("x = 1")
        block.flush()
        await pilot.pause()
        copy_before = block.copy_content()

        app.apply_skin({"preview-syntax-theme": "emacs", "app-bg": "#1e1e1e"})
        await pilot.pause()

        assert block._state == "FLUSHED"
        assert block._pygments_theme == "emacs"
        assert block.copy_content() == copy_before


@pytest.mark.asyncio
async def test_apply_skin_rerenders_tool_preview_blocks_with_callback():
    """Tool preview blocks with a rerender hook should rebuild styled lines in place."""
    app = HermesApp(cli=MagicMock())
    phase = {"value": "old"}

    def rerender():
        return [phase["value"]], ["plain"]

    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        app.mount_tool_block("code", ["old"], ["plain"], rerender)
        await pilot.pause()

        block = app.query_one(ToolBlock)
        assert block._lines == ["old"]
        assert block.copy_content() == "plain"

        phase["value"] = "new"
        app.apply_skin({"preview-syntax-theme": "emacs", "app-bg": "#1e1e1e"})
        await pilot.pause()

        assert block._lines == ["new"]
        assert block.copy_content() == "plain"


@pytest.mark.asyncio
async def test_apply_skin_rerenders_preview_panel_without_reloading_file(tmp_path: Path):
    """PreviewPanel should recolor cached source in place on skin change."""
    py_file = tmp_path / "hello.py"
    py_file.write_text("def hello():\n    return 1\n", encoding="utf-8")

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        app.query_one(CompletionOverlay).add_class("--visible")
        panel = app.query_one(PreviewPanel)
        panel.candidate = PathCandidate(display="hello.py", abs_path=str(py_file))
        await asyncio.sleep(0.5)
        await pilot.pause()

        assert panel._syntax_abs_path == str(py_file)
        assert panel._syntax_head is not None

        with patch.object(panel, "_render_syntax", wraps=panel._render_syntax) as render_spy, \
             patch.object(panel, "_load_preview", wraps=panel._load_preview) as load_spy:
            app.apply_skin({"preview-syntax-theme": "emacs", "app-bg": "#1e1e1e"})
            await pilot.pause()

        assert render_spy.called
        assert not load_spy.called
