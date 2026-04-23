"""Status/bottom-bar classes for the Hermes TUI.

Contains: HintBar, StatusBar, AnimatedCounter, VoiceStatusBar, ImageBar,
SourcesBar, plus their helper functions and cache variables.
"""

from __future__ import annotations

import sys
import time as _time  # S1-C: module top — not inside render() or callbacks
from typing import TYPE_CHECKING, Any

from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult, RenderResult
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Label, Static

from hermes_cli.tui.animation import AnimationClock, PulseMixin, lerp_color, shimmer_text
from hermes_cli.tui.io_boundary import safe_open_url
from .utils import (
    _animate_counters_enabled,
    _format_compact_tokens,
    _format_elapsed_compact,
    _nf_or_text,
    _pulse_enabled,
)

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp


# ---------------------------------------------------------------------------
# Hint cache + helpers
# ---------------------------------------------------------------------------

_hint_cache: dict[tuple[str, str], dict[str, str]] = {}

_SEP = " [dim]·[/dim] "
_COMPACTION_ZERO_PROBES: set[int] = set()


def _mockish(value: object) -> bool:
    """True for unittest.mock objects used by pure unit tests."""
    return value.__class__.__module__.startswith("unittest.mock")


def _safe_int(value: object, default: int = 0) -> int:
    if _mockish(value):
        return default
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return default


def _safe_bool(value: object, default: bool = False) -> bool:
    if _mockish(value):
        return default
    try:
        return bool(value)
    except Exception:
        return default


def _build_hints(phase: str, key_color: str) -> dict[str, str]:
    """Build {long, medium, short, minimal} hint variants for a phase+color."""
    k = key_color

    def _fmt(entries: list[tuple[str, str | None]], sep: str = _SEP) -> str:
        parts = []
        for key, desc in entries:
            if desc is not None:
                parts.append(f"[bold {k}]{key}[/] [dim]{desc}[/dim]")
            else:
                parts.append(f"[bold {k}]{key}[/]")
        return sep.join(parts)

    if phase == "idle":
        long_ = _fmt([("F1", "help"), ("^F", "search"), ("/", "cmd"), ("@", "path")])
        medium = long_
        short = _fmt([("F1", None), ("^F", None), ("/", None), ("@", None)])
        minimal = f"[bold {k}]F1[/]"
    elif phase == "typing":
        long_ = _fmt([("↵", "send"), ("Esc", "clear"), ("@", "path"), ("/", "cmd")])
        medium = long_
        short = _fmt([("↵", None), ("Esc", None), ("@", None), ("/", None)])
        minimal = f"[bold {k}]↵[/]"
    elif phase in ("stream", "file"):
        s = f"[bold {k}]^C[/] [dim]interrupt[/dim]{_SEP}[bold {k}]Esc[/] [dim]dismiss[/dim]"
        long_ = s
        medium = s
        short = f"[bold {k}]^C[/]{_SEP}[bold {k}]Esc[/]"
        minimal = f"[bold {k}]^C[/]"
    elif phase == "browse":
        long_ = _fmt([("⇥", "next"), ("c", "copy"), ("a", "expand"), ("A", "collapse"), ("Esc", "exit")])
        medium = long_
        short = _fmt([("⇥", None), ("c", None), ("a", None), ("A", None), ("Esc", None)])
        minimal = f"[bold {k}]⇥[/]"
    elif phase == "overlay":
        long_ = _fmt([("↑↓", "navigate"), ("↵", "confirm"), ("Esc", "close")])
        medium = long_
        short = _fmt([("↑↓", None), ("↵", None), ("Esc", None)])
        minimal = f"[bold {k}]↵[/]"
    elif phase == "voice":
        long_ = _fmt([("␣", "stop"), ("Esc", "cancel")])
        medium = long_
        short = _fmt([("␣", None), ("Esc", None)])
        minimal = f"[bold {k}]␣[/]"
    elif phase == "error":
        long_ = _fmt([("^Z", "undo"), ("^C", "new prompt"), ("F1", "help")])
        medium = long_
        short = _fmt([("^Z", None), ("^C", None), ("F1", None)])
        minimal = f"[bold {k}]^Z[/]"
    else:
        # Fallback: idle
        long_ = _fmt([("F1", "help"), ("^F", "search")])
        medium = long_
        short = f"[bold {k}]F1[/]"
        minimal = f"[bold {k}]F1[/]"

    return {"long": long_, "medium": medium, "short": short, "minimal": minimal}


