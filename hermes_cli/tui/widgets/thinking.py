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
import re
import asyncio
import math
import random
import threading
import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.managed_timer_mixin import ManagedTimerMixin

if TYPE_CHECKING:
    from hermes_cli.tui.anim_engines import AnimEngine, AnimParams

logger = logging.getLogger(__name__)
_log = logger


def _schedule_awaitable(value: object) -> None:
    if hasattr(value, "__await__"):
        try:
            asyncio.ensure_future(value)  # type: ignore[arg-type]
        except Exception:
            pass  # ensure_future failed outside a running loop; awaitable dropped safely

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
    "breathe", "glow_settle", "cosmic", "nier", "flash", "shimmer",
})

_DEFAULT_ENGINE = "dna"
_DEFAULT_EFFECT = "breathe"

# ── Hex-color validation ───────────────────────────────────────────────────────

# 3- or 6-digit hex, optional leading "#". Anchored.
_HEX_COLOR_RE = re.compile(r"^#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

_DEFAULT_ACCENT_HEX = "#888888"
_DEFAULT_TEXT_HEX = "#ffffff"
_DEFAULT_SPINNER_DIM_HEX = "#4a4a4a"
_DEFAULT_SPINNER_PEAK_HEX = "#d8d8d8"


def _normalize_hex(value: str | None, default: str) -> str:
    """Return *value* normalized to ``#RRGGBB``; *default* if not a valid hex color."""
    if not value:
        return default
    if not _HEX_COLOR_RE.match(value):
        return default
    body = value.lstrip("#")
    if len(body) == 3:
        body = "".join(ch * 2 for ch in body)
    return f"#{body.lower()}"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    normalized = _normalize_hex(value, _DEFAULT_ACCENT_HEX)
    body = normalized.lstrip("#")
    return int(body[0:2], 16), int(body[2:4], 16), int(body[4:6], 16)


def _interpolate_rgb(
    dim_rgb: tuple[int, int, int],
    peak_rgb: tuple[int, int, int],
    factor: float,
) -> tuple[int, int, int]:
    clamped = max(0.0, min(1.0, factor))
    return tuple(
        int(round(dim + ((peak - dim) * clamped)))
        for dim, peak in zip(dim_rgb, peak_rgb)
    )


def _rgb_style(rgb: tuple[int, int, int]) -> Style:
    return Style(color=f"rgb({rgb[0]},{rgb[1]},{rgb[2]})", dim=True)


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
        self._accent_hex: str = "#888888"
        self._peak_hex: str = _DEFAULT_SPINNER_PEAK_HEX
        self._dim_rgb: tuple[int, int, int] = _hex_to_rgb(self._accent_hex)
        self._peak_rgb: tuple[int, int, int] = _hex_to_rgb(self._peak_hex)
        self._frame_tick: int = 0

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

    def swap_engine(self, engine_key: str) -> None:
        """Re-initialize engine in place; resets elapsed and clears frame buffer."""
        self._engine_key = engine_key
        self._elapsed = 0.0
        self._frame_lines = []
        self._init_engine()

    def tick_anim(
        self,
        dt: float,
        accent_hex: str = "#888888",
        peak_hex: str | None = None,
    ) -> None:
        """Called from ThinkingWidget._tick. Advances frame and refreshes."""
        self._accent_hex = accent_hex
        if peak_hex is None:
            peak_hex = getattr(self, "_peak_hex", _DEFAULT_SPINNER_PEAK_HEX)
        self._peak_hex = peak_hex
        self._dim_rgb = _hex_to_rgb(self._accent_hex)
        self._peak_rgb = _hex_to_rgb(self._peak_hex)
        self._frame_tick = getattr(self, "_frame_tick", 0) + 1
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
                if not raw.strip():
                    return Strip([Segment(" " * width, Style())], width)
                return self._render_gradient_line(raw, y)
        except Exception:
            # thinking content parse failed; widget shows empty content
            pass
        return Strip([Segment(" " * width, Style())], width)

    def _render_gradient_line(self, raw: str, row: int) -> Strip:
        width = len(raw)
        phase_base = (self._frame_tick * 0.75) + (row * 1.35)
        segments: list[Segment] = []
        for idx, ch in enumerate(raw):
            if ch == " ":
                segments.append(Segment(ch, Style(dim=True)))
                continue
            factor = (1.0 + math.sin((idx * 0.65) + phase_base)) / 2.0
            style = _rgb_style(_interpolate_rgb(self._dim_rgb, self._peak_rgb, factor))
            segments.append(Segment(ch, style))
        return Strip(segments, width)


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

class ThinkingWidget(ManagedTimerMixin, Widget):
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
    _reserve_fallback_timer: object | None = None  # A14: 2s safety clear for --reserved
    _effects_lock: "threading.Lock | None" = None  # H10: single lock reused across _LabelLine redraws

    # Config cache (loaded once at first activate)
    _cfg_loaded: bool = False
    _cfg_mode: str = "default"
    _cfg_engine: str | list[str] = "dna"
    _cfg_effect: str | list[str] = "breathe"
    _cfg_tick_hz: float = 12.0
    _cfg_long_wait_after_s: float = 8.0
    _cfg_deep_after_s: float = 120.0  # A4: DEEP only after extended wait
    _cfg_show_elapsed: bool = True
    _cfg_allow_intense: bool = False  # D-5: gate for intense engines
    _cfg_long_wait_engine: str | list[str] = "wave_function"
    _cfg_long_wait_effect: str | list[str] = "shimmer"
    _actual_tick_interval: float = 1.0 / 12.0

    # Children (created in compose)
    _anim_surface: _AnimSurface | None = None
    _resolved_engine: str = _DEFAULT_ENGINE
    _label_line: _LabelLine | None = None
    _resolved_effect: str = _DEFAULT_EFFECT  # D-2: stored so _tick can swap on STARTED→WORKING
    _short_engine_pool: tuple[str, ...] = (_DEFAULT_ENGINE,)
    _short_effect_pool: tuple[str, ...] = (_DEFAULT_EFFECT,)
    _long_wait_engine_pool: tuple[str, ...] = ("wave_function",)
    _long_wait_effect_pool: tuple[str, ...] = ("shimmer",)
    _resolved_long_wait_engine: str | None = None
    _resolved_long_wait_effect: str | None = None

    # Color cache
    _accent_hex: str = _DEFAULT_ACCENT_HEX
    _text_hex: str = _DEFAULT_TEXT_HEX
    _spinner_dim_hex: str = _DEFAULT_SPINNER_DIM_HEX
    _spinner_peak_hex: str = _DEFAULT_SPINNER_PEAK_HEX
    _spinner_dim_rgb: tuple[int, int, int] = _hex_to_rgb(_DEFAULT_SPINNER_DIM_HEX)
    _spinner_peak_rgb: tuple[int, int, int] = _hex_to_rgb(_DEFAULT_SPINNER_PEAK_HEX)

    # Label text
    _base_label: str = "Thinking…"

    # SS-2: stall tracking — updated by on_token_delta()
    _last_token_time: float | None = None

    def compose(self):
        # Children are created in activate() because we don't know mode yet.
        # compose() yields nothing — activate() mounts children dynamically.
        return
        yield  # make it a generator

    def render(self):
        """Return empty Text always.

        Why: during --reserved.--fading transition Textual may briefly invoke
        the default Widget.render() repr fallback before cascaded `display: none`
        resolves under a real PTY (R5-T-M1). ThinkingWidget itself never has
        visible content — all visuals come from _AnimSurface / _LabelLine children.
        """
        from rich.text import Text as RichText  # noqa: PLC0415
        return RichText("")

    def on_mount(self) -> None:
        """Pre-warm config cache during app startup (D-7)."""
        self._load_config()

    def on_unmount(self) -> None:
        self._substate = None
        self._activate_time = None
        self._anim_surface = None
        self._label_line = None
        super().on_unmount()  # ManagedTimerMixin.on_unmount → _stop_all_managed

    def _load_config(self) -> None:
        if self._cfg_loaded:
            return
        self._cfg_loaded = True
        try:
            from hermes_cli.config import read_raw_config
            raw = read_raw_config()
            thinking = raw.get("tui", {}).get("thinking", {})
            self._cfg_mode = str(thinking.get("mode", "default"))
            self._cfg_engine = thinking.get("engine", "dna")
            self._cfg_effect = thinking.get("effect", "breathe")
            self._cfg_tick_hz = float(thinking.get("tick_hz", 12.0))
            self._cfg_long_wait_after_s = float(thinking.get("long_wait_after_s", 8.0))
            self._cfg_deep_after_s = float(thinking.get("deep_after_s", 120.0))
            self._cfg_show_elapsed = bool(thinking.get("show_elapsed", True))
            self._cfg_allow_intense = bool(thinking.get("allow_intense", False))
            self._cfg_long_wait_engine = thinking.get("long_wait_engine", "wave_function")
            self._cfg_long_wait_effect = thinking.get("long_wait_effect", "shimmer")
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
            # streaming widget absent; thinking append skipped
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

    def _engine_whitelist(self, mode: ThinkingMode) -> frozenset[str]:
        if mode == ThinkingMode.DEEP:
            return _WHITELIST_DEEP_INTENSE if self._cfg_allow_intense else _WHITELIST_DEEP_AMBIENT
        return _WHITELIST_SMALL

    @staticmethod
    def _coerce_pool(raw_value: str | list[str] | tuple[str, ...] | None) -> list[str]:
        if isinstance(raw_value, str):
            return [raw_value]
        if isinstance(raw_value, (list, tuple)):
            return [item for item in raw_value if isinstance(item, str)]
        return []

    def _normalize_pool(
        self,
        raw_value: str | list[str] | tuple[str, ...] | None,
        *,
        whitelist: frozenset[str],
        default_key: str,
        field_name: str,
    ) -> tuple[str, ...]:
        values = self._coerce_pool(raw_value)
        dropped = [item for item in values if item not in whitelist]
        valid = tuple(item for item in values if item in whitelist)
        if dropped:
            logger.debug("ThinkingWidget: dropped invalid %s entries: %s", field_name, dropped)
        if valid:
            return valid
        logger.debug(
            "ThinkingWidget: %s had no valid entries, falling back to %s",
            field_name,
            default_key,
        )
        return (default_key,)

    def _normalize_engine_pool(
        self,
        raw_value: str | list[str] | tuple[str, ...] | None,
        mode: ThinkingMode,
        *,
        default_key: str,
        field_name: str,
    ) -> tuple[str, ...]:
        return self._normalize_pool(
            raw_value,
            whitelist=self._engine_whitelist(mode),
            default_key=default_key,
            field_name=field_name,
        )

    def _normalize_effect_pool(
        self,
        raw_value: str | list[str] | tuple[str, ...] | None,
        *,
        default_key: str,
        field_name: str,
    ) -> tuple[str, ...]:
        return self._normalize_pool(
            raw_value,
            whitelist=_WHITELIST_EFFECT,
            default_key=default_key,
            field_name=field_name,
        )

    def _resolve_engine(self, explicit: str | None, mode: ThinkingMode) -> str:
        self._load_config()
        return self._normalize_engine_pool(
            explicit,
            mode,
            default_key=_DEFAULT_ENGINE,
            field_name="engine",
        )[0]

    def _resolve_effect(self, explicit: str | None) -> str:
        self._load_config()
        return self._normalize_effect_pool(
            explicit,
            default_key=_DEFAULT_EFFECT,
            field_name="effect",
        )[0]

    def _refresh_colors(self) -> None:
        css_vars: dict[str, str] = {}
        try:
            css_vars = self.app.get_css_variables()
        except Exception:
            logger.warning("ThinkingWidget._refresh_colors: get_css_variables failed", exc_info=True)
            self._accent_hex = _DEFAULT_ACCENT_HEX
            self._text_hex = _DEFAULT_TEXT_HEX
            self._spinner_dim_hex = _DEFAULT_SPINNER_DIM_HEX
            self._spinner_peak_hex = _DEFAULT_SPINNER_PEAK_HEX
            self._spinner_dim_rgb = _hex_to_rgb(self._spinner_dim_hex)
            self._spinner_peak_rgb = _hex_to_rgb(self._spinner_peak_hex)
            return

        self._accent_hex = _normalize_hex(css_vars.get("accent"), _DEFAULT_ACCENT_HEX)
        self._text_hex = _normalize_hex(css_vars.get("text"), _DEFAULT_TEXT_HEX)
        self._spinner_dim_hex = _normalize_hex(
            css_vars.get("thinking-spinner-dim"),
            _DEFAULT_SPINNER_DIM_HEX,
        )
        self._spinner_peak_hex = _normalize_hex(
            css_vars.get("thinking-spinner-peak"),
            _DEFAULT_SPINNER_PEAK_HEX,
        )
        self._spinner_dim_rgb = _hex_to_rgb(self._spinner_dim_hex)
        self._spinner_peak_rgb = _hex_to_rgb(self._spinner_peak_hex)

    # ── Public API ─────────────────────────────────────────────────────────────

    def activate(
        self,
        mode: ThinkingMode | None = None,
        engine: str | None = None,
        effect: str | None = None,
    ) -> None:
        """Show the widget and start animation."""
        # Idempotent: if already active with a live timer, do nothing.
        if self._timer is not None and self.has_class("--active"):
            return

        if os.environ.get("HERMES_DETERMINISTIC"):
            # D-6: Show a static LINE-mode indicator so class-based observers work.
            self.add_class("--active", "--mode-line")
            self.app.add_class("thinking-active")
            self._substate = "WORKING"
            self._activate_time = time.monotonic()
            if self._label_line is None:
                if self._effects_lock is None:
                    self._effects_lock = threading.Lock()
                self._label_line = _LabelLine("breathe", _lock=self._effects_lock)
                _schedule_awaitable(self.mount(self._label_line))
                self._label_line.update_static("Thinking…")
            return  # no timer started — deterministic

        # M8: stop any orphaned timer from a prior activate-without-deactivate cycle
        self._stop_all_managed()
        self._timer = None

        resolved_mode = self._resolve_mode(mode)
        if resolved_mode == ThinkingMode.OFF:
            return  # stay hidden

        self._short_engine_pool = self._normalize_engine_pool(
            self._cfg_engine,
            resolved_mode,
            default_key=_DEFAULT_ENGINE,
            field_name="engine",
        )
        self._short_effect_pool = self._normalize_effect_pool(
            self._cfg_effect,
            default_key=_DEFAULT_EFFECT,
            field_name="effect",
        )
        self._long_wait_engine_pool = self._normalize_engine_pool(
            self._cfg_long_wait_engine,
            resolved_mode,
            default_key="wave_function",
            field_name="long_wait_engine",
        )
        self._long_wait_effect_pool = self._normalize_effect_pool(
            self._cfg_long_wait_effect,
            default_key="shimmer",
            field_name="long_wait_effect",
        )
        self._resolved_long_wait_engine = None
        self._resolved_long_wait_effect = None

        resolved_engine = (
            self._resolve_engine(engine, resolved_mode)
            if engine is not None
            else random.choice(self._short_engine_pool)
        )
        resolved_effect = (
            self._resolve_effect(effect)
            if effect is not None
            else random.choice(self._short_effect_pool)
        )
        self._resolved_engine = resolved_engine
        self._resolved_effect = resolved_effect  # D-2: stored for STARTED→WORKING swap
        self._current_mode = resolved_mode

        # Refresh colors
        self._refresh_colors()

        # Create and mount children
        anim_rows = _MODE_DIMS[resolved_mode][1]
        if anim_rows > 0:
            # No fixed id — avoids DuplicateIds when deactivate's 150ms fade-out
            # timer hasn't fired yet and activate() is called for the next turn.
            self._anim_surface = _AnimSurface(resolved_engine)
            _schedule_awaitable(self.mount(self._anim_surface))
        else:
            self._anim_surface = None

        # H10: allocate lock once per widget lifecycle, reuse for all _LabelLine redraws
        if self._effects_lock is None:
            self._effects_lock = threading.Lock()
        # D-2/E-3: create with flash effect for STARTED phase; pass shared thread-safe lock
        self._label_line = _LabelLine("flash", _lock=self._effects_lock)
        _schedule_awaitable(self.mount(self._label_line))

        # Apply CSS classes
        mode_cls = _MODE_CSS.get(resolved_mode, "--mode-default")
        self.add_class("--active", mode_cls)
        self.app.add_class("thinking-active")

        # Set substate
        self._activate_time = time.monotonic()
        self._substate = "STARTED"

        # Start single timer — registered through mixin so on_unmount stops it automatically
        self._load_config()
        hz = max(1.0, self._cfg_tick_hz) if anim_rows > 0 else 4.0
        interval = 1.0 / hz
        self._actual_tick_interval = interval
        self._timer = self._register_timer(self.set_interval(interval, self._tick))

    def deactivate(self) -> None:
        """Stop animation timer immediately; schedule 150ms visual fade-out."""
        # L9: stop managed timers synchronously so flush_live can proceed without
        # racing against a still-running animation tick.
        self._stop_all_managed()
        self._timer = None
        if self._substate == "ABOUT_TO_STREAM":
            return  # already fading
        self._substate = "ABOUT_TO_STREAM"
        self.add_class("--fading")  # D-3: trigger CSS opacity transition
        self.set_timer(0.15, self._do_hide)

    def _do_hide(self) -> None:
        if not self.is_attached:
            return
        # _stop_all_managed was already called in deactivate; _timer is None here.
        # Defensive: stop if somehow still set (e.g. double-deactivate race).
        if self._timer is not None:
            self._stop_all_managed()
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
                # scroll target unavailable; thinking display continues
                pass
            self._anim_surface = None
        if self._label_line is not None:
            try:
                _schedule_awaitable(self._label_line.remove())
            except Exception:
                # scroll target unavailable; thinking display continues
                pass
            self._label_line = None

        # D-4: hold 1-row reserve until first live-line token clears it (A14: 2s fallback)
        self._substate = "--reserved"
        self.add_class("--reserved")
        self._reserve_fallback_timer = self.set_timer(2.0, self._clear_reserve_fallback)

    def _clear_reserve_fallback(self) -> None:
        """A14: safety clear if no prose chunk fires within 2s of deactivate."""
        self._reserve_fallback_timer = None
        if self.has_class("--reserved"):
            self.clear_reserve()

    def clear_reserve(self) -> None:
        """Called by output system on first streamed chunk to collapse the held row (D-4)."""
        if self._reserve_fallback_timer is not None:
            try:
                self._reserve_fallback_timer.stop()
            except Exception:
                # widget absent during cleanup; skip gracefully
                pass
            self._reserve_fallback_timer = None
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

    def on_token_delta(self) -> None:
        """Called by the streaming path on each token arrival to reset stall timer."""
        self._last_token_time = time.monotonic()

    def _get_label_text(self, elapsed: float | None = None) -> str:
        """A9: derive label text for current substate."""
        from hermes_cli.tui.streaming_microcopy import STALL_THRESHOLD_S, _stall_markup
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
            elapsed_since_token = (
                time.monotonic() - self._last_token_time
                if self._last_token_time is not None
                else 0.0
            )
            stall_str = _stall_markup(elapsed_since_token >= STALL_THRESHOLD_S)
            return f"{prefix}… ({n}s){stall_str}"
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
            # TW-A — engine swap
            if self._anim_surface is not None:
                if self._resolved_long_wait_engine is None:
                    self._resolved_long_wait_engine = random.choice(self._long_wait_engine_pool)
                lw_engine = self._resolved_long_wait_engine
                if lw_engine != self._anim_surface._engine_key:
                    self._anim_surface.swap_engine(lw_engine)
            # TW-C — effect swap
            if self._label_line is not None:
                if self._resolved_long_wait_effect is None:
                    self._resolved_long_wait_effect = random.choice(self._long_wait_effect_pool)
                lw_effect = self._resolved_long_wait_effect
                try:
                    from hermes_cli.stream_effects import make_stream_effect
                    self._label_line._effect = make_stream_effect(
                        {"stream_effect": lw_effect},
                        lock=self._label_line._lock,
                    )
                except Exception:
                    logger.warning("ThinkingWidget: long_wait effect swap failed", exc_info=True)

        # ── Label text ─────────────────────────────────────────────────────────
        label_text = self._get_label_text(elapsed)

        # ── Drive children ─────────────────────────────────────────────────────
        if self._anim_surface is not None:
            self._anim_surface.tick_anim(
                dt,
                self._spinner_dim_hex or "#888888",
                self._spinner_peak_hex,
            )

        if self._label_line is not None:
            # STARTED: use flash effect for first cycle
            # ABOUT_TO_STREAM: label line still ticks during fade
            self._label_line.tick_label(label_text, self._accent_hex, self._text_hex)
