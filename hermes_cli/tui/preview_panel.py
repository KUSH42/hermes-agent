"""Live syntax-highlighted file preview — the "ink-killer" feature.

``PreviewPanel`` is a ``RichLog`` subclass with a ``candidate`` reactive.
When a ``PathCandidate`` is assigned, a threaded worker reads the file head,
sniffs for binary content, and posts raw preview payload back to the event
loop. The event loop builds ``Syntax`` objects from cached source so skin/theme
changes can rerender current preview without rereading the filesystem.

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
from textual.worker import get_current_worker

from .path_search import PathCandidate

_MAX_PREVIEW_LINES = 80
_MAX_PREVIEW_BYTES = 128 * 1024
_BINARY_SNIFF_BYTES = 4096


def _hex_luminance(hex_color: str) -> float:
    """WCAG relative luminance from a #rrggbb string.  Returns 0–255 scale."""
    h = hex_color.lstrip("#")
    if len(h) == 6:
        try:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return 0.2126 * r + 0.7152 * g + 0.0722 * b
        except ValueError:
            pass
    return 0.0  # fallback → treat as dark


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

    class PreviewReady(Message):
        """Carries preview source for Syntax rendering on the event loop."""

        __slots__ = ("abs_path", "head")

        def __init__(self, abs_path: str, head: str) -> None:
            super().__init__()
            self.abs_path = abs_path
            self.head = head

    class PlainReady(Message):
        """Carries a plain-text fallback message from the background reader."""

        __slots__ = ("abs_path", "text")

        def __init__(self, abs_path: str, text: str) -> None:
            super().__init__()
            self.abs_path = abs_path
            self.text = text

    # --- Reactive state ---

    candidate: reactive[PathCandidate | None] = reactive(None)

    def __init__(self) -> None:
        super().__init__(markup=False, wrap=False, auto_scroll=False)
        self._syntax_abs_path: str | None = None
        self._syntax_head: str | None = None
        self._plain_text: str | None = None
        self._preview_lines: list[str] = []

    @property
    def preview_lines(self) -> list[str]:
        """Logical preview lines — usable even when RichLog hasn't rendered yet."""
        return self._preview_lines

    def watch_candidate(self, candidate: PathCandidate | None) -> None:
        if candidate is None:
            self._clear_cached_state()
            self.clear()
            return
        self._load_preview(candidate.abs_path)

    def _clear_cached_state(self) -> None:
        self._syntax_abs_path = None
        self._syntax_head = None
        self._plain_text = None
        self._preview_lines = []

    def _candidate_matches(self, abs_path: str) -> bool:
        current = self.candidate
        return current is not None and current.abs_path == abs_path

    def _render_syntax(self, abs_path: str, head: str) -> None:
        try:
            css = self.app.get_css_variables()
            theme = css.get("preview-syntax-theme", "")
            background = css.get("app-bg", "#1e1e1e")
            if not theme:
                theme = "monokai" if _hex_luminance(background) < 128 else "default"
        except Exception:
            theme = "monokai"
            background = "#1e1e1e"
        syntax = Syntax(
            head,
            Syntax.guess_lexer(abs_path, head),
            theme=theme,
            line_numbers=True,
            word_wrap=False,
            indent_guides=False,
            background_color=background,
        )
        self.clear()
        self.write(syntax)
        self._syntax_abs_path = abs_path
        self._syntax_head = head
        self._plain_text = None
        self._preview_lines = head.splitlines() or [""]

    def refresh_theme(self) -> None:
        """Rebuild current syntax preview from cached source on skin change."""
        if self._syntax_abs_path and self._syntax_head is not None:
            self._render_syntax(self._syntax_abs_path, self._syntax_head)

    @work(thread=True, exclusive=True, group="preview")
    def _load_preview(self, abs_path: str) -> None:
        # P0-C: check cancellation before any I/O — rapid selection changes
        # may cancel this worker before it starts meaningful work.
        worker = get_current_worker()
        if worker.is_cancelled:
            return
        try:
            path = Path(abs_path)
            if path.is_dir():
                try:
                    all_entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name))
                    lines = []
                    for entry in all_entries[:40]:
                        prefix = "d " if entry.is_dir() else "  "
                        lines.append(f"{prefix}{entry.name}")
                    if len(all_entries) > 40:
                        lines.append(f"  … ({len(all_entries)} total)")
                    # B4: prepend directory name + total count as header
                    header = f"{path.name}/  ({len(all_entries)} items)"
                    body = "\n".join(lines) if lines else "(empty)"
                    text = f"{header}\n\n{body}"
                except OSError as e:
                    text = f"(cannot read directory: {e})"
                if not worker.is_cancelled:
                    self.post_message(self.PlainReady(abs_path, text))
                return
            size = path.stat().st_size
            if size > _MAX_PREVIEW_BYTES:
                if not worker.is_cancelled:
                    self.post_message(self.PlainReady(abs_path, f"(too large: {size // 1024} KB)"))
                return
            # Read raw bytes first so we can binary-sniff without corrupting
            # the decode on a non-UTF-8 text file.
            with path.open("rb") as fb:
                raw = fb.read(_MAX_PREVIEW_BYTES)
            # P0-C: check again after the blocking read — cancellation can't
            # interrupt open().read(), so the earliest safe checkpoint is here.
            if worker.is_cancelled:
                return
            if _looks_binary(raw):
                self.post_message(self.PlainReady(abs_path, f"(binary file: {size} bytes)"))
                return
            text = raw.decode("utf-8", errors="replace")
            head = "\n".join(text.splitlines()[:_MAX_PREVIEW_LINES])
            if not worker.is_cancelled:
                self.post_message(self.PreviewReady(abs_path, head))
        except OSError as e:
            if not worker.is_cancelled:
                self.post_message(self.PlainReady(abs_path, f"(cannot read: {e})"))

    # --- Message handlers (run on event loop) ---

    def on_preview_panel_preview_ready(self, event: "PreviewPanel.PreviewReady") -> None:
        if not self._candidate_matches(event.abs_path):
            return
        self._render_syntax(event.abs_path, event.head)

    def on_preview_panel_plain_ready(self, event: "PreviewPanel.PlainReady") -> None:
        if not self._candidate_matches(event.abs_path):
            return
        self.clear()
        self.write(event.text)
        self._syntax_abs_path = None
        self._syntax_head = None
        self._plain_text = event.text
        self._preview_lines = event.text.splitlines() or [""]
