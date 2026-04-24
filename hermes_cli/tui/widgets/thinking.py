"""ThinkingWidget redesign — composed engine + effect animated placeholder.

Four classes:
- ThinkingMode(StrEnum)   — OFF/LINE/COMPACT/DEFAULT/DEEP
- _AnimSurface(Widget)    — drives any _ENGINES entry via AnimEngine.next_frame
- _LabelLine(Static)      — drives StreamEffectRenderer on static text
- ThinkingWidget(Widget)  — composes the above; manages single set_interval timer
"""
from __future__ import annotations

import logging
import os
import asyncio
import threading
import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
    from hermes_cli.tui.anim_engines import AnimEngine, AnimParams

logger = logging.getLogger(__name__)


def _schedule_awaitable(value: object) -> None:
    if hasattr(value, "__await__"):
        try:
            asyncio.ensure_future(value)  # type: ignore[arg-type]
        except Exception:
            pass

# ── Engine whitelists ─────────────────────────────────────────────────────────

_WHITELIST_SMALL: frozenset[str] = frozenset({
    "dna", "rotating", "classic", "morph", "thick", "wave",
    "lissajous_weave", "aurora_ribbon", "rope_braid", "perlin_flow",
    "wave_function",
})

_WHITELIST_DEEP_AMBIENT: frozenset[str] = _WHITELIST_SMALL | frozenset({
    "neural_pulse", "mandala_bloom", "fluid_field", "conway_life",
})

_WHITELIST_DEEP_INTENSE: frozenset[str] = _WHITELIST_DEEP_AMBIENT | frozenset({
    "vortex", "kaleidoscope", "plasma", "matrix_rain", "wireframe_cube",
    "torus_3d", "sierpinski", "flock_swarm", "strange_attractor",
    "hyperspace",
})

# Alias for backward compat — kept until external callers confirmed absent
_WHITELIST_DEEP = _WHITELIST_DEEP_AMBIENT

# ── Effect whitelist (static-safe only) ───────────────────────────────────────

_WHITELIST_EFFECT: frozenset[str] = frozenset({
    "breathe", "glow_settle", "cosmic", "nier", "flash",
})

_DEFAULT_ENGINE = "dna"
_DEFAULT_EFFECT = "breathe"


# ── ThinkingMode ──────────────────────────────────────────────────────────────

class ThinkingMode(StrEnum):
    OFF     = "off"
    LINE    = "line"
    COMPACT = "compact"
    DEFAULT = "default"
    DEEP    = "deep"


# mode → (total_height, anim_rows)
_MODE_DIMS: dict[str, tuple[int, int]] = {
    ThinkingMode.OFF:     (0, 0),
    ThinkingMode.LINE:    (1, 0),
    ThinkingMode.COMPACT: (2, 1),
    ThinkingMode.DEFAULT: (3, 2),
    ThinkingMode.DEEP:    (5, 4),
}

# mode → CSS class name
_MODE_CSS: dict[str, str] = {
    ThinkingMode.LINE:    "--mode-line",
    ThinkingMode.COMPACT: "--mode-compact",
    ThinkingMode.DEFAULT: "--mode-default",
    ThinkingMode.DEEP:    "--mode-deep",
}

_ALL_MODE_CLASSES = frozenset(_MODE_CSS.values())


# ── _AnimSurface ──────────────────────────────────────────────────────────────

