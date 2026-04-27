"""ToolTail and StreamingToolBlock widgets."""
from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from textual.timer import Timer

import re

logger = logging.getLogger(__name__)

# MC-2: canonical live-tail chip text (concept §Microcopy contract + line 185).
_MORE_ROWS_CHIP = "↓ {n} more-rows"

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.widgets import Button, Static

from hermes_cli.tui.body_renderers import RendererKind
from hermes_cli.tui.widgets import CopyableRichLog, FlashMessage, HintBar, KindOverrideChanged, _strip_ansi


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
from hermes_cli.tui.managed_timer_mixin import ManagedTimerMixin

_FLUSH_MAX_RETRIES = 32

# SK-1: pre-first-chunk skeleton row constants
_SKELETON_DELAY_S = 0.1
_SKELETON_GLYPH = "· · ·"
_SKELETON_PULSE_S = 0.4


# ---------------------------------------------------------------------------
# ToolTail — scroll-lock badge shown when auto-scroll is disengaged
# ---------------------------------------------------------------------------

class ToolTail(Static):
    """Single-line badge: '↓ N more-rows' — right-aligned, dim.

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
            self.update(_MORE_ROWS_CHIP.format(n=n))
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

class StreamingToolBlock(ManagedTimerMixin, ToolBlock):
    """ToolBlock with IDLE → STREAMING → COMPLETED lifecycle.

    LL-4: `t` cycles renderer kind; `Shift+T` reverts to auto.
    LL-5: adoption flash on GENERATED→STARTED transition.
    """

    BINDINGS = [
        Binding("t", "cycle_kind", "Cycle renderer kind"),
        Binding("T", "kind_revert", "Revert to auto kind"),
    ]

    # ------------------------------------------------------------------
    # docstring continued (not a second docstring — just a comment block)
    # Lines arrive via ``append_line()`` (called from the event loop via
    # ``call_from_thread``).  A 60 fps flush timer drains the pending-line
    # buffer into the RichLog.  Back-pressure is handled by:
    #
    # * **Render throttle** — the flush timer batches all lines that arrived
    #   between ticks into a single render pass.
    # * **Visible cap** — at most ``_VISIBLE_CAP`` (200) lines are written to
    #   the RichLog.  Additional lines are tracked only in plain-text storage.
    # * **Byte cap** — lines longer than ``_LINE_BYTE_CAP`` (2000 chars) are
    #   truncated before rendering and before plain-text storage.

    DEFAULT_CSS = "StreamingToolBlock { height: auto; }"

    def __init__(self, label: str, tool_name: str | None = None, tool_input: "dict | None" = None,
                 is_first_in_turn: bool = False, tool_call_id: str | None = None,
                 **kwargs: Any) -> None:
        super().__init__(label=label, lines=[], plain_lines=[], tool_name=tool_name, **kwargs)
        self._stream_label = label
        self._tool_input = tool_input
        self._is_first_in_turn: bool = is_first_in_turn
        self._tool_call_id: str | None = tool_call_id
        self._pending: list[tuple[Text, str]] = []
        self._flush_retry: int = 0
        self._broken: bool = False
        self._all_plain: list[str] = []
        self._all_rich: list[Text] = []
        self._visible_start: int = 0
        self._visible_count: int = 0
        self._total_received: int = 0
        self._omission_bar_top: OmissionBar | None = None
        self._omission_bar_bottom: OmissionBar | None = None
        self._omission_bar_top_mounted: bool = False
        self._omission_bar_bottom_mounted: bool = False
        self._completed: bool = False
        self._is_unmounted: bool = False  # PERF-4: guard timer resurrection after unmount
        self._render_timer: "Timer | None" = None  # PERF-4: pre-init; on_mount overwrites with live handle
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
        # PG-3: streaming error line count; reset to 0 in complete()
        self._line_err_count: int = 0
        # LL-5: adoption flash — True on GENERATED entry, False on terminal states.
        self._was_generated: bool = False
        self._remove_adopted_timer: "Timer | None" = None
        # FS-3: settled state — arms 600ms after terminal phase; suppresses incidental flashes
        self._settled: bool = False
        self._settled_timer: "Timer | None" = None
        # LL-4: renderer kind override cycling
        self._kind_override: "RendererKind | None" = None
        # SK-1: skeleton row — single-use; never re-armed once dismissed.
        # Init in __init__ so _dismiss_skeleton()/complete() are safe on a
        # block whose on_mount never ran (unit tests).
        self._skeleton_widget: "Static | None" = None
        self._skeleton_timer: "Timer | None" = None
        self._skeleton_pulse_timer: "Timer | None" = None
        self._skeleton_dim: bool = True
        self._body._omission_parent_block = self

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._body
        yield self._tail

    def on_mount(self) -> None:
        self._header._has_affordances = False
        self._stream_started_at = time.monotonic()
        self._last_line_time = self._stream_started_at
        self._header._duration = "0.0s"
        self._render_timer = self._register_timer(self.set_interval(1 / 60, self._flush_pending))
        self._duration_timer = self._register_timer(self.set_interval(0.1, self._tick_duration))
        try:
            display_cfg = self.app.cfg.get("display", {})  # type: ignore[attr-defined]
            self._visible_cap: int = int(display_cfg.get("tool_visible_cap", _VISIBLE_CAP))
            self._line_byte_cap: int = int(display_cfg.get("tool_line_byte_cap", _LINE_BYTE_CAP))
        except Exception:  # noqa: bare-except
            self._visible_cap = _VISIBLE_CAP
            self._line_byte_cap = _LINE_BYTE_CAP
        try:
            self._microcopy_widget = self._body.query_one(".--microcopy", Static)
        except Exception:  # noqa: bare-except
            self._microcopy_widget = None
        try:
            self._cached_body_log = self._body.query_one(CopyableRichLog)
        except Exception:  # noqa: bare-except
            pass
        if self._omission_bar_top is not None:
            self._omission_bar_top.display = False
        if self._omission_bar_bottom is not None:
            self._omission_bar_bottom.display = False
        # Compose pre-mounts bars and sets _omission_bar_bottom_mounted = True.
        self._header._pulse_start()
        self._header._streaming_phase = True
        try:
            from hermes_cli.tui.tool_category import spec_for as _spec_for
            _spec = _spec_for(self._tool_name or "")
            _sec = _secondary_args_text(_spec.category, self._tool_input)
            if _sec:
                self._body.update_secondary_args(_sec)
                self._secondary_args_snapshot = _sec
        except Exception:  # noqa: bare-except
            pass
        if self._is_first_in_turn:
            try:
                panel = self.parent.parent
                if panel is not None:
                    panel.add_class("first-in-turn")
            except Exception:  # noqa: bare-except
                pass
        # SK-1: arm pre-first-chunk skeleton timer (100ms). Registered with
        # ManagedTimerMixin so unmount/_stop_all_managed cancel it.
        self._skeleton_timer = self._register_timer(
            self.set_timer(_SKELETON_DELAY_S, self._maybe_mount_skeleton)
        )

    # ------------------------------------------------------------------
    # Streaming API
    # ------------------------------------------------------------------

    _HTTP_STATUS_LINE_RE = re.compile(r'^HTTP/\S+\s+(\d+\s+.+)$')

    _MAX_HISTORY_LINES: int = 10_000
    _EVICT_CHUNK: int = 500

    def append_line(self, raw: str) -> None:
        if self._broken:
            logger.debug("dropping line on broken block (call_id=%s)", self._tool_call_id)
            return
        if self._completed:
            return
        # SK-1: first chunk dismisses the skeleton (covers <100ms and ≥100ms paths).
        if self._skeleton_widget is not None or self._skeleton_timer is not None:
            self._dismiss_skeleton()
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
            if self._render_timer is not None:
                self._render_timer.stop()
                self._render_timer = None
            if not self._is_unmounted:  # PERF-4: don't resurrect timer after unmount
                self._render_timer = self._register_timer(self.set_interval(1 / 60, self._flush_pending))
        # PG-3: notify ToolGroup ancestor for live error-count tracking
        from hermes_cli.tui.tool_group import ToolGroup as _TG
        self.post_message(_TG.StreamingLineAppended(plain))

    # ------------------------------------------------------------------
    # SK-1: pre-first-chunk skeleton row
    # ------------------------------------------------------------------

    def _maybe_mount_skeleton(self) -> None:
        self._skeleton_timer = None
        if (
            self._total_received > 0
            or self._completed
            or self._is_unmounted
            or not self.is_attached
        ):
            return
        icon = self._best_kind_icon()
        text = Text()
        text.append(f"{icon} ", style="dim")
        text.append(_SKELETON_GLYPH, style="dim")
        self._skeleton_widget = Static(
            text, classes="tool-skeleton tool-skeleton--dim"
        )
        # Anchor above ToolTail so the skeleton sits between body and tail.
        self.mount(self._skeleton_widget, before=self._tail)
        reduced_motion = getattr(getattr(self, "app", None), "_reduced_motion", False)
        if not reduced_motion:
            self._skeleton_pulse_timer = self._register_timer(
                self.set_interval(_SKELETON_PULSE_S, self._toggle_skeleton_pulse)
            )

    def _best_kind_icon(self) -> str:
        view = getattr(self, "_view", None)
        hint = getattr(view, "streaming_kind_hint", None) if view is not None else None
        if hint is not None:
            from hermes_cli.tui.tool_blocks._header import ToolHeader
            ToolHeader._build_kind_hint_maps()
            glyph = ToolHeader._KIND_HINT_ICON.get(hint)
            if glyph:
                return glyph
        header_icon = getattr(self._header, "_tool_icon", "") or ""
        if header_icon:
            return header_icon
        return "▸"

    def has_partial_visible_lines(self) -> bool:
        return self._visible_count < len(self._all_plain)

    def _toggle_skeleton_pulse(self) -> None:
        if self._skeleton_widget is None or not self._skeleton_widget.is_mounted:
            return
        self._skeleton_dim = not self._skeleton_dim
        if self._skeleton_dim:
            self._skeleton_widget.add_class("tool-skeleton--dim")
        else:
            self._skeleton_widget.remove_class("tool-skeleton--dim")

    def _dismiss_skeleton(self) -> None:
        # getattr defaults — tests construct partially-initialized blocks via __new__
        timer = getattr(self, "_skeleton_timer", None)
        if timer is not None:
            timer.stop()
            self._skeleton_timer = None
        pulse = getattr(self, "_skeleton_pulse_timer", None)
        if pulse is not None:
            pulse.stop()
            self._skeleton_pulse_timer = None
        widget = getattr(self, "_skeleton_widget", None)
        if widget is not None:
            if widget.is_mounted:
                widget.remove()
            self._skeleton_widget = None

    def inject_diff(self, diff_lines: list[str], header_stats: "ToolHeaderStats | None") -> None:
        for raw in diff_lines:
            self.append_line(raw)
        if header_stats is not None:
            self._header._stats = header_stats
        self._header.add_class("--diff-header")

    def on_unmount(self) -> None:
        self._is_unmounted = True  # PERF-4: block timer resurrection at both reassign sites
        if self._remove_adopted_timer is not None:
            self._remove_adopted_timer.stop()
        # FS-3: stop settled timer; not via ManagedTimerMixin (must survive complete())
        if self._settled_timer is not None:
            self._settled_timer.stop()
            self._settled_timer = None
        # LL-4: clear kind chip directly — post_message unavailable after message loop closes
        try:
            self.app.query_one(HintBar).clear_kind_override()
        except NoMatches:
            pass
        except Exception:
            logger.debug("clear_kind_override on unmount failed", exc_info=True)
        super().on_unmount()  # ManagedTimerMixin.on_unmount → _stop_all_managed

    def complete(self, duration: str, is_error: bool = False) -> None:
        if self._completed:
            return
        self._completed = True
        self._follow_tail = False
        self._line_err_count = 0  # PG-3: reset; on_tool_panel_completed reconciles group counter
        # SK-1: drop skeleton row before stopping timers — _stop_all_managed
        # only stops timers, doesn't unmount the widget.
        self._dismiss_skeleton()
        # L4: use mixin — marks entries stopped=True so on_unmount skips them (no double-stop)
        self._stop_all_managed()
        self._header._pulse_stop()
        self._header._streaming_phase = False
        self._header.set_error(is_error)
        self._flush_pending()
        self._tail.dismiss()
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
            self.add_class("--compact-success")
        if getattr(self, '_detected_cwd', None):
            from rich.text import Text as _RichText
            try:
                from hermes_cli.tui.widgets import CopyableRichLog as _CRL
                log = self._body.query_one(_CRL)
                log.write(_RichText(f"  cwd: {self._detected_cwd}", style="dim"))
            except Exception:  # noqa: bare-except
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
        except Exception:  # noqa: bare-except
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
            except Exception:  # noqa: bare-except
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
        except Exception:  # noqa: bare-except
            pass

        return mounted

    # ------------------------------------------------------------------
    # Internal timers
    # ------------------------------------------------------------------

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
        except Exception:  # noqa: bare-except
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
        except Exception:  # noqa: bare-except
            pass
        stalled = (
            not self._completed
            and self._last_line_time > 0.0
            and (time.monotonic() - self._last_line_time) > 5.0
        )
        # CL-4: freeze pulse when stalled; resume on next line (lags up to one tick ~100ms)
        if stalled and not self._header._pulse_paused:
            self._header._pulse_paused = True
        elif not stalled and self._header._pulse_paused:
            self._header._pulse_paused = False
        # SCT-1: route stall warning through SkinColors so theme overrides apply.
        try:
            from hermes_cli.tui.body_renderers._grammar import SkinColors
            colors = SkinColors.from_app(self.app) if self.app is not None else None
        except Exception:  # noqa: bare-except
            import logging as _logging
            _logging.getLogger(__name__).debug(
                "streaming microcopy: SkinColors.from_app failed", exc_info=True
            )
            colors = None
        text = microcopy_line(
            spec, state,
            reduced_motion=reduced_motion,
            shimmer_phase=self._shimmer_phase,
            stalled=stalled,
            colors=colors,
        )
        if text:
            self._body.set_microcopy(text)
            self._microcopy_shown = True

    def _flush_pending(self) -> None:
        if not self._flush_slow and not self._completed:
            now = time.monotonic()
            if now - self._last_line_time > 2.0:
                self._flush_slow = True
                if self._render_timer is not None:
                    self._render_timer.stop()
                    self._render_timer = None
                if not self._is_unmounted:  # PERF-4: don't resurrect timer after unmount
                    self._render_timer = self._register_timer(self.set_interval(1 / 10, self._flush_pending))

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
                self._flush_retry = 0
            except NoMatches:
                self._flush_retry += 1
                if self._flush_retry >= _FLUSH_MAX_RETRIES:
                    logger.exception(
                        "body log never appeared after %d retries; marking block broken",
                        self._flush_retry,
                    )
                    self._broken = True
                    self._pending.clear()
                    return
                # Body log not yet mounted — re-prepend batch and retry next tick.
                # Bounded by _FLUSH_MAX_RETRIES; loud log on exhaustion above.
                logger.debug(
                    "body log not mounted; retry %d/%d", self._flush_retry, _FLUSH_MAX_RETRIES
                )
                self._pending = batch + self._pending
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
            except Exception:  # noqa: bare-except
                scrolled_up = False
            if scrolled_up:
                new_total = self._tail._new_line_count + lines_written
                try:
                    self._tail.update_count(new_total)
                except Exception:  # noqa: bare-except
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
        if self._broken:
            return
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
        if self._broken:
            return
        try:
            log = self._body.query_one(CopyableRichLog)
        except NoMatches:
            return
        for rich_line, plain in zip(self._all_rich[start:end], self._all_plain[start:end]):
            log.write_with_source(rich_line, plain, link=_first_link(plain))
        self._visible_count += end - start
        self._refresh_omission_bars()

    def collapse_to(self, new_end: int) -> None:
        if self._broken:
            return
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
            except Exception:  # noqa: bare-except
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
    # LL-5: adoption state — GENERATED → STARTED flash + CSS class
    # ------------------------------------------------------------------

    def set_block_state(self, new_state: "Any") -> None:
        """Notify the block of a state transition for lifecycle legibility.

        Called by external service/code when the tool-call state changes.
        Handles LL-5 adoption flash and _was_generated tracking.
        """
        from hermes_cli.tui.services.tools import ToolCallState

        if new_state == ToolCallState.GENERATED:
            self._was_generated = True
            self._clear_settled()  # FS-3: retry path resets settled

        elif new_state == ToolCallState.STARTED:
            self._clear_settled()  # FS-3: retry path resets settled
            if self._was_generated:
                if self.is_attached:
                    self.post_message(FlashMessage("started", duration=1.2))
                try:
                    self.add_class("adopted")
                except Exception:
                    logger.warning("failed to add adopted class", exc_info=True)
                self._remove_adopted_timer = self.set_timer(0.6, self._remove_adopted)

        elif new_state in (ToolCallState.DONE, ToolCallState.ERROR, ToolCallState.CANCELLED):
            self._was_generated = False
            self._arm_settled_timer()  # FS-3: begin 600ms quiescence countdown

    def _remove_adopted(self) -> None:
        if self.is_attached:
            try:
                self.remove_class("adopted")
            except Exception:
                logger.warning("failed to remove adopted class", exc_info=True)
        self._remove_adopted_timer = None

    # ------------------------------------------------------------------
    # FS-3: settled state helpers
    # ------------------------------------------------------------------

    def _arm_settled_timer(self) -> None:
        """Start 600ms quiescence timer; replaces any in-flight timer.

        Clears _settled first — a retry/re-arm on an already-settled block must reset
        the flag so flashes fire again during the new quiescence window.
        Do NOT register via ManagedTimerMixin — complete() calls _stop_all_managed()
        which would cancel the settled timer before it fires.
        """
        self._settled = False
        self._cancel_settled_timer()
        self._settled_timer = self.set_timer(0.6, self._on_settled_timer)

    def _cancel_settled_timer(self) -> None:
        if self._settled_timer is not None:
            self._settled_timer.stop()
            self._settled_timer = None

    def _on_settled_timer(self) -> None:
        self._settled = True
        self._settled_timer = None

    def _clear_settled(self) -> None:
        """Reset settled on non-terminal transition (retry path)."""
        self._settled = False
        self._cancel_settled_timer()

    # ------------------------------------------------------------------
    # LL-4: renderer kind override cycling via `t` / `Shift+T`
    # ------------------------------------------------------------------

    def _do_cycle_kind(self) -> None:
        kinds = list(RendererKind)
        if self._kind_override is None:
            next_kind = kinds[0]
        else:
            idx = kinds.index(self._kind_override)
            next_kind = kinds[(idx + 1) % len(kinds)]
        self._kind_override = next_kind
        if self.is_attached:
            self.post_message(KindOverrideChanged(
                override=next_kind,
                cycle_callback=self._do_cycle_kind,
            ))

    def action_cycle_kind(self) -> None:
        self._do_cycle_kind()

    def action_kind_revert(self) -> None:
        if self._kind_override is None:
            if self.is_attached:
                self.post_message(FlashMessage("no override", duration=1.0))
            return
        self._kind_override = None
        auto_kind = self._auto_renderer_kind()
        if self.is_attached:
            self.post_message(KindOverrideChanged(override=None, cycle_callback=None))
            self.post_message(FlashMessage(f"kind: auto ({auto_kind.value.lower()})", duration=1.2))

    def _auto_renderer_kind(self) -> RendererKind:
        """Return the renderer kind the classifier would choose without an override."""
        try:
            from hermes_cli.tui.body_renderers import pick_renderer
            from hermes_cli.tui.services.tools import ToolCallState
            view = getattr(self, "_view", None)
            if view is not None and view.kind is not None:
                from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
                renderer_cls = pick_renderer(
                    view.kind,
                    view.args,  # type: ignore[arg-type]
                    phase=ToolCallState.DONE,
                    density=DensityTier.DEFAULT,
                )
                name = renderer_cls.__name__.lower()
                for rk in RendererKind:
                    if rk.value in name:
                        return rk
        except Exception:
            logger.debug("_auto_renderer_kind failed", exc_info=True)
        return RendererKind.PLAIN

    # ------------------------------------------------------------------
    # Override copy_content / refresh_skin
    # ------------------------------------------------------------------

    def copy_content(self) -> str:
        rendered = getattr(self, "_rendered_plain_text", "")
        if rendered:
            return rendered
        return "\n".join(self._all_plain)

    def replace_body_widget(self, widget, *, plain_text: str = "") -> None:
        # Regression guard: stop live timers before body replacement.
        # complete() already handles this in the normal completion flow.
        if not self._completed:
            # L4: use mixin — marks entries stopped=True so on_unmount skips them
            self._stop_all_managed()
        super().replace_body_widget(widget, plain_text=plain_text)

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
            except Exception:  # noqa: bare-except
                return
        styled = _T(text, style="dim")
        mc.update(styled)
        mc.add_class("--active")
        mc.remove_class("--secondary-args")
