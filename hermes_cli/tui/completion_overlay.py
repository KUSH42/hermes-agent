"""CompletionOverlay — container for the virtual completion list + preview panel.

Mounted once at startup, positioned directly above ``HermesInput`` via
``HermesApp.compose`` ordering (no ``dock``, no ``offset-y`` hacks).
Visibility is driven by a CSS class so children preserve their reactives
and scroll position across rapid show/hide cycles.

CSS class states
----------------
(no class)      → hidden (``display: none`` in DEFAULT_CSS)
``--visible``   → shown as a Vertical container: ContentRow above overflow badge
``--slash-only`` (combined with ``--visible``) → preview panel hidden,
                  completion list takes full width

Layout
------
CompletionOverlay (Vertical)
├── _ContentRow (Horizontal, height: auto, max-height: 13)
│   ├── VirtualCompletionList
│   └── PreviewPanel
└── #overflow-badge (Static, height: 1, display: none when ≤13 items)
"""

from __future__ import annotations

import logging

from textual import events

logger = logging.getLogger(__name__)
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import RichLog, Static

from .completion_list import VirtualCompletionList
from .path_search import SlashCandidate
from .preview_panel import PreviewPanel
from .resize_utils import THRESHOLD_COMP_NARROW, crosses_threshold


class SlashDescPanel(RichLog):
    """Shows the description for the currently highlighted slash command."""

    DEFAULT_CSS = """
    SlashDescPanel {
        width: 1fr;
        min-width: 20;
        height: auto;
        max-height: 12;
        display: none;
    }
    """

    def __init__(self) -> None:
        super().__init__(markup=True, wrap=True, auto_scroll=False)

    def on_mount(self) -> None:
        self.watch(self.app, "highlighted_candidate", self._on_candidate)

    def _on_candidate(self, c: object) -> None:
        if isinstance(c, SlashCandidate):
            self.clear()
            # Build title line: "/command [args_hint]"
            args = f" [dim]{c.args_hint}[/dim]" if c.args_hint else ""
            title = f"[bold]{c.command}[/bold]{args}"
            desc = c.description or "(no description)"
            # Keybind hint on same line as description (right-aligned dim)
            keybind = f"  [dim]{c.keybind_hint}[/dim]" if c.keybind_hint else ""
            self.write(f"{title}\n\n{desc}{keybind}")
        else:
            self.clear()


class _ContentRow(Horizontal):
    """Inner row containing the list and preview panel side-by-side."""

    DEFAULT_CSS = """
    _ContentRow {
        height: auto;
        max-height: 13;
    }
    _ContentRow > VirtualCompletionList {
        width: 40%;
    }
    _ContentRow > PreviewPanel {
        width: 60%;
    }
    """


class CompletionOverlay(Vertical):
    """Sibling of HermesInput; holds the completion list + preview panel.

    Visibility is driven by a CSS class, not by mount/unmount, so the
    children preserve their reactives and scroll position across rapid
    dismiss/re-show cycles.
    """

    DEFAULT_CSS = """
    CompletionOverlay {
        layer: overlay;
        dock: bottom;
        margin-bottom: 4;
        height: auto;
        min-height: 4;
        max-height: 14;
        display: none;
    }
    CompletionOverlay.--visible {
        display: block;
    }
    CompletionOverlay.--slash-only _ContentRow > PreviewPanel {
        display: none;
    }
    CompletionOverlay.--slash-only _ContentRow > VirtualCompletionList {
        width: 40%;
    }
    CompletionOverlay.--slash-only SlashDescPanel {
        display: block;
        width: 60%;
    }
    CompletionOverlay.--narrow.--slash-only SlashDescPanel {
        display: none;
    }
    CompletionOverlay.--narrow _ContentRow > PreviewPanel {
        display: none;
    }
    CompletionOverlay.--narrow _ContentRow > VirtualCompletionList {
        width: 100%;
    }
    CompletionOverlay.--narrow.--slash-only _ContentRow > VirtualCompletionList {
        width: 100%;
    }
    #overflow-badge {
        height: 1;
        display: none;
    }
    """

    def compose(self) -> ComposeResult:
        with _ContentRow():
            yield VirtualCompletionList()
            yield PreviewPanel()
            yield SlashDescPanel()
        yield Static("", id="overflow-badge")

    def on_mount(self) -> None:
        self._last_applied_w: int = 0
        # A3: apply initial --narrow class based on current app width so a
        # terminal that starts narrow doesn't need a resize event to trigger it.
        try:
            w = self.app.size.width
            self.set_class(w < THRESHOLD_COMP_NARROW, "--narrow")
            self._last_applied_w = w
        except Exception:
            logger.debug("CompletionOverlay.on_mount: narrow-class setup failed", exc_info=True)

    def on_resize(self, event: events.Resize) -> None:
        w = event.size.width
        if self._last_applied_w == 0 or crosses_threshold(self._last_applied_w, w, THRESHOLD_COMP_NARROW):
            self.set_class(w < THRESHOLD_COMP_NARROW, "--narrow")
        self._last_applied_w = w
        # B1: cap max-height dynamically so overlay does not clip at short terminal heights
        avail = max(4, event.size.height - 8)
        try:
            self.styles.max_height = avail
        except Exception:
            logger.debug("CompletionOverlay.on_resize: max_height set failed", exc_info=True)

    def _clear_highlighted_candidate(self) -> None:
        """Reset app.highlighted_candidate so ghost text is cleared."""
        try:
            self.app.highlighted_candidate = None
        except Exception:
            logger.debug("CompletionOverlay._clear_highlighted_candidate failed", exc_info=True)

    def on_virtual_completion_list_auto_dismiss(
        self, _message: VirtualCompletionList.AutoDismiss,
    ) -> None:
        """Auto-close when the empty-state timer fires (P0-B)."""
        self.remove_class("--visible")
        self.remove_class("--slash-only")
        self._clear_highlighted_candidate()
