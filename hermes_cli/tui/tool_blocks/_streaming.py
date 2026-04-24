"""ToolTail and StreamingToolBlock widgets."""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

import re

logger = logging.getLogger(__name__)

from rich.text import Text
from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.widgets import Button, Static

from hermes_cli.tui.widgets import CopyableRichLog, _strip_ansi

from hermes_cli.tui.animation import make_spinner_identity, SpinnerIdentity

from ._shared import (
    _VISIBLE_CAP,
    _OB_WARN_THRESHOLD,
    _LINE_BYTE_CAP,
    _PAGE_SIZE,
    _SPINNER_FRAMES,
    _linkify_text,
    _first_link,
    _build_args_row_text,
    _secondary_args_text,
    _format_duration_v4,
    _MEDIA_LINE_RE,
    _extract_image_path,
    ImageMounted,
    OmissionBar,
    ToolHeaderStats,
)
from ._block import ToolBlock, COLLAPSE_THRESHOLD


# ---------------------------------------------------------------------------
# ToolTail — scroll-lock badge shown when auto-scroll is disengaged
# ---------------------------------------------------------------------------

class ToolTail(Static):
    """Single-line badge: '  ↓ N new lines' — right-aligned, dim.

    Hidden (``display: none``) when auto-scroll is active or the tool has
    completed.  Clicking it re-engages auto-scroll.
    """

    DEFAULT_CSS = """
    ToolTail {
        height: 1;
        display: none;
        text-align: right;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._new_line_count = 0

    def update_count(self, n: int) -> None:
        self._new_line_count = n
        if n > 0:
            self.update(f"  ↓ {n} new lines  ")
            self.display = True
            self.add_class("--visible")
        else:
            self.display = False
            self.remove_class("--visible")

    def dismiss(self) -> None:
        self._new_line_count = 0
        self.display = False
        self.remove_class("--visible")


# ---------------------------------------------------------------------------
# StreamingToolBlock — live output during tool execution
# ---------------------------------------------------------------------------

class StreamingToolBlock(ToolBlock):
    """ToolBlock with IDLE → STREAMING → COMPLETED lifecycle.

    Lines arrive via ``append_line()`` (called from the event loop via
    ``call_from_thread``).  A 60 fps flush timer drains the pending-line
    buffer into the RichLog.  Back-pressure is handled by:

    * **Render throttle** — the flush timer batches all lines that arrived
      between ticks into a single render pass.
    * **Visible cap** — at most ``_VISIBLE_CAP`` (200) lines are written to
      the RichLog.  Additional lines are tracked only in plain-text storage.
    * **Byte cap** — lines longer than ``_LINE_BYTE_CAP`` (2000 chars) are
      truncated before rendering and before plain-text storage.

    Used for real-time output during tool execution (terminal, execute_code).
    Content is written directly to the RichLog via ``_flush_pending()`` — the
    inherited ``self._lines`` / ``self._plain_lines`` are always empty.

    For post-completion summaries with full skin-refresh support, see
    ``ToolBlock`` (static).
    """

    DEFAULT_CSS = "StreamingToolBlock { height: auto; }"

    def __init__(self, label: str, tool_name: str | None = None, tool_input: "dict | None" = None,
                 is_first_in_turn: bool = False, tool_call_id: str | None = None,
                 **kwargs: Any) -> None:
        super().__init__(label=label, lines=[], plain_lines=[], tool_name=tool_name, **kwargs)
        self._stream_label = label
        self._tool_input = tool_input
        self._is_first_in_turn: bool = is_first_in_turn
        self._spinner_identity: "SpinnerIdentity | None" = (
            make_spinner_identity(tool_call_id) if tool_call_id else None
        )
        self._pending: list[tuple[Text, str]] = []
        self._all_plain: list[str] = []
        self._all_rich: list[Text] = []
        self._visible_start: int = 0
        self._visible_count: int = 0
        self._total_received: int = 0
        self._omission_bar_top: OmissionBar | None = None
        self._omission_bar_bottom: OmissionBar | None = None
        self._omission_bar_top_mounted: bool = False
        self._omission_bar_bottom_mounted: bool = False
        self._spinner_frame: int = 0
        self._completed: bool = False
        self._tail = ToolTail()
        self._bytes_received: int = 0
        self._last_line_time: float = 0.0
        self._flush_slow: bool = False
        self._microcopy_widget: "Static | None" = None
        self._rate_samples: deque[tuple[float, int]] = deque(maxlen=60)
        self._last_http_status: str | None = None
        self._follow_tail: bool = False
        self._follow_tail_dirty: bool = False
        self._cached_body_log: "CopyableRichLog | None" = None
        self._microcopy_tick: int = 0
        self._shimmer_phase: float = 0.0
        self._microcopy_shown: bool = False
        self._secondary_args_snapshot: str = ""
        self._history_capped: bool = False
        self._truncated_line_count: int = 0
        self._should_strip_cwd: bool = False
        self._detected_cwd: str | None = None
        self._body._omission_parent_block = self

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._body
        yield self._tail

    def on_mount(self) -> None:
        self._header._has_affordances = False
        self._header._spinner_identity = self._spinner_identity
        frames = self._spinner_identity.frames if self._spinner_identity else _SPINNER_FRAMES
        self._header._spinner_char = frames[0]
        self._stream_started_at = time.monotonic()
        self._last_line_time = self._stream_started_at
        self._header._duration = "0.0s"
        self._render_timer = self.set_interval(1 / 60, self._flush_pending)
        self._spinner_timer = self.set_interval(0.25, self._tick_spinner)
        self._duration_timer = self.set_interval(0.1, self._tick_duration)
        try:
            display_cfg = self.app.cfg.get("display", {})  # type: ignore[attr-defined]
            self._visible_cap: int = int(display_cfg.get("tool_visible_cap", _VISIBLE_CAP))
            self._line_byte_cap: int = int(display_cfg.get("tool_line_byte_cap", _LINE_BYTE_CAP))
        except Exception:
            self._visible_cap = _VISIBLE_CAP
            self._line_byte_cap = _LINE_BYTE_CAP
        try:
            self._microcopy_widget = self._body.query_one(".--microcopy", Static)
        except Exception:
            self._microcopy_widget = None
        try:
            self._cached_body_log = self._body.query_one(CopyableRichLog)
        except Exception:
            pass
        if self._omission_bar_top is not None:
            self._omission_bar_top.display = False
        if self._omission_bar_bottom is not None:
            self._omission_bar_bottom.display = False
        # Compose pre-mounts bars and sets _omission_bar_bottom_mounted = True.
        self._header._pulse_start()
        try:
            from hermes_cli.tui.tool_category import spec_for as _spec_for
            _spec = _spec_for(self._tool_name or "")
            _sec = _secondary_args_text(_spec.category, self._tool_input)
            if _sec:
                self._body.update_secondary_args(_sec)
                self._secondary_args_snapshot = _sec
        except Exception:
            pass
        if self._is_first_in_turn:
            try:
                panel = self.parent.parent
                if panel is not None:
                    panel.add_class("first-in-turn")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Streaming API
    # ------------------------------------------------------------------

    _HTTP_STATUS_LINE_RE = re.compile(r'^HTTP/\S+\s+(\d+\s+.+)$')

    _MAX_HISTORY_LINES: int = 10_000
    _EVICT_CHUNK: int = 500

    def append_line(self, raw: str) -> None:
        if self._completed:
            return
        line_byte_cap = getattr(self, "_line_byte_cap", _LINE_BYTE_CAP)
        if len(raw) > line_byte_cap:
            over = len(raw) - line_byte_cap
            raw = raw[:line_byte_cap] + f"… (+{over} chars)"
            self._truncated_line_count += 1
        if self._should_strip_cwd:
            from hermes_cli.tui.cwd_strip import strip_cwd
            cleaned, cwd = strip_cwd(raw)
            if cwd is not None:
                self._detected_cwd = cwd
            if not cleaned.strip():
                return
            raw = cleaned
        plain = _strip_ansi(raw)
        self._total_received += 1
        self._bytes_received += len(raw)
        now = time.monotonic()
        self._last_line_time = now
        rich = _linkify_text(plain, Text.from_ansi(raw))
        self._pending.append((rich, plain))
        self._all_plain.append(plain)
        self._all_rich.append(rich)
        if len(self._all_plain) >= self._MAX_HISTORY_LINES:
            del self._all_plain[:self._EVICT_CHUNK]
            del self._all_rich[:self._EVICT_CHUNK]
            self._visible_start = max(0, self._visible_start - self._EVICT_CHUNK)
            self._history_capped = True
        total = len(self._all_plain)
        if self._follow_tail and total > getattr(self, "_visible_cap", _VISIBLE_CAP):
            self._follow_tail_dirty = True
        self._rate_samples.append((now, len(raw)))
        m = self._HTTP_STATUS_LINE_RE.match(plain.strip())
        if m:
            self._last_http_status = m.group(1).strip()
        if self._flush_slow:
            self._flush_slow = False
            self._render_timer.stop()
            self._render_timer = self.set_interval(1 / 60, self._flush_pending)

    def inject_diff(self, diff_lines: list[str], header_stats: "ToolHeaderStats | None") -> None:
        for raw in diff_lines:
            self.append_line(raw)
        if header_stats is not None:
            self._header._stats = header_stats
        self._header.add_class("--diff-header")

    def on_unmount(self) -> None:
        try:
            self._render_timer.stop()
        except Exception:
            pass
        try:
            self._spinner_timer.stop()
        except Exception:
            pass
        try:
            self._duration_timer.stop()
        except Exception:
            pass

    def complete(self, duration: str, is_error: bool = False) -> None:
        if self._completed:
            return
        self._completed = True
        self._follow_tail = False
        try:
            self._render_timer.stop()
            self._spinner_timer.stop()
            self._duration_timer.stop()
        except Exception:
            pass
        self._header._pulse_stop()
        self._header.set_error(is_error)
        self._flush_pending()
        self._tail.dismiss()
        self._header._spinner_char = None
        self._header._is_complete = True
        started = getattr(self, "_stream_started_at", None)
        if started is not None:
            elapsed_ms = (time.monotonic() - started) * 1000.0
            self._header._elapsed_ms = elapsed_ms
            self._header._duration = _format_duration_v4(elapsed_ms)
        else:
            self._header._duration = duration
        self._header._line_count = self._total_received
        if self._total_received > COLLAPSE_THRESHOLD:
            self._header._has_affordances = True
        self._header.refresh()
        self._clear_microcopy_on_complete()
        if self._secondary_args_snapshot:
            self._body.update_secondary_args(self._secondary_args_snapshot)
        if not is_error and self._total_received == 0:
            self._header.add_class("result-empty")
        if getattr(self, '_detected_cwd', None):
            from rich.text import Text as _RichText
            try:
                from hermes_cli.tui.widgets import CopyableRichLog as _CRL
                log = self._body.query_one(_CRL)
                log.write(_RichText(f"  cwd: {self._detected_cwd}", style="dim"))
            except Exception:
                pass
        if is_error:
            self._header.flash_error()
        else:
            self._header.flash_success()
        self._try_mount_media()
        try:
            from hermes_cli.tui.tool_category import spec_for as _spec_for
            _spec = _spec_for(self._tool_name or "")
            _args_text = _build_args_row_text(_spec, self._tool_input)
            if _args_text:
                self._body.set_args_row(_args_text)
        except Exception:
            pass

    def _clear_microcopy_on_complete(self) -> None:
        self._body.clear_microcopy()

    def _try_mount_media(self) -> bool:
        mounted = False

        # Scan in reverse for last image match — avoids joining all_plain into one string
        image_path: "str | None" = None
        for line in reversed(self._all_plain):
            m = _MEDIA_LINE_RE.search(line)
            if m:
                image_path = _extract_image_path(m.group(0))
                if image_path:
                    break
        if image_path is not None:
            try:
                from hermes_cli.tui.widgets import InlineImage
                self._body.mount(InlineImage(image=image_path, max_rows=24))
                self.post_message(ImageMounted(image_path))
                mounted = True
            except Exception:
                pass

        try:
            from hermes_cli.tui.media_player import (
                _AUDIO_EXT_RE, _VIDEO_EXT_RE, _YOUTUBE_RE, _inline_media_config,
            )
            from hermes_cli.tui.widgets import InlineMediaWidget
            cfg = _inline_media_config()
            if cfg.enabled:
                seen: set[str] = set()
                for line in self._all_plain:
                    for url in _AUDIO_EXT_RE.findall(line):
                        if url not in seen:
                            seen.add(url)
                            self.mount(InlineMediaWidget(url=url, kind="audio"))
                            mounted = True
                    for url in _VIDEO_EXT_RE.findall(line):
                        if url not in seen:
                            seen.add(url)
                            self.mount(InlineMediaWidget(url=url, kind="video"))
                            mounted = True
                    for url in _YOUTUBE_RE.findall(line):
                        if url not in seen:
                            seen.add(url)
                            self.mount(InlineMediaWidget(url=url, kind="youtube"))
                            mounted = True
        except Exception:
            pass

        return mounted

    # ------------------------------------------------------------------
    # Internal timers
    # ------------------------------------------------------------------

    def _tick_spinner(self) -> None:
        if self._completed:
            return
        frames = self._spinner_identity.frames if self._spinner_identity is not None else _SPINNER_FRAMES
        self._spinner_frame = (self._spinner_frame + 1) % len(frames)
        self._header._spinner_char = frames[self._spinner_frame]
        self._header.refresh()

    def _tick_duration(self) -> None:
        if self._completed:
            return
        started = getattr(self, "_stream_started_at", None)
        if started is None:
            return
        elapsed_ms = (time.monotonic() - started) * 1000.0
        self._header._elapsed_ms = elapsed_ms
        self._header._duration = _format_duration_v4(elapsed_ms)
        self._header.refresh()

    def _bytes_per_second(self) -> float | None:
        now = time.monotonic()
        cutoff = now - 2.0
        recent = [(t, b) for t, b in self._rate_samples if t >= cutoff]
        if len(recent) < 2:
            return None
        return sum(b for _, b in recent) / 2.0

    def _update_microcopy(self) -> None:
        if self._completed:
            return
        started = getattr(self, "_stream_started_at", None)
        if started is None:
            return
        elapsed_s = time.monotonic() - started
        if elapsed_s < 0.5:
            return
        try:
            from hermes_cli.tui.tool_category import spec_for
            from hermes_cli.tui.streaming_microcopy import StreamingState, microcopy_line
        except Exception:
            return
        spec = spec_for(self._tool_name or "")
        state = StreamingState(
            lines_received=self._total_received,
            bytes_received=self._bytes_received,
            elapsed_s=elapsed_s,
            last_status=self._last_http_status,
            rate_bps=self._bytes_per_second(),
        )
        reduced_motion = getattr(getattr(self, "app", None), "_reduced_motion", False)
        try:
            from hermes_cli.tui.tool_category import ToolCategory as _TC
            if spec.category == _TC.AGENT:
                self._shimmer_phase = (self._shimmer_phase + 0.05) % 2.0
        except Exception:
            pass
        stalled = (
            not self._completed
            and self._last_line_time > 0.0
            and (time.monotonic() - self._last_line_time) > 5.0
        )
        text = microcopy_line(spec, state, reduced_motion=reduced_motion, shimmer_phase=self._shimmer_phase, stalled=stalled)
        if text:
            self._body.set_microcopy(text)
            self._microcopy_shown = True

    def _flush_pending(self) -> None:
        if not self._flush_slow and not self._completed:
            now = time.monotonic()
            if now - self._last_line_time > 2.0:
                self._flush_slow = True
                self._render_timer.stop()
                self._render_timer = self.set_interval(1 / 10, self._flush_pending)

        self._microcopy_tick = (self._microcopy_tick + 1) % 6
        do_microcopy = self._microcopy_tick == 0

        if not self._pending:
            if do_microcopy:
                self._update_microcopy()
            return
        batch = self._pending
        self._pending = []

        log = self._cached_body_log
        if log is None:
            try:
                log = self._body.query_one(CopyableRichLog)
                self._cached_body_log = log
            except NoMatches:
                return

        lines_written = 0
        visible_cap = getattr(self, "_visible_cap", _VISIBLE_CAP)
        for rich, plain in batch:
            if self._visible_count < visible_cap:
                log.write_with_source(rich, plain, link=_first_link(plain))
                self._visible_count += 1
                lines_written += 1

        if self._omission_bar_bottom_mounted or self._omission_bar_top_mounted:
            self._refresh_omission_bars()

        if lines_written:
            try:
                scrolled_up = getattr(self.app.query_one("#output-panel"), "_user_scrolled_up", False)
            except Exception:
                scrolled_up = False
            if scrolled_up:
                new_total = self._tail._new_line_count + lines_written
                try:
                    self._tail.update_count(new_total)
                except Exception:
                    pass

        if self._follow_tail_dirty:
            self._follow_tail_dirty = False
            total = len(self._all_plain)
            visible_cap = getattr(self, "_visible_cap", _VISIBLE_CAP)
            if total > visible_cap:
                self.rerender_window(total - visible_cap, total)

        if do_microcopy:
            self._update_microcopy()

    # ------------------------------------------------------------------
    # OmissionBar callbacks
    # ------------------------------------------------------------------

    def rerender_window(self, start: int, end: int) -> None:
        log = self._cached_body_log
        if log is None:
            try:
                log = self._body.query_one(CopyableRichLog)
                self._cached_body_log = log
            except NoMatches:
                return
        log.clear()
        for rich_line, plain in zip(self._all_rich[start:end], self._all_plain[start:end]):
            log.write_with_source(rich_line, plain, link=_first_link(plain))
        self._visible_start = start
        self._visible_count = end - start
        self._refresh_omission_bars()

    def reveal_lines(self, start: int, end: int) -> None:
        try:
            log = self._body.query_one(CopyableRichLog)
        except NoMatches:
            return
        for rich_line, plain in zip(self._all_rich[start:end], self._all_plain[start:end]):
            log.write_with_source(rich_line, plain, link=_first_link(plain))
        self._visible_count += end - start
        self._refresh_omission_bars()

    def collapse_to(self, new_end: int) -> None:
        try:
            log = self._body.query_one(CopyableRichLog)
        except NoMatches:
            return
        log.clear()
        for rich_line, plain in zip(self._all_rich[:new_end], self._all_plain[:new_end]):
            log.write_with_source(rich_line, plain, link=_first_link(plain))
        self._visible_start = 0
        self._visible_count = new_end
        self._refresh_omission_bars()

    def _refresh_omission_bars(self) -> None:
        total = len(self._all_plain)
        visible_start = self._visible_start
        visible_end = visible_start + self._visible_count
        visible_cap = getattr(self, "_visible_cap", _VISIBLE_CAP)

        cap_msg: str | None = None
        if self._history_capped:
            cap_msg = "⚠ history capped at 10k lines"
            if self._truncated_line_count > 0:
                cap_msg += f" · {self._truncated_line_count} truncated"
        elif total > visible_cap:
            cap_msg = f"⚠ {total} total · cap {visible_cap}"
            if self._truncated_line_count > 0:
                cap_msg += f" · {self._truncated_line_count} truncated"
        elif self._truncated_line_count > 0:
            try:
                from hermes_cli.tui.streaming_microcopy import _human_size
                line_cap_str = _human_size(getattr(self, "_line_byte_cap", _LINE_BYTE_CAP))
            except Exception:
                line_cap_str = f"{getattr(self, '_line_byte_cap', _LINE_BYTE_CAP)}b"
            cap_msg = f"⚠ {self._truncated_line_count} lines truncated ({line_cap_str} cap)"

        if self._omission_bar_top_mounted and self._omission_bar_top is not None:
            show_top = visible_start > 0
            if self._omission_bar_top.display != show_top:
                self._omission_bar_top.display = show_top
            self._omission_bar_top.set_counts(
                visible_start=visible_start,
                visible_end=visible_end,
                total=total,
                above=visible_start,
                cap_msg=cap_msg,
                visible_cap=visible_cap,  # H1
            )

        if self._omission_bar_bottom_mounted and self._omission_bar_bottom is not None:
            show_bottom = (visible_end < total) or bool(cap_msg)
            if self._omission_bar_bottom.display != show_bottom:
                self._omission_bar_bottom.display = show_bottom
            self._omission_bar_bottom.set_counts(
                visible_start=visible_start,
                visible_end=visible_end,
                total=total,
                below=total - visible_end,
                cap_msg=cap_msg,
                visible_cap=visible_cap,  # H1
            )

    # ------------------------------------------------------------------
    # Override copy_content / refresh_skin
    # ------------------------------------------------------------------

    def copy_content(self) -> str:
        return "\n".join(self._all_plain)

    def refresh_skin(self) -> None:
        """Refresh header cosmetics only — skip body re-render."""
        self._header._refresh_gutter_color()
        self._header._refresh_tool_icon()
        self._header.refresh()
        for bar in (self._omission_bar_top, self._omission_bar_bottom):
            if bar is not None and bar.is_mounted:
                try:
                    btn = bar.query_one(".--ob-cap", Button)
                    btn.label = OmissionBar._reset_label()
                except NoMatches:
                    logger.debug("omission bar reset button not found during skin refresh", exc_info=True)
                except AttributeError as exc:
                    logger.warning("omission bar API drift in refresh_skin: %s", exc, exc_info=True)

    def set_age_microcopy(self, text: str) -> None:
        """F1: update the microcopy slot with age text (only when complete)."""
        if not self._completed:
            return
        from rich.text import Text as _T
        mc = self._microcopy_widget
        if mc is None:
            try:
                mc = self._body.query_one(".--microcopy", Static)
                self._microcopy_widget = mc
            except Exception:
                return
        styled = _T(text, style="dim")
        mc.update(styled)
        mc.add_class("--active")
        mc.remove_class("--secondary-args")
