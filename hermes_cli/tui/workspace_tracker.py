"""WorkspaceTracker — git working-tree tracking for WorkspaceOverlay.

Tracks the current visible working-tree state from Git and overlays Hermes
session metadata (write counts, touched badge, complexity warnings) as
annotation only.

All tracker mutations (record_write, apply_snapshot, set_complexity) run on the
Textual event loop thread. Blocking I/O (subprocess, file reads) runs in
@work threads on HermesApp.
"""

from __future__ import annotations

import ast
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from textual.message import Message


_CONFLICT_XY: frozenset[str] = frozenset({"DD", "AU", "UD", "UA", "DU", "AA", "UU"})


@dataclass
class GitSnapshotEntry:
    path: str
    rel_path: str
    git_xy: str
    git_index_status: str
    git_worktree_status: str
    git_status: str
    git_staged: bool
    git_untracked: bool
    git_conflicted: bool
    git_renamed: bool
    renamed_from: str | None = None


@dataclass
class FileEntry:
    path: str
    rel_path: str
    git_xy: str
    git_index_status: str
    git_worktree_status: str
    git_status: str
    git_staged: bool
    git_untracked: bool
    git_conflicted: bool
    git_renamed: bool
    session_added: int
    session_removed: int
    git_renamed_from: str | None = None
    hermes_touched: bool = False
    last_write: float = 0.0
    complexity_warning: str | None = None


@dataclass
class GitSnapshot:
    branch: str
    dirty_count: int
    entries: list[GitSnapshotEntry]
    staged_count: int
    untracked_count: int
    modified_count: int
    deleted_count: int
    renamed_count: int
    conflicted_count: int
    is_git_repo: bool = True


@dataclass
class _SessionMeta:
    rel_path: str
    session_added: int = 0
    session_removed: int = 0
    hermes_touched: bool = False
    last_write: float = 0.0
    complexity_warning: str | None = None


class WorkspaceUpdated(Message):
    """Posted by HermesApp._run_git_poll when a new GitSnapshot is ready."""

    def __init__(self, snapshot: GitSnapshot, poll_elapsed_ms: float | None = None) -> None:
        super().__init__()
        self.snapshot = snapshot
        self.poll_elapsed_ms = poll_elapsed_ms


