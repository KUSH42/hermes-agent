"""WriteFileBlock — per-chunk content streaming for write_file / create_file.

Extends StreamingToolBlock with:
- PartialJSONCodeExtractor(field="content") for delta routing
- Optional CharacterPacer typewriter effect
- Per-line Pygments highlight during streaming
- rich.Syntax full-file re-highlight on completion
- Path-aware header via ToolHeader.set_path()
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)

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
        self._pre_mount_chunks: list[str] = []  # H9: buffer raw deltas before mount
        self._progress: Static | None = None  # J2: single widget — starts "writing…", updates to "writing · NKB"
        # Legacy aliases kept for any external callers
        self._writing_hint: Static | None = None
        self._progress_label: Static | None = None
        self._bytes_written: int = 0                # B4
        self._bytes_total: int = 0                  # B4
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
            _log.debug("WriteFileBlock: config read failed", exc_info=True)
        try:
            css_vars = self.app.get_css_variables()
            if css_vars.get("reduced-motion", "0") not in ("0", "", None):
                cps = 0
        except Exception:
            _log.debug("WriteFileBlock: css var lookup failed", exc_info=True)

        pacer = CharacterPacer(
            cps=cps,
            on_reveal=self.append_content_chars,
            app=self.app,
        )
        self._pacer = self._register_pacer(pacer)

        # H9: drain any deltas that arrived before mount completed
        if self._pre_mount_chunks:
            for raw in self._pre_mount_chunks:
                chunk = self._extractor.feed(raw)
                if chunk:
                    self._pacer.feed(chunk)
            self._pre_mount_chunks.clear()

        if cps == 0:
            # J2: single progress widget — text transitions from "writing…" to "writing · NKB"
            self._progress = Static("writing…", classes="--wfb-progress")
            self._writing_hint = self._progress   # alias for compat
            self._progress_label = self._progress  # alias for compat
            self._body.mount(self._progress)

    def _apply_write_mount_overrides(self) -> None:
        """Run after all MRO on_mount handlers. Re-apply write_file-specific state."""
        self._body.add_class("expanded")
        self._header.collapsed = False

    # ------------------------------------------------------------------
    # Path update (called from _on_tool_start when full args are known)
    # ------------------------------------------------------------------

    def update_progress(self, written: int, total: int = 0) -> None:
        """J2: update single progress widget — transitions from 'writing…' to 'writing · NKB'."""
        self._bytes_written = written
        self._bytes_total = total
        widget = self._progress
        if widget is None:
            return
        if written == 0:
            widget.update("writing…")
            return
        try:
            from hermes_cli.tui.streaming_microcopy import _human_size
            msg = f"writing · {_human_size(written)}"
            if total > 0:
                msg += f" / {_human_size(total)}"
            widget.update(msg)
        except Exception:
            _log.debug("WriteFileBlock.update_progress: _human_size failed", exc_info=True)
            widget.update(f"writing · {written}B")

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
        if self._completed:
            return
        if self._extractor is None or self._pacer is None:
            # H9: before mount — buffer raw delta for drain in on_mount
            self._pre_mount_chunks.append(delta)
            return
        chunk = self._extractor.feed(delta)
        if chunk:
            self._pacer.feed(chunk)

    def append_content_chars(self, chars: str) -> None:
        """Append decoded content chars, splitting on newlines. Event-loop only."""
        if self._completed:
            return
        self._line_scratch += chars
        while "\n" in self._line_scratch:
            line, self._line_scratch = self._line_scratch.split("\n", 1)
            self._emit_content_line(line)

    def _lookup_view_state(self) -> "Any | None":
        """Return the ToolCallViewState for this block, or None (no view-state context)."""
        return None

    def _emit_content_line(self, line: str) -> None:
        """Append a single decoded content line to the body with per-line highlight."""
        self._content_lines.append(line)
        self._content_line_count += 1
        try:
            log = self._body.query_one(CopyableRichLog)
        except NoMatches:
            return
        try:
            from hermes_cli.tui.body_renderers import pick_renderer, _STREAMING_EMPTY_CLS
            from hermes_cli.tui.tool_payload import ToolPayload
            from hermes_cli.tui.tool_category import ToolCategory
            from hermes_cli.tui.services.tools import ToolCallState
            from hermes_cli.tui.tool_panel.density import DensityTier

            view = self._lookup_view_state()
            density = view.density if view is not None else DensityTier.DEFAULT
            _payload = ToolPayload(
                tool_name="write_file", category=ToolCategory.FILE,
                args={}, input_display=None, output_raw="", line_count=0,
            )
            renderer_cls = pick_renderer(
                _STREAMING_EMPTY_CLS, _payload,
                phase=ToolCallState.STREAMING, density=density,
            )
            renderer = renderer_cls(_payload, _STREAMING_EMPTY_CLS)
            lang = _lang_for_path(self._path)
            renderable = renderer.render_stream_line(line, line, lang=lang)
            log.write_with_source(renderable, line)
        except Exception:
            _log.debug("WriteFileBlock._emit_content_line: renderer failed", exc_info=True)
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

        # Clear progress widget if shown (CPS=0 path)
        if self._progress is not None:
            try:
                self._progress.remove()
            except Exception:
                _log.debug("WriteFileBlock.complete: progress widget remove failed", exc_info=True)
            self._progress = None
            self._writing_hint = None
            self._progress_label = None

        # Re-highlight full body with rich.Syntax
        self._rehighlight_body()

        # Finalize lifecycle (mirrors StreamingToolBlock.complete but uses content count)
        self._completed = True
        try:
            self._render_timer.stop()
            self._spinner_timer.stop()
            self._duration_timer.stop()
        except Exception:
            _log.debug("WriteFileBlock.complete: timer stop failed", exc_info=True)
        self._header._pulse_stop()
        self._header.set_error(is_error)
        self._flush_pending()  # no-op (we never use _pending)
        self._tail.dismiss()
        started = getattr(self, "_stream_started_at", None)
        if started is not None:
            elapsed_ms = (time.monotonic() - started) * 1000.0
            from hermes_cli.tui.tool_blocks import _format_duration_v4
            self._header._duration = _format_duration_v4(elapsed_ms)
        else:
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
            from hermes_cli.tui.body_renderers import pick_renderer, _STREAMING_EMPTY_CLS
            from hermes_cli.tui.tool_payload import ToolPayload
            from hermes_cli.tui.tool_category import ToolCategory
            from hermes_cli.tui.services.tools import ToolCallState
            from hermes_cli.tui.tool_panel.density import DensityTier

            view = self._lookup_view_state()
            density = view.density if view is not None else DensityTier.DEFAULT
            _payload = ToolPayload(
                tool_name="write_file", category=ToolCategory.FILE,
                args={}, input_display=None, output_raw="", line_count=0,
            )
            renderer_cls = pick_renderer(
                _STREAMING_EMPTY_CLS, _payload,
                phase=ToolCallState.STREAMING, density=density,
            )
            renderer = renderer_cls(_payload, _STREAMING_EMPTY_CLS)
            lang = _lang_for_path(self._path)
            renderable = renderer.finalize(self._content_lines, lang=lang)
            if renderable is not None:
                full_content = "\n".join(self._content_lines)
                log.write_with_source(renderable, full_content)
        except Exception:
            _log.debug("WriteFileBlock._rehighlight_body: re-highlight failed", exc_info=True)

    # ------------------------------------------------------------------
    # Copy override — return all content lines (no display cap)
    # ------------------------------------------------------------------

    def copy_content(self) -> str:
        return "\n".join(self._content_lines)

    def on_unmount(self) -> None:
        super().on_unmount()  # ManagedTimerMixin.on_unmount → _stop_all_managed
