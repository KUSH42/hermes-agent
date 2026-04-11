"""Live syntax-highlighted file preview — the "ink-killer" feature.

``PreviewPanel`` is a ``RichLog`` subclass with a ``candidate`` reactive.
When a ``PathCandidate`` is assigned, a threaded worker reads the file head,
sniffs for binary content, builds a ``Syntax`` object via Pygments, and
updates the log via ``post_message`` (same thread-safe pattern as
``PathSearchProvider``).

The ``"preview"`` worker group is ``exclusive=True``: holding arrow-down
through 500 path candidates only commits the *last* read, not all 500.

Binary sniff: null-byte heuristic matching git's ``is_binary`` check — any
``NUL`` in the first 4 KiB of the file.

Size cap: files larger than 128 KB show a "(too large: N KB)" message instead
of reading potentially huge blobs into the TUI.
"""

from __future__ import annotations

from pathlib import Path

from rich.syntax import Syntax
from textual import work
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import RichLog

from .path_search import PathCandidate

_MAX_PREVIEW_LINES = 80
_MAX_PREVIEW_BYTES = 128 * 1024
_BINARY_SNIFF_BYTES = 4096


def _looks_binary(head_bytes: bytes) -> bool:
    """Null-byte heuristic.  Matches git's is_binary check: any NUL in the
    first 4 KiB → binary.  Cheap and good enough for preview skip/fallback."""
    return b"\x00" in head_bytes[:_BINARY_SNIFF_BYTES]


class PreviewPanel(RichLog):
    """Live-updating syntax-highlighted preview of the highlighted path candidate."""

    DEFAULT_CSS = """
    PreviewPanel {
        width: 1fr;
        min-width: 30;
        height: auto;
        max-height: 12;
    }
    """

    # --- Internal messages (thread-safe via post_message, same as PathSearchProvider) ---

    class SyntaxReady(Message):
        """Carries a rendered Syntax object from the background reader."""
        __slots__ = ("syntax",)
        def __init__(self, syntax: Syntax) -> None:
            super().__init__()
            self.syntax = syntax

    class PlainReady(Message):
        """Carries a plain-text fallback message from the background reader."""
        __slots__ = ("text",)
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    # --- Reactive state ---

    candidate: reactive[PathCandidate | None] = reactive(None)

    def __init__(self) -> None:
        super().__init__(markup=False, wrap=False, auto_scroll=False)

    def watch_candidate(self, candidate: PathCandidate | None) -> None:
        if candidate is None:
            self.clear()
            return
        self._load_preview(candidate.abs_path)

    @work(thread=True, exclusive=True, group="preview")
    def _load_preview(self, abs_path: str) -> None:
        try:
            path = Path(abs_path)
            size = path.stat().st_size
            if size > _MAX_PREVIEW_BYTES:
                self.post_message(self.PlainReady(f"(too large: {size // 1024} KB)"))
                return
            # Read raw bytes first so we can binary-sniff without corrupting
            # the decode on a non-UTF-8 text file.
            with path.open("rb") as fb:
                raw = fb.read(_MAX_PREVIEW_BYTES)
            if _looks_binary(raw):
                self.post_message(self.PlainReady(f"(binary file: {size} bytes)"))
                return
            text = raw.decode("utf-8", errors="replace")
            head = "\n".join(text.splitlines()[:_MAX_PREVIEW_LINES])
            syntax = Syntax(
                head,
                Syntax.guess_lexer(abs_path, head),
                theme="monokai",
                line_numbers=True,
                word_wrap=False,
                indent_guides=False,
            )
            self.post_message(self.SyntaxReady(syntax))
        except OSError as e:
            self.post_message(self.PlainReady(f"(cannot read: {e})"))

    # --- Message handlers (run on event loop) ---

    def on_preview_panel_syntax_ready(self, event: "PreviewPanel.SyntaxReady") -> None:
        self.clear()
        self.write(event.syntax)

    def on_preview_panel_plain_ready(self, event: "PreviewPanel.PlainReady") -> None:
        self.clear()
        self.write(event.text)
