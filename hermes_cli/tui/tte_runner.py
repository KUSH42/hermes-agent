"""TerminalTextEffects runner for Hermes TUI.

Provides a curated subset of TTE effects tuned to the Hermes AI coding agent
persona. TTE is an optional dependency — import errors are handled gracefully.

Usage (inside App.suspend()):
    from hermes_cli.tui.tte_runner import run_effect
    run_effect("matrix", "Hermes")
"""

from __future__ import annotations

import logging
from typing import Any

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Effect catalogue
# ---------------------------------------------------------------------------

EFFECT_MAP: dict[str, tuple[str, str]] = {
    # Reveal / dramatic
    "matrix":      ("terminaltexteffects.effects.effect_matrix",      "Matrix"),
    "blackhole":   ("terminaltexteffects.effects.effect_blackhole",    "Blackhole"),
    "decrypt":     ("terminaltexteffects.effects.effect_decrypt",      "Decrypt"),
    "laseretch":   ("terminaltexteffects.effects.effect_laseretch",    "LaserEtch"),
    "binarypath":  ("terminaltexteffects.effects.effect_binarypath",   "BinaryPath"),
    "synthgrid":   ("terminaltexteffects.effects.effect_synthgrid",    "SynthGrid"),
    # Flow / ambient
    "beams":       ("terminaltexteffects.effects.effect_beams",        "Beams"),
    "waves":       ("terminaltexteffects.effects.effect_waves",        "Waves"),
    "rain":        ("terminaltexteffects.effects.effect_rain",         "Rain"),
    "overflow":    ("terminaltexteffects.effects.effect_overflow",     "Overflow"),
    "sweep":       ("terminaltexteffects.effects.effect_sweep",        "Sweep"),
    # Text reveal / typewriter family
    "print":       ("terminaltexteffects.effects.effect_print",        "Print"),
    "slide":       ("terminaltexteffects.effects.effect_slide",        "Slide"),
    "highlight":   ("terminaltexteffects.effects.effect_highlight",    "Highlight"),
    # Fun
    "wipe":        ("terminaltexteffects.effects.effect_wipe",         "Wipe"),
    # Additional effects (20+ more from TTE library)
    "colorshift":  ("terminaltexteffects.effects.effect_colorshift",   "ColorShift"),
    "crumble":     ("terminaltexteffects.effects.effect_crumble",       "Crumble"),
    "burn":        ("terminaltexteffects.effects.effect_burn",          "Burn"),
    "errorcorrect": ("terminaltexteffects.effects.effect_errorcorrect", "ErrorCorrect"),
    "expand":      ("terminaltexteffects.effects.effect_expand",        "Expand"),
    "fireworks":   ("terminaltexteffects.effects.effect_fireworks",     "Fireworks"),
    "middleout":   ("terminaltexteffects.effects.effect_middleout",     "MiddleOut"),
    "orbittingvolley": ("terminaltexteffects.effects.effect_orbittingvolley", "OrbittingVolley"),
    "pour":        ("terminaltexteffects.effects.effect_pour",          "Pour"),
    "randomsequence": ("terminaltexteffects.effects.effect_randomsequence", "RandomSequence"),
    "rings":       ("terminaltexteffects.effects.effect_rings",         "Rings"),
    "scattered":   ("terminaltexteffects.effects.effect_scattered",     "Scattered"),
    "slice":       ("terminaltexteffects.effects.effect_slice",         "Slice"),
    "smoke":       ("terminaltexteffects.effects.effect_smoke",         "Smoke"),
    "spotlights":  ("terminaltexteffects.effects.effect_spotlights",    "Spotlights"),
    "spray":       ("terminaltexteffects.effects.effect_spray",         "Spray"),
    "swarm":       ("terminaltexteffects.effects.effect_swarm",         "Swarm"),
    "thunderstorm": ("terminaltexteffects.effects.effect_thunderstorm", "Thunderstorm"),
    "unstable":    ("terminaltexteffects.effects.effect_unstable",      "Unstable"),
    "vhstape":     ("terminaltexteffects.effects.effect_vhstape",       "VHSTape"),
    "bouncyballs": ("terminaltexteffects.effects.effect_bouncyballs",   "BouncyBalls"),
    "bubbles":     ("terminaltexteffects.effects.effect_bubbles",       "Bubbles"),
}

