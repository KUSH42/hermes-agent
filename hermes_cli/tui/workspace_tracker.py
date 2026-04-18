"""WorkspaceTracker — session-scoped file change tracking for WorkspaceOverlay.

Tracks which files the agent touched this session (via tool intercepts), merges
live git status, and runs AST-based complexity analysis on .py files.

All tracker mutations (record_write, apply_git_status, set_complexity) run on
the Textual event loop thread.  Blocking I/O (subprocess, file reads) runs in
@work threads on HermesApp.
"""

from __future__ import annotations

import ast
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from textual.message import Message


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class FileEntry:
    path: str                         # absolute path
    rel_path: str                     # relative to repo root
    git_status: str                   # M / A / D / ? / ' '
    session_added: int                # lines added this session
    session_removed: int              # lines removed this session
    git_staged: bool                  # True if in git index
    last_write: float                 # time.monotonic() of last agent write
    complexity_warning: str | None    # e.g. "1,847 lines · class HermesApp 1,203L"


@dataclass
class GitSnapshot:
    branch: str
    dirty_count: int
    status_lines: list[str]           # raw `git status --short` lines


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

class WorkspaceUpdated(Message):
    """Posted by HermesApp._run_git_poll when a new GitSnapshot is ready."""
    def __init__(self, snapshot: GitSnapshot) -> None:
        super().__init__()
        self.snapshot = snapshot


# ---------------------------------------------------------------------------
# WorkspaceTracker
# ---------------------------------------------------------------------------

class WorkspaceTracker:
    """Session-scoped registry of agent file writes and their git status.

    All public methods are called from the Textual event loop thread.
    """

    def __init__(self, repo_root: str) -> None:
        self._repo_root = repo_root.rstrip("/") if repo_root else ""
        self._entries: dict[str, FileEntry] = {}  # keyed by absolute path

    # ------------------------------------------------------------------
    # Mutation (event loop thread)
    # ------------------------------------------------------------------

    def record_write(self, path: str, added: int, removed: int) -> None:
        """Create or update the FileEntry for path, accumulating line deltas."""
        if path in self._entries:
            e = self._entries[path]
            self._entries[path] = FileEntry(
                path=e.path,
                rel_path=e.rel_path,
                git_status=e.git_status,
                session_added=e.session_added + added,
                session_removed=e.session_removed + removed,
                git_staged=e.git_staged,
                last_write=time.monotonic(),
                complexity_warning=e.complexity_warning,
            )
        else:
            rel = self._rel(path)
            self._entries[path] = FileEntry(
                path=path,
                rel_path=rel,
                git_status=" ",
                session_added=added,
                session_removed=removed,
                git_staged=False,
                last_write=time.monotonic(),
                complexity_warning=None,
            )

    def apply_git_status(self, status_lines: list[str]) -> None:
        """Merge git status --short output into tracked entries.

        Ignores paths not in the session set (workspace is session-scoped).
        Skips rename lines (R  old -> new) for v1.
        """
        for line in status_lines:
            if len(line) < 3:
                continue
            xy = line[:2]
            rest = line[3:]
            # Skip rename lines — format is "R  old -> new" (contains " -> ")
            if " -> " in rest:
                continue
            path_str = rest.strip()
            # Resolve to absolute path for matching
            abs_path = path_str if Path(path_str).is_absolute() else str(
                (Path(self._repo_root) / path_str).resolve()
            )
            if abs_path not in self._entries:
                # Also try matching by rel_path suffix
                abs_path = self._find_by_rel(path_str)
                if abs_path is None:
                    continue
            e = self._entries[abs_path]
            index_char = xy[0].strip()
            wt_char = xy[1].strip()
            git_status = index_char if index_char else wt_char if wt_char else "?"
            git_staged = bool(index_char)
            self._entries[abs_path] = FileEntry(
                path=e.path,
                rel_path=e.rel_path,
                git_status=git_status,
                session_added=e.session_added,
                session_removed=e.session_removed,
                git_staged=git_staged,
                last_write=e.last_write,
                complexity_warning=e.complexity_warning,
            )

    def set_complexity(self, path: str, warning: str | None) -> None:
        """Store complexity warning on matching entry. No-op if not in session set."""
        if path not in self._entries:
            return
        e = self._entries[path]
        self._entries[path] = FileEntry(
            path=e.path,
            rel_path=e.rel_path,
            git_status=e.git_status,
            session_added=e.session_added,
            session_removed=e.session_removed,
            git_staged=e.git_staged,
            last_write=e.last_write,
            complexity_warning=warning,
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def entries(self) -> list[FileEntry]:
        """Return entries sorted by last_write descending (most recent first)."""
        return sorted(self._entries.values(), key=lambda e: e.last_write, reverse=True)

    def session_totals(self) -> tuple[int, int]:
        """Return (total_added, total_removed) across all entries."""
        added = sum(e.session_added for e in self._entries.values())
        removed = sum(e.session_removed for e in self._entries.values())
        return added, removed

    def counts_by_status(self) -> dict[str, int]:
        """Return counts keyed by git_status character."""
        counts: dict[str, int] = {}
        for e in self._entries.values():
            counts[e.git_status] = counts.get(e.git_status, 0) + 1
        return counts

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _rel(self, path: str) -> str:
        if self._repo_root and path.startswith(self._repo_root + "/"):
            return path[len(self._repo_root) + 1:]
        return path

    def _find_by_rel(self, rel_path: str) -> str | None:
        """Find absolute path in entries where rel_path suffix matches."""
        for abs_path, e in self._entries.items():
            if e.rel_path == rel_path or abs_path.endswith("/" + rel_path):
                return abs_path
        return None


# ---------------------------------------------------------------------------
# GitPoller
# ---------------------------------------------------------------------------

class GitPoller:
    """Runs git subprocess calls synchronously.  Must be called from a worker thread."""

    def __init__(self, repo_root: str) -> None:
        self._repo_root = repo_root

    def poll(self) -> GitSnapshot:
        """Run git rev-parse + git status --short.  Returns a GitSnapshot."""
        branch = "unknown"
        status_lines: list[str] = []
        try:
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL,
                cwd=self._repo_root or None,
                timeout=5,
            ).decode().strip()
        except Exception:
            pass
        try:
            raw = subprocess.check_output(
                ["git", "status", "--short"],
                stderr=subprocess.DEVNULL,
                cwd=self._repo_root or None,
                timeout=5,
            ).decode()
            status_lines = [l for l in raw.splitlines() if l.strip()]
        except Exception:
            pass
        dirty_count = len(status_lines)
        return GitSnapshot(branch=branch, dirty_count=dirty_count, status_lines=status_lines)