class WorkspaceTracker:
    """Git-scoped registry of visible working-tree rows plus Hermes metadata."""

    def __init__(self, repo_root: str, is_git_repo: bool = True) -> None:
        self._repo_root = repo_root.rstrip("/") if repo_root else ""
        self._is_git_repo = is_git_repo
        self._entries: dict[str, FileEntry] = {}
        self._session_meta: dict[str, _SessionMeta] = {}

    @property
    def is_git_repo(self) -> bool:
        return self._is_git_repo

    def record_write(self, path: str, added: int, removed: int) -> None:
        """Accumulate Hermes session deltas for *path*."""

        rel = self._rel(path)
        cur = self._session_meta.get(path)
        now = time.monotonic()
        if cur is None:
            meta = _SessionMeta(
                rel_path=rel,
                session_added=added,
                session_removed=removed,
                hermes_touched=True,
                last_write=now,
            )
        else:
            meta = _SessionMeta(
                rel_path=cur.rel_path or rel,
                session_added=cur.session_added + added,
                session_removed=cur.session_removed + removed,
                hermes_touched=True,
                last_write=now,
                complexity_warning=cur.complexity_warning,
            )
        self._session_meta[path] = meta
        if path in self._entries:
            self._entries[path] = self._merge_entry(self._entries[path], meta)

    def apply_snapshot(self, snapshot: GitSnapshot) -> None:
        """Replace visible row set from Git snapshot and merge Hermes metadata."""

        self._is_git_repo = snapshot.is_git_repo
        if not snapshot.is_git_repo:
            self._entries = {}
            return

        new_entries: dict[str, FileEntry] = {}
        for row in snapshot.entries:
            meta = self._session_meta.get(row.path)
            new_entries[row.path] = FileEntry(
                path=row.path,
                rel_path=row.rel_path,
                git_xy=row.git_xy,
                git_index_status=row.git_index_status,
                git_worktree_status=row.git_worktree_status,
                git_status=row.git_status,
                git_staged=row.git_staged,
                git_untracked=row.git_untracked,
                git_conflicted=row.git_conflicted,
                git_renamed=row.git_renamed,
                git_renamed_from=row.renamed_from,
                session_added=meta.session_added if meta else 0,
                session_removed=meta.session_removed if meta else 0,
                hermes_touched=meta.hermes_touched if meta else False,
                last_write=meta.last_write if meta else 0.0,
                complexity_warning=meta.complexity_warning if meta else None,
            )
        self._entries = new_entries

    def set_complexity(self, path: str, warning: str | None) -> None:
        """Store complexity warning on Hermes metadata and visible row if present."""

        rel = self._rel(path)
        cur = self._session_meta.get(path)
        if cur is None:
            meta = _SessionMeta(
                rel_path=rel,
                hermes_touched=True,
                last_write=time.monotonic(),
                complexity_warning=warning,
            )
        else:
            meta = _SessionMeta(
                rel_path=cur.rel_path or rel,
                session_added=cur.session_added,
                session_removed=cur.session_removed,
                hermes_touched=cur.hermes_touched,
                last_write=cur.last_write,
                complexity_warning=warning,
            )
        self._session_meta[path] = meta
        if path in self._entries:
            e = self._entries[path]
            self._entries[path] = FileEntry(
                path=e.path,
                rel_path=e.rel_path,
                git_xy=e.git_xy,
                git_index_status=e.git_index_status,
                git_worktree_status=e.git_worktree_status,
                git_status=e.git_status,
                git_staged=e.git_staged,
                git_untracked=e.git_untracked,
                git_conflicted=e.git_conflicted,
                git_renamed=e.git_renamed,
                git_renamed_from=e.git_renamed_from,
                session_added=e.session_added,
                session_removed=e.session_removed,
                hermes_touched=e.hermes_touched,
                last_write=e.last_write,
                complexity_warning=warning,
            )

    def entries(self) -> list[FileEntry]:
        """Return visible rows with Hermes-touched files promoted first."""

        return sorted(
            self._entries.values(),
            key=lambda e: (
                0 if e.hermes_touched else 1,
                -e.last_write if e.hermes_touched else 0.0,
                e.rel_path,
            ),
        )

    def session_totals(self) -> tuple[int, int]:
        added = sum(m.session_added for m in self._session_meta.values())
        removed = sum(m.session_removed for m in self._session_meta.values())
        return added, removed

    def counts_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for e in self._entries.values():
            counts[e.git_status] = counts.get(e.git_status, 0) + 1
        return counts

    def _rel(self, path: str) -> str:
        if self._repo_root and path.startswith(self._repo_root + "/"):
            return path[len(self._repo_root) + 1:]
        return path

    def _merge_entry(self, entry: FileEntry, meta: _SessionMeta) -> FileEntry:
        return FileEntry(
            path=entry.path,
            rel_path=entry.rel_path,
            git_xy=entry.git_xy,
            git_index_status=entry.git_index_status,
            git_worktree_status=entry.git_worktree_status,
            git_status=entry.git_status,
            git_staged=entry.git_staged,
            git_untracked=entry.git_untracked,
            git_conflicted=entry.git_conflicted,
            git_renamed=entry.git_renamed,
            git_renamed_from=entry.git_renamed_from,
            session_added=meta.session_added,
            session_removed=meta.session_removed,
            hermes_touched=meta.hermes_touched,
            last_write=meta.last_write,
            complexity_warning=meta.complexity_warning,
        )


