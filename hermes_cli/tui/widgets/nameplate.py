"""AssistantNameplate and associated private helpers."""
from __future__ import annotations

import enum
import logging
import math
import random as _random
import time
from dataclasses import dataclass
from typing import Any

from rich.style import Style
from rich.text import Text
from textual.widget import Widget

_log = logging.getLogger(__name__)
_LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level color constants
# ---------------------------------------------------------------------------

_NP_POOL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*"
_NP_DECRYPT_COLOR = Style.parse("bold #00ff41")
_NP_IDLE_COLOR = Style.parse("#888888")
_NP_ACTIVE_COLOR = Style.parse("bold #7b68ee")
_NP_ERROR_COLOR = Style.parse("bold red")
_NP_DIM_COLOR = Style.parse("dim #888888")


def _lerp_hex(a: str, b: str, t: float) -> str:
    """Interpolate between two #rrggbb hex colors."""
    a, b = a.lstrip("#"), b.lstrip("#")
    ra, ga, ba_ = int(a[0:2], 16), int(a[2:4], 16), int(a[4:6], 16)
    rb, gb, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
    return "#{:02x}{:02x}{:02x}".format(
        int(ra + (rb - ra) * t),
        int(ga + (gb - ga) * t),
        int(ba_ + (bb - ba_) * t),
    )


@dataclass
class _NPChar:
    target: str
    current: str
    locked: bool
    lock_at: float
    style: Style


class _NPState(enum.Enum):
    STARTUP = "startup"
    IDLE = "idle"
    MORPH_TO_ACTIVE = "morph_to_active"
    ACTIVE_IDLE = "active_idle"
    GLITCH = "glitch"
    MORPH_TO_IDLE = "morph_to_idle"
    ERROR_FLASH = "error_flash"


class _NPIdleBeat(enum.Enum):
    NONE    = "none"
    PULSE   = "pulse"
    SHIMMER = "shimmer"
    DECRYPT = "decrypt"


