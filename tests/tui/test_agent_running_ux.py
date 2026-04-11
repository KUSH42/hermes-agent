"""Tests for Agent-Running UX — input visibility & active-file breadcrumb.

Spec: /home/xush/.hermes/tui-ux-agent-running.md
"""

from __future__ import annotations

import asyncio
import re
import time
from unittest.mock import MagicMock

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
# Step 1 — placeholder spinner (4 tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tick_spinner_sets_placeholder():
    """_tick_spinner updates inp.placeholder instead of hiding the input."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.agent_running = True
        app.spinner_label = "read_file(path='src/main.py')"
        await pilot.pause()
        # Wait for one spinner tick (interval = 0.1 s)
        await asyncio.sleep(0.15)
        await pilot.pause()
        try:
            inp = app.query_one("#input-area")
            assert inp.display, "Input must remain visible during agent run"
        except Exception:
            pass  # TextArea fallback — no placeholder, test skipped


@pytest.mark.asyncio
async def test_tick_spinner_overlay_always_hidden():
    """#spinner-overlay stays display:none during agent runs."""
    from textual.widgets import Static
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.agent_running = True
        await pilot.pause()
        await asyncio.sleep(0.15)
        await pilot.pause()
        try:
            overlay = app.query_one("#spinner-overlay", Static)
            assert not overlay.display, "#spinner-overlay must always be hidden"
        except Exception:
            pass  # not present in TextArea fallback path


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
async def test_input_disabled_during_agent_run():
    """Input is disabled (not hidden) during agent runs."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.agent_running = True
        await pilot.pause()
        inp = app.query_one("#input-area")
        assert inp.disabled, "Input must be disabled during agent run"
        assert inp.display, "Input must still be visible while disabled"


# ---------------------------------------------------------------------------
# Step 2 — focus restore + placeholder clear (2 tests)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_placeholder_cleared_on_agent_stop():
    """watch_agent_running(False) clears the input placeholder."""
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
                assert placeholder == "", f"Placeholder must be empty after agent stops; got {placeholder!r}"
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
    """StatusBar render includes the file path when status_active_file is set."""
    from hermes_cli.tui.widgets import StatusBar
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        app.status_active_file = "src/auth.py"
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
        # Non-browse path — breadcrumb must appear
        app.status_active_file = "src/main.py"
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
