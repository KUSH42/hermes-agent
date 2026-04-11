"""TerminalTextEffects runner for Hermes TUI.

Provides a curated subset of TTE effects tuned to the Hermes AI coding agent
persona. TTE is an optional dependency — import errors are handled gracefully.

Usage (inside App.suspend()):
    from hermes_cli.tui.tte_runner import run_effect
    run_effect("matrix", "Hermes")
"""

from __future__ import annotations

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
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_effect(name: str) -> tuple[str, str] | None:
    """Return (module_path, class_name) for *name*, or None if unknown."""
    return EFFECT_MAP.get(name.strip().lower())


def run_effect(effect_name: str, text: str, skin=None) -> None:
    """Run a TTE effect synchronously.

    The caller is responsible for having suspended the Textual TUI first
    (e.g. inside ``App.suspend()``).  TTE writes directly to the raw terminal.

    Args:
        effect_name: Key from :data:`EFFECT_MAP`.
        text: Text to animate.
        skin: Optional skin object exposing ``get_color(key, default)``.
              When *None*, the active skin is loaded automatically.
    """
    import importlib

    spec = resolve_effect(effect_name)
    if spec is None:
        available = ", ".join(sorted(EFFECT_MAP))
        print(f"  Unknown effect: {effect_name!r}")
        print(f"  Available: {available}")
        return

    try:
        mod = importlib.import_module(spec[0])
        cls = getattr(mod, spec[1])
    except ImportError:
        print("  TerminalTextEffects is not installed.")
        print('  Install it with: pip install "hermes-agent[fun]"')
        return

    effect = cls(text)

    # Skin-aware gradient — applied to effects that support final_gradient_stops
    try:
        if skin is None:
            from hermes_cli.skin_engine import get_active_skin
            skin = get_active_skin()
        gradient = (
            skin.get_color("banner_dim",    "#CD7F32"),
            skin.get_color("banner_accent", "#FFBF00"),
            skin.get_color("banner_title",  "#FFD700"),
        )
        color_mod = importlib.import_module("terminaltexteffects.utils.graphics")
        Color = getattr(color_mod, "Color")
        cfg = getattr(effect, "effect_config", None)
        if cfg and hasattr(cfg, "final_gradient_stops"):
            effect.effect_config.final_gradient_stops = tuple(Color(c) for c in gradient)
        tc = getattr(effect, "terminal_config", None)
        if tc:
            tc.frame_rate = 0   # unlimited — let the terminal pace it
    except Exception:
        pass  # skin failure is non-fatal; default TTE colours apply

    with effect.terminal_output() as terminal:
        for frame in effect:
            terminal.print(frame)
