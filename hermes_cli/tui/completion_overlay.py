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

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import RichLog, Static

from .completion_list import VirtualCompletionList
from .path_search import SlashCandidate
from .preview_panel import PreviewPanel


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
            self.write(f"[bold]{c.command}[/bold]\n\n{c.description or '(no description)'}")
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

    def on_resize(self, event: events.Resize) -> None:
        self.set_class(event.size.width < 100, "--narrow")

    def on_virtual_completion_list_auto_dismiss(
        self, _message: VirtualCompletionList.AutoDismiss,
    ) -> None:
        """Auto-close when the empty-state timer fires (P0-B)."""
        self.remove_class("--visible")
        self.remove_class("--slash-only")
