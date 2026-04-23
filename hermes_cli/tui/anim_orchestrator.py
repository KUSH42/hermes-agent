"""AnimOrchestrator — engine lifecycle, carousel, SDF warmup.

No Textual dependency. Owned by DrawbrailleOverlay at self._orchestrator.
Reads overlay._current_phase / .animation / .gradient at runtime (duck-typed).
Never calls overlay.update() or any Textual widget method.
"""
from __future__ import annotations

import logging
import random
import time
from typing import TYPE_CHECKING

from hermes_cli.tui.anim_engines import (
    AnimEngine,
    AnimParams,
    TrailCanvas,
    CrossfadeEngine,
)

if TYPE_CHECKING:
    from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay, DrawbrailleOverlayCfg

_LOG = logging.getLogger(__name__)


class AnimOrchestrator:
    """Engine lifecycle — selection, caching, carousel, SDF warmup.

    Owned by DrawbrailleOverlay at self._orchestrator.
    Reads overlay._current_phase / .animation / .gradient at runtime.
    Never calls overlay.update() or any Textual widget method.
    """

    def __init__(self, overlay: "DrawbrailleOverlay") -> None:
        self._overlay = overlay

        # Engine instance cache
        self._current_engine_instance: object | None = None
        self._current_engine_key: str = ""

        # SDF warmup state
        self._sdf_engine: object | None = None
        self._sdf_warmup_instance: object | None = None
        self._sdf_crossfade: object | None = None
        self._sdf_baker_was_ready: bool = False
        self._sdf_permanently_failed: bool = False

        # Carousel state
        self._carousel_engines: list[str] = []
        self._carousel_idx: int = 0
        self._carousel_last_switch: float = 0.0
        self._carousel_crossfade: "CrossfadeEngine | None" = None
        self._carousel_key: str = ""

        # External trail for stateless engines
        self._external_trail: "TrailCanvas | None" = None

    # ── Engine selection ───────────────────────────────────────────────────

    def get_engine(
        self,
        params: AnimParams,
        cfg: "DrawbrailleOverlayCfg | None",
        resolved_color: str,
        resolved_color_b: str | None,
    ) -> AnimEngine:
        """Return cached engine for current cfg.animation.

        resolved_color / resolved_color_b are passed here so get_sdf_engine
        can forward them to SDFMorphEngine at construction time.
        """
        # Lazy import to avoid circular import at module load
        from hermes_cli.tui.drawbraille_overlay import _ENGINES

        # Carousel path: delegate to get_carousel_engine when carousel active
        if cfg and cfg.carousel and len(self._carousel_engines) >= 2:
            return self.get_carousel_engine(cfg)

        key = cfg.animation if cfg else self._overlay.animation

        # Switching away from sdf_morph — clear SDF state
        if self._current_engine_key == "sdf_morph" and key != "sdf_morph":
            self._sdf_warmup_instance = None
            self._sdf_crossfade = None
            self._sdf_baker_was_ready = False
            self._external_trail = None

        # Key changed — reset external trail
        if key != self._current_engine_key and self._external_trail is not None:
            self._external_trail = None

        if key != "sdf_morph":
            if self._current_engine_instance is None or self._current_engine_key != key:
                cls = _ENGINES.get(key, _ENGINES["dna"])
                self._current_engine_instance = cls()
                self._current_engine_key = key
                if hasattr(self._current_engine_instance, "on_mount"):
                    self._current_engine_instance.on_mount(self._overlay)  # type: ignore[arg-type]
            return self._current_engine_instance  # type: ignore[return-value]

        # sdf_morph path — delegate entirely to get_sdf_engine (handles warmup/crossfade/failure)
        self._current_engine_key = "sdf_morph"
        return self.get_sdf_engine(params, cfg, resolved_color, resolved_color_b)

    def get_sdf_engine(
        self,
        params: AnimParams,
        cfg: "DrawbrailleOverlayCfg | None",
        resolved_color: str,
        resolved_color_b: str | None,
    ) -> AnimEngine:
        """Return warmup or real SDF engine. Passes resolved colors to SDFMorphEngine."""
        from hermes_cli.tui.drawbraille_overlay import _ENGINES

        # Permanently failed → fallback
        if self._sdf_permanently_failed:
            fallback = (cfg.sdf_warmup_engine if cfg else None) or "dna"
            if fallback not in _ENGINES:
                fallback = "dna"
            return _ENGINES[fallback]()  # type: ignore[return-value]

        if self._sdf_engine is not None:
            # Check baker.failed BEFORE baker.ready (C2)
            baker = getattr(self._sdf_engine, "_baker", None)
            if baker is not None and hasattr(baker, "failed") and baker.failed.is_set():
                if not self._sdf_permanently_failed:
                    _LOG.warning("SDF baker failed — falling back to warmup engine")
                    self._sdf_permanently_failed = True
                self._sdf_engine = None
                self._sdf_warmup_instance = None
                self._sdf_baker_was_ready = False
                fallback = (cfg.sdf_warmup_engine if cfg else None) or "dna"
                if fallback not in _ENGINES:
                    fallback = "dna"
                return _ENGINES[fallback]()  # type: ignore[return-value]

            # Baker not ready yet → serve warmup engine
            if baker is not None and hasattr(baker, "ready") and not baker.ready.is_set():
                warmup_key = (cfg.sdf_warmup_engine if cfg else None) or "dna"
                if warmup_key not in _ENGINES:
                    warmup_key = "dna"
                if self._sdf_warmup_instance is None:
                    self._sdf_warmup_instance = _ENGINES[warmup_key]()
                return self._sdf_warmup_instance  # type: ignore[return-value]

            # Baker ready → serve real SDF engine (and kick off crossfade if first time)
            if baker is not None and hasattr(baker, "ready") and baker.ready.is_set():
                if not self._sdf_baker_was_ready and self._sdf_warmup_instance is not None:
                    # Crossfade from warmup to SDF
                    speed = cfg.crossfade_speed if cfg else 0.04
                    self._sdf_crossfade = CrossfadeEngine(
                        self._sdf_warmup_instance, self._sdf_engine, speed=speed  # type: ignore[arg-type]
                    )
                    self._sdf_baker_was_ready = True
                    return self._sdf_crossfade  # type: ignore[return-value]
                if self._sdf_crossfade is not None:
                    if self._sdf_crossfade.progress < 1.0:
                        return self._sdf_crossfade  # type: ignore[return-value]
                    self._sdf_crossfade = None
                return self._sdf_engine  # type: ignore[return-value]

            return self._sdf_engine  # type: ignore[return-value]

        if self._sdf_engine is None:
            from hermes_cli.tui.sdf_morph import SDFMorphEngine
            gradient = self._overlay.gradient if hasattr(self._overlay, "gradient") else False
            self._sdf_engine = SDFMorphEngine(
                text=params.sdf_text,
                hold_ms=params.sdf_hold_ms,
                morph_ms=params.sdf_morph_ms,
                mode=params.sdf_render_mode,
                outline_w=params.sdf_outline_width,
                dissolve_spread=params.sdf_dissolve_spread,
                font_size=params.sdf_font_size,
                color=resolved_color,
                color_b=resolved_color_b if gradient else None,
            )
            if hasattr(self._sdf_engine, "on_mount"):
                self._sdf_engine.on_mount(self._overlay)  # type: ignore[arg-type]

        return self._sdf_engine  # type: ignore[return-value]

    # ── Carousel ───────────────────────────────────────────────────────────

    def pick_carousel_candidate(self, phase: str, cfg: "DrawbrailleOverlayCfg") -> str | None:
        """Return a random engine key filtered by phase category, excluding current."""
        from hermes_cli.tui.drawbraille_overlay import _PHASE_CATEGORIES, _ENGINE_META

        if not self._carousel_engines:
            return None
        if cfg.phase_aware_carousel:
            allowed = _PHASE_CATEGORIES.get(phase, [])
            if allowed:
                candidates = [
                    k for k in self._carousel_engines
                    if _ENGINE_META.get(k, {}).get("category") in allowed
                    and k != self._carousel_key
                    and k != "sdf_morph"
                ]
            else:
                candidates = []
        else:
            candidates = [k for k in self._carousel_engines if k != self._carousel_key and k != "sdf_morph"]
        if not candidates:
            # Fallback: any engine excluding sdf_morph
            candidates = [k for k in self._carousel_engines if k != "sdf_morph"]
        return random.choice(candidates) if candidates else None

    def get_carousel_engine(self, cfg: "DrawbrailleOverlayCfg") -> AnimEngine:
        """Return current carousel engine, advancing timer first.

        Calls advance_carousel internally. If advance_carousel returns True
        (switch occurred), wraps the new engine in a CrossfadeEngine.
        """
        from hermes_cli.tui.drawbraille_overlay import _ENGINES, _PHASE_CATEGORIES, _ENGINE_META

        # Phase D: ambient guard — freeze carousel during ambient state
        visibility = getattr(self._overlay, "_visibility_state", "active")
        if visibility == "ambient":
            if self._current_engine_instance is None:
                ambient_key = (cfg.ambient_engine if cfg else "perlin_flow") or "perlin_flow"
                if ambient_key not in _ENGINES:
                    ambient_key = "perlin_flow"
                self._current_engine_instance = _ENGINES[ambient_key]()
                self._carousel_key = ambient_key
            return self._current_engine_instance  # type: ignore[return-value]

        # If crossfade active and not done, return it
        if self._carousel_crossfade is not None:
            if self._carousel_crossfade.progress < 1.0:
                return self._carousel_crossfade  # type: ignore[return-value]
            else:
                # Crossfade done — commit new engine key
                if self._carousel_engines:
                    self._carousel_idx %= len(self._carousel_engines)
                    self._current_engine_key = self._carousel_engines[self._carousel_idx]
                    self._carousel_key = self._current_engine_key
                self._carousel_crossfade = None

        # Check if time to advance (wall-clock based); advance_carousel handles the interval guard
        now = time.monotonic()
        switched = self.advance_carousel(now, cfg)
        if switched:
            # advance_carousel already installed crossfade; return it
            if self._carousel_crossfade is not None:
                return self._carousel_crossfade  # type: ignore[return-value]

        # Normal: return current cached engine
        if self._carousel_engines:
            self._carousel_idx %= len(self._carousel_engines)
        if (self._current_engine_instance is None
                or (self._carousel_engines and self._current_engine_key != self._carousel_engines[self._carousel_idx])):
            if self._carousel_engines:
                key = self._carousel_engines[self._carousel_idx]
                self._current_engine_key = key
                self._carousel_key = key
                self._current_engine_instance = _ENGINES.get(key, _ENGINES["dna"])()
        return self._current_engine_instance  # type: ignore[return-value]

    def advance_carousel(self, now: float, cfg: "DrawbrailleOverlayCfg") -> bool:
        """Tick carousel timer; returns True if engine switched this tick.

        now is time.monotonic() (wall time). Interval tracking is wall-clock based.
        Returns False if the carousel interval has not elapsed yet.
        """
        from hermes_cli.tui.drawbraille_overlay import _ENGINES, _PHASE_CATEGORIES, _ENGINE_META

        if not self._carousel_engines:
            return False

        interval = cfg.carousel_interval_s if cfg else 12.0
        if (now - self._carousel_last_switch) <= interval:
            return False

        current_phase = getattr(self._overlay, "_current_phase", "thinking")

        if cfg.phase_aware_carousel:
            allowed = _PHASE_CATEGORIES.get(current_phase, [])
            if allowed:
                candidates = [
                    k for k in self._carousel_engines
                    if _ENGINE_META.get(k, {}).get("category") in allowed
                ]
            else:
                candidates = []
        else:
            candidates = self._carousel_engines

        if not candidates:
            candidates = self._carousel_engines  # fallback

        if len(candidates) < 1:
            return False

        others = [k for k in candidates if k != self._carousel_key] or candidates
        next_key = random.choice(others)
        self._carousel_key = next_key

        if next_key in self._carousel_engines:
            self._carousel_idx = self._carousel_engines.index(next_key)

        engine_a = self._current_engine_instance
        if engine_a is None:
            cur = self._carousel_key or (self._carousel_engines[0] if self._carousel_engines else "dna")
            engine_a = _ENGINES.get(cur, _ENGINES["dna"])()

        engine_b = _ENGINES.get(next_key, _ENGINES["dna"])()
        speed = cfg.crossfade_speed if cfg else 0.04
        self._carousel_crossfade = CrossfadeEngine(engine_a, engine_b, speed=speed)
        self._carousel_last_switch = now
        return True

    def init_carousel(self, cfg: "DrawbrailleOverlayCfg") -> None:
        """Seed or clear carousel state from cfg.

        If cfg.carousel=True: build engine list from _ENGINES, reset idx/last_switch.
        If cfg.carousel=False: clear _carousel_engines=[], _carousel_crossfade=None.
        Always called from show() — handles both branches internally.
        """
        from hermes_cli.tui.drawbraille_overlay import _ENGINES, _ENGINE_META

        if cfg.carousel:
            self._carousel_engines = [
                k for k in _ENGINES
                if _ENGINE_META.get(k, {}).get("category") not in {"Premium", "System"}
            ]
            if len(self._carousel_engines) < 2:
                self._carousel_engines = []
            self._carousel_idx = 0
            self._carousel_last_switch = time.monotonic()
            self._carousel_crossfade = None
            if self._carousel_engines:
                self._carousel_key = self._carousel_engines[0]
        else:
            self._carousel_engines = []
            self._carousel_crossfade = None

    def on_phase_signal(self, phase: str, cfg: "DrawbrailleOverlayCfg") -> None:
        """Handle phase change signal — may install CrossfadeEngine for phase transition.

        No-op when phase == 'token'.
        When crossfade is installed, resets _carousel_last_switch = time.monotonic().
        5C guard: if crossfade is in early flight (progress < 0.5), skip install but
        update _carousel_key and _carousel_idx to next_key so completing crossfade
        lands on the correct engine.
        """
        from hermes_cli.tui.drawbraille_overlay import _ENGINES

        if phase == "token":
            return

        if not cfg.carousel or not self._carousel_engines:
            return

        next_key = self.pick_carousel_candidate(phase, cfg)
        if not next_key or next_key == self._carousel_key:
            return

        # 5C: rapid crossfade guard
        if (self._carousel_crossfade is not None
                and self._carousel_crossfade.progress < 0.5):
            # Crossfade in early flight — skip new install; update targets so
            # the completing crossfade lands on next_key.
            if next_key in self._carousel_engines:
                self._carousel_idx = self._carousel_engines.index(next_key)
            self._carousel_key = next_key
            return

        eng_a = (self._current_engine_instance
                 or (_ENGINES.get(self._carousel_key) or _ENGINES["dna"])())
        eng_b = _ENGINES[next_key]()
        self._carousel_crossfade = CrossfadeEngine(
            eng_a, eng_b, speed=cfg.phase_crossfade_speed
        )
        self._carousel_key = next_key
        self._carousel_last_switch = time.monotonic()

    def transition_to_active(self, cfg: "DrawbrailleOverlayCfg") -> None:
        """Set up carousel crossfade for ambient→active transition.

        Calls pick_carousel_candidate("thinking"), constructs CrossfadeEngine
        from current engine → next candidate, sets _carousel_key = next_key.
        No-op if no carousel candidate available.
        """
        from hermes_cli.tui.drawbraille_overlay import _ENGINES

        next_key = self.pick_carousel_candidate("thinking", cfg)
        if not next_key:
            return
        eng_a = self._current_engine_instance or (
            _ENGINES.get(self._carousel_key) or _ENGINES["dna"]
        )()
        eng_b = _ENGINES[next_key]()
        self._carousel_crossfade = CrossfadeEngine(
            eng_a, eng_b, speed=cfg.phase_crossfade_speed
        )
        self._carousel_key = next_key

    def set_ambient_engine(self, key: str) -> None:
        """Instantiate ambient engine.

        Sets _current_engine_instance = _ENGINES[key](),
        _current_engine_key = key, _carousel_key = key.
        """
        from hermes_cli.tui.drawbraille_overlay import _ENGINES

        self._current_engine_instance = _ENGINES[key]()
        self._current_engine_key = key
        self._carousel_key = key

    # ── External trail ─────────────────────────────────────────────────────

    def apply_external_trail(
        self,
        frame_str: str,
        params: AnimParams,
        cfg: "DrawbrailleOverlayCfg | None",
    ) -> str:
        """Wrap frame through TrailCanvas when cfg.trail_decay > 0 and engine has no _trail."""
        if cfg is None or cfg.trail_decay <= 0:
            return frame_str

        engine = self._current_engine_instance
        if engine is not None and hasattr(engine, "_trail"):
            return frame_str

        w = params.width
        h = params.height
        if (self._external_trail is None
                or getattr(self._external_trail, "_w", None) != w
                or getattr(self._external_trail, "_h", None) != h):
            self._external_trail = TrailCanvas(decay=cfg.trail_decay)
            self._external_trail._w = w  # type: ignore[attr-defined]
            self._external_trail._h = h  # type: ignore[attr-defined]

        et = self._external_trail
        for row_idx, row in enumerate(frame_str.split("\n")):
            for col_idx, ch in enumerate(row):
                if 0x2800 <= ord(ch) <= 0x28FF:
                    bits = ord(ch) - 0x2800
                    for dy in range(4):
                        for dx in range(2):
                            bit_idx = dy * 2 + dx
                            if bits & (1 << bit_idx):
                                px = col_idx * 2 + dx
                                py = row_idx * 4 + dy
                                et.set(px, py, 1.0)
        et.decay_all()
        return et.to_canvas().frame()

    # ── Cleanup ────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Clear engine cache, carousel state, SDF warmup state, external trail.

        Does NOT clear _sdf_permanently_failed — that is only cleared by
        DrawbrailleOverlay._do_hide() via explicit assignment.
        """
        self._current_engine_instance = None
        self._current_engine_key = ""
        self._sdf_engine = None
        self._sdf_warmup_instance = None
        self._sdf_crossfade = None
        self._sdf_baker_was_ready = False
        self._external_trail = None
        self._carousel_engines = []
        self._carousel_idx = 0
        self._carousel_last_switch = 0.0
        self._carousel_crossfade = None
        self._carousel_key = ""
        # NOTE: _sdf_permanently_failed intentionally NOT cleared here
