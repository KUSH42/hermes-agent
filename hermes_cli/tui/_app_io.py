"""_AppIOMixin — output queue, TTE effects, and flush methods for HermesApp."""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual import work
from textual.css.query import NoMatches

from hermes_cli.tui._app_utils import _CPYTHON_FAST_PATH, _run_effect_sync

if TYPE_CHECKING:
    pass

import logging as _logging
import os as _os_mod

logger = _logging.getLogger(__name__)


class _AppIOMixin:
    """Output queue consumer, write_output, TTE animation, and flush methods.

    Extracted from HermesApp to reduce file size.  Self is always a HermesApp
    instance at runtime — all attribute access on self is valid.

    R4: Logic migrated to IOService. Mixin keeps @work wrappers + permanent
    public API forwarders (write_output / flush_output).
    """

    # --- Output consumer (bounded queue → RichLog) ---

    @work(exclusive=True)
    async def _consume_output(self) -> None:
        """Async worker — delegates body to IOService.consume_output."""
        await self._svc_io.consume_output()  # type: ignore[attr-defined]

    # --- Thread-safe output writing (PERMANENT public API — no DEPRECATED) ---

    def write_output(self, text: str) -> None:
        """Thread-safe: enqueue text for the output consumer."""
        return self._svc_io.write_output(text)  # type: ignore[attr-defined]

    def flush_output(self) -> None:
        """Thread-safe: send flush sentinel to commit any trailing partial line."""
        return self._svc_io.flush_output()  # type: ignore[attr-defined]

    # --- TTE effects (suspend-based) ---

    async def _play_effects_async(
        self,
        effect_name: str,
        text: str,
        params: dict[str, object] | None = None,
    ) -> bool:
        return await self._svc_io.play_effects_async(effect_name, text, params)  # type: ignore[attr-defined]

    @work
    async def _play_effects(
        self,
        effect_name: str,
        text: str,
        params: dict[str, object] | None = None,
    ) -> None:
        """Suspend Textual, run a TTE animation, then resume."""
        await self._svc_io.play_effects_async(effect_name, text, params)  # type: ignore[attr-defined]

    def play_effects_blocking(
        self,
        effect_name: str,
        text: str,
        params: dict[str, object] | None = None,
    ) -> bool:
        """Run a TTE animation and block caller until it completes."""
        return self._svc_io.play_effects_blocking(effect_name, text, params)  # type: ignore[attr-defined]

    def get_working_directory(self) -> Path:
        """Return TUI workspace root used for path completion and file-drop links."""
        return self._svc_io.get_working_directory()  # type: ignore[attr-defined]

    def _play_tte_main(
        self,
        effect_name: str,
        text: str,
        params: dict[str, object] | None = None,
        done_event: "threading.Event | None" = None,
    ) -> bool:
        return self._svc_io.play_tte_main(effect_name, text, params, done_event)  # type: ignore[attr-defined]

    def play_tte(
        self,
        effect_name: str,
        text: str,
        params: dict[str, object] | None = None,
        done_event: "threading.Event | None" = None,
    ) -> bool:
        """Play a TTE animation inline in TUI."""
        return self._svc_io.play_tte(effect_name, text, params, done_event)  # type: ignore[attr-defined]

    def play_tte_blocking(
        self,
        effect_name: str,
        text: str,
        params: dict[str, object] | None = None,
        timeout_s: float = 15.0,
    ) -> bool:
        """Play a TTE animation inline and wait for completion."""
        return self._svc_io.play_tte_blocking(effect_name, text, params, timeout_s)  # type: ignore[attr-defined]

    def _stop_tte_main(self) -> None:
        return self._svc_io.stop_tte_main()  # type: ignore[attr-defined]

    def stop_tte(self) -> None:
        """Stop any running inline TTE animation."""
        return self._svc_io.stop_tte()  # type: ignore[attr-defined]
