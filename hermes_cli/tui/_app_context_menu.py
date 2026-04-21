"""_ContextMenuMixin — right-click context menu + clipboard copy helpers for HermesApp."""
from __future__ import annotations

from typing import Any

from textual.css.query import NoMatches


class _ContextMenuMixin:
    """Context menu display, clipboard copy, and tool panel path actions.

    Extracted from HermesApp to reduce file size.  Self is always a HermesApp
    instance at runtime — all attribute access on self is valid.
    """

    async def on_click(self, event: Any) -> None:
        """Left-click focuses input; right-click (button=3) shows context menu."""
        if event.button == 1:
            from hermes_cli.tui.widgets import OutputPanel as _OP, HistorySearchOverlay as _HSO
            node = getattr(event, "widget", None)
            while node is not None:
                if isinstance(node, (_OP, _HSO)):
                    return
                node = getattr(node, "parent", None)
            try:
                self.query_one("#input-area").focus()  # type: ignore[attr-defined]
            except NoMatches:
                pass
            return
        if event.button != 3:
            return
        items = self._build_context_items(event)
        if not items:
            return
        event.prevent_default()
        sx = event.screen_x if event.screen_x is not None else event.x
        sy = event.screen_y if event.screen_y is not None else event.y
        await self._show_context_menu_at(items, sx, sy)

    async def _show_context_menu_for_focused(self) -> None:
        """Show context menu at the center of the currently focused widget."""
        widget = self.focused  # type: ignore[attr-defined]
        items: list = []
        if widget is not None:
            class _FakeEvent:
                button = 3
                widget = None
            fake = _FakeEvent()
            fake.widget = widget
            items = self._build_context_items(fake)
        if not items:
            return
        x, y = 0, 0
        if widget is not None:
            try:
                region = widget.content_region
                x = region.x + region.width // 2
                y = region.y + region.height // 2
            except Exception:
                pass
        await self._show_context_menu_at(items, x, y)

    async def _show_context_menu_at(self, items: list, x: int, y: int) -> None:
        """Position and reveal the ContextMenu at given screen coordinates."""
        try:
            from hermes_cli.tui.context_menu import ContextMenu as _CM
            await self.query_one(_CM).show(items, x, y)  # type: ignore[attr-defined]
        except NoMatches:
            pass

    def on_path_search_provider_batch(self, message: Any) -> None:
        """Relay PathSearchProvider.Batch to HermesInput (siblings can't bubble)."""
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.query_one(HermesInput).on_path_search_provider_batch(message)  # type: ignore[attr-defined]
        except (NoMatches, ImportError):
            pass

    def _build_context_items(self, event: Any) -> list:
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
                    return self._build_tool_block_menu_items(node)
            except ImportError:
                pass

            try:
                from hermes_cli.tui.tool_blocks import ToolHeader as _TH, ToolBlock as _TB
                if isinstance(node, _TH):
                    parent = node.parent
                    if isinstance(parent, _TB):
                        return self._build_tool_block_menu_items(parent)
            except ImportError:
                pass

            try:
                from hermes_cli.tui.widgets import StreamingCodeBlock as _SCB
                if isinstance(node, _SCB):
                    cb = node
                    items = [
                        MenuItem("⎘  Copy code block", "", lambda b=cb: self._copy_code_block(b)),
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
                        return [MenuItem("⎘  Copy message", "", lambda t=msg_text: self._copy_text_with_hint(t))]  # type: ignore[attr-defined]
            except ImportError:
                pass

            try:
                from hermes_cli.tui.widgets import MessagePanel as _MP
                if isinstance(node, _MP):
                    panel = node
                    items = []
                    selected = self._get_selected_text()  # type: ignore[attr-defined]
                    if selected:
                        sel_text = selected
                        items.append(MenuItem("⎘  Copy selected", "", lambda t=sel_text: self._copy_text(t)))
                    items.append(MenuItem("⎘  Copy full response", "", lambda p=panel: self._copy_panel(p)))
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
                            sel_text = getattr(node, "selected_text", "")
                        if sel_text:
                            items.append(MenuItem("⎘  Copy selected", "ctrl+c", lambda t=sel_text: self._copy_text(t)))
                    items += [
                        MenuItem(f"{ICON_COPY}  Paste", "ctrl+v", lambda: self._paste_into_input()),
                        MenuItem("✕  Clear input", "", lambda: self._clear_input()),
                    ]
                    return items
            except ImportError:
                pass

            if getattr(node, "id", None) == "input-row":
                return [
                    MenuItem(f"{ICON_COPY}  Paste", "ctrl+v", lambda: self._paste_into_input()),
                    MenuItem("✕  Clear input", "", lambda: self._clear_input()),
                ]

            node = getattr(node, "parent", None)

        items = []
        selected = self._get_selected_text()  # type: ignore[attr-defined]
        if selected:
            sel_text = selected
            items.append(MenuItem("⎘  Copy selected", "", lambda t=sel_text: self._copy_text(t)))
        from hermes_cli.tui.constants import ICON_COPY
        items.append(MenuItem(f"{ICON_COPY}  Paste", "ctrl+v", lambda: self._paste_into_input()))
        return items

    # --- Context menu action helpers ---

    def _copy_code_block(self, block: Any) -> None:
        """Copy a StreamingCodeBlock's plain-text content to clipboard and flash footer."""
        try:
            content = block.copy_content()
            self._copy_text_with_hint(content)  # type: ignore[attr-defined]
            if hasattr(block, "flash_copy"):
                block.flash_copy()
        except Exception:
            self._flash_hint("⚠ copy failed", 1.5)  # type: ignore[attr-defined]

    def _copy_tool_output(self, block: Any) -> None:
        """Copy a ToolBlock's plain-text content to clipboard and flash hint."""
        try:
            content = block.copy_content()
            self._copy_text_with_hint(content)  # type: ignore[attr-defined]
        except Exception:
            self._flash_hint("⚠ copy failed", 1.5)  # type: ignore[attr-defined]

    def _build_tool_block_menu_items(self, block: Any) -> list:
        """Build context menu items for a ToolBlock, including path actions."""
        from hermes_cli.tui.context_menu import MenuItem
        import sys
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
                    MenuItem("Open link",  "", lambda p=path, h=header, o=opener: self._open_path_action(h, p, o, False)),
                    MenuItem("Copy link",  "", lambda p=path, h=header:            self._copy_path_action(h, p)),
                ]
            else:
                items += [
                    MenuItem("Open",                   "", lambda p=path, h=header, o=opener: self._open_path_action(h, p, o, False)),
                    MenuItem("Copy path",              "", lambda p=path, h=header:            self._copy_path_action(h, p)),
                    MenuItem("Open containing folder", "", lambda p=path, h=header, o=opener: self._open_path_action(h, p, o, True)),
                ]

        sep = bool(path)
        items += [
            MenuItem("⎘  Copy tool output", "", lambda b=block: self._copy_tool_output(b), separator_above=sep),
            MenuItem("▸/▾  Expand/Collapse", "", lambda b=block: b.toggle()),
            MenuItem("⎘  Copy all output",  "", lambda: self._copy_all_output(), separator_above=True),
        ]
        return items

    def _copy_path_action(self, header: Any, path: str) -> None:
        """Copy path/URL to clipboard. Event-loop only."""
        self._copy_text_with_hint(path)  # type: ignore[attr-defined]
        if header is not None:
            header.flash_success()

    def _open_external_url(self, url: str) -> None:
        """Open a URL or file:// path in the system browser/file manager."""
        _ALLOWED = ("http://", "https://", "file://")
        if not any(url.startswith(s) for s in _ALLOWED):
            return
        import threading, subprocess, sys
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        threading.Thread(target=lambda: subprocess.run([opener, url], check=False), daemon=True).start()

    def on_copyable_rich_log_link_clicked(self, event: "Any") -> None:
        """Handle link clicks bubbled from CopyableRichLog widgets."""
        if getattr(event, "ctrl", False):
            self._open_external_url(event.url)
        else:
            self._copy_text_with_hint(event.url)  # type: ignore[attr-defined]

    def _open_path_action(self, header: Any, path: str, opener: str, folder: bool) -> None:
        """Open file/URL or containing folder in a worker thread."""
        import threading

        def _run() -> None:
            import subprocess
            from pathlib import Path
            if header is not None:
                self.call_from_thread(header._pulse_start)  # type: ignore[attr-defined]
            try:
                target = str(Path(path).parent) if folder else path
                subprocess.run([opener, target], check=True)
                if header is not None:
                    self.call_from_thread(header._pulse_stop)  # type: ignore[attr-defined]
                    self.call_from_thread(header.flash_success)  # type: ignore[attr-defined]
            except Exception:
                if header is not None:
                    self.call_from_thread(header._pulse_stop)  # type: ignore[attr-defined]
                    self.call_from_thread(header.flash_error)  # type: ignore[attr-defined]

        t = threading.Thread(target=_run, daemon=True)
        t.start()

    def _copy_all_output(self) -> None:
        """Copy plain text from every CopyableRichLog in the output panel."""
        try:
            from hermes_cli.tui.widgets import CopyableRichLog as _CRL
            parts = [log.copy_content() for log in self.query(_CRL)]  # type: ignore[attr-defined]
            content = "\n".join(p for p in parts if p)
            self._copy_text_with_hint(content)  # type: ignore[attr-defined]
        except Exception:
            self._flash_hint("⚠ copy failed", 1.5)  # type: ignore[attr-defined]

    def _copy_panel(self, panel: Any) -> None:
        """Copy a MessagePanel's response log content to clipboard."""
        try:
            from hermes_cli.tui.widgets import MessagePanel as _MP, CopyableRichLog as _CRL
            if isinstance(panel, _MP):
                content = panel.all_prose_text()
            elif isinstance(panel, _CRL):
                content = panel.copy_content()
            else:
                return
            self._copy_text_with_hint(content)  # type: ignore[attr-defined]
        except Exception:
            self._flash_hint("⚠ copy failed", 1.5)  # type: ignore[attr-defined]

    def _copy_text(self, text: str) -> None:
        """Copy arbitrary text to clipboard and flash hint."""
        self._copy_text_with_hint(text)  # type: ignore[attr-defined]

    def _paste_into_input(self) -> None:
        """Paste app clipboard content into the input and flash a paste hint."""
        try:
            inp = self.query_one("#input-area")  # type: ignore[attr-defined]
            text = self.clipboard  # type: ignore[attr-defined]
            if not text:
                inp.focus()
                self._flash_hint("clipboard empty", 1.5)  # type: ignore[attr-defined]
                return
            if hasattr(inp, "insert_text"):
                inp.insert_text(text)
            elif hasattr(inp, "value"):
                inp.value = f"{getattr(inp, 'value', '')}{text}"
            inp.focus()
            self._flash_hint(f"⎘  {len(text)} chars pasted", 1.2)  # type: ignore[attr-defined]
        except NoMatches:
            pass

    def _clear_input(self) -> None:
        """Clear the input content."""
        try:
            inp = self.query_one("#input-area")  # type: ignore[attr-defined]
            if hasattr(inp, "clear"):
                inp.clear()
            elif hasattr(inp, "value"):
                inp.value = ""
        except NoMatches:
            pass

    # --- ToolPanel events ---

    def on_tool_panel_path_focused(self, event: "Any") -> None:
        """Flash one-shot 'press o to open file' hint when OSC 8 not available."""
        if self._path_open_hint_shown:  # type: ignore[attr-defined]
            return
        try:
            from hermes_cli.tui.osc8 import is_supported as _osc8_supported
            if _osc8_supported():
                return
        except Exception:
            pass
        self._path_open_hint_shown = True  # type: ignore[attr-defined]
        self._flash_hint("press o to open file", 3.0)  # type: ignore[attr-defined]

    # --- Overlay management ---

    def _dismiss_all_info_overlays(self) -> None:
        """Remove --visible from all info overlays."""
        from hermes_cli.tui.overlays import (
            CommandsOverlay, HelpOverlay, ModelOverlay, ModelPickerOverlay,
            ReasoningPickerOverlay, SessionOverlay, SkinPickerOverlay,
            UsageOverlay, VerbosePickerOverlay, WorkspaceOverlay, YoloConfirmOverlay,
            ToolPanelHelpOverlay as _TPHO,
        )
        for cls in (
            HelpOverlay, UsageOverlay, CommandsOverlay, ModelOverlay, WorkspaceOverlay,
            SessionOverlay,
            ModelPickerOverlay, ReasoningPickerOverlay, SkinPickerOverlay,
            YoloConfirmOverlay, VerbosePickerOverlay, _TPHO,
        ):
            for widget in self.query(cls):  # type: ignore[attr-defined]
                widget.remove_class("--visible")
        self._sync_workspace_polling_state()  # type: ignore[attr-defined]
