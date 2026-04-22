"""_ContextMenuMixin — right-click context menu + clipboard copy helpers for HermesApp."""
from __future__ import annotations

from typing import Any

from textual.css.query import NoMatches


class _ContextMenuMixin:
    """Context menu display, clipboard copy, and tool panel path actions.

    Extracted from HermesApp to reduce file size.  Self is always a HermesApp
    instance at runtime — all attribute access on self is valid.

    NOTE: Most logic has moved to ContextMenuService (_svc_context).
    Methods here are 1-line adapters preserved for backward compatibility.
    Remove in Phase 3.
    """

    async def on_click(self, event: Any) -> None:
        """DEPRECATED: remove in Phase 3."""
        return await self._svc_context.handle_click(event)  # type: ignore[attr-defined]

    async def _show_context_menu_for_focused(self) -> None:
        """DEPRECATED: remove in Phase 3."""
        return await self._svc_context.show_context_menu_for_focused()  # type: ignore[attr-defined]

    async def _show_context_menu_at(self, items: list, x: int, y: int) -> None:
        """DEPRECATED: remove in Phase 3."""
        return await self._svc_context.show_context_menu_at(items, x, y)  # type: ignore[attr-defined]

    def on_path_search_provider_batch(self, message: Any) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_context.on_path_search_provider_batch(message)  # type: ignore[attr-defined]

    def _build_context_items(self, event: Any) -> list:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_context.build_context_items(event)  # type: ignore[attr-defined]

    def _copy_code_block(self, block: Any) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_context.copy_code_block(block)  # type: ignore[attr-defined]

    def _copy_tool_output(self, block: Any) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_context.copy_tool_output(block)  # type: ignore[attr-defined]

    def _build_tool_block_menu_items(self, block: Any) -> list:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_context.build_tool_block_menu_items(block)  # type: ignore[attr-defined]

    def _copy_path_action(self, header: Any, path: str) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_context.copy_path_action(header, path)  # type: ignore[attr-defined]

    def _open_external_url(self, url: str) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_context.open_external_url(url)  # type: ignore[attr-defined]

    def on_copyable_rich_log_link_clicked(self, event: Any) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_context.on_copyable_rich_log_link_clicked(event)  # type: ignore[attr-defined]

    def _open_path_action(self, header: Any, path: str, opener: str, folder: bool) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_context.open_path_action(header, path, opener, folder)  # type: ignore[attr-defined]

    def _copy_all_output(self) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_context.copy_all_output()  # type: ignore[attr-defined]

    def _copy_panel(self, panel: Any) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_context.copy_panel(panel)  # type: ignore[attr-defined]

    def _copy_text(self, text: str) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_context.copy_text(text)  # type: ignore[attr-defined]

    def _paste_into_input(self) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_context.paste_into_input()  # type: ignore[attr-defined]

    def _clear_input(self) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_context.clear_input()  # type: ignore[attr-defined]

    def on_tool_panel_path_focused(self, event: Any) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_context.on_tool_panel_path_focused(event)  # type: ignore[attr-defined]

    def _dismiss_all_info_overlays(self) -> None:
        """DEPRECATED: remove in Phase 3."""
        return self._svc_context.dismiss_all_info_overlays()  # type: ignore[attr-defined]