# ---------------------------------------------------------------------------
# Complexity analysis (pure function — called from @work thread)
# ---------------------------------------------------------------------------

def analyze_complexity(path: str) -> str | None:
    """Return a complexity warning string for a .py file, or None if under threshold.

    Thresholds:
    - File total > 800 lines  → flag (shows largest class label if present)
    - Largest class > 300 lines → flag
    - Largest function > 150 lines → flag (top-level or method)

    Only .py files are analyzed; all other extensions return None immediately.
    """
    if not path.endswith(".py"):
        return None
    try:
        src = Path(path).read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(src)
    except Exception:
        return None

    worst_class: tuple[int, str] | None = None
    worst_fn: tuple[int, str] | None = None

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            end = getattr(node, "end_lineno", None)
            if end is None:
                continue
            size = end - node.lineno
            if isinstance(node, ast.ClassDef):
                if worst_class is None or size > worst_class[0]:
                    worst_class = (size, node.name)
            else:
                if worst_fn is None or size > worst_fn[0]:
                    worst_fn = (size, node.name)

    total = src.count("\n") + 1

    if total > 800:
        label = f"class {worst_class[1]} {worst_class[0]}L" if worst_class else ""
        result = f"{total:,} lines"
        if label:
            result += f" · {label}"
        return result
    if worst_class is not None and worst_class[0] > 300:
        return f"{total:,} lines · class {worst_class[1]} {worst_class[0]}L"
    if worst_fn is not None and worst_fn[0] > 150:
        return f"{total:,} lines · fn {worst_fn[1]} {worst_fn[0]}L"
    return None
