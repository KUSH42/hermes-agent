"""_KeyHandlerMixin — thin adapters delegating to KeyDispatchService."""
from __future__ import annotations

from typing import Any


class _KeyHandlerMixin:
    """Thin adapter layer. All logic lives in KeyDispatchService."""

    def on_key(self, event: Any) -> None:
        # DEPRECATED: remove in Phase 3
        self._svc_keys.dispatch_key(event)  # type: ignore[attr-defined]

    def on_hermes_input_submitted(self, event: Any) -> None:
        # DEPRECATED: remove in Phase 3
        self._svc_keys.dispatch_input_submitted(event)  # type: ignore[attr-defined]

    def on_hermes_input_files_dropped(self, event: Any) -> None:
        self._svc_watchers.handle_file_drop(event.paths)  # type: ignore[attr-defined]
