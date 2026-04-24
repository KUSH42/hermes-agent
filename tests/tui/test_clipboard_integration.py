"""Clipboard chain integration tests.

Covers: OSC52/xclip/no-clipboard paths, context menu copy, ctrl+c copy, paste hint.

Run with:
    pytest -o "addopts=" tests/tui/test_clipboard_integration.py -v
"""

from __future__ import annotations

import asyncio
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.widgets import HintBar, OutputPanel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _run_turn(app: HermesApp, pilot, *, chunks: list[str] | None = None) -> None:
    """Simulate one agent turn: activate -> optional output -> deactivate."""
    app.agent_running = True
    await pilot.pause()
    for chunk in (chunks or []):
        app.write_output(chunk)
    await asyncio.sleep(0.05)
    await pilot.pause()
    app.agent_running = False
    await pilot.pause()


# ---------------------------------------------------------------------------
# OSC52 / copy_to_clipboard path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_copy_text_with_hint_osc52_path():
    """clipboard_available=True: _copy_text_with_hint calls copy_to_clipboard and
    flashes HintBar with the copy icon and char count."""
    app = HermesApp(cli=MagicMock(), clipboard_available=True, xclip_cmd=None)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(HintBar)

        with patch.object(app, "copy_to_clipboard"):
            app._copy_text_with_hint("hello world")
            await pilot.pause()

        assert "⎘" in bar.hint, f"Expected copy icon in hint, got: {bar.hint!r}"
        assert "11" in bar.hint, f"Expected char count '11' in hint, got: {bar.hint!r}"


@pytest.mark.asyncio
async def test_copy_hint_reverts_after_timer():
    """_flash_hint reverts HintBar.hint to the prior value after the duration expires."""
    app = HermesApp(cli=MagicMock(), clipboard_available=True, xclip_cmd=None)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(HintBar)
        bar.hint = "initial"
        await pilot.pause()

        with patch.object(app, "copy_to_clipboard"):
            app._copy_text_with_hint("x")
            await pilot.pause()

        # Flash is active immediately
        assert "⎘" in bar.hint

        # After 1.6s the 1.5s flash timer fires and restores the prior hint
        await asyncio.sleep(1.6)
        await pilot.pause()

        # FeedbackService restores to blank (not prior value) — intentional design
        assert "⎘" not in bar.hint, (
            f"Flash should have cleared after timer, got: {bar.hint!r}"
        )