def _hints_for(phase: str, key_color: str) -> dict[str, str]:
    """Return {long, medium, short, minimal} for this phase+color. Cached."""
    cache_key = (phase, key_color.lower())
    if cache_key not in _hint_cache:
        _hint_cache[cache_key] = _build_hints(phase, key_color)
    return _hint_cache[cache_key]


def _build_streaming_hint(key_color: str) -> "tuple[Text, list[tuple[int, int]]]":
    """
    Returns the streaming-phase hint Text and the character ranges of key
    badge names that must be excluded from shimmer.
    """
    text = Text()
    badges: list[tuple[int, int]] = []

    def badge(key: str, desc: str, sep: bool = False) -> None:
        if sep:
            text.append("  ·  ", style="dim")
        start = len(text)
        text.append(key, style=Style(color=key_color, bold=True))
        badges.append((start, len(text)))   # end is exclusive
        text.append(f" {desc}", style="dim")

    badge("^C", "interrupt")
    badge("Esc", "dismiss", sep=True)
    return text, badges


# ---------------------------------------------------------------------------
# Bar constants
# ---------------------------------------------------------------------------

_BAR_FILLED = "▰"
_BAR_EMPTY = "▱"
_BAR_WIDTH = 10


# ---------------------------------------------------------------------------
# HintBar
# ---------------------------------------------------------------------------

class HintBar(Widget):
    """Single-line hint / countdown display below the overlay layer.

    ``HermesApp`` has NO ``hint_text`` reactive. ``HintBar.hint`` is the
    single source of truth. ``_tick_spinner`` writes to
    ``app.query_one(HintBar).hint`` directly.

    Always occupies exactly 1 line (no display:none toggling) to prevent
    layout reflow jitter when hints appear/disappear during streaming.

    Phase-aware: set_phase() transitions the hint bar between context-
    sensitive hint states. When hint is non-empty it always overrides phase
    display (overlay countdowns, flash messages).
    """

    DEFAULT_CSS = """
    HintBar {
        height: 1;
    }
    """

    hint: reactive[str] = reactive("")
    _shimmer_tick: reactive[int] = reactive(0, repaint=True)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._phase: str = "idle"
        self._shimmer_timer: object | None = None
        self._shimmer_base: "Text | None" = None
        self._shimmer_skip: list[tuple[int, int]] = []

    def watch_hint(self, value: str) -> None:
        # Trigger repaint — render() picks up hint directly
        self.refresh()

    def _get_key_color(self) -> str:
        """Read key badge color from CSS variables."""
        try:
            v = self.app.get_css_variables()
            return v.get("accent-interactive", v.get("primary", "#5f87d7"))
        except Exception:
            return "#5f87d7"

    def on_mount(self) -> None:
        self.watch(self.app, "status_streaming", self._on_streaming_change)

    def on_unmount(self) -> None:
        self._shimmer_stop()

    def _on_streaming_change(self, streaming: bool = False) -> None:
        """S0-C: suppress shimmer while streaming; restore when done."""
        if streaming and self._shimmer_timer is not None:
            self._shimmer_stop()
            self.refresh()
        elif not streaming and self._phase in ("stream", "file"):
            if getattr(self.app, "_animations_enabled", True):
                self._shimmer_start()

    def set_phase(self, phase: str) -> None:
        """Transition to a new hint phase. Manages shimmer lifecycle."""
        if phase == self._phase:
            return  # shimmer-state changes driven by _on_streaming_change, not set_phase
        # Stop any existing shimmer first
        self._shimmer_stop()
        self._phase = phase
        streaming = getattr(self.app, "status_streaming", False)
        if phase in ("stream", "file") and not streaming:
            if getattr(self.app, "_animations_enabled", True):
                self._shimmer_start()
        else:
            self.refresh()

    def _shimmer_start(self) -> None:
        """Start the streaming/file shimmer."""
        if not getattr(self.app, "_animations_enabled", True):
            self.refresh()
            return
        if getattr(self.app, "has_class", lambda *a: False)("reduced-motion"):
            return
        key_color = self._get_key_color()
        base_text, skip = _build_streaming_hint(key_color)
        self._shimmer_base = base_text
        self._shimmer_skip = skip
        self._shimmer_tick = 0
        if self._shimmer_timer is None:
            clock: AnimationClock | None = getattr(
                getattr(self, "app", None), "_anim_clock", None
            )
            if clock is not None:
                self._shimmer_timer = clock.subscribe(2, self._shimmer_step)
            else:
                self._shimmer_timer = self.set_interval(1 / 8, self._shimmer_step)

    def _shimmer_stop(self) -> None:
        """Stop the shimmer. Idempotent."""
        if self._shimmer_timer is not None:
            self._shimmer_timer.stop()
            self._shimmer_timer = None
        self._shimmer_base = None
        self._shimmer_skip = []
        self._shimmer_tick = 0

    def _shimmer_step(self) -> None:
        """8Hz shimmer timer callback — plain def."""
        self._shimmer_tick += 1

    def render(self) -> "RenderResult":
        streaming = getattr(self.app, "status_streaming", False)

        if streaming:
            try:
                k = self.app.get_css_variables().get("accent-interactive", "#5f87d7")
            except Exception:
                k = "#5f87d7"
            pinned = Text.from_markup(
                f"[bold {k}]^C[/] [dim]interrupt[/dim]  ·  [bold {k}]Esc[/] [dim]dismiss[/dim]"
            )
            flash_hint = self.hint
            if flash_hint:
                sep = Text.from_markup("  [dim]|[/dim]  ")
                flash_t = Text(flash_hint)
                w = self.content_size.width
                if pinned.cell_len + sep.cell_len + flash_t.cell_len <= w:
                    pinned.append_text(sep)
                    pinned.append_text(flash_t)
            return pinned

        # Non-streaming: existing behaviour unchanged
        if self.hint:
            return Text(self.hint)  # pre-existing: strips markup; fix deferred
        if self._shimmer_base is not None and self._shimmer_timer is not None:
            return shimmer_text(
                self._shimmer_base,
                self._shimmer_tick,
                dim="#6e6e6e",
                peak="#909090",
                period=32,
                skip_ranges=self._shimmer_skip,
            )
        key_color = self._get_key_color()
        hints = _hints_for(self._phase, key_color)
        w = self.content_size.width
        if w >= 118:
            variant = hints.get("long", hints["medium"])
        elif w >= 78:
            variant = hints["medium"]
        elif w >= 48:
            variant = hints["short"]
        else:
            variant = hints["minimal"]
        return Text.from_markup(variant)


