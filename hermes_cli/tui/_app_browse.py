"""_BrowseMixin — adapter shell; logic lives in services/browse.py."""
from __future__ import annotations


class _BrowseMixin:
    """Adapter shell — all methods delegate to self._svc_browse."""

    def _apply_browse_focus(self) -> None:  # DEPRECATED
        return self._svc_browse.apply_browse_focus()  # type: ignore[attr-defined]

    def watch_browse_mode(self, value: bool) -> None:
        self._svc_browse.on_browse_mode(value)  # type: ignore[attr-defined]

    def _mount_minimap_default(self) -> None:  # DEPRECATED
        return self._svc_browse.mount_minimap_default()  # type: ignore[attr-defined]

    async def action_toggle_minimap(self) -> None:
        await self._svc_browse.action_toggle_minimap()  # type: ignore[attr-defined]

    def watch_browse_index(self, _value: int) -> None:
        self._svc_browse.on_browse_index(_value)  # type: ignore[attr-defined]

    def _rebuild_browse_anchors(self) -> None:  # DEPRECATED
        return self._svc_browse.rebuild_browse_anchors()  # type: ignore[attr-defined]

    def _jump_anchor(self, direction: int, filter_type=None) -> None:  # DEPRECATED
        return self._svc_browse.jump_anchor(direction, filter_type)  # type: ignore[attr-defined]

    def _focus_anchor(self, idx: int, anchor, *, _retry: bool = True) -> None:  # DEPRECATED
        return self._svc_browse.focus_anchor(idx, anchor, _retry=_retry)  # type: ignore[attr-defined]

    def _clear_browse_highlight(self) -> None:  # DEPRECATED
        return self._svc_browse.clear_browse_highlight()  # type: ignore[attr-defined]

    def _clear_browse_pips(self) -> None:  # DEPRECATED
        return self._svc_browse.clear_browse_pips()  # type: ignore[attr-defined]

    def _apply_browse_pips(self) -> None:  # DEPRECATED
        return self._svc_browse.apply_browse_pips()  # type: ignore[attr-defined]

    def _update_browse_status(self, anchor) -> None:  # DEPRECATED
        return self._svc_browse.update_browse_status(anchor)  # type: ignore[attr-defined]

    def action_jump_subagent_prev(self) -> None:
        self._svc_browse.action_jump_subagent_prev()  # type: ignore[attr-defined]

    def action_jump_subagent_next(self) -> None:
        self._svc_browse.action_jump_subagent_next()  # type: ignore[attr-defined]

    def _focus_tool_panel(self, direction: int) -> None:  # DEPRECATED
        return self._svc_browse.focus_tool_panel(direction)  # type: ignore[attr-defined]
