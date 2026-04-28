"""Right-click context menu items service extracted from _app_context_menu.py."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.css.query import NoMatches

from .base import AppService
from hermes_cli.tui.io_boundary import safe_open_url

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp

_log = logging.getLogger(__name__)


class ContextMenuService(AppService):
    """
    Right-click context menu display, clipboard copy, and tool panel path actions.
    Migrated from _ContextMenuMixin in _app_context_menu.py.

    Methods:
      handle_click             — core logic of on_click (button routing)
      show_context_menu_for_focused
      show_context_menu_at
      on_path_search_provider_batch
      build_context_items
      copy_code_block          — was _copy_code_block
      copy_tool_output         — was _copy_tool_output
      build_tool_block_menu_items  — was _build_tool_block_menu_items
      copy_path_action         — was _copy_path_action
      open_external_url        — was _open_external_url
      on_copyable_rich_log_link_clicked
      open_path_action         — was _open_path_action
      copy_all_output          — was _copy_all_output
      copy_panel               — was _copy_panel
      copy_text                — was _copy_text
      paste_into_input         — was _paste_into_input
      clear_input              — was _clear_input
      on_tool_panel_path_focused
      dismiss_all_info_overlays — was _dismiss_all_info_overlays
    """

    def __init__(self, app: "HermesApp") -> None:
        super().__init__(app)

    async def handle_click(self, event: Any) -> None:
        """Core logic of on_click — routes left/right button events."""
        app = self.app
        if event.button == 1:
            from hermes_cli.tui.widgets import OutputPanel as _OP, HistorySearchOverlay as _HSO
            node = getattr(event, "widget", None)
            while node is not None:
                if isinstance(node, (_OP, _HSO)):
                    return
                node = getattr(node, "parent", None)
            try:
                app.query_one("#input-area").focus()
            except NoMatches:
                pass
            return
        if event.button != 3:
            return
        items = self.build_context_items(event)
        if not items:
            return
        event.prevent_default()
        sx = event.screen_x if event.screen_x is not None else event.x
        sy = event.screen_y if event.screen_y is not None else event.y
        await self.show_context_menu_at(items, sx, sy)

    async def show_context_menu_for_focused(self) -> None:
        """Show context menu at the center of the currently focused widget."""
        app = self.app
        widget = app.focused
        items: list = []
        if widget is not None:
            class _FakeEvent:
                button = 3
                widget = None
            fake = _FakeEvent()
            fake.widget = widget
            items = self.build_context_items(fake)
        if not items:
            return
        x, y = 0, 0
        if widget is not None:
            try:
                region = widget.content_region
                x = region.x + region.width // 2
                y = region.y + region.height // 2
            except Exception:
                # Region unavailable; use (0, 0) as fallback position — correct for menu placement
                pass
        await self.show_context_menu_at(items, x, y)

    async def show_context_menu_at(self, items: list, x: int, y: int) -> None:
        """Position and reveal the ContextMenu at given screen coordinates."""
        try:
            from hermes_cli.tui.context_menu import ContextMenu as _CM
            await self.app.query_one(_CM).show(items, x, y)
        except NoMatches:
            pass

    def on_path_search_provider_batch(self, message: Any) -> None:
        """Relay PathSearchProvider.Batch to HermesInput (siblings can't bubble)."""
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).on_path_search_provider_batch(message)
        except (NoMatches, ImportError):
            pass

    def build_context_items(self, event: Any) -> list:
        """Walk the clicked widget's parent chain and return context menu items.

        Priority (first match wins):
        1. ToolBlock / ToolHeader → tool copy + expand/collapse + copy-all
        2. MessagePanel          → copy selected (if any) + copy full response
        3. HermesInput / #input-row → paste hint + clear input
        4. Fallback              → copy selected only (if selection is active)
        """
        from hermes_cli.tui.context_menu import MenuItem
        from hermes_cli.tui.constants import ICON_COPY

        widget = getattr(event, "widget", None)
        if widget is None:
            return []

        node = widget
        while node is not None:
            try:
                from hermes_cli.tui.tool_blocks import ToolBlock as _TB
                if isinstance(node, _TB):
                    return self.build_tool_block_menu_items(node)
            except ImportError:
                pass

            try:
                from hermes_cli.tui.tool_blocks import ToolHeader as _TH, ToolBlock as _TB
                if isinstance(node, _TH):
                    parent = node.parent
                    if isinstance(parent, _TB):
                        return self.build_tool_block_menu_items(parent)
            except ImportError:
                pass

            try:
                from hermes_cli.tui.widgets import StreamingCodeBlock as _SCB
                if isinstance(node, _SCB):
                    cb = node
                    items = [
                        MenuItem("⎘  Copy code block", "", lambda b=cb: self.copy_code_block(b)),
                    ]
                    if cb.can_toggle():
                        items.append(MenuItem("▸/▾  Expand/Collapse", "", lambda b=cb: b.toggle_collapsed()))
                    return items
            except ImportError:
                pass

            try:
                from hermes_cli.tui.widgets import UserMessagePanel as _UMP
                if isinstance(node, _UMP):
                    msg_text = getattr(node, "_message", "")
                    if msg_text:
                        return [MenuItem("⎘  Copy message", "", lambda t=msg_text: self.app._svc_theme.copy_text_with_hint(t))]
            except ImportError:
                pass

            try:
                from hermes_cli.tui.widgets import MessagePanel as _MP
                if isinstance(node, _MP):
                    panel = node
                    items = []
                    selected = self.app._svc_theme.get_selected_text()
                    if selected:
                        sel_text = selected
                        items.append(MenuItem("⎘  Copy selected", "", lambda t=sel_text: self.app._svc_theme.copy_text_with_hint(t)))
                    items.append(MenuItem("⎘  Copy full response", "", lambda p=panel: self.copy_panel(p)))
                    return items
            except ImportError:
                pass

            try:
                from hermes_cli.tui.input_widget import HermesInput as _HI
                if isinstance(node, _HI):
                    items = []
                    sel = getattr(node, "selection", None)
                    if sel is not None and not sel.is_empty:
                        try:
                            sel_text = node.get_text_range(sel.start, sel.end)
                        except Exception:
                            # get_text_range not available in this widget version; fall back to selected_text
                            sel_text = getattr(node, "selected_text", "")
                        if sel_text:
                            items.append(MenuItem("⎘  Copy selected", "ctrl+c", lambda t=sel_text: self.app._svc_theme.copy_text_with_hint(t)))
                    items += [
                        MenuItem(f"{ICON_COPY}  Paste", "ctrl+v", lambda: self.paste_into_input()),
                        MenuItem("✕  Clear input", "", lambda: self.clear_input()),
                    ]
                    return items
            except ImportError:
                pass

            if getattr(node, "id", None) == "input-row":
                return [
                    MenuItem(f"{ICON_COPY}  Paste", "ctrl+v", lambda: self.paste_into_input()),
                    MenuItem("✕  Clear input", "", lambda: self.clear_input()),
                ]

            node = getattr(node, "parent", None)

        items = []
        selected = self.app._svc_theme.get_selected_text()
        if selected:
            sel_text = selected
            items.append(MenuItem("⎘  Copy selected", "", lambda t=sel_text: self.app._svc_theme.copy_text_with_hint(t)))
        from hermes_cli.tui.constants import ICON_COPY
        items.append(MenuItem(f"{ICON_COPY}  Paste", "ctrl+v", lambda: self.paste_into_input()))
        return items

    # --- Context menu action helpers ---

    def copy_code_block(self, block: Any) -> None:
        """Copy a StreamingCodeBlock's plain-text content to clipboard and flash footer."""
        try:
            content = block.copy_content()
            self.app._svc_theme.copy_text_with_hint(content)
            if hasattr(block, "flash_copy"):
                block.flash_copy()
        except Exception:
            _log.debug("copy action failed", exc_info=True)
            self.app._flash_hint("⚠ copy failed", 1.5)

    def copy_tool_output(self, block: Any) -> None:
        """Copy a ToolBlock's plain-text content to clipboard and flash hint."""
        try:
            content = block.copy_content()
            self.app._svc_theme.copy_text_with_hint(content)
        except Exception:
            _log.debug("copy action failed", exc_info=True)
            self.app._flash_hint("⚠ copy failed", 1.5)

    def build_tool_block_menu_items(self, block: Any) -> list:
        """Build context menu items for a ToolBlock, including path actions."""
        from hermes_cli.tui.context_menu import MenuItem
        items: list[MenuItem] = []
        opener = "open" if sys.platform == "darwin" else "xdg-open"

        header = getattr(block, "_header", None)
        header_path = getattr(header, "_full_path", None) if header is not None else None
        diff_path = getattr(block, "_diff_file_path", None)
        path = header_path or diff_path
        is_url = getattr(header, "_is_url", False) if path == header_path and header is not None else False

        if path:
            if is_url:
                items += [
                    MenuItem("Open link",  "", lambda p=path, h=header, o=opener: self.open_path_action(h, p, o, False)),
                    MenuItem("Copy link",  "", lambda p=path, h=header:            self.copy_path_action(h, p)),
                ]
            else:
                items += [
                    MenuItem("Open",                   "", lambda p=path, h=header, o=opener: self.open_path_action(h, p, o, False)),
                    MenuItem("Copy path",              "", lambda p=path, h=header:            self.copy_path_action(h, p)),
                    MenuItem("Open containing folder", "", lambda p=path, h=header, o=opener: self.open_path_action(h, p, o, True)),
                ]

        sep = bool(path)
        items += [
            MenuItem("⎘  Copy tool output", "", lambda b=block: self.copy_tool_output(b), separator_above=sep),
            MenuItem("▸/▾  Expand/Collapse", "", lambda b=block: b.toggle()),
            MenuItem("⎘  Copy all output",  "", lambda: self.copy_all_output(), separator_above=True),
        ]
        return items

    def copy_path_action(self, header: Any, path: str) -> None:
        """Copy path/URL to clipboard. Event-loop only."""
        self.app._svc_theme.copy_text_with_hint(path)
        if header is not None:
            header.flash_success()

    def open_external_url(self, url: str) -> None:
        """Open a URL or file:// path in the system browser/file manager."""
        _ALLOWED = ("http://", "https://", "file://")
        if not any(url.startswith(s) for s in _ALLOWED):
            return
        safe_open_url(self.app, url)

    def on_copyable_rich_log_link_clicked(self, event: Any) -> None:
        """Handle link clicks bubbled from CopyableRichLog widgets."""
        if getattr(event, "ctrl", False):
            self.open_external_url(event.url)
        else:
            self.app._svc_theme.copy_text_with_hint(event.url)

    def open_path_action(self, header: Any, path: str, opener: str, folder: bool) -> None:  # noqa: ARG002
        """Open file/URL or containing folder via safe_open_url."""
        target = str(Path(path).parent) if folder else path
        _err_fired = False

        def _on_error(exc: Exception, h: Any = header) -> None:
            nonlocal _err_fired
            _err_fired = True
            if h is not None and h.is_mounted:
                h.flash_error()

        safe_open_url(
            self.app,
            Path(target).resolve().as_uri(),
            on_error=_on_error if header is not None else None,
        )
        if header is not None and not _err_fired:
            header.flash_success()

    def copy_all_output(self) -> None:
        """Copy plain text from every CopyableRichLog in the output panel."""
        try:
            from hermes_cli.tui.widgets import CopyableRichLog as _CRL
            parts = [log.copy_content() for log in self.app.query(_CRL)]
            content = "\n".join(p for p in parts if p)
            self.app._svc_theme.copy_text_with_hint(content)
        except Exception:
            _log.debug("copy action failed", exc_info=True)
            self.app._flash_hint("⚠ copy failed", 1.5)

    def copy_panel(self, panel: Any) -> None:
        """Copy a MessagePanel's response log content to clipboard."""
        try:
            from hermes_cli.tui.widgets import MessagePanel as _MP, CopyableRichLog as _CRL
            if isinstance(panel, _MP):
                content = panel.all_prose_text()
            elif isinstance(panel, _CRL):
                content = panel.copy_content()
            else:
                return
            self.app._svc_theme.copy_text_with_hint(content)
        except Exception:
            _log.debug("copy action failed", exc_info=True)
            self.app._flash_hint("⚠ copy failed", 1.5)

    def copy_text(self, text: str) -> None:
        """Copy arbitrary text to clipboard and flash hint."""
        self.app._svc_theme.copy_text_with_hint(text)

    def paste_into_input(self) -> None:
        """Paste app clipboard content into the input and flash a paste hint."""
        app = self.app
        try:
            inp = app.query_one("#input-area")
            text = app.clipboard
            if not text:
                inp.focus()
                app._flash_hint("clipboard empty", 1.5)
                return
            if hasattr(inp, "insert_text"):
                inp.insert_text(text)
            elif hasattr(inp, "value"):
                inp.value = f"{getattr(inp, 'value', '')}{text}"
            inp.focus()
            app._flash_hint(f"⎘  {len(text)} chars pasted", 1.2)
        except NoMatches:
            pass

    def clear_input(self) -> None:
        """Clear the input content."""
        try:
            inp = self.app.query_one("#input-area")
            if hasattr(inp, "clear"):
                inp.clear()
            elif hasattr(inp, "value"):
                inp.value = ""
        except NoMatches:
            pass

    # --- ToolPanel events ---

    def on_tool_panel_path_focused(self, event: Any) -> None:
        """Flash one-shot 'press o to open file' hint when OSC 8 not available."""
        app = self.app
        if app._path_open_hint_shown:
            return
        try:
            from hermes_cli.tui.osc8 import is_supported as _osc8_supported
            if _osc8_supported():
                return
        except Exception:
            # osc8 support check failed; assume unsupported and show plain hint
            pass
        app._path_open_hint_shown = True
        app._flash_hint("press o to open file", 3.0)

    # --- Overlay management ---

    def dismiss_all_info_overlays(self) -> None:
        """Remove --visible from all info overlays."""
        from hermes_cli.tui.overlays import (
            CommandsOverlay, ConfigOverlay, HelpOverlay, SessionOverlay,
            UsageOverlay, WorkspaceOverlay,
            ToolPanelHelpOverlay as _TPHO,
        )
        app = self.app
        for cls in (
            HelpOverlay, UsageOverlay, CommandsOverlay, WorkspaceOverlay,
            SessionOverlay, ConfigOverlay, _TPHO,
        ):
            for widget in app.query(cls):
                widget.remove_class("--visible")
        app._sync_workspace_polling_state()
