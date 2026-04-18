"""Tests for WorkspaceOverlay TUI integration.

Tests 18–33 (requires Textual pilot).

18. WorkspaceOverlay hidden by default
19. /workspace shows overlay
20. w key shows overlay (input NOT focused)
21. w key does NOT open overlay when HermesInput has focus
22. Esc hides overlay, restores input focus
23. refresh_data updates file rows
24. Modified files show M status char
25. Added files show A status char
26. +N -N counts rendered from FileEntry
27. Dirty indicator ● shown for dirty files
28. Complexity warning row appears when complexity_warning is set
29. Complexity section hidden when no warnings
30. _dismiss_all_info_overlays hides WorkspaceOverlay
31. Agent start (watch_agent_running True) dismisses WorkspaceOverlay
32. Flash hint shown once on first file write (not twice)
33. refresh_data(tracker, snapshot=None) renders header without branch/dirty chip
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.overlays import WorkspaceOverlay
from hermes_cli.tui.workspace_tracker import FileEntry, GitSnapshot, WorkspaceTracker
from textual.widgets import Static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.agent = None
    return HermesApp(cli=cli)


async def _submit(pilot, app, cmd: str) -> None:
    from hermes_cli.tui.input_widget import HermesInput
    inp = app.query_one(HermesInput)
    inp.value = cmd
    inp.action_submit()
    await pilot.pause()


def _make_tracker(entries: list[FileEntry] | None = None) -> WorkspaceTracker:
    t = WorkspaceTracker("/repo")
    if entries:
        for e in entries:
            t._entries[e.path] = e
    return t


def _entry(
    path: str = "/repo/foo.py",
    rel_path: str = "foo.py",
    git_status: str = "M",
    session_added: int = 10,
    session_removed: int = 2,
    git_staged: bool = False,
    last_write: float | None = None,
    complexity_warning: str | None = None,
) -> FileEntry:
    return FileEntry(
        path=path,
        rel_path=rel_path,
        git_status=git_status,
        session_added=session_added,
        session_removed=session_removed,
        git_staged=git_staged,
        last_write=last_write if last_write is not None else time.monotonic(),
        complexity_warning=complexity_warning,
    )


# ---------------------------------------------------------------------------
# 18  Default visibility
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workspace_overlay_hidden_by_default():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        assert not ov.has_class("--visible")


# ---------------------------------------------------------------------------
# 19  /workspace command
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_workspace_slash_command_shows_overlay():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _submit(pilot, app, "/workspace")
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        assert ov.has_class("--visible")


# ---------------------------------------------------------------------------
# 20  w key when input not focused
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_w_key_shows_overlay_when_input_not_focused():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.input_widget import HermesInput
        inp = app.query_one(HermesInput)
        # Blur the input by focusing the app root
        app.set_focus(None)
        await pilot.pause()
        await pilot.press("w")
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        assert ov.has_class("--visible")


# ---------------------------------------------------------------------------
# 21  w key when input IS focused — overlay stays hidden
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_w_key_does_not_open_overlay_when_input_focused():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        from hermes_cli.tui.input_widget import HermesInput
        inp = app.query_one(HermesInput)
        inp.focus()
        await pilot.pause()
        assert inp.has_focus
        await pilot.press("w")
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        assert not ov.has_class("--visible")


# ---------------------------------------------------------------------------
# 22  Esc hides overlay, restores input focus
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_esc_hides_workspace_overlay():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _submit(pilot, app, "/workspace")
        await pilot.pause()
        assert app.query_one(WorkspaceOverlay).has_class("--visible")
        await pilot.press("escape")
        await pilot.pause()
        assert not app.query_one(WorkspaceOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_esc_restores_input_focus():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        from hermes_cli.tui.input_widget import HermesInput
        await pilot.pause()
        await _submit(pilot, app, "/workspace")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        inp = app.query_one(HermesInput)
        assert inp.has_focus


# ---------------------------------------------------------------------------
# 23  refresh_data updates file rows
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_data_updates_file_rows():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        tracker = _make_tracker([_entry(path="/repo/foo.py", rel_path="foo.py")])
        ov.refresh_data(tracker, None)
        await pilot.pause()
        files = ov.query_one("#ws-files")
        children = list(files.children)
        assert len(children) == 1


# ---------------------------------------------------------------------------
# 24  M status char shown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_modified_file_shows_m_status():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        tracker = _make_tracker([_entry(git_status="M")])
        ov.refresh_data(tracker, None)
        await pilot.pause()
        files = ov.query_one("#ws-files")
        child = list(files.children)[0]
        rendered = child.render()
        assert "M" in str(rendered)


# ---------------------------------------------------------------------------
# 25  A status char shown
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_added_file_shows_a_status():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        tracker = _make_tracker([_entry(git_status="A")])
        ov.refresh_data(tracker, None)
        await pilot.pause()
        files = ov.query_one("#ws-files")
        child = list(files.children)[0]
        rendered = str(child.render())
        assert "A" in rendered


# ---------------------------------------------------------------------------
# 26  +N -N counts rendered
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_file_row_shows_line_counts():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        tracker = _make_tracker([_entry(session_added=42, session_removed=7)])
        ov.refresh_data(tracker, None)
        await pilot.pause()
        files = ov.query_one("#ws-files")
        child = list(files.children)[0]
        rendered = str(child.render())
        assert "42" in rendered
        assert "7" in rendered


# ---------------------------------------------------------------------------
# 27  Dirty indicator ●
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dirty_indicator_shown():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        tracker = _make_tracker([_entry(git_status="M", git_staged=False)])
        ov.refresh_data(tracker, None)
        await pilot.pause()
        files = ov.query_one("#ws-files")
        child = list(files.children)[0]
        rendered = str(child.render())
        assert "●" in rendered


# ---------------------------------------------------------------------------
# 28  Complexity warning row appears
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complexity_warning_row_appears():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        tracker = _make_tracker([
            _entry(complexity_warning="1,847 lines · class HermesApp 1,203L")
        ])
        ov.refresh_data(tracker, None)
        await pilot.pause()
        complexity = ov.query_one("#ws-complexity")
        children = list(complexity.children)
        # blank separator + 1 warning row
        assert len(children) >= 2


# ---------------------------------------------------------------------------
# 29  Complexity section hidden when no warnings
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complexity_section_empty_when_no_warnings():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        tracker = _make_tracker([_entry(complexity_warning=None)])
        ov.refresh_data(tracker, None)
        await pilot.pause()
        complexity = ov.query_one("#ws-complexity")
        assert len(list(complexity.children)) == 0


# ---------------------------------------------------------------------------
# 30  _dismiss_all_info_overlays hides WorkspaceOverlay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dismiss_all_hides_workspace_overlay():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        ov.add_class("--visible")
        await pilot.pause()
        app._dismiss_all_info_overlays()
        await pilot.pause()
        assert not ov.has_class("--visible")


# ---------------------------------------------------------------------------
# 31  watch_agent_running(True) dismisses WorkspaceOverlay
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_start_dismisses_workspace_overlay():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        ov.add_class("--visible")
        await pilot.pause()
        app.agent_running = True
        await pilot.pause()
        assert not ov.has_class("--visible")


# ---------------------------------------------------------------------------
# 32  Flash hint shown once on first write (not twice)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flash_hint_shown_once():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        flash_calls: list[str] = []
        original_flash = app._flash_hint
        app._flash_hint = lambda msg, dur: flash_calls.append(msg)

        snapshot = GitSnapshot(branch="main", dirty_count=1, status_lines=["M  foo.py"])
        # Set up tracker with one entry
        tracker = WorkspaceTracker("/repo")
        tracker.record_write("/repo/foo.py", 5, 0)
        app._workspace_tracker = tracker

        # First workspace update
        from hermes_cli.tui.workspace_tracker import WorkspaceUpdated
        app.post_message(WorkspaceUpdated(snapshot))
        await pilot.pause()
        await pilot.pause()

        # Second workspace update — hint should NOT fire again
        app.post_message(WorkspaceUpdated(snapshot))
        await pilot.pause()
        await pilot.pause()

        # Restore
        app._flash_hint = original_flash
        workspace_hints = [c for c in flash_calls if "workspace" in c]
        assert len(workspace_hints) == 1


# ---------------------------------------------------------------------------
# 33  refresh_data(snapshot=None) renders header without branch/dirty chip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_data_none_snapshot_shows_plain_header():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        ov = app.query_one(WorkspaceOverlay)
        tracker = _make_tracker()
        ov.refresh_data(tracker, None)
        await pilot.pause()
        header = ov.query_one("#ws-header", Static)
        rendered = str(header.render())
        # Should contain "Workspace" but no branch or dirty chip
        assert "Workspace" in rendered
        assert "dirty" not in rendered
