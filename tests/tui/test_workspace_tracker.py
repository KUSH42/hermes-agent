"""Unit tests for WorkspaceTracker, GitSnapshot, FileEntry, and analyze_complexity.

Tests 1–17 (no Textual app needed — pure Python).

1.  record_write creates entry with correct path + counts
2.  record_write second call accumulates adds/removes
3.  record_write updates last_write to most recent
4.  entries() sorted by last_write descending
5.  session_totals() sums across all entries
6.  counts_by_status() correct counts per status char
7.  apply_git_status sets git_status on matching entry
8.  apply_git_status ignores paths not in session set
9.  apply_git_status sets git_staged=True for index-staged files
10. apply_git_status skips rename lines (R  old -> new format)
11. set_complexity updates complexity_warning; no-op for unknown path
12. analyze_complexity returns None for small file
13. analyze_complexity returns warning for large class (>300L)
14. analyze_complexity returns warning for large function (>150L)
15. analyze_complexity returns warning for file >800 total lines
16. analyze_complexity returns None for non-Python file
17. analyze_complexity returns None on parse error (bad syntax)
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

import pytest

from hermes_cli.tui.workspace_tracker import (
    FileEntry,
    GitSnapshot,
    WorkspaceTracker,
    analyze_complexity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tracker(repo_root: str = "/repo") -> WorkspaceTracker:
    return WorkspaceTracker(repo_root)


# ---------------------------------------------------------------------------
# 1–3  record_write
# ---------------------------------------------------------------------------

def test_record_write_creates_entry():
    t = _tracker()
    t.record_write("/repo/foo.py", 10, 2)
    entries = t.entries()
    assert len(entries) == 1
    e = entries[0]
    assert e.path == "/repo/foo.py"
    assert e.session_added == 10
    assert e.session_removed == 2
    assert e.git_status == " "
    assert not e.git_staged


def test_record_write_accumulates():
    t = _tracker()
    t.record_write("/repo/foo.py", 10, 2)
    t.record_write("/repo/foo.py", 5, 1)
    e = t.entries()[0]
    assert e.session_added == 15
    assert e.session_removed == 3


def test_record_write_updates_last_write():
    t = _tracker()
    t.record_write("/repo/foo.py", 1, 0)
    first = t.entries()[0].last_write
    time.sleep(0.01)
    t.record_write("/repo/foo.py", 1, 0)
    second = t.entries()[0].last_write
    assert second > first


# ---------------------------------------------------------------------------
# 4  entries() sort order
# ---------------------------------------------------------------------------

def test_entries_sorted_by_last_write_desc():
    t = _tracker()
    t.record_write("/repo/a.py", 1, 0)
    time.sleep(0.01)
    t.record_write("/repo/b.py", 1, 0)
    paths = [e.path for e in t.entries()]
    assert paths == ["/repo/b.py", "/repo/a.py"]


# ---------------------------------------------------------------------------
# 5–6  session_totals / counts_by_status
# ---------------------------------------------------------------------------

def test_session_totals():
    t = _tracker()
    t.record_write("/repo/a.py", 10, 2)
    t.record_write("/repo/b.py", 5, 3)
    added, removed = t.session_totals()
    assert added == 15
    assert removed == 5


def test_counts_by_status():
    t = _tracker()
    t.record_write("/repo/a.py", 1, 0)
    t.record_write("/repo/b.py", 1, 0)
    t.apply_git_status([" M a.py", "?? b.py"])
    counts = t.counts_by_status()
    assert counts.get("M", 0) == 1
    assert counts.get("?", 0) == 1


# ---------------------------------------------------------------------------
# 7–10  apply_git_status
# ---------------------------------------------------------------------------

def test_apply_git_status_sets_git_status():
    t = _tracker()
    t.record_write("/repo/foo.py", 1, 0)
    t.apply_git_status([" M foo.py"])
    assert t.entries()[0].git_status == "M"


def test_apply_git_status_ignores_unknown_paths():
    t = _tracker()
    t.record_write("/repo/foo.py", 1, 0)
    t.apply_git_status([" M bar.py"])  # not in session set
    assert t.entries()[0].git_status == " "  # unchanged


def test_apply_git_status_staged():
    t = _tracker()
    t.record_write("/repo/foo.py", 1, 0)
    t.apply_git_status(["M  foo.py"])  # index char 'M', wt ' '
    e = t.entries()[0]
    assert e.git_staged is True
    assert e.git_status == "M"


def test_apply_git_status_skips_rename_lines():
    t = _tracker()
    t.record_write("/repo/old.py", 1, 0)
    # Rename line — should be ignored
    t.apply_git_status(["R  old.py -> new.py"])
    assert t.entries()[0].git_status == " "  # unchanged


# ---------------------------------------------------------------------------
# 11  set_complexity
# ---------------------------------------------------------------------------

def test_set_complexity_updates_entry():
    t = _tracker()
    t.record_write("/repo/foo.py", 1, 0)
    t.set_complexity("/repo/foo.py", "1,200 lines · class Foo 900L")
    assert t.entries()[0].complexity_warning == "1,200 lines · class Foo 900L"


def test_set_complexity_noop_for_unknown_path():
    t = _tracker()
    # Should not raise, should have no effect
    t.set_complexity("/repo/nonexistent.py", "whatever")
    assert t.entries() == []


# ---------------------------------------------------------------------------
# 12–17  analyze_complexity (uses real files via tmp_path)
# ---------------------------------------------------------------------------

def test_analyze_complexity_small_file_returns_none(tmp_path):
    f = tmp_path / "small.py"
    f.write_text("def foo():\n    return 1\n")
    assert analyze_complexity(str(f)) is None


def test_analyze_complexity_large_class(tmp_path):
    # Build a class > 300 lines
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
    # > 800 lines total
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