EFFECT_DESCRIPTIONS: dict[str, str] = {
    "matrix":     "Digital rain cascade",
    "blackhole":  "Characters spiral into a singularity",
    "decrypt":    "Scrambled characters resolve to final text",
    "laseretch":  "Laser burns text into the terminal",
    "binarypath": "Binary particles assemble into text",
    "synthgrid":  "Retro synth-wave grid reveal",
    "beams":      "Scanning light beams illuminate text",
    "waves":      "Text ripples as a wave",
    "rain":       "Characters fall like rain",
    "overflow":   "Characters overflow and settle",
    "sweep":      "Directional character sweep",
    "print":      "Typewriter-style character-by-character reveal",
    "slide":      "Characters slide in from the edges",
    "highlight":  "Spotlight scans and highlights text",
    "wipe":       "Clean directional wipe",
    # Additional effect descriptions
    "colorshift": "Gradient colors shift across the display",
    "crumble":    "Characters crumble into dust then reform",
    "burn":       "Characters ignite and burn up the screen",
    "errorcorrect": "Text flickers with errors before correcting",
    "expand":     "Text expands outward from a point",
    "fireworks":  "Text explodes into colorful fireworks",
    "middleout":  "Text reveals from center outward",
    "orbittingvolley": "Characters orbit around a central point",
    "pour":       "Text pours like liquid from top to bottom",
    "randomsequence": "Random characters cycle through the text",
    "rings":      "Concentric rings form through the text",
    "scattered":  "Text scatters and reforms in place",
    "slice":      "Text is sliced through by a moving blade",
    "smoke":      "Text dissolves into smoke and reforms",
    "spotlights": "Text illuminated by moving spotlights",
    "spray":      "Text is sprayed with particles",
    "swarm":      "Characters swarm and orbit around text",
    "thunderstorm": "Lightning strikes through the text",
    "unstable":   "Text appears unstable with glitch effects",
    "vhstape":    "Retro VHS tape with glitches and scanlines",
    "bouncyballs": "Characters fall as bouncy balls then settle",
    "bubbles":    "Characters form bubbles that float and pop",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_effect(name: str) -> tuple[str, str] | None:
    """Return (module_path, class_name) for *name*, or None if unknown."""
    return EFFECT_MAP.get(name.strip().lower())


def iter_frames(effect_name: str, text: str, skin=None, params: dict[str, object] | None = None):
    """Yield TTE animation frames as ANSI strings without stdout takeover."""
    import importlib

    spec = resolve_effect(effect_name)
    if spec is None:
        return

    try:
        mod = importlib.import_module(spec[0])
        cls = getattr(mod, spec[1])
    except ImportError:
        return

    effect = cls(text)
    color_cls = None

    try:
        color_mod = importlib.import_module("terminaltexteffects.utils.graphics")
        color_cls = getattr(color_mod, "Color")
    except Exception:
        _log.debug("tte_runner: terminaltexteffects.utils.graphics import failed", exc_info=True)
        color_mod = None

    has_colors_override = _apply_effect_params(effect_name, effect, color_cls, params)

    try:
        if skin is None:
            from hermes_cli.skin_engine import get_active_skin
            skin = get_active_skin()
        gradient = (
            skin.get_color("banner_title", "#FFD700"),
            skin.get_color("banner_accent", "#FFBF00"),
            skin.get_color("banner_dim", "#CD7F32"),
        )
        cfg = getattr(effect, "effect_config", None)
        if color_cls is not None and cfg and hasattr(cfg, "final_gradient_stops") and not has_colors_override:
            effect.effect_config.final_gradient_stops = tuple(color_cls(c) for c in gradient)
        tc = getattr(effect, "terminal_config", None)
        if tc:
            tc.frame_rate = 0  # disable TTE's internal sleep; producer in cli.py paces via deadline loop
    except Exception:
        _log.debug("tte_runner: skin/gradient apply failed", exc_info=True)

    for frame in effect:
        yield frame


def _coerce_effect_param(raw: object, current: object, color_cls: type | None) -> object:
    """Coerce a config value to match an effect-config field shape."""
    if isinstance(current, bool):
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str):
            lowered = raw.strip().lower()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
        raise ValueError("expected bool")
    if isinstance(current, int) and not isinstance(current, bool):
        if isinstance(raw, bool):
            raise ValueError("expected int")
        return int(raw)
    if isinstance(current, float):
        if isinstance(raw, bool):
            raise ValueError("expected float")
        return float(raw)
    if isinstance(current, str):
        if isinstance(raw, str):
            return raw
        raise ValueError("expected string")
    if isinstance(current, tuple):
        if not isinstance(raw, (list, tuple)):
            raise ValueError("expected list/tuple")
        items = list(raw)
        if not current:
            return tuple(items)
        sample = current[0]
        if isinstance(sample, bool):
            return tuple(_coerce_effect_param(item, False, color_cls) for item in items)
        if isinstance(sample, int) and not isinstance(sample, bool):
            return tuple(int(item) for item in items)
        if isinstance(sample, float):
            return tuple(float(item) for item in items)
        if isinstance(sample, str):
            return tuple(str(item) for item in items)
        if color_cls is not None and isinstance(sample, color_cls):
            return tuple(color_cls(str(item)) for item in items)
        raise ValueError("unsupported tuple item type")
    if color_cls is not None and isinstance(current, color_cls):
        return color_cls(str(raw))
    raise ValueError("unsupported parameter type")


