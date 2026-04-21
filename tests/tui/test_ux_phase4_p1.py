"""Phase 4 Phase 1 tests — A1, A2, D1, E2.

A1: edit_cmd action wired and pre-populates input
A2: open_url action wired + open_primary fallback for WEB tool
D1: error always expands regardless of _user_collapse_override
E2: open_first removed; open_primary handles file+url artifacts
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# A1 — edit_cmd action
# ---------------------------------------------------------------------------

def test_edit_cmd_in_implemented_actions():
    from hermes_cli.tui.tool_panel import _IMPLEMENTED_ACTIONS
    assert "edit_cmd" in _IMPLEMENTED_ACTIONS


def test_open_url_in_implemented_actions():
    from hermes_cli.tui.tool_panel import _IMPLEMENTED_ACTIONS
    assert "open_url" in _IMPLEMENTED_ACTIONS


@pytest.mark.asyncio
async def test_action_edit_cmd_prepopulates_input():
    """action_edit_cmd sets HermesInput.value to the cmd payload."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_result_parse import (
        ResultSummaryV4, Action, Chip,
    )

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(
                block=StreamingToolBlock(label="bash", tool_name="bash"),
                tool_name="bash",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        summary = ResultSummaryV4(
            primary="✗ exit 1", exit_code=1,
            chips=(Chip("exit 1", "exit", "error"),),
            stderr_tail="",
            actions=(
                Action("copy err", "e", "copy_err", None, False),
                Action("edit cmd", "E", "edit_cmd", "ls -la /tmp", False),
            ),
            artifacts=(), is_error=True,
        )
        panel.set_result_summary(summary)

        class _FakeInput:
            value = ""
            def focus(self): pass

        fake_inp = _FakeInput()

        # Patch the input_widget module so query_one returns our fake
        import hermes_cli.tui.input_widget as _iw
        _real_cls = getattr(_iw, "HermesInput", None)
        with patch.object(pilot.app, "query_one", return_value=fake_inp):
            panel.action_edit_cmd()

        assert fake_inp.value == "ls -la /tmp"


@pytest.mark.asyncio
async def test_action_edit_cmd_noop_when_no_payload():
    """action_edit_cmd is silent when no edit_cmd action in summary."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(
                block=StreamingToolBlock(label="bash", tool_name="bash"),
                tool_name="bash",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        # No summary set — should not raise
        panel.action_edit_cmd()


# ---------------------------------------------------------------------------
# A2 — open_url action
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_action_open_url_opens_artifact_url():
    """action_open_url calls xdg-open / open with the first URL artifact."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_result_parse import (
        ResultSummaryV4, Action, Artifact,
    )

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(
                block=StreamingToolBlock(label="fetch", tool_name="fetch"),
                tool_name="fetch",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        summary = ResultSummaryV4(
            primary="✓ 200 OK", exit_code=200, chips=(), stderr_tail="",
            actions=(Action("open url", "O", "open_url", None, False),),
            artifacts=(Artifact(label="example.com", path_or_url="https://example.com/page", kind="url"),),
            is_error=False,
        )
        panel.set_result_summary(summary)

        opened = []
        with patch("subprocess.Popen", side_effect=lambda args, **kw: opened.append(args)):
            panel.action_open_url()

        assert len(opened) == 1
        assert "https://example.com/page" in opened[0]


@pytest.mark.asyncio
async def test_action_open_url_noop_when_no_urls():
    """action_open_url is a no-op when no URL artifacts."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(
                block=StreamingToolBlock(label="bash", tool_name="bash"),
                tool_name="bash",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        opened = []
        with patch("subprocess.Popen", side_effect=lambda args, **kw: opened.append(args)):
            panel.action_open_url()
        assert len(opened) == 0


@pytest.mark.asyncio
async def test_action_open_primary_falls_back_to_url_artifact():
    """action_open_primary uses URL artifact when header not path-clickable."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Artifact

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(
                block=StreamingToolBlock(label="fetch", tool_name="fetch"),
                tool_name="fetch",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        summary = ResultSummaryV4(
            primary="✓ 200 OK", exit_code=200, chips=(), stderr_tail="",
            actions=(), is_error=False,
            artifacts=(Artifact(label="example.com", path_or_url="https://example.com", kind="url"),),
        )
        panel.set_result_summary(summary)

        opened = []
        with patch("subprocess.Popen", side_effect=lambda args, **kw: opened.append(args)):
            panel.action_open_primary()

        assert len(opened) == 1
        assert "https://example.com" in opened[0]


# ---------------------------------------------------------------------------
# D1 — error always expands regardless of user_collapse_override
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_error_expands_despite_user_collapse_override():
    """An errored tool always expands even when user manually collapsed first."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Chip, Action

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(
                block=StreamingToolBlock(label="bash", tool_name="bash"),
                tool_name="bash",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        await pilot.pause(0.05)

        # Simulate user manually collapsing before completion
        panel.action_toggle_collapse()
        assert panel._user_collapse_override is True
        assert panel.collapsed is True

        # Tool errors → must expand
        summary = ResultSummaryV4(
            primary="✗ exit 1", exit_code=1,
            chips=(Chip("exit 1", "exit", "error"),),
            stderr_tail="command not found",
            actions=(Action("retry", "r", "retry", None, False),),
            artifacts=(), is_error=True,
        )
        panel.set_result_summary(summary)
        await pilot.pause(0.05)

        assert panel.collapsed is False, "Error should force-expand even with user override"


@pytest.mark.asyncio
async def test_non_error_respects_user_collapse_override():
    """Non-error completion respects user collapse override."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(
                block=StreamingToolBlock(label="bash", tool_name="bash"),
                tool_name="bash",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        await pilot.pause(0.05)

        panel.action_toggle_collapse()
        assert panel.collapsed is True

        summary = ResultSummaryV4(
            primary="✓ 5 lines", exit_code=0, chips=(), stderr_tail="",
            actions=(), artifacts=(), is_error=False,
        )
        panel.set_result_summary(summary)
        await pilot.pause(0.05)

        assert panel.collapsed is True, "Non-error should keep user-collapsed state"


# ---------------------------------------------------------------------------
# E2 — open_first removed; open_primary covers file + url artifacts
# ---------------------------------------------------------------------------

def test_action_open_first_removed():
    """action_open_first no longer exists as a standalone method."""
    from hermes_cli.tui.tool_panel import ToolPanel
    assert not hasattr(ToolPanel, "action_open_first"), (
        "action_open_first should be removed — use action_open_primary instead"
    )


@pytest.mark.asyncio
async def test_open_primary_covers_file_artifact():
    """action_open_primary opens file artifact when no header path."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Artifact

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(
                block=StreamingToolBlock(label="bash", tool_name="bash"),
                tool_name="bash",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        summary = ResultSummaryV4(
            primary="✓ done", exit_code=0, chips=(), stderr_tail="",
            actions=(), is_error=False,
            artifacts=(Artifact(label="out.txt", path_or_url="/tmp/out.txt", kind="file"),),
        )
        panel.set_result_summary(summary)

        opened = []
        with patch("subprocess.Popen", side_effect=lambda args, **kw: opened.append(args)):
            panel.action_open_primary()

        assert len(opened) == 1
        assert "/tmp/out.txt" in opened[0]


@pytest.mark.asyncio
async def test_build_hint_text_shows_edit_cmd():
    """_build_hint_text shows 'E edit cmd' when edit_cmd action with payload present."""
    from textual.app import App, ComposeResult
    from hermes_cli.tui.tool_blocks import StreamingToolBlock
    from hermes_cli.tui.tool_panel import ToolPanel
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4, Action, Chip

    class _App(App):
        def compose(self) -> ComposeResult:
            yield ToolPanel(
                block=StreamingToolBlock(label="bash", tool_name="bash"),
                tool_name="bash",
            )

    async with _App().run_test() as pilot:
        panel = pilot.app.query_one(ToolPanel)
        panel._result_summary_v4 = ResultSummaryV4(
            primary="✗ exit 1", exit_code=1,
            chips=(Chip("exit 1", "exit", "error"),),
            stderr_tail="",
            actions=(Action("edit cmd", "E", "edit_cmd", "ls /tmp", False),),
            artifacts=(), is_error=True,
        )
        hint = panel._build_hint_text()
        from rich.text import Text
        assert isinstance(hint, Text)
        assert "edit cmd" in hint.plain.lower() or "E" in hint.plain
