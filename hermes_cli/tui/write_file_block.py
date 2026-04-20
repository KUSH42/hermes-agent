"""WriteFileBlock — per-chunk content streaming for write_file / create_file.

Extends StreamingToolBlock with:
- PartialJSONCodeExtractor(field="content") for delta routing
- Optional CharacterPacer typewriter effect
- Per-line Pygments highlight during streaming
- rich.Syntax full-file re-highlight on completion
- Path-aware header via ToolHeader.set_path()
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.css.query import NoMatches

from hermes_cli.tui.tool_blocks import (
    COLLAPSE_THRESHOLD,
    StreamingToolBlock,
    _SPINNER_FRAMES,
)
from textual.widgets import Static

from hermes_cli.tui.widgets import CopyableRichLog

_LANG_MAP: dict[str, str] = {
    "py": "python", "js": "javascript", "ts": "typescript",
    "tsx": "tsx", "jsx": "jsx", "rs": "rust", "go": "go",
    "java": "java", "c": "c", "cpp": "cpp", "cs": "csharp",
    "rb": "ruby", "sh": "bash", "bash": "bash", "zsh": "bash",
    "yml": "yaml", "yaml": "yaml", "json": "json", "toml": "toml",
    "md": "markdown", "html": "html", "css": "css", "sql": "sql",
    "xml": "xml", "txt": "text",
}


def _lang_for_path(path: str) -> str:
    suffix = Path(path).suffix.lstrip(".").lower()
    return _LANG_MAP.get(suffix, "text")


class WriteFileBlock(StreamingToolBlock):
    """StreamingToolBlock for write_file/create_file — streams content field.

    Lifecycle: GEN_START → GEN_STREAMING (content chars via feed_delta) →
    TOOL_START (set_final_path) → TOOL_COMPLETE (complete())
    """

    DEFAULT_CSS = "WriteFileBlock { height: auto; }"
    _content_type: str = "tool"

    def __init__(self, path: str = "", **kwargs: Any) -> None:
        label = path if path else "write_file"
        super().__init__(label=label, tool_name="write_file", **kwargs)
        self._path = path
        self._content_line_count = 0
        self._line_scratch = ""         # partial line buffer
        self._content_lines: list[str] = []
        self._pacer = None
        self._extractor = None
        self._writing_hint: Static | None = None
        if path:
            self._header.set_path(path)

    def on_mount(self) -> None:
        # StreamingToolBlock.on_mount() also runs (MRO: derived first, then parent).
        # Queue overrides to run after all on_mount handlers complete.
        self.call_after_refresh(self._apply_write_mount_overrides)

        from hermes_cli.tui.partial_json import PartialJSONCodeExtractor
        from hermes_cli.tui.character_pacer import CharacterPacer

        self._extractor = PartialJSONCodeExtractor(field="content")

        cps = 0
        try:
            from hermes_cli.config import read_raw_config
            cps = int(read_raw_config().get("display", {}).get(
                "write_file_typewriter_cps", 0
            ))
        except Exception:
            pass
        try:
            css_vars = self.app.get_css_variables()
            if css_vars.get("reduced-motion", "0") not in ("0", "", None):
                cps = 0
        except Exception:
            pass

        self._pacer = CharacterPacer(
            cps=cps,
            on_reveal=self.append_content_chars,
            app=self.app,
        )

        if cps == 0:
            self._writing_hint = Static("writing…", classes="--wfb-writing-hint")
            self._body.mount(self._writing_hint)

    def _apply_write_mount_overrides(self) -> None:
        """Run after all MRO on_mount handlers. Re-apply write_file-specific state."""
        self._body.add_class("expanded")
        self._header.collapsed = False

    # ------------------------------------------------------------------
    # Path update (called from _on_tool_start when full args are known)
    # ------------------------------------------------------------------

    def set_final_path(self, path: str) -> None:
        """Update path from tool_start function_args. Event-loop only."""
        if not path:
            return
        self._path = path
        self._header.set_path(path)
        self._header._label = path
        self._header.refresh()

    # ------------------------------------------------------------------
    # Streaming API
    # ------------------------------------------------------------------

    def feed_delta(self, delta: str) -> None:
        """Feed JSON streaming delta through content extractor to pacer."""
        if self._extractor is None or self._completed:
            return
        chunk = self._extractor.feed(delta)
        if chunk and self._pacer is not None:
            self._pacer.feed(chunk)

    def append_content_chars(self, chars: str) -> None:
        """Append decoded content chars, splitting on newlines. Event-loop only."""
        if self._completed:
            return
        self._line_scratch += chars
        while "\n" in self._line_scratch:
            line, self._line_scratch = self._line_scratch.split("\n", 1)
            self._emit_content_line(line)

    def _emit_content_line(self, line: str) -> None:
        """Append a single decoded content line to the body with per-line highlight."""
        self._content_lines.append(line)
        self._content_line_count += 1
        try:
            log = self._body.query_one(CopyableRichLog)
        except NoMatches:
            return
        try:
            from hermes_cli.tui.body_renderer import BodyRenderer
            from hermes_cli.tui.tool_category import ToolCategory
            renderer = BodyRenderer.for_category(ToolCategory.FILE)
            lang = _lang_for_path(self._path)
            renderable = renderer.render_stream_line(line, line, lang=lang)
            log.write_with_source(renderable, line)
        except Exception:
            log.write_with_source(Text(line), line)

    # ------------------------------------------------------------------
    # Completion
    # ------------------------------------------------------------------

    def complete(self, duration: str, is_error: bool = False) -> None:
        """WriteFileBlock completion: flush pacer, re-highlight, finalize header."""
        if self._completed:
            return

        # Flush pacer buffer
        if self._pacer is not None:
            self._pacer.flush()
            self._pacer.stop()

        # Flush any partial scratch line
        if self._line_scratch:
            self._emit_content_line(self._line_scratch)
            self._line_scratch = ""

        # Clear writing hint if shown (CPS=0 path)
        if self._writing_hint is not None:
            self._writing_hint.remove()
            self._writing_hint = None

        # Re-highlight full body with rich.Syntax
        self._rehighlight_body()

        # Finalize lifecycle (mirrors StreamingToolBlock.complete but uses content count)
        self._completed = True
        try:
            self._render_timer.stop()
            self._spinner_timer.stop()
            self._duration_timer.stop()
        except Exception:
            pass
        self._header._pulse_stop()
        self._header.set_error(is_error)
        self._flush_pending()  # no-op (we never use _pending)
        self._tail.dismiss()
        self._header._spinner_char = None
        self._header._duration = duration
        self._header._line_count = self._content_line_count

        if self._content_line_count > COLLAPSE_THRESHOLD:
            self._header._has_affordances = True
            self._header.collapsed = True
            self._body.remove_class("expanded")
        elif self._content_line_count == 0:
            self._body.styles.display = "none"
            self._header.collapsed = False
        else:
            self._header.collapsed = False

        self._header.refresh()
        if is_error:
            self._header.flash_error()
        else:
            self._header.flash_success()

    def _rehighlight_body(self) -> None:
        """Clear body and re-render full content as rich.Syntax via FileRenderer."""
        if not self._content_lines:
            return
        try:
            log = self._body.query_one(CopyableRichLog)
            log.clear()
            from hermes_cli.tui.body_renderer import BodyRenderer
            from hermes_cli.tui.tool_category import ToolCategory
            renderer = BodyRenderer.for_category(ToolCategory.FILE)
            lang = _lang_for_path(self._path)
            renderable = renderer.finalize(self._content_lines, lang=lang)
            if renderable is not None:
                full_content = "\n".join(self._content_lines)
                log.write_with_source(renderable, full_content)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Copy override — return all content lines (no display cap)
    # ------------------------------------------------------------------

    def copy_content(self) -> str:
        return "\n".join(self._content_lines)

    def on_unmount(self) -> None:
        if self._pacer is not None:
            self._pacer.stop()
        super().on_unmount()