class GitPoller:
    """Runs Git subprocess calls synchronously. Must be called from a worker thread."""

    def __init__(self, repo_root: str, is_git_repo: bool = True) -> None:
        self._repo_root = repo_root
        self._is_git_repo = is_git_repo

    @property
    def is_git_repo(self) -> bool:
        return self._is_git_repo

    def poll(self) -> GitSnapshot:
        """Return parsed git working-tree snapshot for the active repo."""

        if not self._is_git_repo:
            return GitSnapshot(
                branch="",
                dirty_count=0,
                entries=[],
                staged_count=0,
                untracked_count=0,
                modified_count=0,
                deleted_count=0,
                renamed_count=0,
                conflicted_count=0,
                is_git_repo=False,
            )

        branch = "unknown"
        try:
            branch = subprocess.check_output(  # allow-sync-io: dispatched from run_worker context, not event loop
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                stderr=subprocess.DEVNULL,
                cwd=self._repo_root or None,
                timeout=5,
            ).decode().strip()
        except Exception:
            pass

        try:
            raw = subprocess.check_output(  # allow-sync-io: dispatched from run_worker context, not event loop
                ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
                stderr=subprocess.DEVNULL,
                cwd=self._repo_root or None,
                timeout=5,
            )
        except Exception:
            raw = b""

        tokens = [t for t in raw.split(b"\0") if t]
        entries: list[GitSnapshotEntry] = []
        staged_count = 0
        untracked_count = 0
        modified_count = 0
        deleted_count = 0
        renamed_count = 0
        conflicted_count = 0

        i = 0
        while i < len(tokens):
            token = tokens[i].decode("utf-8", errors="replace")
            if len(token) < 3:
                i += 1
                continue
            xy = token[:2]
            path_part = token[3:]
            renamed = "R" in xy or "C" in xy
            renamed_from: str | None = None
            if renamed and i + 1 < len(tokens):
                renamed_from = tokens[i + 1].decode("utf-8", errors="replace")
                i += 1

            abs_path = self._abs(path_part)
            rel_path = path_part
            index_status = xy[0]
            worktree_status = xy[1]
            untracked = xy == "??"
            conflicted = xy in _CONFLICT_XY
            staged = index_status not in (" ", "?", "!")
            git_status = self._normalize_status(xy, index_status, worktree_status)

            if staged:
                staged_count += 1
            if untracked:
                untracked_count += 1
            if conflicted:
                conflicted_count += 1
            if renamed:
                renamed_count += 1
            if not conflicted and not untracked and ("M" in xy):
                modified_count += 1
            if "D" in xy and not conflicted:
                deleted_count += 1

            entries.append(
                GitSnapshotEntry(
                    path=abs_path,
                    rel_path=rel_path,
                    git_xy=xy,
                    git_index_status=index_status,
                    git_worktree_status=worktree_status,
                    git_status=git_status,
                    git_staged=staged,
                    git_untracked=untracked,
                    git_conflicted=conflicted,
                    git_renamed=renamed,
                    renamed_from=renamed_from,
                )
            )
            i += 1

        return GitSnapshot(
            branch=branch,
            dirty_count=len(entries),
            entries=entries,
            staged_count=staged_count,
            untracked_count=untracked_count,
            modified_count=modified_count,
            deleted_count=deleted_count,
            renamed_count=renamed_count,
            conflicted_count=conflicted_count,
            is_git_repo=True,
        )

    def _abs(self, rel_path: str) -> str:
        if not rel_path:
            return self._repo_root
        if Path(rel_path).is_absolute():
            return rel_path
        return str((Path(self._repo_root) / rel_path).resolve())

    @staticmethod
    def _normalize_status(xy: str, index_status: str, worktree_status: str) -> str:
        if xy == "??":
            return "?"
        if xy in _CONFLICT_XY:
            return "U"
        if index_status not in (" ", "?"):
            return index_status
        if worktree_status not in (" ", "?"):
            return worktree_status
        return " "


def analyze_complexity(path: str) -> str | None:
    """Return a complexity warning string for a .py file, or None if under threshold."""

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
