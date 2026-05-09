"""Tests for WorkspaceOverlay auto-popup and ESC suppression (WSO-AUTO-1/2/3)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hermes_cli.tui.app import HermesApp
from hermes_cli.tui.overlays import WorkspaceOverlay
from hermes_cli.tui.workspace_tracker import (
    GitSnapshot,
    GitSnapshotEntry,
    WorkspaceTracker,
)


def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.agent = None
    return HermesApp(cli=cli)


def _snap_entry(path: str = "/repo/foo.py", rel_path: str = "foo.py") -> GitSnapshotEntry:
    return GitSnapshotEntry(
        path=path,
        rel_path=rel_path,
        git_xy=" M",
        git_index_status=" ",
        git_worktree_status="M",
        git_status="M",
        git_staged=False,
        git_untracked=False,
        git_conflicted=False,
        git_renamed=False,
        renamed_from=None,
    )


def _snapshot(entries: list[GitSnapshotEntry]) -> GitSnapshot:
    return GitSnapshot(
        branch="main",
        dirty_count=len(entries),
        entries=entries,
        staged_count=0,
        untracked_count=0,
        modified_count=len(entries),
        deleted_count=0,
        renamed_count=0,
        conflicted_count=0,
        is_git_repo=True,
    )


def _make_tracker_with_entries() -> WorkspaceTracker:
    tracker = WorkspaceTracker("/repo", is_git_repo=True)
    snap = _snapshot([_snap_entry()])
    tracker.apply_snapshot(snap)
    return tracker


def _make_tracker_empty() -> WorkspaceTracker:
    return WorkspaceTracker("/repo", is_git_repo=True)


# ---------------------------------------------------------------------------
# TestSuppressionFlag — WSO-AUTO-1
# ---------------------------------------------------------------------------

class TestSuppressionFlag:
    def test_suppression_flag_initialised_false(self):
        app = _make_app()
        assert app._workspace_auto_suppressed is False


# ---------------------------------------------------------------------------
# TestAutoShow — WSO-AUTO-2
# ---------------------------------------------------------------------------

class TestAutoShow:
    @pytest.mark.asyncio
    async def test_auto_show_fires_on_run_end_with_entries(self):
        app = _make_app()
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            app._workspace_tracker = _make_tracker_with_entries()
            app._workspace_auto_suppressed = False
            app.agent_running = True
            await pilot.pause()
            app.agent_running = False
            await pilot.pause()
            assert app.query_one(WorkspaceOverlay).has_class("--visible")

    @pytest.mark.asyncio
    async def test_auto_show_skipped_when_suppressed(self):
        app = _make_app()
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            app._workspace_tracker = _make_tracker_with_entries()
            app.agent_running = True
            await pilot.pause()
            # Set suppression AFTER run-start clears it (simulates user dismissing during run)
            app._workspace_auto_suppressed = True
            app.agent_running = False
            await pilot.pause()
            assert not app.query_one(WorkspaceOverlay).has_class("--visible")

    @pytest.mark.asyncio
    async def test_auto_show_skipped_when_no_entries(self):
        app = _make_app()
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            app._workspace_tracker = _make_tracker_empty()
            app._workspace_auto_suppressed = False
            app.agent_running = True
            await pilot.pause()
            app.agent_running = False
            await pilot.pause()
            assert not app.query_one(WorkspaceOverlay).has_class("--visible")

    @pytest.mark.asyncio
    async def test_auto_show_skipped_when_focus_blocking(self):
        app = _make_app()
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            app._workspace_tracker = _make_tracker_with_entries()
            app._workspace_auto_suppressed = False
            # Patch _focus_blocking_overlay_visible to return True
            app._focus_blocking_overlay_visible = lambda: True
            app.agent_running = True
            await pilot.pause()
            app.agent_running = False
            await pilot.pause()
            assert not app.query_one(WorkspaceOverlay).has_class("--visible")

    @pytest.mark.asyncio
    async def test_auto_show_skipped_when_already_visible(self):
        app = _make_app()
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            app._workspace_tracker = _make_tracker_with_entries()
            app.agent_running = True
            await pilot.pause()
            # Add --visible AFTER run-start (which dismisses info overlays) to
            # simulate the overlay being open when the run ends.
            ov = app.query_one(WorkspaceOverlay)
            ov.add_class("--visible")
            show_calls: list[int] = []
            original_show = ov.show_overlay
            def _track_show() -> None:
                show_calls.append(1)
                original_show()
            ov.show_overlay = _track_show  # type: ignore[method-assign]
            app.agent_running = False
            await pilot.pause()
            assert len(show_calls) == 0


# ---------------------------------------------------------------------------
# TestDismissLifecycle — WSO-AUTO-3
# ---------------------------------------------------------------------------

class TestDismissLifecycle:
    def test_esc_dismiss_sets_suppressed(self):
        class _StubOverlay(WorkspaceOverlay):
            def __init__(self) -> None:
                self._mock_app = MagicMock()
                self.dismiss_overlay = MagicMock()  # type: ignore[method-assign]

            @property  # type: ignore[override]
            def app(self):
                return self._mock_app

        ov = _StubOverlay()
        ov.action_dismiss()
        assert ov._mock_app._workspace_auto_suppressed is True
        ov._mock_app._sync_workspace_polling_state.assert_called_once()
        ov.dismiss_overlay.assert_called_once()

    @pytest.mark.asyncio
    async def test_suppressed_clears_on_run_start(self):
        app = _make_app()
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            app._workspace_auto_suppressed = True
            app.agent_running = True
            await pilot.pause()
            assert app._workspace_auto_suppressed is False

    @pytest.mark.asyncio
    async def test_toggle_close_sets_suppressed(self):
        app = _make_app()
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            # Open the overlay first
            ov = app.query_one(WorkspaceOverlay)
            ov.add_class("--visible")
            await pilot.pause()
            # Toggle via action (which calls action_dismiss when visible)
            app.action_toggle_workspace()
            await pilot.pause()
            assert app._workspace_auto_suppressed is True
            assert not ov.has_class("--visible")


# ---------------------------------------------------------------------------
# TestFingerprintGate — change-detection gate (no repeat pop for same state)
# ---------------------------------------------------------------------------

class TestFingerprintGate:
    @pytest.mark.asyncio
    async def test_no_repop_when_workspace_unchanged(self):
        """Overlay should NOT pop on second turn end if workspace unchanged."""
        app = _make_app()
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            tracker = _make_tracker_with_entries()
            # Pin tracker and disable git poll so _init_workspace_tracker background
            # worker cannot replace our test tracker between turns.
            app._workspace_tracker = tracker
            app._git_poller = None
            app._workspace_auto_suppressed = False
            # First turn: fires and stores fingerprint
            app.agent_running = True
            await pilot.pause()
            # Re-pin in case background worker fired during pause
            app._workspace_tracker = tracker
            app._git_poller = None
            app.agent_running = False
            await pilot.pause()
            ov = app.query_one(WorkspaceOverlay)
            assert ov.has_class("--visible"), "First pop should fire"
            stored_fp = app._workspace_last_shown_fingerprint
            assert stored_fp is not None
            # Dismiss and start a second turn without changing workspace
            ov.remove_class("--visible")
            app._workspace_auto_suppressed = False  # simulate suppression cleared by run-start
            app.agent_running = True
            await pilot.pause()
            # Re-pin again
            app._workspace_tracker = tracker
            app._git_poller = None
            app.agent_running = False
            await pilot.pause()
            assert not ov.has_class("--visible"), "Should NOT repop — workspace unchanged"
            assert app._workspace_last_shown_fingerprint == stored_fp

    @pytest.mark.asyncio
    async def test_repop_when_workspace_changes(self):
        """Overlay SHOULD pop again if a new file appears after the first show."""
        app = _make_app()
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            tracker = _make_tracker_with_entries()
            app._workspace_tracker = tracker
            app._git_poller = None
            app._workspace_auto_suppressed = False
            # First turn fires
            app.agent_running = True
            await pilot.pause()
            app._workspace_tracker = tracker
            app._git_poller = None
            app.agent_running = False
            await pilot.pause()
            ov = app.query_one(WorkspaceOverlay)
            assert ov.has_class("--visible")
            ov.remove_class("--visible")
            # Add a new file to tracker
            snap = _snapshot([_snap_entry(), _snap_entry("/repo/bar.py", "bar.py")])
            tracker.apply_snapshot(snap)
            # Second turn — workspace changed — should pop
            app._workspace_auto_suppressed = False
            app.agent_running = True
            await pilot.pause()
            app._workspace_tracker = tracker
            app._git_poller = None
            app.agent_running = False
            await pilot.pause()
            assert ov.has_class("--visible"), "Should pop — workspace changed"

    def test_fingerprint_stored_on_show(self):
        """_workspace_last_shown_fingerprint starts None and is distinct per state."""
        t1 = _make_tracker_with_entries()
        t2 = _make_tracker_empty()
        assert t1.fingerprint() != t2.fingerprint()
        assert t2.fingerprint() == t2.fingerprint()  # stable

    def test_fingerprint_changes_on_new_file(self):
        tracker = WorkspaceTracker("/repo", is_git_repo=True)
        fp_before = tracker.fingerprint()
        tracker.apply_snapshot(_snapshot([_snap_entry()]))
        assert tracker.fingerprint() != fp_before

    def test_fingerprint_changes_on_status_change(self):
        tracker = _make_tracker_with_entries()
        fp1 = tracker.fingerprint()
        # Apply snapshot with different git_xy
        entry = _snap_entry()
        entry = GitSnapshotEntry(
            path=entry.path,
            rel_path=entry.rel_path,
            git_xy="M ",
            git_index_status="M",
            git_worktree_status=" ",
            git_status="M",
            git_staged=True,
            git_untracked=False,
            git_conflicted=False,
            git_renamed=False,
            renamed_from=None,
        )
        tracker.apply_snapshot(_snapshot([entry]))
        assert tracker.fingerprint() != fp1
