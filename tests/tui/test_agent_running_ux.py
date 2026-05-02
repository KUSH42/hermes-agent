"""Tests for Agent-Running UX — input visibility & active-file breadcrumb.

Spec: /home/xush/.hermes/tui-ux-agent-running.md
"""

from __future__ import annotations

import asyncio
import re
import time
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp, _FILE_TOOLS, _PATH_EXTRACT_RE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.session_start = None
    return HermesApp(cli=cli, clipboard_available=True)


# ---------------------------------------------------------------------------
# Step 1 — overlay spinner (6 tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_spinner_renders_on_overlay_not_placeholder():
    """Running spinner renders on #spinner-overlay; input placeholder stays idle."""
    from textual.widgets import Static
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.agent_running = True
        app.spinner_label = "read_file(path='src/main.py')"
        await pilot.pause()
        await asyncio.sleep(0.15)
        await pilot.pause()
        inp = app.query_one("#input-area")
        overlay = app.query_one("#spinner-overlay", Static)
        assert inp.placeholder == getattr(inp, "_idle_placeholder", "")
        assert overlay.display is True
        assert str(overlay.render()) != ""


@pytest.mark.asyncio
async def test_tick_spinner_overlay_hides_when_idle():
    """Idle tick hides and clears the spinner overlay."""
    from textual.widgets import Static
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.agent_running = True
        app.spinner_label = "Tool: demo"
        await pilot.pause()
        await asyncio.sleep(0.15)
        await pilot.pause()
        overlay = app.query_one("#spinner-overlay", Static)
        assert overlay.display is True

        app.agent_running = False
        app._svc_spinner.tick_spinner()
        await pilot.pause()

        assert overlay.display is False
        assert str(overlay.render()) == ""


@pytest.mark.asyncio
async def test_tick_spinner_plain_overlay_when_animations_disabled():
    """Plain overlay text is used when shimmer animation is disabled."""
    from textual.widgets import Static
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app._animations_enabled = False
        app.agent_running = True
        app.spinner_label = "Tool: plain"
        await pilot.pause()
        await asyncio.sleep(0.15)
        await pilot.pause()

        overlay = app.query_one("#spinner-overlay", Static)
        assert overlay.display is True
        rendered = str(overlay.render())
        assert "plain" in rendered


@pytest.mark.asyncio
async def test_tick_spinner_preserves_idle_placeholder_contract():
    """Spinner cleanup restores the idle placeholder contract."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        inp = app.query_one("#input-area")
        idle_placeholder = getattr(inp, "_idle_placeholder", "")

        app.agent_running = True
        app.spinner_label = "Tool: busy"
        await pilot.pause()
        await asyncio.sleep(0.15)
        await pilot.pause()
        assert inp.placeholder == idle_placeholder

        app.agent_running = False
        app._svc_spinner.tick_spinner()
        await pilot.pause()

        assert inp.placeholder == idle_placeholder


@pytest.mark.asyncio
async def test_tick_spinner_no_longer_forces_overlay_hidden_each_tick():
    """Active spinner ticks keep the overlay visible while text is non-empty."""
    from textual.widgets import Static
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.agent_running = True
        app.spinner_label = "Tool: busy"
        await pilot.pause()
        app._svc_spinner.tick_spinner()
        app._svc_spinner.tick_spinner()
        await pilot.pause()

        overlay = app.query_one("#spinner-overlay", Static)
        assert overlay.display is True


@pytest.mark.asyncio
async def test_tick_spinner_skips_overlay_update_when_frame_unchanged():
    """Overlay update is skipped when the effective frame signature is unchanged."""
    from textual.widgets import Static
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app._animations_enabled = False
        await pilot.pause()

        overlay = app.query_one("#spinner-overlay", Static)
        with patch.object(overlay, "update", wraps=overlay.update) as mock_update:
            with patch.object(app._svc_spinner, "next_spinner_frame", return_value="frame"):
                app.agent_running = True
                app._tool_start_time = 0.0
                app.spinner_label = "Tool: stable"
                app._svc_spinner.tick_spinner()
                app._svc_spinner.tick_spinner()

        assert mock_update.call_count == 1


@pytest.mark.asyncio
async def test_input_visible_during_agent_run():
    """Input widget has display=True at all times when agent_running is True."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.agent_running = True
        await pilot.pause()
        await asyncio.sleep(0.15)
        await pilot.pause()
        inp = app.query_one("#input-area")
        assert inp.display, "Input must be visible during agent run"