def _apply_effect_params(
    effect_name: str,
    effect: object,
    color_cls: type | None,
    params: dict[str, object] | None,
) -> None:
    """Validate and apply supported config params to an instantiated effect."""
    if not params:
        return
    cfg = getattr(effect, "effect_config", None)
    if cfg is None:
        print(f"  Effect {effect_name!r} does not expose configurable startup params.")
        return
    known_keys = set(getattr(cfg, "__dict__", {}).keys())
    known_keys.update(getattr(type(cfg), "__dict__", {}).keys())
    has_colors_override = False

    for key, raw in params.items():
        if key == "final_gradient_stops":
            # Allow users to override skin-derived colors
            print(f"  Using custom colors from config (will override skin palette).")
            has_colors_override = True
            continue
        if key == "parser_spec" or key not in known_keys:
            print(f"  Ignoring unknown {effect_name} param: {key}")
            continue
        current = getattr(cfg, key)
        try:
            value = _coerce_effect_param(raw, current, color_cls)
        except (TypeError, ValueError):
            print(f"  Ignoring invalid {effect_name} param {key!r}: {raw!r}")
            continue
        setattr(cfg, key, value)

    return has_colors_override


def run_effect(effect_name: str, text: str, skin=None, params: dict[str, object] | None = None) -> bool:
    """Run a TTE effect synchronously.

    The caller is responsible for having suspended the Textual TUI first
    (e.g. inside ``App.suspend()``).  TTE writes directly to the raw terminal.

    Args:
        effect_name: Key from :data:`EFFECT_MAP`.
        text: Text to animate.
        skin: Optional skin object exposing ``get_color(key, default)``.
              When *None*, the active skin is loaded automatically.
        params: Optional validated startup-effect config overrides.
    """
    import importlib

    spec = resolve_effect(effect_name)
    if spec is None:
        available = ", ".join(sorted(EFFECT_MAP))
        print(f"  Unknown effect: {effect_name!r}")
        print(f"  Available: {available}")
        return False

    try:
        mod = importlib.import_module(spec[0])
        cls = getattr(mod, spec[1])
    except ImportError:
        print("  TerminalTextEffects is not installed.")
        print('  Install it with: pip install "hermes-agent[fun]"')
        return False

    effect = cls(text)
    color_cls = None

    try:
        color_mod = importlib.import_module("terminaltexteffects.utils.graphics")
        color_cls = getattr(color_mod, "Color")
    except Exception:
        _log.debug("tte_runner.run_effect_inline: terminaltexteffects.utils.graphics import failed", exc_info=True)
        color_mod = None

    has_colors_override = _apply_effect_params(effect_name, effect, color_cls, params)

    # Skin-aware gradient — applied to effects that support final_gradient_stops
    # Skip if colors were explicitly overridden via config params
    try:
        if skin is None:
            from hermes_cli.skin_engine import get_active_skin
            skin = get_active_skin()
        gradient = (
            skin.get_color("banner_title",  "#FFD700"),
            skin.get_color("banner_accent", "#FFBF00"),
            skin.get_color("banner_dim",    "#CD7F32"),
        )
        cfg = getattr(effect, "effect_config", None)
        if color_cls is not None and cfg and hasattr(cfg, "final_gradient_stops"):
            # Only apply skin colors if not already overridden via params
            if not has_colors_override:
                effect.effect_config.final_gradient_stops = tuple(color_cls(c) for c in gradient)
                print(f"  Using skin-derived colors: {skin.get_color('banner_title')}, {skin.get_color('banner_accent')}, {skin.get_color('banner_dim')}")
            else:
                print(f"  Using custom colors from config params")
        tc = getattr(effect, "terminal_config", None)
        if tc:
            tc.frame_rate = 0  # disable TTE's internal sleep; producer in cli.py paces via deadline loop
    except Exception:
        _log.debug("tte_runner.run_effect_inline: skin/gradient apply failed", exc_info=True)
        # skin failure is non-fatal; default TTE colours apply

    with effect.terminal_output() as terminal:
        for frame in effect:
            terminal.print(frame)
    return True
