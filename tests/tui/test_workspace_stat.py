"""Tests for WSO-STAT-1/2/3 — git numstat stat bar in WorkspaceOverlay."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.overlays import WorkspaceOverlay
from hermes_cli.tui.workspace_tracker import (
    FileEntry,
    GitSnapshot,
    GitSnapshotEntry,
    GitPoller,
    WorkspaceTracker,
)
from textual.widgets import Static


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snap_entry(
    path: str = "/repo/foo.py",
    rel_path: str = "foo.py",
    git_xy: str = " M",
    git_status: str = "M",
    git_staged: bool = False,
    git_untracked: bool = False,
    git_conflicted: bool = False,
    git_renamed: bool = False,
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
    )


def _snapshot(
    entries: list[GitSnapshotEntry],
    *,
    branch: str = "main",
    is_git_repo: bool = True,
    numstat: dict[str, tuple[int, int]] | None = None,
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
        numstat=numstat or {},
    )


def _make_tracker(repo_root: str = "/repo") -> WorkspaceTracker:
    return WorkspaceTracker(repo_root)


def _make_app():
    from hermes_cli.tui.app import HermesApp
    cli = MagicMock()
    cli.agent = None
    return HermesApp(cli=cli)


# ---------------------------------------------------------------------------
# WSO-STAT-1 — numstat populated in GitSnapshot from poll()
# ---------------------------------------------------------------------------


class TestNumstatSnapshot:
    def _make_poller(self) -> GitPoller:
        return GitPoller("/repo", is_git_repo=True)

    def test_numstat_populated_from_git_output(self):
        poller = self._make_poller()

        def fake_check_output(cmd, **kwargs):
            if "--porcelain=v1" in cmd:
                return b" M foo.py\0"
            if "--numstat" in cmd:
                return b"5\t3\tfoo.py\n"
            if "--abbrev-ref" in cmd:
                return b"main\n"
            return b""

        with patch("subprocess.check_output", side_effect=fake_check_output):
            snapshot = poller.poll()

        assert snapshot.numstat == {"foo.py": (5, 3)}

    def test_numstat_binary_line_skipped(self):
        poller = self._make_poller()

        def fake_check_output(cmd, **kwargs):
            if "--porcelain=v1" in cmd:
                return b" M foo.bin\0"
            if "--numstat" in cmd:
                return b"-\t-\tfoo.bin\n"
            if "--abbrev-ref" in cmd:
                return b"main\n"
            return b""

        with patch("subprocess.check_output", side_effect=fake_check_output):
            snapshot = poller.poll()

        assert snapshot.numstat == {}


# ---------------------------------------------------------------------------
# WSO-STAT-2 — numstat propagated into FileEntry
# ---------------------------------------------------------------------------


class TestFileEntryPropagation:
    def test_apply_snapshot_sets_git_added_removed(self):
        tracker = _make_tracker()
        snap = _snapshot(
            [_snap_entry(path="/repo/foo.py", rel_path="foo.py")],
            numstat={"foo.py": (5, 3)},
        )
        tracker.apply_snapshot(snap)
        entry = tracker.entries()[0]
        assert entry.git_added == 5
        assert entry.git_removed == 3

    def test_apply_snapshot_numstat_missing_key_defaults_zero(self):
        tracker = _make_tracker()
        snap = _snapshot(
            [_snap_entry(path="/repo/foo.py", rel_path="foo.py")],
            numstat={},
        )
        tracker.apply_snapshot(snap)
        entry = tracker.entries()[0]
        assert entry.git_added == 0
        assert entry.git_removed == 0

    def test_record_write_preserves_git_added(self):
        tracker = _make_tracker()
        snap = _snapshot(
            [_snap_entry(path="/repo/foo.py", rel_path="foo.py")],
            numstat={"foo.py": (5, 3)},
        )
        tracker.apply_snapshot(snap)
        tracker.record_write("/repo/foo.py", 1, 0)
        entry = tracker.entries()[0]
        assert entry.git_added == 5  # not zeroed by _merge_entry


# ---------------------------------------------------------------------------
# WSO-STAT-3 — WorkspaceOverlay renders correct stat bar
# ---------------------------------------------------------------------------


def _make_file_entry(
    path: str = "/repo/foo.py",
    rel_path: str = "foo.py",
    git_xy: str = " M",
    git_status: str = "M",
    git_staged: bool = False,
    git_untracked: bool = False,
    git_conflicted: bool = False,
    git_renamed: bool = False,
    session_added: int = 0,
    session_removed: int = 0,
    hermes_touched: bool = False,
    git_added: int = 0,
    git_removed: int = 0,
) -> FileEntry:
    return FileEntry(
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
        session_added=session_added,
        session_removed=session_removed,
        hermes_touched=hermes_touched,
        git_added=git_added,
        git_removed=git_removed,
    )


class TestOverlayRender:
    @pytest.mark.asyncio
    async def test_render_git_wins_over_session(self):
        app = _make_app()
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            tracker = _make_tracker()
            entry = _make_file_entry(
                git_added=5, git_removed=3,
                session_added=2, session_removed=0,
                hermes_touched=True,
            )
            snap = _snapshot([_snap_entry()], numstat={"foo.py": (5, 3)})
            tracker.apply_snapshot(snap)

            ov = app.query_one(WorkspaceOverlay)
            ov.refresh_data(tracker, snap)
            await pilot.pause()

            rows = list(ov.query_one("#ws-files").children)
            assert rows, "expected at least one file row"
            row_text = str(rows[0].render())
            assert "+5" in row_text
            assert "-3" in row_text

    @pytest.mark.asyncio
    async def test_render_session_fallback(self):
        app = _make_app()
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            tracker = _make_tracker()
            snap = _snapshot([_snap_entry()], numstat={})
            tracker.apply_snapshot(snap)
            tracker.record_write("/repo/foo.py", 3, 1)

            ov = app.query_one(WorkspaceOverlay)
            ov.refresh_data(tracker, snap)
            await pilot.pause()

            rows = list(ov.query_one("#ws-files").children)
            assert rows, "expected at least one file row"
            row_text = str(rows[0].render())
            assert "+3" in row_text
            assert "-1" in row_text

    @pytest.mark.asyncio
    async def test_render_untracked_no_delta(self):
        app = _make_app()
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            tracker = _make_tracker()
            snap = _snapshot(
                [_snap_entry(git_xy="??", git_status="?", git_untracked=True)],
                numstat={},
            )
            tracker.apply_snapshot(snap)
            tracker.record_write("/repo/foo.py", 5, 0)

            ov = app.query_one(WorkspaceOverlay)
            ov.refresh_data(tracker, snap)
            await pilot.pause()

            rows = list(ov.query_one("#ws-files").children)
            assert rows, "expected at least one file row"
            row_text = str(rows[0].render())
            # untracked: no delta should be shown even though session_added=5
            assert "+5" not in row_text

    @pytest.mark.asyncio
    async def test_render_zero_both_hidden(self):
        app = _make_app()
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            tracker = _make_tracker()
            snap = _snapshot([_snap_entry()], numstat={})
            tracker.apply_snapshot(snap)

            ov = app.query_one(WorkspaceOverlay)
            ov.refresh_data(tracker, snap)
            await pilot.pause()

            rows = list(ov.query_one("#ws-files").children)
            assert rows, "expected at least one file row"
            row_text = str(rows[0].render())
            # zero delta both sources: no +0 should appear
            assert "+0" not in row_text
