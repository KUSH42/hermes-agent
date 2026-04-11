"""CompletionOverlay — container for the virtual completion list + preview panel.

Mounted once at startup, positioned directly above ``HermesInput`` via
``HermesApp.compose`` ordering (no ``dock``, no ``offset-y`` hacks).
Visibility is driven by a CSS class so children preserve their reactives
and scroll position across rapid show/hide cycles.

CSS class states
----------------
(no class)      → hidden (``display: none`` in DEFAULT_CSS)
``--visible``   → shown as a horizontal split
``--slash-only`` (combined with ``--visible``) → preview panel hidden,
                  completion list takes full width
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal

from .completion_list import VirtualCompletionList
from .preview_panel import PreviewPanel


class CompletionOverlay(Horizontal):
    """Sibling of HermesInput; holds the completion list + preview panel.

    Visibility is driven by a CSS class, not by mount/unmount, so the
    children preserve their reactives and scroll position across rapid
    dismiss/re-show cycles.
    """

    DEFAULT_CSS = """
    CompletionOverlay {
        height: auto;
        max-height: 14;
        display: none;
    }
    CompletionOverlay.--visible {
        display: block;
    }
    CompletionOverlay > VirtualCompletionList {
        width: 40%;
    }
    CompletionOverlay > PreviewPanel {
        width: 60%;
    }
    CompletionOverlay.--slash-only > PreviewPanel {
        display: none;
    }
    CompletionOverlay.--slash-only > VirtualCompletionList {
        width: 100%;
    }
    """

    def compose(self) -> ComposeResult:
        yield VirtualCompletionList()
        yield PreviewPanel()