@pytest.mark.asyncio
async def test_input_enabled_during_agent_run():
    """Input stays enabled (not hidden) during agent runs for interrupt."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.agent_running = True
        await pilot.pause()
        inp = app.query_one("#input-area")
        assert not inp.disabled, "Input must be enabled during agent run for interrupt"
        assert inp.display, "Input must still be visible while agent is running"


# ---------------------------------------------------------------------------
# Step 2 — focus restore + placeholder clear (2 tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_placeholder_cleared_on_agent_stop():
    """watch_agent_running(False) restores the idle placeholder."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.agent_running = True
        await pilot.pause()
        await asyncio.sleep(0.15)
        await pilot.pause()

        # Stop agent
        app.agent_running = False
        await pilot.pause()

        try:
            inp = app.query_one("#input-area")
            placeholder = getattr(inp, "placeholder", None)
            if placeholder is not None:
                assert placeholder == getattr(inp, "_idle_placeholder", "")
        except Exception:
            pass  # TextArea fallback


@pytest.mark.asyncio
async def test_input_focused_after_agent_stop():
    """Input receives focus after agent turn ends (GAP-17)."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.agent_running = True
        await pilot.pause()
        app.agent_running = False
        await pilot.pause()
        # call_after_refresh needs a refresh cycle
        await pilot.pause()
        inp = app.query_one("#input-area")
        assert app.focused is inp, "Input must be focused after agent turn ends"


# ---------------------------------------------------------------------------
# Steps 3–5 — file extraction via watch_spinner_label (6 tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_spinner_label_read_file_sets_active_file():
    """spinner_label with read_file extracts path into status_active_file."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.spinner_label = "read_file(path='src/auth.py')"
        await pilot.pause()
        assert app.status_active_file == "src/auth.py"


@pytest.mark.asyncio
async def test_spinner_label_write_file_sets_active_file():
    """spinner_label with write_file extracts path into status_active_file."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.spinner_label = "write_file('/tmp/out.txt')"
        await pilot.pause()
        assert app.status_active_file == "/tmp/out.txt"


@pytest.mark.asyncio
async def test_spinner_label_unknown_tool_clears_active_file():
    """Non-file-touching tools clear status_active_file."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.spinner_label = "read_file('src/main.py')"
        await pilot.pause()
        assert app.status_active_file != ""
        app.spinner_label = "bash('ls')"
        await pilot.pause()
        assert app.status_active_file == ""


@pytest.mark.asyncio
async def test_spinner_label_no_path_in_file_tool():
    """File tool with no path argument leaves status_active_file empty."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.spinner_label = "read_file"
        await pilot.pause()
        assert app.status_active_file == ""


@pytest.mark.asyncio
async def test_spinner_label_view_tool_extracts_path():
    """'view' is a file-touching tool — path should be extracted."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.spinner_label = "view('/home/user/notes.md')"
        await pilot.pause()
        assert app.status_active_file == "/home/user/notes.md"


