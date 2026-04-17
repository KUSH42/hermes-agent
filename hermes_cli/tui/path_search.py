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
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from textual import log, work
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
    insert_text: str = ""                           # text inserted into input on accept


@dataclass(frozen=True, slots=True)
class SlashCandidate(Candidate):
    command: str = ""                               # canonical command name, e.g. "/help"


# ---------------------------------------------------------------------------
# PathSearchProvider widget
# ---------------------------------------------------------------------------

def _log_first_batch(ms: float) -> None:
    """Emit first-batch latency to Textual console with budget check."""
    budget = 50.0
    if ms > budget:
        log.warning(f"[PERF] path-walker first-batch: {ms:.1f}ms ⚠ OVER {budget:.0f}ms budget")
    else:
        log(f"[PERF] path-walker first-batch: {ms:.1f}ms (target <{budget:.0f}ms)")


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

    def search(
        self,
        query: str,
        root: Path,
        *,
        match_query: str | None = None,
        insert_prefix: str = "",
    ) -> None:
        """Start a new walk; cancels any prior ``"path-search"`` worker."""
        self._walk(query, root, match_query or query, insert_prefix)

    @work(thread=True, exclusive=True, group="path-search")
    def _walk(
        self,
        query: str,
        root: Path,
        match_query: str,
        insert_prefix: str,
    ) -> None:
        # --------------- perf instrumentation --------------------------------
        # Target: first batch in <50 ms so the overlay populates before the
        # user finishes typing.  Total scan of 50 k files should finish <2 s.
        # Monitor via: TEXTUAL_LOG=1 + filter Textual Console for [PERF].
        # Torture test: hold '@' then type a deep path fragment rapidly.
        # Expected: worker count peaks at 2, then drops; no UI frame drops.
        # ----------------------------------------------------------------------
        t_start = time.perf_counter()
        first_batch_sent = False
        total_files = 0

        BATCH = 512
        IGNORE = {".git", "node_modules", "__pycache__", ".venv", "dist", "build"}
        buf: list[PathCandidate] = []
        q_lower = match_query.lower()
        root_str = str(root)
        worker = get_current_worker()  # correct API; WorkerManager has no .current

        for dirpath, _dirnames, filenames in self._iwalk(root, IGNORE):
            # Cooperative cancellation at directory granularity.
            # Per-file checks cost more than the walk itself on warm caches.
            if worker.is_cancelled:
                t_cancel = (time.perf_counter() - t_start) * 1000
                log(f"[PERF] path-walker cancelled after {t_cancel:.0f}ms, {total_files} files")
                return
            rel_dir = dirpath[len(root_str) + 1:] if dirpath != root_str else ""
            for name in filenames:
                total_files += 1
                # Cheap prefilter BEFORE allocation — PathCandidate alloc is
                # the dominant cost once the FS cache is warm.
                if q_lower and q_lower not in name.lower() and q_lower not in rel_dir.lower():
                    continue
                rel = f"{rel_dir}/{name}" if rel_dir else name
                buf.append(PathCandidate(
                    display=rel,
                    abs_path=os.path.join(dirpath, name),
                    insert_text=f"{insert_prefix}{rel}" if insert_prefix else rel,
                ))
                if len(buf) >= BATCH:
                    if not first_batch_sent:
                        first_batch_ms = (time.perf_counter() - t_start) * 1000
                        _log_first_batch(first_batch_ms)
                        first_batch_sent = True
                    self.post_message(self.Batch(query, buf, final=False))
                    buf = []

        # Final batch (may be smaller than BATCH)
        if not first_batch_sent:
            first_batch_ms = (time.perf_counter() - t_start) * 1000
            _log_first_batch(first_batch_ms)

        self.post_message(self.Batch(query, buf, final=True))
        total_ms = (time.perf_counter() - t_start) * 1000
        log(f"[PERF] path-walker done: {total_ms:.0f}ms, {total_files} files scanned")

    @staticmethod
    def _iwalk(root: Path, ignore: set[str]) -> Iterator[tuple[str, list[str], list[str]]]:
        """scandir-based walk — ~3× faster than os.walk on deep trees because
        DirEntry.is_dir() avoids the per-entry os.stat syscall.

        Sorts dirs/files alphabetically per directory.  Dirs are pushed to the
        stack in reverse order so the LIFO pop yields them in forward alpha
        (leftmost directory visited first).
        """
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
                            else:
                                files.append(entry.name)
                        except OSError:
                            continue
                    # Deterministic order: alphabetical within each category.
                    dirs.sort()
                    files.sort()
                    # Push in reverse so stack.pop() yields forward alpha order.
                    for d in reversed(dirs):
                        stack.append(os.path.join(dirpath, d))
                    yield dirpath, dirs, files
            except OSError:
                continue
