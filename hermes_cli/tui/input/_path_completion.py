"""Path-resolver, overlay-visibility, and batch-handler mixin for HermesInput."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from textual.css.query import NoMatches

from hermes_cli.tui.completion_context import CompletionContext
from hermes_cli.tui.completion_list import VirtualCompletionList
from hermes_cli.tui.completion_overlay import CompletionOverlay
from hermes_cli.tui.path_search import Candidate, PathSearchProvider
from hermes_cli.tui.perf import measure


@dataclass(frozen=True, slots=True)
class _PathSearchRequest:
    batch_key: str
    match_query: str
    root: Path
    insert_prefix: str


class _PathCompletionMixin:
    """Mixin: path resolution, overlay visibility, and batch result handling."""

    # State initialised by HermesInput.__init__
    _current_trigger: Any
    _raw_candidates: list
    _path_debounce_timer: Any

    # --- Overlay visibility helpers ---

    def _set_searching(self, value: bool) -> None:
        try:
            clist = self.screen.query_one(VirtualCompletionList)  # type: ignore[attr-defined]
            clist.searching = value
        except Exception:
            pass

    def _set_overlay_mode(self, *, slash_only: bool) -> None:
        try:
            overlay = self.screen.query_one(CompletionOverlay)  # type: ignore[attr-defined]
        except NoMatches:
            return
        overlay.set_class(slash_only, "--slash-only")

    def _show_completion_overlay(self) -> None:
        try:
            overlay = self.screen.query_one(CompletionOverlay)  # type: ignore[attr-defined]
        except NoMatches:
            return
        overlay.add_class("--visible")
        # Clear ghost text and set tab-hint so user knows how to accept
        self.suggestion = ""  # type: ignore[attr-defined]
        try:
            self.app._completion_hint = "Tab accept  ·  ↑↓ navigate  ·  Esc dismiss"  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            self._mode = self._compute_mode()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _hide_completion_overlay(self) -> None:
        if self._path_debounce_timer is not None:
            self._path_debounce_timer.stop()
            self._path_debounce_timer = None
        self._set_searching(False)
        try:
            overlay = self.screen.query_one(CompletionOverlay)  # type: ignore[attr-defined]
        except NoMatches:
            return
        overlay.remove_class("--visible")
        overlay.remove_class("--slash-only")
        try:
            self.app._completion_hint = ""  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            self._mode = self._compute_mode()  # type: ignore[attr-defined]
        except Exception:
            pass

    def _completion_overlay_visible(self) -> bool:
        try:
            return self.screen.query_one(CompletionOverlay).has_class("--visible")  # type: ignore[attr-defined]
        except NoMatches:
            return False

    def _completion_overlay_slash_only(self) -> bool:
        try:
            overlay = self.screen.query_one(CompletionOverlay)  # type: ignore[attr-defined]
            return overlay.has_class("--visible") and overlay.has_class("--slash-only")
        except NoMatches:
            return False

    def _move_highlight(self, delta: int) -> None:
        try:
            clist = self.screen.query_one(VirtualCompletionList)  # type: ignore[attr-defined]
        except NoMatches:
            return
        if not clist.items:
            return
        clist.highlighted = max(0, min(len(clist.items) - 1, clist.highlighted + delta))

    # --- Path resolution ---

    def _working_directory(self) -> Path:
        app = getattr(self, "app", None)
        getter = getattr(app, "get_working_directory", None)
        if callable(getter):
            return getter()
        return Path.cwd()

    def _resolve_path_search_request(self) -> _PathSearchRequest:
        trig = self._current_trigger
        cwd = self._working_directory()
        if trig.context is CompletionContext.PATH_REF:
            raw = trig.fragment
        else:
            raw = self.value[trig.start:self.cursor_position]  # type: ignore[attr-defined]

        if not raw:
            return _PathSearchRequest("", "", cwd, "")

        if raw.startswith("~/"):
            anchor = Path.home()
            remainder = raw[2:]
        elif raw.startswith("/"):
            anchor = Path("/")
            remainder = raw[1:]
        else:
            anchor = cwd
            remainder = raw

        if raw.endswith("/"):
            dir_part = remainder.rstrip("/")
            leaf = ""
        else:
            dir_part, _, leaf = remainder.rpartition("/")

        intended_base = (anchor / dir_part).resolve(strict=False) if dir_part else anchor
        base = intended_base
        missing_parts: list[str] = []
        while not (base.exists() and base.is_dir()):
            part = base.name
            parent = base.parent
            if part:
                missing_parts.append(part)
            if parent == base:
                break
            base = parent
        if not (base.exists() and base.is_dir()):
            base = anchor
        query_parts = list(reversed(missing_parts))
        if leaf:
            query_parts.append(leaf)
        match_query = "/".join(part for part in query_parts if part)
        insert_prefix = raw[:-len(match_query)] if match_query else raw
        return _PathSearchRequest(raw, match_query, base, insert_prefix)

    def _fire_path_search(self, fragment: str) -> None:
        self._path_debounce_timer = None
        if self._current_trigger.context not in (
            CompletionContext.PATH_REF,
            CompletionContext.PLAIN_PATH_REF,
            CompletionContext.ABSOLUTE_PATH_REF,
        ):
            return
        if self._current_trigger.fragment != fragment:
            return
        try:
            provider = self.screen.query_one(PathSearchProvider)  # type: ignore[attr-defined]
        except NoMatches:
            return
        request = self._resolve_path_search_request()
        provider.search(
            request.batch_key,
            request.root,
            match_query=request.match_query,
            insert_prefix=request.insert_prefix,
        )

    def _show_path_completions(self, fragment: str) -> None:
        if self._path_debounce_timer is not None:
            self._path_debounce_timer.stop()
            self._path_debounce_timer = None
        self._set_overlay_mode(slash_only=False)
        self._push_to_list([])
        self._set_searching(True)
        self._show_completion_overlay()
        self._path_debounce_timer = self.set_timer(  # type: ignore[attr-defined]
            0.12, lambda: self._fire_path_search(fragment)
        )

    # --- Batch handler ---

    def on_path_search_provider_batch(
        self, message: PathSearchProvider.Batch,
    ) -> None:
        """Accumulate walker batches and re-rank candidates."""
        from hermes_cli.tui.fuzzy import fuzzy_rank

        if self._current_trigger.context not in (
            CompletionContext.PATH_REF,
            CompletionContext.PLAIN_PATH_REF,
            CompletionContext.ABSOLUTE_PATH_REF,
        ):
            return
        request = self._resolve_path_search_request()
        if message.query != request.batch_key:
            return

        if len(self._raw_candidates) < 4096:
            self._raw_candidates.extend(message.batch)
        with measure("path_completion.fuzzy_rerank", budget_ms=4.0, silent=True):
            ranked = fuzzy_rank(
                request.match_query or self._current_trigger.fragment,
                self._raw_candidates,
                limit=200,
            )
        self._push_to_list(ranked)
        if message.final:
            self._set_searching(False)

    def _push_to_list(self, candidates: list[Candidate]) -> None:
        try:
            clist = self.screen.query_one(VirtualCompletionList)  # type: ignore[attr-defined]
        except NoMatches:
            return
        request = self._resolve_path_search_request()
        new_query = request.match_query or self._current_trigger.fragment
        new_items = tuple(candidates)
        # Guard: avoid triggering watch_items when nothing changed.
        if new_items == clist.items and new_query == clist.current_query:
            return
        clist.current_query = new_query
        clist.items = new_items
