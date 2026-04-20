"""Tests for WorkspaceOverlay TUI integration."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.commands import COMMANDS
from hermes_cli.tui.overlays import WorkspaceOverlay
from hermes_cli.tui.workspace_tracker import (
    GitSnapshot,
    GitSnapshotEntry,
    WorkspaceTracker,
    WorkspaceUpdated,
)
from textual.widgets import Static


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


def _make_tracker(repo_root: str = "/repo", is_git_repo: bool = True) -> WorkspaceTracker:
    return WorkspaceTracker(repo_root, is_git_repo=is_git_repo)


def test_workspace_slash_command_is_registered():
    assert "/workspace" in COMMANDS


def _snap_entry(
    path: str = "/repo/foo.py",
    rel_path: str = "foo.py",
    git_xy: str = " M",
    git_status: str = "M",
    git_staged: bool = False,
    git_untracked: bool = False,
    git_conflicted: bool = False,
    git_renamed: bool = False,
    renamed_from: str | None = None,
) -> GitSnapshotEntry:
    return GitSnapshotEntry(
        path=path,
        rel_path=rel_path,
        git_xy=git_xy,
        git_index_status=git_xy[0],
        git_worktree_status=git_xy[1],
        git_status=git_status,
        git_staged=git_staged,
        git_untracked=git_untracked,
        git_conflicted=git_conflicted,
        git_renamed=git_renamed,
        renamed_from=renamed_from,
    )


def _snapshot(
    entries: list[GitSnapshotEntry],
    *,
    branch: str = "main",
    is_git_repo: bool = True,
) -> GitSnapshot:
    return GitSnapshot(
        branch=branch,
        dirty_count=len(entries),
        entries=entries,
        staged_count=sum(1 for e in entries if e.git_staged),
        untracked_count=sum(1 for e in entries if e.git_untracked),
        modified_count=sum(1 for e in entries if e.git_status == "M"),
        deleted_count=sum(1 for e in entries if e.git_status == "D"),
        renamed_count=sum(1 for e in entries if e.git_renamed),
        conflicted_count=sum(1 for e in entries if e.git_conflicted),
        is_git_repo=is_git_repo,
    )


@pytest.mark.asyncio
async def test_workspace_overlay_hidden_by_default():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        assert not app.query_one(WorkspaceOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_workspace_slash_command_shows_overlay():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        await _submit(pilot, app, "/workspace")
        await pilot.pause()
        assert app.query_one(WorkspaceOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_w_key_shows_overlay_when_input_not_focused():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        app.set_focus(None)
        await pilot.pause()
        await pilot.press("w")
        await pilot.pause()
        assert app.query_one(WorkspaceOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_w_key_does_not_open_overlay_when_input_focused():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        from hermes_cli.tui.input_widget import HermesInput

        await pilot.pause()
        inp = app.query_one(HermesInput)
        inp.focus()
        await pilot.pause()
        await pilot.press("w")
        await pilot.pause()
        assert not app.query_one(WorkspaceOverlay).has_class("--visible")


@pytest.mark.asyncio
async def test_esc_hides_workspace_overlay_and_restores_input_focus():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        from hermes_cli.tui.input_widget import HermesInput

        await pilot.pause()
        await _submit(pilot, app, "/workspace")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not app.query_one(WorkspaceOverlay).has_class("--visible")
        assert app.query_one(HermesInput).has_focus


@pytest.mark.asyncio
async def test_refresh_data_renders_git_header_summary_and_file_rows():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        tracker = _make_tracker()
        snap = _snapshot(
            [
                _snap_entry(path="/repo/foo.py", rel_path="foo.py", git_xy=" M", git_status="M"),
                _snap_entry(
                    path="/repo/new.txt",
                    rel_path="new.txt",
                    git_xy="??",
                    git_status="?",
                    git_untracked=True,
                ),
            ]
        )
        tracker.apply_snapshot(snap)
        ov = app.query_one(WorkspaceOverlay)
        ov.refresh_data(tracker, snap)
        await pilot.pause()

        header = str(ov.query_one("#ws-header", Static).render())
        summary = str(ov.query_one("#ws-summary", Static).render())
        rows = list(ov.query_one("#ws-files").children)

        assert "Workspace" in header
        assert "main" in header
        assert "2 dirty" in header
        assert "1 modified" in summary
        assert "1 untracked" in summary
        assert len(rows) == 2
        rendered_rows = [str(child.render()) for child in rows]
        assert any("foo.py" in row and "M" in row for row in rendered_rows)
        assert any("new.txt" in row and "untracked" in row for row in rendered_rows)


@pytest.mark.asyncio
async def test_refresh_data_renders_hermes_annotations_and_complexity():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        tracker = _make_tracker()
        tracker.record_write("/repo/foo.py", 42, 7)
        tracker.set_complexity("/repo/foo.py", "1,847 lines · class HermesApp 1,203L")
        snap = _snapshot([_snap_entry(path="/repo/foo.py", rel_path="foo.py")])
        tracker.apply_snapshot(snap)

        ov = app.query_one(WorkspaceOverlay)
        ov.refresh_data(tracker, snap)
        await pilot.pause()

        row = str(list(ov.query_one("#ws-files").children)[0].render())
        complexity_rows = [str(child.render()) for child in ov.query_one("#ws-complexity").children]

        assert "Hermes" in row
        assert "+42" in row
        assert "-7" in row
        assert any("HermesApp" in child for child in complexity_rows)


@pytest.mark.asyncio
async def test_refresh_data_shows_rename_microcopy():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        tracker = _make_tracker()
        snap = _snapshot(
            [
                _snap_entry(
                    path="/repo/new_name.py",
                    rel_path="new_name.py",
                    git_xy="R ",
                    git_status="R",
                    git_staged=True,
                    git_renamed=True,
                    renamed_from="old_name.py",
                )
            ]
        )
        tracker.apply_snapshot(snap)
        ov = app.query_one(WorkspaceOverlay)
        ov.refresh_data(tracker, snap)
        await pilot.pause()

        row = str(list(ov.query_one("#ws-files").children)[0].render())
        assert "new_name.py" in row
        assert "old_name.py" in row
        assert "staged" in row


@pytest.mark.asyncio
async def test_refresh_data_none_snapshot_shows_loading_state():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        tracker = _make_tracker()
        ov = app.query_one(WorkspaceOverlay)
        ov.refresh_data(tracker, None)
        await pilot.pause()

        header = str(ov.query_one("#ws-header", Static).render())
        summary = str(ov.query_one("#ws-summary", Static).render())
        assert "Workspace" in header
        assert "Loading git status" in summary


@pytest.mark.asyncio
async def test_refresh_data_non_git_repo_shows_empty_state():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        tracker = _make_tracker(is_git_repo=False)
        ov = app.query_one(WorkspaceOverlay)
        ov.refresh_data(tracker, None)
        await pilot.pause()

        summary = str(ov.query_one("#ws-summary", Static).render())
        assert "requires a Git repository" in summary
        assert len(list(ov.query_one("#ws-files").children)) == 0


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


@pytest.mark.asyncio
async def test_flash_hint_shown_once_for_first_non_empty_workspace_update():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        flash_calls: list[str] = []
        app._flash_hint = lambda msg, dur: flash_calls.append(msg)

        tracker = _make_tracker()
        tracker.record_write("/repo/foo.py", 5, 0)
        app._workspace_tracker = tracker

        snap = _snapshot([_snap_entry(path="/repo/foo.py", rel_path="foo.py")])
        app.post_message(WorkspaceUpdated(snap))
        await pilot.pause()
        await pilot.pause()

        app.post_message(WorkspaceUpdated(snap))
        await pilot.pause()
        await pilot.pause()

        workspace_hints = [msg for msg in flash_calls if "workspace" in msg]
        assert len(workspace_hints) == 1


@pytest.mark.asyncio
async def test_hermes_touched_files_sort_ahead_of_other_dirty_files():
    app = _make_app()
    async with app.run_test(size=(80, 30)) as pilot:
        await pilot.pause()
        tracker = _make_tracker()
        tracker.record_write("/repo/z.py", 1, 0)
        time.sleep(0.01)
        tracker.record_write("/repo/m.py", 1, 0)
        snap = _snapshot(
            [
                _snap_entry(path="/repo/a.py", rel_path="a.py"),
                _snap_entry(path="/repo/m.py", rel_path="m.py"),
                _snap_entry(path="/repo/z.py", rel_path="z.py"),
            ]
        )
        tracker.apply_snapshot(snap)

        ov = app.query_one(WorkspaceOverlay)
        ov.refresh_data(tracker, snap)
        await pilot.pause()

        rendered_rows = [str(child.render()) for child in ov.query_one("#ws-files").children]
        assert "m.py" in rendered_rows[0]
        assert "z.py" in rendered_rows[1]
        assert "a.py" in rendered_rows[2]