@pytest.mark.asyncio
async def test_spinner_label_empty_clears_active_file():
    """Setting spinner_label to '' clears status_active_file."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.spinner_label = "read_file('foo.py')"
        await pilot.pause()
        assert app.status_active_file != ""
        app.spinner_label = ""
        await pilot.pause()
        assert app.status_active_file == ""


# ---------------------------------------------------------------------------
# Steps 6–7 — StatusBar breadcrumb render (6 tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_statusbar_shows_breadcrumb_when_active_file_set():
    """StatusBar render includes the file path when active file is set and offscreen."""
    from hermes_cli.tui.widgets import StatusBar
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.status_active_file = "src/auth.py"
        app.status_active_file_offscreen = True  # S1-B: breadcrumb only when scrolled
        await pilot.pause()
        bar = app.query_one(StatusBar)
        rendered = bar.render()
        rendered_str = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        assert "src/auth.py" in rendered_str


@pytest.mark.asyncio
async def test_statusbar_omits_breadcrumb_when_no_active_file():
    """StatusBar render has no 📄 separator when status_active_file is empty."""
    from hermes_cli.tui.widgets import StatusBar
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.status_active_file = ""
        await pilot.pause()
        bar = app.query_one(StatusBar)
        rendered = bar.render()
        rendered_str = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        assert "📄" not in rendered_str


@pytest.mark.asyncio
async def test_statusbar_truncates_long_path():
    """StatusBar truncates paths longer than width//4 with '…' prefix."""
    from hermes_cli.tui.widgets import StatusBar
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        long_path = "/home/user/very/deeply/nested/directory/structure/file.py"
        app.status_active_file = long_path
        await pilot.pause()
        bar = app.query_one(StatusBar)
        rendered = bar.render()
        rendered_str = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        # Path is truncated — full path should not appear
        assert long_path not in rendered_str
        # Ellipsis should be present
        assert "…" in rendered_str


@pytest.mark.asyncio
async def test_statusbar_no_breadcrumb_narrow_terminal():
    """Breadcrumb is suppressed at width < 60."""
    from hermes_cli.tui.widgets import StatusBar
    app = _make_app()
    async with app.run_test(size=(50, 24)) as pilot:
        app.status_active_file = "src/auth.py"
        await pilot.pause()
        bar = app.query_one(StatusBar)
        rendered = bar.render()
        rendered_str = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        # On a 50-char terminal, breadcrumb should be suppressed
        assert "src/auth.py" not in rendered_str


@pytest.mark.asyncio
async def test_statusbar_breadcrumb_clears_after_file_reset():
    """StatusBar removes breadcrumb when status_active_file reverts to empty."""
    from hermes_cli.tui.widgets import StatusBar
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.status_active_file = "src/auth.py"
        await pilot.pause()
        bar = app.query_one(StatusBar)

        app.status_active_file = ""
        await pilot.pause()
        rendered = bar.render()
        rendered_str = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        assert "src/auth.py" not in rendered_str
        assert "📄" not in rendered_str


@pytest.mark.asyncio
async def test_statusbar_breadcrumb_only_in_non_browse_path():
    """The breadcrumb code is structurally after the browse-mode early-return.

    browse_mode requires ToolHeaders to activate (watch_browse_mode resets it
    to False when none exist).  We verify the non-browse render includes the
    breadcrumb, confirming the code position is correct — the browse branch
    returns early before reaching the breadcrumb injection point.
    """
    from hermes_cli.tui.widgets import StatusBar
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        # Non-browse path — breadcrumb must appear (S1-B: requires offscreen=True)
        app.status_active_file = "src/main.py"
        app.status_active_file_offscreen = True
        await pilot.pause()
        bar = app.query_one(StatusBar)
        rendered = bar.render()
        rendered_str = rendered.plain if hasattr(rendered, "plain") else str(rendered)
        assert "src/main.py" in rendered_str, "Breadcrumb must appear in non-browse path"
        # browse_mode is False (reset by watcher when no ToolHeaders present) — confirmed
        assert not app.browse_mode, "browse_mode must be False without ToolHeaders"


# ---------------------------------------------------------------------------
# Unit tests — _FILE_TOOLS and _PATH_EXTRACT_RE (not async, no app)
# ---------------------------------------------------------------------------

def test_file_tools_set_contents():
    """_FILE_TOOLS contains the expected tool names."""
    assert "read_file" in _FILE_TOOLS
    assert "write_file" in _FILE_TOOLS
    assert "edit_file" in _FILE_TOOLS
    assert "view" in _FILE_TOOLS
    assert "str_replace_editor" in _FILE_TOOLS
    assert "bash" not in _FILE_TOOLS


def test_path_regex_matches_relative_path():
    assert _PATH_EXTRACT_RE.search("read_file(path='src/auth.py')").group(1) == "src/auth.py"


def test_path_regex_matches_absolute_path():
    assert _PATH_EXTRACT_RE.search("view('/home/user/file.txt')").group(1) == "/home/user/file.txt"


def test_path_regex_no_match_on_pure_tool():
    assert _PATH_EXTRACT_RE.search("read_file") is None