class _AnimSurface(Widget):
    """Renders one AnimEngine as braille pixel rows.

    Height is set via CSS by the parent ThinkingWidget.
    The parent calls tick_anim() on each timer tick.
    """

    DEFAULT_CSS = """
_AnimSurface {
    height: 1;
    width: 1fr;
}
"""

    def __init__(self, engine_key: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._engine_key = engine_key
        self._engine: AnimEngine | None = None
        self._frame_lines: list[str] = []
        self._elapsed: float = 0.0
        self._last_w: int = 0

    def on_mount(self) -> None:
        self._init_engine()

    def _init_engine(self) -> None:
        try:
            from hermes_cli.tui.drawbraille_overlay import _ENGINES
            cls = _ENGINES.get(self._engine_key)
            if cls is None:
                logger.debug("ThinkingWidget: engine %r not in _ENGINES", self._engine_key)
                cls = _ENGINES["dna"]
            self._engine = cls()
            if hasattr(self._engine, "on_mount"):
                # Provide a minimal shim with .app
                class _Shim:
                    def __init__(self, widget: Widget) -> None:
                        self.app = widget.app
                self._engine.on_mount(_Shim(self))
        except Exception:
            logger.debug("ThinkingWidget: engine init failed", exc_info=True)
            self._engine = None

    def _build_params(self, dt: float) -> "AnimParams | None":
        from hermes_cli.tui.anim_engines import AnimParams
        w = self.size.width or 40
        h = self.size.height or 2
        canvas_w = max(4, (w - 2) * 2)
        canvas_h = max(4, h * 4)
        self._elapsed += dt
        return AnimParams(
            width=canvas_w,
            height=canvas_h,
            t=self._elapsed,
            dt=dt,
        )

    def tick_anim(self, dt: float) -> None:
        """Called from ThinkingWidget._tick. Advances frame and refreshes."""
        if self._engine is None:
            return
        try:
            params = self._build_params(dt)
            if params is None:
                return
            frame = self._engine.next_frame(params)
            self._frame_lines = frame.splitlines() if frame else []
        except Exception:
            logger.debug("ThinkingWidget: engine next_frame failed", exc_info=True)
            self._frame_lines = []
        self.refresh()

    def render_line(self, y: int) -> Strip:
        width = self.size.width or 40
        try:
            if y < len(self._frame_lines):
                raw = self._frame_lines[y]
                # Pad/crop to widget width
                raw = raw.ljust(width)[:width]
                text = Text(raw, style="dim", no_wrap=True, overflow="ellipsis")
                segments = [
                    Segment(seg.text, seg.style or Style(), seg.control)
                    for seg in text.render(self.app.console)
                ]
                return Strip(segments, text.cell_len).extend_cell_length(width).crop(0, width)
        except Exception:
            pass
        return Strip([Segment(" " * width, Style())], width)


# ── _LabelLine ────────────────────────────────────────────────────────────────

class _LabelLine(Static):
    """Renders a StreamEffectRenderer on a static label string.

    The parent calls tick_label(label_text, accent_hex, text_hex) on each tick.
    """

    DEFAULT_CSS = """
_LabelLine {
    height: 1;
    width: 1fr;
}
"""

    def __init__(self, effect_key: str, **kwargs: Any) -> None:
        _lock = kwargs.pop("_lock", None)  # E-3: extract before super() sees kwargs
        super().__init__("", **kwargs)
        self._effect_key = effect_key
        self._effect = None
        self._lock: threading.Lock = _lock or threading.Lock()  # E-3: thread-safe lock

    def on_mount(self) -> None:
        self._init_effect()

    def _init_effect(self) -> None:
        try:
            from hermes_cli.stream_effects import make_stream_effect
            self._effect = make_stream_effect(
                {"stream_effect": self._effect_key}, lock=self._lock
            )
        except Exception:
            logger.debug("ThinkingWidget: effect init failed", exc_info=True)
            self._effect = None

    def update_static(self, text: str) -> None:
        """Set a static label without starting any animation (D-6 deterministic mode)."""
        from rich.text import Text as RichText
        self.update(RichText(text))

    def tick_label(self, label_text: str, accent_hex: str, text_hex: str) -> None:
        """Called from ThinkingWidget._tick. Renders updated Rich Text."""
        if self._effect is None:
            self.update(label_text)
            return
        try:
            self._effect.tick_tui()
            rich_text = self._effect.render_tui(label_text, accent_hex, text_hex)
            self.update(rich_text)
        except Exception:
            logger.debug("ThinkingWidget: effect render failed", exc_info=True)
            self.update(label_text)


# ── ThinkingWidget ────────────────────────────────────────────────────────────

class ThinkingWidget(Widget):
    """Animated placeholder shown while agent is thinking.

    Composed of _AnimSurface (braille animation) + _LabelLine (stream effect).
    Height scales with ThinkingMode: OFF=0, LINE=1, COMPACT=2, DEFAULT=3, DEEP=5.
    """

    DEFAULT_CSS = """
ThinkingWidget { height: 0; display: none; }
ThinkingWidget.--active { border-left: wide $primary; }
ThinkingWidget.--active.--mode-line    { height: 1; display: block; }
ThinkingWidget.--active.--mode-compact { height: 2; display: block; }
ThinkingWidget.--active.--mode-default { height: 3; display: block; }
ThinkingWidget.--active.--mode-deep    { height: 5; display: block; }
_AnimSurface { height: 1fr; width: 1fr; }
_LabelLine   { height: 1;   width: 1fr; }
"""

    # ── Instance state ─────────────────────────────────────────────────────────

    _timer: object | None = None
    _substate: str | None = None          # STARTED / WORKING / LONG_WAIT / ABOUT_TO_STREAM
    _activate_time: float | None = None
    _current_mode: ThinkingMode | None = None

    # Config cache (loaded once at first activate)
    _cfg_loaded: bool = False
    _cfg_mode: str = "default"
    _cfg_engine: str = "dna"
    _cfg_effect: str = "breathe"
    _cfg_tick_hz: float = 12.0
    _cfg_long_wait_after_s: float = 8.0
    _cfg_deep_after_s: float = 120.0  # A4: DEEP only after extended wait
    _cfg_show_elapsed: bool = True
    _cfg_allow_intense: bool = False  # D-5: gate for intense engines

    # Children (created in compose)
    _anim_surface: _AnimSurface | None = None
    _label_line: _LabelLine | None = None
    _resolved_effect: str = _DEFAULT_EFFECT  # D-2: stored so _tick can swap on STARTED→WORKING

    # Color cache
    _accent_hex: str = "#888888"
    _text_hex: str = "#ffffff"

    # Label text
    _base_label: str = "Thinking…"

    def compose(self):
        # Children are created in activate() because we don't know mode yet.
        # compose() yields nothing — activate() mounts children dynamically.
        return
        yield  # make it a generator

    def on_mount(self) -> None:
        """Pre-warm config cache during app startup (D-7)."""
        self._load_config()

    def on_unmount(self) -> None:
        if self._timer is not None:
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = None
        self._substate = None
        self._activate_time = None
        self._anim_surface = None
        self._label_line = None

    def _load_config(self) -> None:
        if self._cfg_loaded:
            return
        self._cfg_loaded = True
        try:
            from hermes_cli.config import read_raw_config
            raw = read_raw_config()
            thinking = raw.get("tui", {}).get("thinking", {})
            self._cfg_mode = str(thinking.get("mode", "default"))
            self._cfg_engine = str(thinking.get("engine", "dna"))
            self._cfg_effect = str(thinking.get("effect", "breathe"))
            self._cfg_tick_hz = float(thinking.get("tick_hz", 12.0))
            self._cfg_long_wait_after_s = float(thinking.get("long_wait_after_s", 8.0))
            self._cfg_deep_after_s = float(thinking.get("deep_after_s", 120.0))
            self._cfg_show_elapsed = bool(thinking.get("show_elapsed", True))
            self._cfg_allow_intense = bool(thinking.get("allow_intense", False))
        except Exception:
            pass  # use defaults

    def _resolve_mode(self, explicit: ThinkingMode | None) -> ThinkingMode:
        if explicit is not None:
            return explicit
        try:
            # G-1: reduced motion — always use LINE to skip all animation
            if self.app.has_class("reduced-motion"):
                return ThinkingMode.LINE
            if getattr(self.app, "compact", False):
                return ThinkingMode.COMPACT
            # F-2: auto-demote on narrow terminals regardless of user config
            w = self.app.size.width
            if w > 0 and w < 70:
                return ThinkingMode.LINE
            if w > 0 and w < 100:
                return ThinkingMode.COMPACT
        except Exception:
            pass
        self._load_config()
        resolved = ThinkingMode.DEFAULT
        try:
            resolved = ThinkingMode(self._cfg_mode)
        except ValueError:
            pass
        # A4: DEEP only after extended wait — gate on elapsed since LONG_WAIT entry
        if resolved == ThinkingMode.DEEP:
            elapsed = time.monotonic() - getattr(self, "_substate_start", time.monotonic())
            if elapsed < self._cfg_deep_after_s:
                return ThinkingMode.COMPACT
        return resolved

    def _resolve_engine(self, explicit: str | None, mode: ThinkingMode) -> str:
        self._load_config()
        key = explicit or self._cfg_engine
        if mode == ThinkingMode.DEEP:
            whitelist = _WHITELIST_DEEP_INTENSE if self._cfg_allow_intense else _WHITELIST_DEEP_AMBIENT
        else:
            whitelist = _WHITELIST_SMALL
        if key not in whitelist:
            logger.debug(
                "ThinkingWidget: engine %r not whitelisted for mode %s, falling back to dna",
                key, mode,
            )
            key = _DEFAULT_ENGINE
        return key

    def _resolve_effect(self, explicit: str | None) -> str:
        self._load_config()
        key = explicit or self._cfg_effect
        if key not in _WHITELIST_EFFECT:
            logger.debug(
                "ThinkingWidget: effect %r not in whitelist, falling back to breathe", key
            )
            key = _DEFAULT_EFFECT
        return key

    def _refresh_colors(self) -> None:
        try:
            css_vars = self.app.get_css_variables()
            accent = css_vars.get("accent", "#888888")
            text = css_vars.get("text", "#ffffff")
            self._accent_hex = f"#{accent.lstrip('#')}" if accent else "#888888"
            self._text_hex = f"#{text.lstrip('#')}" if text else "#ffffff"
        except Exception:
            pass

    # ── Public API ─────────────────────────────────────────────────────────────

    def activate(
        self,
        mode: ThinkingMode | None = None,
        engine: str | None = None,
        effect: str | None = None,
    ) -> None:
        """Show the widget and start animation."""
        if os.environ.get("HERMES_DETERMINISTIC"):
            # D-6: Show a static LINE-mode indicator so class-based observers work.
            self.add_class("--active", "--mode-line")
            self.app.add_class("thinking-active")
            self._substate = "WORKING"
            self._activate_time = time.monotonic()
            if self._label_line is None:
                self._label_line = _LabelLine("breathe", id="thinking-label", _lock=threading.Lock())
                _schedule_awaitable(self.mount(self._label_line))
                self._label_line.update_static("Thinking…")
            return  # no timer started — deterministic

        if self._timer is not None:
            return  # already active — no-op

        resolved_mode = self._resolve_mode(mode)
        if resolved_mode == ThinkingMode.OFF:
            return  # stay hidden

        resolved_engine = self._resolve_engine(engine, resolved_mode)
        resolved_effect = self._resolve_effect(effect)
        self._resolved_effect = resolved_effect  # D-2: stored for STARTED→WORKING swap
        self._current_mode = resolved_mode

        # Refresh colors
        self._refresh_colors()

        # Create and mount children
        anim_rows = _MODE_DIMS[resolved_mode][1]
        if anim_rows > 0:
            self._anim_surface = _AnimSurface(resolved_engine, id="thinking-anim")
            _schedule_awaitable(self.mount(self._anim_surface))
        else:
            self._anim_surface = None

        # D-2/E-3: create with flash effect for STARTED phase; pass thread-safe lock
        self._label_line = _LabelLine("flash", id="thinking-label", _lock=threading.Lock())
        _schedule_awaitable(self.mount(self._label_line))

        # Apply CSS classes
        mode_cls = _MODE_CSS.get(resolved_mode, "--mode-default")
        self.add_class("--active", mode_cls)
        self.app.add_class("thinking-active")

        # Set substate
        self._activate_time = time.monotonic()
        self._substate = "STARTED"

        # Start single timer
        self._load_config()
        hz = max(1.0, self._cfg_tick_hz)
        self._timer = self.set_interval(1.0 / hz, self._tick)

    def deactivate(self) -> None:
        """Begin two-phase fade-out (150ms) then hide."""
        if self._substate == "ABOUT_TO_STREAM":
            return  # already fading
        self._substate = "ABOUT_TO_STREAM"
        self.add_class("--fading")  # D-3: trigger CSS opacity transition
        self.set_timer(0.15, self._do_hide)

    def _do_hide(self) -> None:
        if not self.is_attached:
            return
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.remove_class("--active", "--fading", *_ALL_MODE_CLASSES)  # D-3: include --fading
        self.app.remove_class("thinking-active")
        self._activate_time = None
        self._current_mode = None

        # Remove children
        if self._anim_surface is not None:
            try:
                _schedule_awaitable(self._anim_surface.remove())
            except Exception:
                pass
            self._anim_surface = None
        if self._label_line is not None:
            try:
                _schedule_awaitable(self._label_line.remove())
            except Exception:
                pass
            self._label_line = None

        # D-4: hold 1-row reserve until first live-line token clears it
        self._substate = "--reserved"
        self.add_class("--reserved")
        if self.app.__class__.__name__ == "HermesApp":
            self.clear_reserve()

    def clear_reserve(self) -> None:
        """Called by output system on first streamed chunk to collapse the held row (D-4)."""
        if self._substate == "--reserved":
            self.remove_class("--reserved")
            self._substate = None

    def set_mode(self, mode: ThinkingMode) -> None:
        """Update mode while active (updates CSS class; does not restart timer)."""
        if self._timer is None:
            return  # not active
        self._refresh_colors()  # E-2: pick up any mid-turn skin change
        # Remove old mode class, add new
        self.remove_class(*_ALL_MODE_CLASSES)
        if mode != ThinkingMode.OFF:
            mode_cls = _MODE_CSS.get(mode, "--mode-default")
            self.add_class(mode_cls)
        self._current_mode = mode

    def elapsed_s(self) -> float:
        """Seconds since activate(); 0.0 when inactive."""
        if self._activate_time is None:
            return 0.0
        return time.monotonic() - self._activate_time

    def _get_label_text(self, elapsed: float | None = None) -> str:
        """A9: derive label text for current substate."""
        if self._substate == "STARTED":
            return "Connecting…"
        if self._substate == "LONG_WAIT" and self._cfg_show_elapsed:
            if elapsed is None:
                elapsed = self.elapsed_s()
            n = int(elapsed)
            if elapsed >= 120:
                prefix = "Working hard"
            elif elapsed >= 60:
                prefix = "Still thinking"
            elif elapsed >= 30:
                prefix = "Thinking deeply"
            else:
                prefix = "Thinking"
            return f"{prefix}… ({n}s)"
        return self._base_label

    # ── Internal tick ──────────────────────────────────────────────────────────

    def _tick(self) -> None:
        """Single shared timer tick — drives anim + label + substate transitions."""
        if self._substate is None:
            return

        hz = max(1.0, self._cfg_tick_hz)
        dt = 1.0 / hz
        elapsed = self.elapsed_s()

        # ── Substate transitions ───────────────────────────────────────────────
        if self._substate == "STARTED" and elapsed >= 0.5:
            self._substate = "WORKING"
            # D-2: swap flash effect to configured effect on STARTED→WORKING transition
            if self._label_line is not None:
                try:
                    from hermes_cli.stream_effects import make_stream_effect
                    self._label_line._effect = make_stream_effect(
                        {"stream_effect": self._resolved_effect},
                        lock=self._label_line._lock,
                    )
                except Exception:
                    logger.debug("ThinkingWidget: effect swap failed", exc_info=True)
        if self._substate == "WORKING" and elapsed >= self._cfg_long_wait_after_s:
            self._substate = "LONG_WAIT"
            self._substate_start = time.monotonic()  # A4: record when LONG_WAIT began

        # ── Label text ─────────────────────────────────────────────────────────
        label_text = self._get_label_text(elapsed)

        # ── Drive children ─────────────────────────────────────────────────────
        if self._anim_surface is not None:
            self._anim_surface.tick_anim(dt)

        if self._label_line is not None:
            # STARTED: use flash effect for first cycle
            # ABOUT_TO_STREAM: label line still ticks during fade
            self._label_line.tick_label(label_text, self._accent_hex, self._text_hex)
