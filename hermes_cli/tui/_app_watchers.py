"""_WatchersMixin — thin adapters delegating to WatchersService."""
from __future__ import annotations

from pathlib import Path
from typing import Any


class _WatchersMixin:
    """Thin adapter layer. All logic lives in WatchersService."""

    def on_text_area_changed(self, event: Any) -> None:
        self._svc_watchers.on_text_area_changed(event)  # type: ignore[attr-defined]

    def on_input_changed(self, event: Any) -> None:
        self._svc_watchers.on_input_changed(event)  # type: ignore[attr-defined]

    def watch_size(self, size: Any) -> None:
        self._svc_watchers.on_size(size)  # type: ignore[attr-defined]

    def watch_compact(self, value: bool) -> None:
        self._svc_watchers.on_compact(value)  # type: ignore[attr-defined]

    def _sync_compact_visibility(self) -> None:
        # DEPRECATED: remove in Phase 3
        self._svc_watchers.sync_compact_visibility()  # type: ignore[attr-defined]

    def watch_status_compaction_progress(self, value: float) -> None:
        self._svc_watchers.on_status_compaction_progress(value)  # type: ignore[attr-defined]

    def watch_voice_mode(self, value: bool) -> None:
        self._svc_watchers.on_voice_mode(value)  # type: ignore[attr-defined]

    def watch_voice_recording(self, value: bool) -> None:
        self._svc_watchers.on_voice_recording(value)  # type: ignore[attr-defined]

    def watch_attached_images(self, value: list) -> None:
        self._svc_watchers.on_attached_images(value)  # type: ignore[attr-defined]

    def _append_attached_images(self, images: list[Path]) -> None:
        # DEPRECATED: remove in Phase 3
        self._svc_watchers.append_attached_images(images)  # type: ignore[attr-defined]

    def _clear_attached_images(self) -> None:
        # DEPRECATED: remove in Phase 3
        self._svc_watchers.clear_attached_images()  # type: ignore[attr-defined]

    def _insert_link_tokens(self, tokens: list[str]) -> None:
        # DEPRECATED: remove in Phase 3
        self._svc_watchers.insert_link_tokens(tokens)  # type: ignore[attr-defined]

    @staticmethod
    def _drop_path_display(path: Path, cwd: Path) -> str:
        # DEPRECATED: remove in Phase 3
        from hermes_cli.tui.services.watchers import WatchersService
        return WatchersService.drop_path_display(path, cwd)

    def handle_file_drop(self, paths: list[Path]) -> None:
        """Route terminal drag-and-drop pasted paths into input bar."""
        self._svc_watchers.handle_file_drop(paths)  # type: ignore[attr-defined]

    def _handle_file_drop_inner(self, paths: list[Path]) -> None:
        # DEPRECATED: remove in Phase 3
        self._svc_watchers.handle_file_drop_inner(paths)  # type: ignore[attr-defined]

    def watch_clarify_state(self, value: Any) -> None:
        self._svc_watchers.on_clarify_state(value)  # type: ignore[attr-defined]

    def watch_approval_state(self, value: Any) -> None:
        self._svc_watchers.on_approval_state(value)  # type: ignore[attr-defined]

    def watch_highlighted_candidate(self, c: Any) -> None:
        self._svc_watchers.on_highlighted_candidate(c)  # type: ignore[attr-defined]

    def watch_sudo_state(self, value: Any) -> None:
        self._svc_watchers.on_sudo_state(value)  # type: ignore[attr-defined]

    def watch_secret_state(self, value: Any) -> None:
        self._svc_watchers.on_secret_state(value)  # type: ignore[attr-defined]

    def watch_status_error(self, value: str) -> None:
        self._svc_watchers.on_status_error(value)  # type: ignore[attr-defined]

    def _auto_clear_status_error(self, expected: str) -> None:
        # DEPRECATED: remove in Phase 3
        self._svc_watchers.auto_clear_status_error(expected)  # type: ignore[attr-defined]

    def watch_undo_state(self, value: Any) -> None:
        self._svc_watchers.on_undo_state(value)  # type: ignore[attr-defined]