class AssistantNameplate(Widget):
    """Animated assistant name above the input bar."""

    _MORPH_TICKS: int = 8  # ≈267 ms at 30 fps; controls active/idle morph speed only

    DEFAULT_CSS = """
    AssistantNameplate {
        height: 1;
        width: 1fr;
        padding: 0 1;
        background: transparent;
    }
    """

    def __init__(
        self,
        name: str = "Hermes",
        effects_enabled: bool = True,
        idle_effect: str = "auto",
        idle_beat_min_s: float = 30.0,
        idle_beat_max_s: float = 60.0,
        morph_speed: float = 1.0,
        glitch_enabled: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._target_name = name
        self._active_label = "● thinking"
        self._state = _NPState.STARTUP
        self._frame: list[_NPChar] = []
        self._tick = 0
        self._startup_t0 = 0.0  # wall-clock start of decrypt animation
        self._timer = None
        self._effects_enabled = effects_enabled
        if idle_effect == "breathe":
            idle_effect = "pulse"
        self._idle_effect_name = idle_effect
        self._cfg_idle_effect = idle_effect  # A6: alias for tests/config inspection
        self._idle_beat_min_s: float = idle_beat_min_s
        self._idle_beat_max_s: float = max(idle_beat_max_s, idle_beat_min_s + 1.0)
        self._idle_beat_timer = None
        self._idle_beat_tick: int = 0
        self._idle_beat_type: _NPIdleBeat = _NPIdleBeat.NONE
        self._beat_decrypt_frame: list[_NPChar] = []
        self._morph_speed = morph_speed
        self._glitch_enabled = glitch_enabled
        self._glitch_frame = 0
        self._glitch_from_idle = False  # True when glitch was triggered from IDLE state
        self._error_frame = 0
        self._last_was_error = False
        self._error_color_hex: str = "#ef5350"
        self._accent_hex = "#7b68ee"
        self._linked_rule: "Any | None" = None
        self._active_dim_hex = "#3d3480"
        self._text_hex = "#cccccc"
        self._decrypt_style: Style = _NP_DECRYPT_COLOR
        self._morph_dim_style: Style = _NP_DIM_COLOR
        # C-5/C-2: derived in on_mount; fallbacks point to module constants until then
        self._active_style: Style = _NP_ACTIVE_COLOR
        self._idle_color_hex: str = "#888888"
        self._active_phase: float = 0.0
        # C-2/C-5: theme-derived colors (updated in on_mount; fallbacks match constants)
        self._active_style: Style = _NP_ACTIVE_COLOR
        self._idle_color_hex: str = "#888888"
        # morph state
        self._morph_src = ""
        self._morph_dst = ""
        self._morph_dissolve: list[int] = []  # ticks remaining per position
        self._canvas_width: int = 80
        self._last_nameplate_w: int = 0
        # minimum animation duration gate (toolcall must animate >= 5s)
        self._MIN_ANIM_S: float = 5.0
        self._anim_min_end: float = 0.0  # monotonic deadline; 0 = no gate
        self._pending_idle: bool = False

    def _resolve_accent_hex(self, css_vars: dict, tier: "str | None" = None) -> str:
        """Resolve accent in priority order: tier_accents → nameplate-active-color → default."""
        if tier:
            tier_key = f"nameplate-tier-{tier}-accent"
            if tier_key in css_vars:
                return css_vars[tier_key]
            tier_accents_raw = css_vars.get("tier_accents", {})
            if isinstance(tier_accents_raw, dict) and tier in tier_accents_raw:
                return tier_accents_raw[tier]
        return css_vars.get("nameplate-active-color", "#7b68ee")

    def _derive_skin_colors(self, css_vars: dict, tier: "str | None" = None) -> None:
        """Recompute all skin-derived color fields from *css_vars*. Safe to call post-mount."""
        self._accent_hex = self._resolve_accent_hex(css_vars, tier)
        self._text_hex = css_vars.get("foreground", "#cccccc")
        self._active_dim_hex = _lerp_hex("#000000", self._accent_hex, 0.30)
        self._active_style = Style.parse(f"bold {self._accent_hex}")
        self._idle_color_hex = _lerp_hex(self._text_hex, self._accent_hex, 0.25)
        self._error_color_hex = css_vars.get("status-error-color", "#ef5350")
        decrypt_hex = css_vars.get("nameplate-decrypt-color", "#00ff41")
        self._decrypt_style = Style.parse(f"bold {decrypt_hex}")
        morph_dim_hex = _lerp_hex(self._text_hex, "#000000", 0.72)
        self._morph_dim_style = Style.parse(morph_dim_hex)

    def refresh_skin_colors(self) -> None:
        """Re-derive all animation colors from the current skin. Called on skin hotswap."""
        try:
            css_vars = self.app.get_css_variables()
            tier = getattr(self.app, "active_tier", None)
            self._derive_skin_colors(css_vars, tier)
            self.refresh()
        except Exception:
            _log.warning("AssistantNameplate.refresh_skin_colors: skin var resolve failed", exc_info=True)
            # Fall through to _DEFAULT_TIER_HEX

    def on_mount(self) -> None:
        try:
            css_vars = self.app.get_css_variables()
            _tier = getattr(self.app, "active_tier", None)
            self._derive_skin_colors(css_vars, _tier)
        except Exception:
            _log.warning("AssistantNameplate.on_mount: skin var resolve failed", exc_info=True)
            # Fall through to _DEFAULT_TIER_HEX — re-derive from whatever _accent_hex/_text_hex already hold
            self._active_style = Style.parse(f"bold {self._accent_hex}")
            self._idle_color_hex = _lerp_hex(self._text_hex, self._accent_hex, 0.25)
        if not self._effects_enabled:
            return  # effects disabled — skip animation/timer setup
        if self.styles.display == "none":
            _log.debug("nameplate on_mount: skipped (display:none)")
            return  # hidden — skip animation setup; widget is paint-ready if display is later restored
        _log.debug("nameplate on_mount: starting decrypt animation for %r", self._target_name)
        self._init_decrypt()
        self._timer = self.set_interval(1 / 30, self._advance)
        # A2: watch status_phase to pause/resume pulse
        try:
            self.watch(self.app, "status_phase", self._on_phase_change)
        except Exception:
            pass
        # A3-1: register error hooks (independent of _effects_enabled)
        try:
            self.app.hooks.register("on_error_set",   self._on_error_set,   owner=self, priority=100, name="nameplate_error_set")
            self.app.hooks.register("on_error_clear", self._on_error_clear, owner=self, priority=100, name="nameplate_error_clear")
        except Exception:
            # best-effort UI update; widget may not be mounted
            pass

    def set_tier(self, tier: "str | None") -> None:
        """Update the active tier and recompute accent color. Triggers a repaint."""
        try:
            css_vars = self.app.get_css_variables()
            self._derive_skin_colors(css_vars, tier)
            self.refresh()
        except Exception:
            _log.warning("AssistantNameplate.set_tier: skin var resolve failed", exc_info=True)
            # Fall through to _DEFAULT_TIER_HEX

    def on_unmount(self) -> None:
        self._stop_all_idle_timers()
        try:
            self.app.hooks.unregister_owner(self)
        except Exception:
            # best-effort UI update; widget may not be mounted
            pass

    def on_resize(self, event: Any) -> None:
        new_w = getattr(getattr(event, "size", None), "width", self._canvas_width)
        from hermes_cli.tui.resize_utils import HYSTERESIS
        if abs(new_w - self._canvas_width) > HYSTERESIS * 2:
            self._canvas_width = new_w
            self.refresh()  # C-6: repaint after canvas-width change
        self._last_nameplate_w = new_w

    # --- public API ---

    def link_to_rule(self, rule: "Any") -> None:
        """Drive *rule*.refresh() from this nameplate's animation timer."""
        self._linked_rule = rule

    def set_name(self, new_name: str) -> None:
        """Live-update the displayed agent name. Morphs from old name to new."""
        if new_name == self._target_name:
            return
        old = self._target_name
        self._target_name = new_name
        if self._state in (_NPState.IDLE, _NPState.STARTUP):
            self._state = _NPState.MORPH_TO_IDLE
            self._init_morph(old, new_name)
            self._set_timer_rate(30)
        elif self._state == _NPState.MORPH_TO_IDLE:
            self._init_morph(self._morph_src, new_name)

    def transition_to_active(self, label: str = "● thinking") -> None:
        _log.debug(
            "nameplate transition_to_active: prev_state=%s label=%r",
            self._state.value, label,
        )
        self._active_label = label
        if self._state == _NPState.MORPH_TO_IDLE:
            self._snap_to_idle()
        self._state = _NPState.MORPH_TO_ACTIVE
        self._init_morph(self._target_name, self._active_label)
        self._set_timer_rate(30)
        self._anim_min_end = time.monotonic() + self._MIN_ANIM_S

    def transition_to_idle(self) -> None:
        _log.debug(
            "nameplate transition_to_idle: prev_state=%s",
            self._state.value,
        )
        if self._last_was_error:
            self._last_was_error = False
            self._state = _NPState.ERROR_FLASH
            self._error_frame = 0
            self._set_timer_rate(30)
            return
        # Already idle — no morph needed; avoids phantom "● thinking" flash when
        # transition_to_active was never called (nameplate stays at name during agent runs).
        if self._state == _NPState.IDLE:
            return
        # gate: don't end animation before minimum duration elapsed
        remaining = self._anim_min_end - time.monotonic()
        if remaining > 0:
            self._pending_idle = True
            self._set_timer_rate(30)
            return
        self._pending_idle = False
        if self._state == _NPState.MORPH_TO_ACTIVE:
            self._snap_to_active()
        self._state = _NPState.MORPH_TO_IDLE
        self._init_morph(self._active_label, self._target_name)
        self._set_timer_rate(30)

    def glitch(self) -> None:
        if self._state != _NPState.ACTIVE_IDLE or not self._glitch_enabled:
            return
        self._glitch_from_idle = False
        self._state = _NPState.GLITCH
        self._glitch_frame = 0
        self._set_timer_rate(30)
        self._anim_min_end = time.monotonic() + self._MIN_ANIM_S

    def glitch_idle(self) -> None:
        """Glitch from IDLE state — corrupts chars in decrypt-green then restores to idle style."""
        if not self._glitch_enabled:
            return
        if self._state not in (_NPState.IDLE, _NPState.ACTIVE_IDLE):
            return
        if self._state == _NPState.IDLE:
            if not self._frame:
                self._init_frame_for(self._target_name, active_style=False)
            self._stop_all_idle_timers()
            self._glitch_from_idle = True
        else:
            self._glitch_from_idle = False
        self._state = _NPState.GLITCH
        self._glitch_frame = 0
        self._set_timer_rate(30)
        self._anim_min_end = time.monotonic() + self._MIN_ANIM_S

    def trigger_event_beat(self, beat: "_NPIdleBeat") -> None:
        """Immediately start an idle beat animation.

        No-op if not in IDLE state or a beat is already running — natural
        throttle for events (e.g. rapid tool calls) that fire frequently.
        """
        if not self._effects_enabled:
            return
        if self._state != _NPState.IDLE or self._idle_beat_type != _NPIdleBeat.NONE:
            return
        if self._idle_beat_timer is not None:
            self._idle_beat_timer.stop()
            self._idle_beat_timer = None
        self._idle_beat_tick = 0
        self._idle_beat_type = beat
        self._init_beat(beat)
        self._set_timer_rate(30)

    def set_active_label(self, label: str) -> None:
        self._active_label = label
        if self._state == _NPState.ACTIVE_IDLE:
            self._init_frame_for(label, active_style=True)

    def mark_error(self) -> None:
        self._last_was_error = True

    # --- render ---

    def render(self) -> Text:
        if not self._effects_enabled:
            return Text(self._target_name)
        if self._state == _NPState.IDLE:
            if self._idle_beat_type != _NPIdleBeat.NONE:
                return self._render_idle_beat(self._idle_beat_type, self._idle_beat_tick)
            return Text(self._target_name, style=Style.parse(self._idle_color_hex))
        if self._state == _NPState.ACTIVE_IDLE:
            return self._render_active_pulse()
        if self._state == _NPState.ERROR_FLASH:
            return Text(self._target_name, style=Style.parse(f"bold {self._error_color_hex}"))
        t = Text()
        for ch in self._frame:
            t.append(ch.current, style=ch.style)
        return t

    def _render_active_pulse(self) -> Text:
        """Traveling sine-wave shimmer in active color while agent is thinking."""
        t = Text()
        n = max(3, len(self._frame))
        offset = math.pi / n  # spans exactly π across name regardless of length
        for i, ch in enumerate(self._frame):
            wave = (math.sin(self._active_phase - i * offset) + 1.0) / 2.0
            color = _lerp_hex(self._active_dim_hex, self._accent_hex, wave)
            t.append(ch.target, style=Style.parse(f"bold {color}"))
        return t

    # --- advance ---

    def _advance(self) -> None:
        self._tick += 1
        # fire pending idle if minimum anim duration has elapsed
        if self._pending_idle and time.monotonic() >= self._anim_min_end:
            self._pending_idle = False
            if self._state == _NPState.MORPH_TO_ACTIVE:
                self._snap_to_active()
            self._state = _NPState.MORPH_TO_IDLE
            self._init_morph(self._active_label, self._target_name)
            # stay at 30fps
        if self._state == _NPState.STARTUP:
            self._tick_startup()
        elif self._state == _NPState.IDLE:
            self._tick_idle()
        elif self._state in (_NPState.MORPH_TO_ACTIVE, _NPState.MORPH_TO_IDLE):
            self._tick_morph()
        elif self._state == _NPState.ACTIVE_IDLE:
            self._tick_active_idle()
        elif self._state == _NPState.GLITCH:
            self._tick_glitch()
        elif self._state == _NPState.ERROR_FLASH:
            self._tick_error_flash()
        self.refresh()
        if self._linked_rule is not None:
            try:
                self._linked_rule.refresh()
            except Exception:
                # best-effort turn-boundary cleanup; widget may be absent
                pass

    def _tick_startup(self) -> None:
        now = time.monotonic()
        elapsed = now - self._startup_t0
        all_locked = True
        newly_locked = 0
        for ch in self._frame:
            if ch.locked:
                continue
            if now >= ch.lock_at:
                ch.current = ch.target
                ch.locked = True
                ch.style = Style.parse(self._idle_color_hex)
                newly_locked += 1
            else:
                ch.current = _random.choice(_NP_POOL)
                ch.style = self._decrypt_style
                all_locked = False
        if newly_locked:
            locked_count = sum(1 for c in self._frame if c.locked)
            _log.debug(
                "nameplate decrypt tick: elapsed=%.3fs newly_locked=%d total=%d/%d",
                elapsed, newly_locked, locked_count, len(self._frame),
            )
        if all_locked and self._frame:
            _log.debug("nameplate decrypt DONE: total_elapsed=%.3fs", elapsed)
            self._state = _NPState.IDLE
            self._enter_idle_timer()

    def _tick_idle(self) -> None:
        if self._idle_beat_type == _NPIdleBeat.NONE:
            return
        self._idle_beat_tick += 1
        done = self._tick_idle_beat(self._idle_beat_type, self._idle_beat_tick)
        if done:
            self._idle_beat_type = _NPIdleBeat.NONE
            self._stop_timer()
            self._schedule_next_beat()

    def _tick_active_idle(self) -> None:
        try:
            if self.app.has_class("reduced-motion"):
                return  # static nameplate in reduced-motion mode
        except Exception:
            pass
        self._active_phase += 0.11  # ~1.9 s full cycle @ 30 fps

    def _tick_morph(self) -> None:
        dst_style = self._active_style if self._state == _NPState.MORPH_TO_ACTIVE else Style.parse(self._idle_color_hex)
        done = True
        for i, ch in enumerate(self._frame):
            if ch.locked:
                continue
            self._morph_dissolve[i] -= 1
            if self._morph_dissolve[i] <= 0:
                ch.current = ch.target
                ch.locked = True
                ch.style = dst_style
            else:
                ch.current = _random.choice(_NP_POOL)
                ch.style = self._morph_dim_style
                done = False
        if done:
            if self._state == _NPState.MORPH_TO_ACTIVE:
                self._state = _NPState.ACTIVE_IDLE
                self._active_phase = 0.0
                self._set_timer_rate(30)
            else:
                self._state = _NPState.IDLE
                self._enter_idle_timer()

    def _tick_glitch(self) -> None:
        self._glitch_frame += 1
        restore_style = Style.parse(self._idle_color_hex) if self._glitch_from_idle else self._active_style
        if self._glitch_frame <= 2:
            # corrupt 1-3 random positions
            for _ in range(_random.randint(1, min(3, len(self._frame)))):
                idx = _random.randrange(len(self._frame))
                self._frame[idx].current = _random.choice(_NP_POOL)
                self._frame[idx].style = self._decrypt_style
        elif self._glitch_frame == 3:
            # partial restore
            for ch in self._frame:
                ch.current = ch.target
                ch.style = restore_style
        else:
            # fully clean; return to appropriate idle state
            for ch in self._frame:
                ch.current = ch.target
                ch.style = restore_style
            self._active_phase = 0.0  # C-4: reset so wave restarts cleanly from glitch
            if self._glitch_from_idle:
                self._glitch_from_idle = False
                self._state = _NPState.IDLE
                self._enter_idle_timer()
            else:
                self._state = _NPState.ACTIVE_IDLE
                self._set_timer_rate(30)

    def _tick_error_flash(self) -> None:
        self._error_frame += 1
        if self._error_frame >= 3:
            # transition directly to MORPH_TO_IDLE without re-entering transition_to_idle
            self._state = _NPState.MORPH_TO_IDLE
            self._init_morph(self._active_label, self._target_name)
            # timer stays at 30fps

    # --- helpers ---

    _DECRYPT_DURATION_S = 5.0  # wall-clock seconds — startup splash only
    _MORPH_TICKS = 8      # ~267ms @ 30fps — active/idle transitions
    _BEAT_PULSE_TICKS    = 30
    _BEAT_SHIMMER_TICKS  = 30
    _BEAT_DECRYPT_TICKS  = 30   # defined for symmetry; not used as completion gate — see NA-2c
    _BEAT_CATALOGUE      = [_NPIdleBeat.PULSE, _NPIdleBeat.SHIMMER, _NPIdleBeat.DECRYPT]

    def _init_decrypt(self) -> None:
        self._frame = []
        self._startup_t0 = time.monotonic()
        n = max(1, len(self._target_name))
        step = self._DECRYPT_DURATION_S / max(1, n - 1)
        for i, ch in enumerate(self._target_name):
            deadline = self._startup_t0 + i * step + _random.uniform(-step * 0.5, step * 0.5)
            self._frame.append(_NPChar(
                target=ch,
                current=_random.choice(_NP_POOL),
                locked=False,
                lock_at=max(self._startup_t0 + 0.03, deadline),
                style=self._decrypt_style,
            ))
        self._tick = 0
        last_lock = max(c.lock_at for c in self._frame) if self._frame else self._startup_t0
        _log.debug(
            "nameplate decrypt init: name=%r n=%d step=%.3fs duration=%.1fs last_lock_in=%.3fs",
            self._target_name, n, step, self._DECRYPT_DURATION_S, last_lock - self._startup_t0,
        )

    def _init_morph(self, src: str, dst: str) -> None:
        self._morph_src = src
        self._morph_dst = dst
        length = max(len(src), len(dst))
        ticks_base = max(1, int(round(self._MORPH_TICKS * self._morph_speed)))
        self._frame = []
        self._morph_dissolve = []
        for i in range(length):
            s_ch = src[i] if i < len(src) else " "
            d_ch = dst[i] if i < len(dst) else " "
            ticks = ticks_base + _random.randint(-2, 2)
            ticks = max(1, ticks)
            self._frame.append(_NPChar(
                target=d_ch,
                current=s_ch,
                locked=(s_ch == d_ch),
                lock_at=ticks,
                style=self._active_style if self._state == _NPState.MORPH_TO_ACTIVE else Style.parse(self._idle_color_hex),
            ))
            self._morph_dissolve.append(ticks)

    def _snap_to_idle(self) -> None:
        self._init_frame_for(self._target_name, active_style=False)

    def _snap_to_active(self) -> None:
        self._init_frame_for(self._active_label, active_style=True)

    def _init_frame_for(self, text: str, *, active_style: bool = False) -> None:
        style = self._active_style if active_style else Style.parse(self._idle_color_hex)
        self._frame = [
            _NPChar(target=ch, current=ch, locked=True, lock_at=0, style=style)
            for ch in text
        ]
        self._morph_dissolve = [0] * len(self._frame)

    def _set_timer_rate(self, fps: int) -> None:
        if self._timer:
            self._timer.stop()
        self._timer = self.set_interval(1 / fps, self._advance)

    def _stop_timer(self) -> None:
        if self._timer:
            self._timer.stop()
            self._timer = None

    def _enter_idle_timer(self) -> None:
        """Enter static wait; schedule first beat one-shot."""
        self._stop_timer()
        self._idle_beat_type = _NPIdleBeat.NONE
        if not self._effects_enabled:
            return
        if self._idle_effect_name == "none":
            return
        self._schedule_next_beat()

    def _schedule_next_beat(self) -> None:
        delay = _random.uniform(self._idle_beat_min_s, self._idle_beat_max_s)
        if self._idle_beat_timer is not None:
            self._idle_beat_timer.stop()
        self._idle_beat_timer = self.set_timer(delay, self._start_idle_beat)

    def _start_idle_beat(self) -> None:
        self._idle_beat_timer = None
        self._idle_beat_tick = 0
        self._idle_beat_type = self._pick_beat_type()
        self._init_beat(self._idle_beat_type)
        self._set_timer_rate(30)

    def _stop_all_idle_timers(self) -> None:
        """Call before leaving IDLE or on unmount."""
        self._stop_timer()
        if self._idle_beat_timer is not None:
            self._idle_beat_timer.stop()
            self._idle_beat_timer = None
        self._idle_beat_type = _NPIdleBeat.NONE

    # --- idle beat catalogue ---

    def _pick_beat_type(self) -> _NPIdleBeat:
        name = self._idle_effect_name
        if name == "auto":
            return _random.choice(self._BEAT_CATALOGUE)
        mapping = {
            "pulse":   _NPIdleBeat.PULSE,
            "shimmer": _NPIdleBeat.SHIMMER,
            "decrypt": _NPIdleBeat.DECRYPT,
        }
        result = mapping.get(name)
        if result is None:
            _LOG.warning("unknown idle_effect %r; falling back to pulse", name)
            result = _NPIdleBeat.PULSE
        return result

    def _init_beat(self, beat: _NPIdleBeat) -> None:
        if beat == _NPIdleBeat.DECRYPT:
            self._beat_decrypt_frame = [
                _NPChar(target=ch, current=_random.choice(_NP_POOL),
                        locked=False, lock_at=0, style=self._decrypt_style)
                for ch in self._target_name
            ]

    def _tick_idle_beat(self, beat: _NPIdleBeat, tick: int) -> bool:
        """Return True when the beat is complete."""
        if beat == _NPIdleBeat.PULSE:
            return tick >= self._BEAT_PULSE_TICKS
        if beat == _NPIdleBeat.SHIMMER:
            return tick >= self._BEAT_SHIMMER_TICKS
        if beat == _NPIdleBeat.DECRYPT:
            return self._tick_beat_decrypt(tick)
        return True

    def _tick_beat_decrypt(self, tick: int) -> bool:
        n = len(self._target_name)
        if tick < 10:
            for ch in self._beat_decrypt_frame:
                ch.current = _random.choice(_NP_POOL)
            return False
        t_rel = tick - 10
        all_locked = True
        for i, ch in enumerate(self._beat_decrypt_frame):
            if ch.locked:
                continue
            if i <= (n - 1) * t_rel / 19:
                ch.current = ch.target
                ch.style = Style.parse(self._idle_color_hex)
                ch.locked = True
            else:
                ch.current = _random.choice(_NP_POOL)
                all_locked = False
        return all_locked

    def _render_idle_beat(self, beat: _NPIdleBeat, tick: int) -> Text:
        if beat == _NPIdleBeat.PULSE:
            return self._render_beat_pulse(tick)
        if beat == _NPIdleBeat.SHIMMER:
            return self._render_beat_shimmer(tick)
        if beat == _NPIdleBeat.DECRYPT:
            t = Text()
            for ch in self._beat_decrypt_frame:
                t.append(ch.current, style=ch.style)
            return t
        return Text(self._target_name, style=Style.parse(self._idle_color_hex))

    def _render_beat_pulse(self, tick: int) -> Text:
        t = Text()
        n = max(3, len(self._target_name))
        phase = 2 * math.pi * tick / self._BEAT_PULSE_TICKS
        offset = math.pi / n
        for i, ch in enumerate(self._target_name):
            w = (math.sin(phase - i * offset) + 1.0) / 2.0
            color = _lerp_hex(self._idle_color_hex, self._accent_hex, w)
            t.append(ch, style=Style.parse(color))
        return t

    def _render_beat_shimmer(self, tick: int) -> Text:
        t = Text()
        n = max(3, len(self._target_name))
        pos = (n + 4) * tick / self._BEAT_SHIMMER_TICKS - 2
        for i, ch in enumerate(self._target_name):
            dist = abs(i - pos)
            w = max(0.0, 1.0 - dist / 1.5)
            color = _lerp_hex(self._idle_color_hex, self._accent_hex, w)
            t.append(ch, style=Style.parse(color))
        return t

    def _pause_pulse(self) -> None:
        """Stop animation timer; --active stays so the turn-in-progress color persists."""
        self._stop_timer()

    def _on_phase_change(self, phase: str) -> None:
        """A2: gate nameplate pulse on status_phase; trigger event beats in IDLE."""
        from hermes_cli.tui.agent_phase import Phase
        try:
            if phase == Phase.REASONING:
                # (re)start pulse if currently active state
                if self._state == _NPState.ACTIVE_IDLE and self._timer is None:
                    self._active_phase = 0.0
                    self._set_timer_rate(30)
            elif phase == Phase.TOOL_EXEC:
                if self._state != _NPState.STARTUP:
                    self._pause_pulse()
                self.trigger_event_beat(_NPIdleBeat.SHIMMER)
            elif phase == Phase.STREAMING:
                if self._state != _NPState.STARTUP:
                    self._pause_pulse()
                self.trigger_event_beat(_NPIdleBeat.PULSE)
            elif phase == Phase.IDLE:
                pass  # transition_to_idle() drives IDLE transitions
            # Phase.ERROR handled by A3 (error-prominence spec)
        except Exception:
            # best-effort status update; widget may be absent
            pass

    def _activate_idle_phase(self) -> None:
        """Resume idle animation after error cleared."""
        self._state = _NPState.IDLE
        self._enter_idle_timer()

    def _on_error_set(self, **_) -> None:
        """A3-1: switch nameplate into error state."""
        try:
            if self._state == _NPState.STARTUP:
                # Abort decrypt early so garbled chars don't freeze on screen.
                self._state = _NPState.IDLE
                self._init_frame_for(self._target_name, active_style=False)
            self._stop_timer()
            self.remove_class("--active", "--idle")
            self.add_class("--error")
            self.refresh()
        except Exception:
            _LOG.debug("nameplate _on_error_set failed", exc_info=True)

    def _on_error_clear(self, **_) -> None:
        """A3-1: restore nameplate after error is cleared."""
        try:
            self.remove_class("--error")
            self._activate_idle_phase()
        except Exception:
            _LOG.debug("nameplate _on_error_clear failed", exc_info=True)
