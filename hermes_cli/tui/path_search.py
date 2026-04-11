"""Threaded path-search worker and candidate dataclasses.

``PathSearchProvider`` is an invisible widget that owns the blocking
``os.scandir`` walk behind a ``@work(thread=True, exclusive=True)`` guard.
New calls automatically cancel prior runs in the same ``"path-search"`` group.
Results arrive as ``PathSearchProvider.Batch`` messages consumed by
``HermesInput.on_path_search_provider_batch``.

Candidate hierarchy
-------------------
``Candidate``      — minimal shared shape (display label, score, match_spans)
``PathCandidate``  — filesystem path; carries ``abs_path``
``SlashCandidate`` — slash command; carries ``command``
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from textual import work
from textual.message import Message
from textual.widget import Widget
from textual.worker import get_current_worker


# ---------------------------------------------------------------------------
# Candidate protocol
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Candidate:
    """Base: anything VirtualCompletionList can render + select."""
    display: str                                    # label shown in the list
    score: int = 0                                  # filled by fuzzy ranker
    match_spans: tuple[tuple[int, int], ...] = ()   # (start, end) bold runs


@dataclass(frozen=True, slots=True)
class PathCandidate(Candidate):
    abs_path: str = ""                              # full path on disk


@dataclass(frozen=True, slots=True)
class SlashCandidate(Candidate):
    command: str = ""                               # canonical command name, e.g. "/help"


# ---------------------------------------------------------------------------
# PathSearchProvider widget
# ---------------------------------------------------------------------------

class PathSearchProvider(Widget):
    """Invisible worker host.  Owns the path-search @work and emits Batches.

    Mount once in ``HermesApp.compose`` at any position — ``DEFAULT_CSS``
    hides it from the compositor.
    """

    DEFAULT_CSS = "PathSearchProvider { display: none; }"

    class Batch(Message):
        """Carries a slice of path candidates from the background walker."""
        __slots__ = ("query", "batch", "final")

        def __init__(
            self,
            query: str,
            batch: list[PathCandidate],
            final: bool,
        ) -> None:
            super().__init__()
            self.query = query
            self.batch = batch
            self.final = final

    def search(self, query: str, root: Path) -> None:
        """Start a new walk; cancels any prior ``"path-search"`` worker."""
        self._walk(query, root)

    @work(thread=True, exclusive=True, group="path-search")
    def _walk(self, query: str, root: Path) -> None:
        BATCH = 512
        IGNORE = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}
        buf: list[PathCandidate] = []
        q_lower = query.lower()
        root_str = str(root)
        worker = get_current_worker()  # correct API; WorkerManager has no .current

        for dirpath, _dirnames, filenames in self._iwalk(root, IGNORE):
            # Cooperative cancellation at directory granularity.
            # Per-file checks cost more than the walk itself on warm caches.
            if worker.is_cancelled:
                return
            rel_dir = dirpath[len(root_str) + 1:] if dirpath != root_str else ""
            for name in filenames:
                # Cheap prefilter BEFORE allocation — PathCandidate alloc is
                # the dominant cost once the FS cache is warm.
                if q_lower and q_lower not in name.lower() and q_lower not in rel_dir.lower():
                    continue
                rel = f"{rel_dir}/{name}" if rel_dir else name
                buf.append(PathCandidate(
                    display=rel,
                    abs_path=os.path.join(dirpath, name),
                ))
                if len(buf) >= BATCH:
                    self.post_message(self.Batch(query, buf, final=False))
                    buf = []
        self.post_message(self.Batch(query, buf, final=True))

    @staticmethod
    def _iwalk(root: Path, ignore: set[str]) -> Iterator[tuple[str, list[str], list[str]]]:
        """scandir-based walk — ~3× faster than os.walk on deep trees because
        DirEntry.is_dir() avoids the per-entry os.stat syscall."""
        stack = [str(root)]
        while stack:
            dirpath = stack.pop()
            try:
                with os.scandir(dirpath) as it:
                    dirs: list[str] = []
                    files: list[str] = []
                    for entry in it:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                if entry.name not in ignore:
                                    dirs.append(entry.name)
                                    stack.append(entry.path)
                            else:
                                files.append(entry.name)
                        except OSError:
                            continue
                    yield dirpath, dirs, files
            except OSError:
                continue