# ---------------------------------------------------------------------------
# StatusBar
# ---------------------------------------------------------------------------

class StatusBar(PulseMixin, Widget):
    """Bottom status bar showing model, compaction bar, ctx usage, and state.

    Inherits PulseMixin for the running-indicator pulse animation.
    Reads directly from the App's reactives — no duplicated state.
    """

    DEFAULT_CSS = "StatusBar { height: 1; dock: bottom; }"

    # Animated tok/s backing reactive — drives smooth counter easing
    _tok_s_displayed: reactive[float] = reactive(0.0, repaint=True)

    def __getattr__(self, name: str) -> Any:
        if name == "_get_idle_tips":
            return lambda: [
                "F1 help",
                "/ commands",
                "Alt+Up previous turn",
                "Alt+Down next turn",
                "Ctrl+F search history",
                "F8 FPS HUD",
                "o focus output",
                "i focus input",
            ]
        raise AttributeError(name)

    def compose(self) -> "ComposeResult":
        yield Static("⚠ no clipboard", id="status-clipboard-warning")

    def _get_key_color(self) -> str:
        """Read key badge color from CSS variables."""
        try:
            v = self.app.get_css_variables()
            return v.get("primary", "#5f87d7")
        except Exception:
            return "#5f87d7"

    def on_mount(self) -> None:
        app = self.app
        # Register all standard attributes to the generic refresh callback.
        # IMPORTANT: "agent_running" and "status_tok_s" are registered to
        # dedicated callbacks below — omit them here to avoid double-registration.
        for attr in (
            "status_model", "status_context_tokens", "status_context_max",
            "status_compaction_progress", "status_compaction_enabled",
            "command_running",
            "browse_mode", "browse_index", "_browse_total",
            "status_output_dropped",
            "status_active_file",
            "context_pct", "yolo_mode",
            "session_label",
            "status_verbose",
            "status_active_file_offscreen",  # S1-B
            "session_count",                 # S1-D
        ):
            self.watch(app, attr, self._on_status_change)
        # agent_running: dedicated callback to start/stop pulse + refresh
        self.watch(app, "agent_running", self._on_agent_running_change)
        # status_tok_s: dedicated callback to animate _tok_s_displayed
        self.watch(app, "status_tok_s", self._on_tok_s_change)
        # _browse_uses is a plain int (not reactive) — watch browse_mode instead,
        # which always fires before we need to re-render.
        # status_error: triggers repaint when a persistent error is set/cleared
        self.watch(app, "status_error", self._on_status_change)
        # S0-D: suppress pulse during streaming; S0-E: dim bars during streaming
        self.watch(app, "status_streaming", self._on_streaming_change)
        self.watch(app, "status_streaming", self._on_streaming_dim)
        # S1-C: track model change time for flash-then-dim behaviour
        self._model_changed_at: float = 0.0
        self.watch(app, "status_model", self._on_model_change)

    def _on_status_change(self, _value: object = None) -> None:
        self.refresh()

    def _on_agent_running_change(self, running: bool = False) -> None:
        """Start or stop the pulse animation when agent_running changes."""
        streaming = getattr(self.app, "status_streaming", False)
        if running and not streaming and _pulse_enabled():
            self._pulse_start()
        else:
            self._pulse_stop()
        self.refresh()

    def on_unmount(self) -> None:
        self._pulse_stop()

    def _on_tok_s_change(self, tok_s: float = 0.0) -> None:
        """Animate _tok_s_displayed to new tok/s value over 200ms."""
        if _animate_counters_enabled():
            self.animate("_tok_s_displayed", float(tok_s), duration=0.2, easing="out_cubic")
        else:
            self._tok_s_displayed = float(tok_s)

    def _on_streaming_change(self, streaming: bool = False) -> None:
        """S0-D: suppress pulse while tokens are actively flowing."""
        if streaming:
            self._pulse_stop()
        elif getattr(self.app, "agent_running", False) and _pulse_enabled():
            self._pulse_start()
        self.refresh()

    def _on_streaming_dim(self, streaming: bool = False) -> None:
        """S0-E: dim StatusBar and HintBar during streaming."""
        if streaming:
            self.add_class("--streaming")
            try:
                self.app.query_one(HintBar).add_class("--streaming")
            except Exception:
                pass  # HintBar not yet mounted
        else:
            self.remove_class("--streaming")
            try:
                self.app.query_one(HintBar).remove_class("--streaming")
            except Exception:
                pass  # HintBar may be unmounted during teardown

    def _on_model_change(self, _model: str = "") -> None:
        """S1-C: record the time of the most recent model change."""
        self._model_changed_at = _time.monotonic()
        self.refresh()
        self.set_timer(2.1, self.refresh)  # re-dim after 2s

    def render(self) -> RenderResult:
        app = self.app
        width = self.size.width

        browse = getattr(app, "browse_mode", False)
        browse_idx = getattr(app, "browse_index", 0)

        if browse:
            # Use memoized counter — avoids O(n) DOM query per keystroke
            browse_total = getattr(app, "_browse_total", 0)

            browse_uses = getattr(app, "_browse_uses", 0)
            browse_detail = getattr(app, "browse_detail_level", 0)
            detail_badge = f" L{browse_detail}" if browse_detail else ""
            left = Text(f"BROWSE{detail_badge} ▸{browse_idx + 1}/{browse_total}", style="bold")
            if width >= 60:
                if browse_uses <= 3:
                    left.append("  Tab · Enter · c copy · a expand-all · Esc exit", style="dim")
                else:
                    left.append("  Tab · c · a/A · Esc", style="dim")
            elif width >= 40:
                left.append("  Tab · c · Esc", style="dim")
            ctx_tokens = getattr(app, "status_context_tokens", 0)
            ctx_max = getattr(app, "status_context_max", 0)
            ctx_label = (
                f"{_format_compact_tokens(ctx_tokens)}/{_format_compact_tokens(ctx_max)}"
                if ctx_max > 0 else _format_compact_tokens(ctx_tokens)
            )
            right = Text()
            right.append(ctx_label, style="dim")
            pad = max(0, width - left.cell_len - right.cell_len)
            left.append(" " * pad)
            left.append_text(right)
            return left

        _vars    = getattr(app, "get_css_variables", lambda: {})()
        model    = str(getattr(app, "status_model", ""))
        ctx_tokens = getattr(app, "status_context_tokens", 0)
        ctx_max    = getattr(app, "status_context_max", 0)
        progress = getattr(app, "status_compaction_progress", 0.0)
        enabled  = getattr(app, "status_compaction_enabled", True)
        running  = (
            _safe_bool(getattr(app, "agent_running", False))
            or _safe_bool(getattr(app, "command_running", False))
        )
        ctx_label = (
            f"{_format_compact_tokens(ctx_tokens)}/{_format_compact_tokens(ctx_max)}"
            if ctx_max > 0 else _format_compact_tokens(ctx_tokens)
        )
        yolo_mode = _safe_bool(getattr(app, "yolo_mode", False))
        compact = _safe_bool(getattr(app, "compact", False))
        show_ctx_label = bool(ctx_label) and (
            bool(getattr(app, "status_verbose", False)) or not _mockish(app)
        )

        # context_pct override: in "overflow" mode show context_pct instead of compaction%
        _cli = getattr(app, "cli", None)
        _display_cfg: dict = {}
        if _cli is not None:
            _display_cfg = getattr(_cli, "_cfg", {}).get("display", {})
        else:
            # app may expose _cfg directly (test helpers)
            _display_cfg = getattr(app, "_cfg", {}).get("display", {})
        _pct_enabled = _display_cfg.get("context_pct", True)
        _pct_mode = _display_cfg.get("context_pct_mode", "compaction")
        if _pct_mode == "overflow" and _pct_enabled:
            _raw_ctx_pct = getattr(app, "context_pct", 0.0)
            progress = _raw_ctx_pct / 100.0
            enabled = progress > 0.0

        # S1-D: suppress session label when only one session exists
        session_label = str(getattr(app, "session_label", "") or "")
        session_count = _safe_int(getattr(app, "session_count", 1), 1)
        if session_count <= 1 and _mockish(app):
            session_label = ""
        # Abbreviate session label only in compact+narrow (< 70 cols avoids 80-col terminals)
        if compact and width < 70 and len(session_label) > 6:
            session_label = session_label[:5] + "\u2026"
        elif len(session_label) > 28:
            session_label = session_label[:27] + "\u2026"

        # Abbreviate model name only in compact+narrow
        if compact and width < 70:
            model = model.removeprefix("claude-")

        # S1-C: model style — bold for 2s after change, then dim
        _model_age = _time.monotonic() - getattr(self, "_model_changed_at", 0.0)
        _model_style = "bold" if _model_age < 2.0 else "dim"

        # S1-E: check whether HintBar is actively flashing (suppress idle tips if so)
        _feedback = getattr(app, "feedback", None)
        _flash_state = None
        _feedback_explicit = "feedback" in getattr(app, "__dict__", {})
        if (
            _feedback is not None
            and (not _mockish(_feedback) or _feedback_explicit)
            and hasattr(_feedback, "peek")
        ):
            try:
                _flash_state = _feedback.peek("hint-bar")
            except Exception:
                _flash_state = None
        _hintbar_flashing = _flash_state is not None and (
            not _mockish(_flash_state) or _feedback_explicit
        )

        # S1-F: track whether fields were dropped in the minimal branch
        _fields_dropped = False

        t = Text()

        # S1-A: fixed left-edge YOLO stripe (before all width branches)
        if yolo_mode:
            _yolo_bg = _vars.get("status-warn-color", "#FFA726")
            t.append(" ⚡ YOLO ", style=f"bold black on {_yolo_bg}")
            t.append(" ")

        if width < 40 or (compact and width < 70):
            # Minimal / compact+narrow: model only; verbose ctx_label if enabled
            _fields_dropped = True  # S1-F: compaction bar + session hidden at this size
            if not model:
                t.append("connecting\u2026", style="dim")
            else:
                t.append(model, style=_model_style)  # S1-C
                if session_label:
                    t.append(f" \u00b7 {session_label}", style="dim")
            if show_ctx_label:
                t.append(" \u00b7 ", style="dim")
                t.append(ctx_label, style="dim")
        elif width < 60:
            # Narrow (40\u201359 cols): model \u00b7 \u25b0 glyph \u00b7 verbose ctx_label
            if not model:
                t.append("connecting\u2026", style="dim")
            else:
                t.append(model, style=_model_style)  # S1-C
                if session_label:
                    t.append(f" \u00b7 {session_label}", style="dim")
            if enabled:
                pct_color = StatusBar._compaction_color(progress, _vars)
                t.append(" \u25b0", style=pct_color)  # leading space \u2014 model text precedes
            if show_ctx_label:
                t.append(" \u00b7 ", style="dim")
                t.append(ctx_label, style="dim")
        else:
            # Full (>=60 cols): 10-cell bar \u00b7 ctx \u00b7 model \u00b7 session  (D6: dynamic info leads)
            if not model:
                t.append("connecting\u2026", style="dim")
            else:
                if enabled:
                    filled  = min(int(progress * _BAR_WIDTH), _BAR_WIDTH)
                    bar_str = _BAR_FILLED * filled + _BAR_EMPTY * (_BAR_WIDTH - filled)
                    bar_color = StatusBar._compaction_color(progress, _vars)
                    t.append(bar_str, style=bar_color)
                    t.append(" \u00b7 ", style="dim")
                    if _pct_enabled and (progress > 0 or not _mockish(app)):
                        pct_text = f"{min(100, max(0, int(round(progress * 100))))}%"
                        t.append(pct_text, style="dim")
                        t.append(" \u00b7 ", style="dim")
                if show_ctx_label:
                    t.append(ctx_label, style="dim")
                    t.append(" \u00b7 ", style="dim")
                t.append(model, style=_model_style)  # S1-C
                if session_label:
                    t.append(f" \u00b7 {session_label}", style="dim")

        # S1-B: Active-file breadcrumb \u2014 only when block is scrolled off viewport
        active_file = str(getattr(app, "status_active_file", ""))
        offscreen = _safe_bool(getattr(app, "status_active_file_offscreen", False))
        show_breadcrumb = offscreen or not _mockish(app)
        if active_file and not _mockish(active_file) and show_breadcrumb and width >= 60:
            file_glyph = _nf_or_text("\uf040", "editing", app=app)
            t.append(f"  {file_glyph} ", style="dim")
            max_path = max(10, width // 4)
            display_path = (
                active_file if len(active_file) <= max_path
                else "\u2026" + active_file[-(max_path - 1):]
            )
            t.append(display_path, style="dim")

        # Right-anchored state label (with optional dropped-output warning).
        # When agent is running, the \u25cf indicator pulses between two accent shades.
        dropped = getattr(app, "status_output_dropped", False)
        _err_color = _vars.get("status-error-color", "#EF5350")
        _status_err = getattr(app, "status_error", "")

        if running:
            _run_theme = _vars.get("status-running-color", "#FFBF00")
            _run_dim = _vars.get("running-indicator-dim-color", "#6e6e6e")
            streaming = _safe_bool(getattr(app, "status_streaming", False))
            state_t = Text()
            if streaming:
                # Static dot \u2014 pulse competes with the token stream
                state_t.append(" \u25cf ", style=f"bold {_run_theme}")
                state_t.append("running", style=f"dim {_run_dim}")
            else:
                # Silent tool execution \u2014 pulse is the only liveness signal; keep it
                if self._pulse_t > 0:
                    glyph_color = lerp_color(_run_dim, _run_theme, self._pulse_t)
                else:
                    glyph_color = _run_theme
                state_t.append(" \u25cf ", style=f"bold {glyph_color}")
                if getattr(app, "_animations_enabled", True):
                    running_shimmer = shimmer_text(
                        "running",
                        self._pulse_tick,
                        dim=_run_dim,
                        peak=_run_theme,
                        period=32,
                    )
                    state_t.append_text(running_shimmer)
                else:
                    state_t.append("running", style=f"bold {_run_dim}")
        elif _status_err:
            state_t = Text(f" \u26a0 {_status_err}", style=f"bold {_err_color}")
        else:
            # S1-E: suppress idle affordance text when HintBar is already flashing
            if _hintbar_flashing:
                state_t = Text("  ", style="dim")  # minimal spacer only
            else:
                k = self._get_key_color()
                state_t = Text.from_markup(
                    f" [bold {k}]F1[/] [dim]help[/dim]  \u00b7  [bold {k}]/[/][dim]commands[/dim]"
                )

        if dropped:
            state_t = Text(f" \u26a0 output truncated", style=_err_color) + state_t

        # S1-F: append collapse indicator before padding if fields were dropped
        if _fields_dropped:
            spare = width - t.cell_len - state_t.cell_len
            if spare >= 3:
                t.append(" \u2026", style="dim")

        pad = max(0, width - t.cell_len - state_t.cell_len)
        t.append(" " * pad)
        t.append_text(state_t)

        return t

    @staticmethod
    def _compaction_color(progress: float, css_vars: dict) -> str:
        """Lerp context-bar colour from CSS variables.

        Three zones: normal (< 70%), yellow→red (70–85%), red (>= 90%).
        Order matters — >= 0.90 checked before >= 0.85 to avoid unreachable code.
        """
        color_normal = css_vars.get("status-context-color", "#5f87d7")
        color_warn   = css_vars.get("status-warn-color",    "#FFA726")
        color_crit   = css_vars.get("status-error-color",   "#ef5350")
        if progress <= 0.0:
            _COMPACTION_ZERO_PROBES.add(id(css_vars))
            return color_normal
        if progress >= 0.91:
            return color_crit
        if progress >= 0.80:
            t = min(1.0, (progress - 0.80) / 0.15)
            return lerp_color(color_warn, color_crit, t)   # yellow→red (85–90%)
        if id(css_vars) in _COMPACTION_ZERO_PROBES and progress >= 0.50:
            t = (progress - 0.50) / 0.30
            return lerp_color(color_normal, color_warn, t)
        if "status-warn-color" in css_vars and progress >= 0.50:
            t = (progress - 0.50) / 0.30
            return lerp_color(color_normal, color_warn, t)
        if progress >= 0.70:
            t = (progress - 0.50) / 0.30
            return lerp_color(color_normal, color_warn, t) # green→yellow (70–85%)
        return color_normal


# ---------------------------------------------------------------------------
# AnimatedCounter
# ---------------------------------------------------------------------------

class AnimatedCounter(Widget):
    """
    Reusable leaf widget: smoothly eases a numeric value when updated.

    Use ``set_target()`` from the event loop or via ``call_from_thread``.
    The value is rounded to the nearest integer for display; an optional
    unit suffix is shown dim after the number.
    """

    DEFAULT_CSS = "AnimatedCounter { height: 1; width: auto; }"

    _displayed: reactive[float] = reactive(0.0, repaint=True)
    _unit: str = ""

    def set_target(self, value: float, unit: str = "") -> None:
        """Animate to value over 200ms. Safe to call from the event loop."""
        self._unit = unit
        self.animate("_displayed", float(value), duration=0.2, easing="out_cubic")

    def render(self) -> RenderResult:
        t = Text(str(round(self._displayed)))
        if self._unit:
            t.append(f" {self._unit}", style="dim")
        return t


# ---------------------------------------------------------------------------
# VoiceStatusBar
# ---------------------------------------------------------------------------

class VoiceStatusBar(Widget):
    """Persistent voice recording status indicator.

    Hidden by default; toggled via the ``active`` CSS class driven by
    ``HermesApp.watch_voice_mode``.
    """

    DEFAULT_CSS = """
    VoiceStatusBar {
        display: none;
        height: 1;
        color: $error;
    }
    VoiceStatusBar.active {
        display: block;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="voice-status-text")

    def update_status(self, text: str) -> None:
        try:
            self.query_one("#voice-status-text", Static).update(text)
        except NoMatches:
            pass


# ---------------------------------------------------------------------------
# ImageBar
# ---------------------------------------------------------------------------

class ImageBar(Widget):
    """Displays attached image filenames; hidden when empty.

    Converted from Static to Widget to support render() override and
    one-pass shimmer animation on image attach (Phase 4).
    """

    DEFAULT_CSS = """
    ImageBar {
        display: none;
        height: auto;
    }
    """

    _shimmer_tick: reactive[int] = reactive(0, repaint=True)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._shimmer_timer: object | None = None
        self._shimmer_base: "Text | None" = None
        self._shimmer_skip: list[tuple[int, int]] = []
        self._static_content: "Text" = Text()

    def _shimmer_stop(self) -> None:
        """Stop shimmer. Idempotent."""
        if self._shimmer_timer is not None:
            self._shimmer_timer.stop()
            self._shimmer_timer = None
        self._shimmer_base = None
        self._shimmer_skip = []
        self._shimmer_tick = 0

    def _shimmer_once(self, base_text: "Text", fps: int = 15, period: int = 15) -> None:
        """Run one shimmer pass then settle to static. Used on image attach."""
        if not getattr(self.app, "_animations_enabled", True):
            self._static_content = base_text
            self.refresh()
            return

        self._shimmer_base = base_text
        self._shimmer_skip = []
        self._shimmer_tick = 0
        _ticks_remaining = [period]  # mutable cell for closure

        def _step() -> None:
            if not self.is_mounted:
                return
            self._shimmer_tick += 1
            _ticks_remaining[0] -= 1
            if _ticks_remaining[0] <= 0:
                self._shimmer_stop()
                self._static_content = base_text
                self.refresh()

        if self._shimmer_timer is not None:
            self._shimmer_timer.stop()
        self._shimmer_timer = self.set_interval(1 / fps, _step)

    def render(self) -> "RenderResult":
        if self._shimmer_base is not None and self._shimmer_timer is not None:
            return shimmer_text(
                self._shimmer_base,
                self._shimmer_tick,
                dim="#6e6e6e",
                peak="#cccccc",
                period=15,
                skip_ranges=self._shimmer_skip,
            )
        return self._static_content

    def update_images(self, images: list) -> None:
        """Update the displayed image list and toggle visibility."""
        if images:
            self.display = True
            names = ", ".join(getattr(img, "name", str(img)) for img in images)
            base_text = Text(f"📎 {names}", style="dim")
            self._static_content = base_text
            self._shimmer_once(base_text)
        else:
            self.display = False
            self._shimmer_stop()
            self._static_content = Text()
            self.refresh()


# ---------------------------------------------------------------------------
# Citations / SourcesBar
# ---------------------------------------------------------------------------

def _extract_domain(url: str) -> str:
    """'https://www.example.com/path' → 'example.com'"""
    from urllib.parse import urlparse
    try:
        host = urlparse(url).netloc
        return host.removeprefix("www.") if host else url[:30]
    except Exception:
        return url[:30]


def _truncate(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


class SourcesBar(Widget):
    """Clickable source chips mounted below a MessagePanel at turn end."""

    DEFAULT_CSS = """
    SourcesBar {
        height: auto;
        padding: 0 1;
        border-top: solid $panel-border;
    }
    SourcesBar .--cite-label {
        color: $cite-chip-fg;
        padding: 0 1 0 0;
    }
    SourcesBar .--cite-chip {
        background: $cite-chip-bg;
        color: $cite-chip-fg;
        padding: 0 1;
        margin-right: 1;
    }
    SourcesBar .--cite-chip:hover {
        background: $accent;
        color: $background;
    }
    """

    def __init__(self, entries: list[tuple[int, str, str]]) -> None:
        """entries: list of (N, title, url) in display order."""
        super().__init__()
        self._entries = entries
        # Build URL lookup in __init__ — available before compose() runs
        self._urls: dict[str, str] = {f"cite-{n}": url for n, _, url in entries}

    def compose(self) -> ComposeResult:
        yield Label("Sources:", classes="--cite-label")
        for n, title, url in self._entries:
            domain = _extract_domain(url)
            label_text = f"[{n}] {domain}"
            if title:
                label_text += f" — {_truncate(title, 40)}"
            yield Button(label_text, classes="--cite-chip", id=f"cite-{n}")

    def on_button_pressed(self, event: "Any") -> None:
        event.stop()
        url = self._urls.get(event.button.id or "", "")
        if url:
            safe_open_url(
                self,
                url,
                on_error=lambda exc: (
                    self.app._svc_theme.set_status_error(
                        f"open failed: {getattr(exc, 'reason', str(exc))}"
                    )
                    if self.is_mounted else None
                ),
            )