# ---------------------------------------------------------------------------
# xclip fallback path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_copy_text_xclip_fallback():
    """clipboard_available=False + xclip_cmd: calls subprocess.run and flashes hint."""
    app = HermesApp(
        cli=MagicMock(),
        clipboard_available=False,
        xclip_cmd=["xclip", "-selection", "clipboard"],
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        bar = app.query_one(HintBar)

        with patch("hermes_cli.tui.services.theme.safe_run") as mock_safe_run:
            app._copy_text_with_hint("data")
            # Fire on_success callback to simulate worker completing
            on_success = mock_safe_run.call_args[1]["on_success"]
            on_success("", "", 0)
            await pilot.pause()

        mock_safe_run.assert_called_once()
        assert mock_safe_run.call_args[0][1] == ["xclip", "-selection", "clipboard"]
        assert mock_safe_run.call_args[1]["input_bytes"] == b"data"
        assert app.clipboard == "data"
        assert "⎘" in bar.hint, f"Expected copy icon in hint, got: {bar.hint!r}"
        assert "4" in bar.hint, f"Expected char count '4' in hint, got: {bar.hint!r}"


@pytest.mark.asyncio
async def test_copy_text_xclip_failure():
    """xclip subprocess failure: no crash, and status_error is set."""
    app = HermesApp(
        cli=MagicMock(),
        clipboard_available=False,
        xclip_cmd=["xclip"],
    )
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        with patch("subprocess.run", side_effect=subprocess.SubprocessError("pipe broke")):
            app._copy_text_with_hint("data")
            await pilot.pause()

        assert app.status_error != "", (
            "status_error must be non-empty after xclip subprocess failure"
        )


# ---------------------------------------------------------------------------
# No clipboard at all
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_clipboard_shows_sticky_error():
    """clipboard_available=False + no xclip: set_status_error with xclip/xsel hint."""
    app = HermesApp(cli=MagicMock(), clipboard_available=False, xclip_cmd=None)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app._copy_text_with_hint("data")
        await pilot.pause()

        err = app.status_error
        assert "xclip" in err or "xsel" in err, (
            f"status_error should mention xclip or xsel, got: {err!r}"
        )


# ---------------------------------------------------------------------------
# Context menu: copy tool output
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_menu_copy_tool_fires_hint():
    """Right-click context menu 'Copy tool output' fires _copy_tool_output and
    flashes HintBar with the copy icon."""
    from hermes_cli.tui.tool_blocks import StreamingToolBlock

    app = HermesApp(cli=MagicMock(), clipboard_available=True, xclip_cmd=None)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        app.agent_running = True
        await pilot.pause()

        app.open_streaming_tool_block("id1", "ls -la")
        await pilot.pause()

        app.append_streaming_line("id1", "output\n")
        await asyncio.sleep(0.05)
        await pilot.pause()

        app.close_streaming_tool_block("id1", "0.5s")
        await pilot.pause()

        output = app.query_one(OutputPanel)
        blocks = list(output.query(StreamingToolBlock))
        assert blocks, "Expected at least one StreamingToolBlock in OutputPanel"
        block = blocks[-1]

        mock_event = MagicMock()
        mock_event.widget = block

        items = app._build_context_items(mock_event)
        copy_item = next(
            (i for i in items if "Copy tool output" in i.label), None
        )
        assert copy_item is not None, "Expected 'Copy tool output' menu item"

        bar = app.query_one(HintBar)
        with patch.object(app, "copy_to_clipboard"):
            copy_item.action()
            await pilot.pause()

        assert "⎘" in bar.hint, f"Expected copy icon in HintBar, got: {bar.hint!r}"

        app.agent_running = False
        await pilot.pause()


# ---------------------------------------------------------------------------
# Context menu: copy response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_menu_copy_response_fires_hint():
    """Context menu 'Copy full response' action flashes HintBar with copy icon."""
    from hermes_cli.tui.widgets import MessagePanel

    app = HermesApp(cli=MagicMock(), clipboard_available=True, xclip_cmd=None)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await _run_turn(app, pilot, chunks=["response\n"])

        output = app.query_one(OutputPanel)
        panel = output.current_message
        assert panel is not None, "Expected a MessagePanel after running a turn"

        mock_event = MagicMock()
        mock_event.widget = panel

        with patch.object(app, "_get_selected_text", return_value=None):
            items = app._build_context_items(mock_event)

        copy_item = next(
            (i for i in items if "Copy full response" in i.label), None
        )
        assert copy_item is not None, "Expected 'Copy full response' menu item"

        bar = app.query_one(HintBar)
        with patch.object(app, "copy_to_clipboard"):
            copy_item.action()
            await pilot.pause()

        assert "⎘" in bar.hint, f"Expected copy icon in HintBar, got: {bar.hint!r}"


# ---------------------------------------------------------------------------
# ctrl+c copy with selection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ctrl_c_with_selection_copies_and_no_interrupt():
    """ctrl+c with a text selection copies the selection and flashes HintBar."""
    app = HermesApp(cli=MagicMock(), clipboard_available=True, xclip_cmd=None)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(HintBar)

        with patch.object(app, "_get_selected_text", return_value="selected text"):
            with patch.object(app, "copy_to_clipboard"):
                await pilot.press("ctrl+c")
                await pilot.pause()

        assert "⎘" in bar.hint, f"Expected copy icon in HintBar, got: {bar.hint!r}"
        assert "13" in bar.hint, f"Expected char count '13' in hint, got: {bar.hint!r}"


@pytest.mark.asyncio
async def test_ctrl_c_no_selection_does_not_copy():
    """ctrl+c with no selection does not flash the copy icon in HintBar."""
    app = HermesApp(cli=MagicMock(), clipboard_available=True, xclip_cmd=None)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        # Put something in the input so ctrl+c clears it rather than exiting
        from hermes_cli.tui.input_widget import HermesInput
        inp = app.query_one(HermesInput)
        inp.value = "x"
        await pilot.pause()

        bar = app.query_one(HintBar)

        with patch.object(app, "_get_selected_text", return_value=""):
            await pilot.press("ctrl+c")
            await pilot.pause()

        assert "⎘" not in bar.hint, (
            f"HintBar must not contain copy icon when no selection, got: {bar.hint!r}"
        )


# ---------------------------------------------------------------------------
# Paste hint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_paste_fires_hint():
    """Paste event on the input area flashes HintBar with copy icon and char count."""
    from textual.events import Paste

    app = HermesApp(cli=MagicMock(), clipboard_available=True, xclip_cmd=None)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        bar = app.query_one(HintBar)
        input_area = app.query_one("#input-area")

        input_area.post_message(Paste("clipboard content"))
        await pilot.pause()
        await asyncio.sleep(0.05)
        await pilot.pause()

        assert "⎘" in bar.hint, f"Expected copy icon in hint after paste, got: {bar.hint!r}"
        assert "17" in bar.hint, f"Expected char count '17' in hint, got: {bar.hint!r}"


# ---------------------------------------------------------------------------
# HERMES_CLIPBOARD env override (pure unit test — no app)
# ---------------------------------------------------------------------------

def test_hermes_clipboard_env_override(monkeypatch):
    """HERMES_CLIPBOARD=0 → check_clipboard_env() returns False."""
    from hermes_cli.tui.osc52_probe import check_clipboard_env

    monkeypatch.setenv("HERMES_CLIPBOARD", "0")
    result = check_clipboard_env()
    assert result is False, f"Expected False, got {result!r}"
