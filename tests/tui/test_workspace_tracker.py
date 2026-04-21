"""Unit tests for WorkspaceTracker, GitPoller parsing helpers, and complexity analysis."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from hermes_cli.tui.workspace_tracker import (
    FileEntry,
    GitPoller,
    GitSnapshot,
    GitSnapshotEntry,
    WorkspaceTracker,
    analyze_complexity,
)


def _tracker(repo_root: str = "/repo", is_git_repo: bool = True) -> WorkspaceTracker:
    return WorkspaceTracker(repo_root, is_git_repo=is_git_repo)


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


def _snapshot(entries: list[GitSnapshotEntry], *, branch: str = "main", is_git_repo: bool = True) -> GitSnapshot:
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


def test_record_write_creates_session_annotation():
    t = _tracker()
    t.record_write("/repo/foo.py", 10, 2)
    added, removed = t.session_totals()
    assert (added, removed) == (10, 2)


def test_record_write_accumulates_session_deltas():
    t = _tracker()
    t.record_write("/repo/foo.py", 10, 2)
    t.record_write("/repo/foo.py", 5, 1)
    assert t.session_totals() == (15, 3)


def test_apply_snapshot_creates_visible_rows_from_git_not_session():
    t = _tracker()
    snap = _snapshot([_snap_entry(path="/repo/bar.py", rel_path="bar.py")])
    t.apply_snapshot(snap)
    rows = t.entries()
    assert len(rows) == 1
    assert rows[0].path == "/repo/bar.py"


def test_apply_snapshot_merges_hermes_metadata_when_present():
    t = _tracker()
    t.record_write("/repo/foo.py", 7, 3)
    snap = _snapshot([_snap_entry(path="/repo/foo.py", rel_path="foo.py")])
    t.apply_snapshot(snap)
    row = t.entries()[0]
    assert row.hermes_touched is True
    assert row.session_added == 7
    assert row.session_removed == 3


def test_clean_file_disappears_when_absent_from_next_snapshot():
    t = _tracker()
    t.record_write("/repo/foo.py", 1, 0)
    t.apply_snapshot(_snapshot([_snap_entry(path="/repo/foo.py", rel_path="foo.py")]))
    assert len(t.entries()) == 1
    t.apply_snapshot(_snapshot([]))
    assert t.entries() == []
    assert t.session_totals() == (1, 0)


def test_entries_promote_hermes_touched_then_sort_remaining_by_rel_path():
    t = _tracker()
    t.record_write("/repo/z.py", 1, 0)
    time.sleep(0.01)
    t.record_write("/repo/m.py", 1, 0)
    snap = _snapshot(
        [
            _snap_entry(path="/repo/a.py", rel_path="a.py"),
            _snap_entry(path="/repo/m.py", rel_path="m.py"),
            _snap_entry(path="/repo/z.py", rel_path="z.py"),
        ]
    )
    t.apply_snapshot(snap)
    paths = [e.rel_path for e in t.entries()]
    assert paths == ["m.py", "z.py", "a.py"]


def test_set_complexity_is_annotation_only_for_hermes_files():
    t = _tracker()
    t.record_write("/repo/foo.py", 1, 0)
    t.set_complexity("/repo/foo.py", "1,200 lines · class Foo 900L")
    t.apply_snapshot(_snapshot([_snap_entry(path="/repo/foo.py", rel_path="foo.py")]))
    assert t.entries()[0].complexity_warning == "1,200 lines · class Foo 900L"


def test_non_git_snapshot_clears_visible_rows_and_marks_tracker_non_git():
    t = _tracker()
    t.record_write("/repo/foo.py", 1, 0)
    t.apply_snapshot(_snapshot([], is_git_repo=False))
    assert t.is_git_repo is False
    assert t.entries() == []


def test_counts_by_status_counts_current_visible_rows():
    t = _tracker()
    t.apply_snapshot(
        _snapshot(
            [
                _snap_entry(path="/repo/a.py", rel_path="a.py", git_status="M"),
                _snap_entry(path="/repo/b.py", rel_path="b.py", git_xy="??", git_status="?", git_untracked=True),
            ]
        )
    )
    counts = t.counts_by_status()
    assert counts == {"M": 1, "?": 1}


def test_git_poller_non_git_repo_returns_non_git_snapshot():
    poller = GitPoller("/tmp", is_git_repo=False)
    snap = poller.poll()
    assert snap.is_git_repo is False
    assert snap.entries == []


def test_git_poller_normalize_status():
    assert GitPoller._normalize_status("??", "?", "?") == "?"
    assert GitPoller._normalize_status("UU", "U", "U") == "U"
    assert GitPoller._normalize_status("M ", "M", " ") == "M"
    assert GitPoller._normalize_status(" M", " ", "M") == "M"


def test_analyze_complexity_small_file_returns_none(tmp_path):
    f = tmp_path / "small.py"
    f.write_text("def foo():\n    return 1\n")
    assert analyze_complexity(str(f)) is None


def test_analyze_complexity_large_class(tmp_path):
    body = "    x = 1\n" * 310
    src = "class BigClass:\n" + body
    f = tmp_path / "big_class.py"
    f.write_text(src)
    result = analyze_complexity(str(f))
    assert result is not None
    assert "BigClass" in result


def test_analyze_complexity_large_function(tmp_path):
    body = "    x = 1\n" * 160
    src = "def big_fn():\n" + body
    f = tmp_path / "big_fn.py"
    f.write_text(src)
    result = analyze_complexity(str(f))
    assert result is not None
    assert "big_fn" in result


def test_analyze_complexity_large_file_total(tmp_path):
    lines = ["x = 1"] * 810
    f = tmp_path / "large.py"
    f.write_text("\n".join(lines))
    result = analyze_complexity(str(f))
    assert result is not None
    assert "810" in result or "lines" in result


def test_analyze_complexity_non_python_file(tmp_path):
    f = tmp_path / "script.sh"
    f.write_text("echo hello\n" * 900)
    assert analyze_complexity(str(f)) is None


def test_analyze_complexity_parse_error(tmp_path):
    f = tmp_path / "broken.py"
    f.write_text("def (:\n    bad syntax here\n")
    assert analyze_complexity(str(f)) is None
