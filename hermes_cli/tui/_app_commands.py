"""_CommandsMixin — TUI slash commands, animation control, undo/retry for HermesApp."""
from __future__ import annotations

from typing import Any

from textual import work

from hermes_cli.tui.state import UndoOverlayState


class _CommandsMixin:
    """TUI command dispatch, animation config, and undo/retry/rollback sequences.

    Extracted from HermesApp to reduce file size.  Self is always a HermesApp
    instance at runtime — all attribute access on self is valid.

    R4: Logic migrated to CommandsService. Mixin keeps 1-line adapters and
    @work wrappers for async sequences.
    """

    def _handle_tui_command(self, text: str) -> bool:  # DEPRECATED
        return self._svc_commands.handle_tui_command(text)  # type: ignore[attr-defined]

    @work(thread=False, group="clear")
    async def _handle_clear_tui(self) -> None:  # DEPRECATED
        await self._svc_commands.handle_clear_tui()  # type: ignore[attr-defined]

    def _has_rollback_checkpoint(self) -> bool:  # DEPRECATED
        return self._svc_commands.has_rollback_checkpoint()  # type: ignore[attr-defined]

    def _open_tools_overlay(self) -> None:  # DEPRECATED
        return self._svc_commands.open_tools_overlay()  # type: ignore[attr-defined]

    def _handle_layout_command(self, args: str) -> None:  # DEPRECATED
        return self._svc_commands.handle_layout_command(args)  # type: ignore[attr-defined]

    def _open_anim_config(self) -> None:  # DEPRECATED
        return self._svc_commands.open_anim_config()  # type: ignore[attr-defined]

    def _persist_anim_config(self, cfg_dict: dict) -> None:  # DEPRECATED
        return self._svc_commands.persist_anim_config(cfg_dict)  # type: ignore[attr-defined]

    def _update_anim_hint(self) -> None:  # DEPRECATED
        return self._svc_commands.update_anim_hint()  # type: ignore[attr-defined]

    def _handle_anim_command(self, stripped: str) -> None:  # DEPRECATED
        return self._svc_commands.handle_anim_command(stripped)  # type: ignore[attr-defined]

    def _try_auto_title(self) -> None:  # DEPRECATED
        return self._svc_commands.try_auto_title()  # type: ignore[attr-defined]

    def _toggle_drawille_overlay(self) -> None:  # DEPRECATED
        return self._svc_commands.toggle_drawille_overlay()  # type: ignore[attr-defined]

    def action_open_anim_config(self) -> None:
        self._toggle_drawille_overlay()  # type: ignore[attr-defined]

    # --- Undo / Retry / Rollback ---

    def _initiate_undo(self) -> None:  # DEPRECATED
        return self._svc_commands.initiate_undo()  # type: ignore[attr-defined]

    @work(thread=False)
    async def _run_undo_sequence(self, panel: Any) -> None:  # DEPRECATED
        await self._svc_commands.run_undo_sequence(panel)  # type: ignore[attr-defined]

    def _initiate_retry(self) -> None:  # DEPRECATED
        return self._svc_commands.initiate_retry()  # type: ignore[attr-defined]

    def _initiate_rollback(self, text: str) -> None:  # DEPRECATED
        return self._svc_commands.initiate_rollback(text)  # type: ignore[attr-defined]

    @work(thread=False)
    async def _run_rollback_sequence(self, n: int) -> None:  # DEPRECATED
        await self._svc_commands.run_rollback_sequence(n)  # type: ignore[attr-defined]
