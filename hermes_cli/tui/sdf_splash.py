"""Standalone SDF splash runner — pre-TUI animation via direct stdout writes.

No Textual dependency. Runs before HermesApp.run() in cli.py.
"""
from __future__ import annotations

import shutil
import sys
import time
from typing import TYPE_CHECKING

from hermes_cli.tui.sdf_morph import SDFBaker, SDFMorphEngine

if TYPE_CHECKING:
    pass


def run_sdf_splash(cfg: object) -> None:
    """Blocking. Runs before Textual starts. Direct stdout rendering.

    cfg is a SdfSplashConfig dataclass (or duck-typed object) with:
        text, hold_ms, morph_ms, render_mode, color, total_duration_s
    """
    text = getattr(cfg, "text", "HERMES")
    hold_ms = float(getattr(cfg, "hold_ms", 400))
    morph_ms = float(getattr(cfg, "morph_ms", 600))
    render_mode = getattr(cfg, "render_mode", "dissolve")
    color = getattr(cfg, "color", "#00ff66")
    total_duration_s = float(getattr(cfg, "total_duration_s", 3.0))

    tw, th = shutil.get_terminal_size((80, 24))
    canvas_w, canvas_h = tw, max(th - 2, 4)

    baker = SDFBaker(font_size=96)
    baker.bake(text)  # blocking in main thread — acceptable pre-TUI

    engine = SDFMorphEngine(
        text=text,
        hold_ms=hold_ms,
        morph_ms=morph_ms,
        mode=render_mode,
        font_size=96,
        dissolve_spread=0.15,
        outline_w=0.08,
        color=color,
    )
    engine._baker = baker  # inject pre-baked baker (ready already set)

    # Hide cursor, clear screen
    sys.stdout.write("\x1b[?25l\x1b[2J\x1b[H")
    sys.stdout.flush()

    deadline = time.monotonic() + total_duration_s
    last = time.monotonic()
    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            dt_ms = (now - last) * 1000.0
            last = now
            frame = engine.tick(dt_ms, canvas_w=canvas_w, canvas_h=canvas_h)
            if frame:
                sys.stdout.write("\x1b[H" + frame)
                sys.stdout.flush()
            time.sleep(1 / 15)
    finally:
        # Restore cursor, clear screen
        sys.stdout.write("\x1b[?25h\x1b[2J\x1b[H")
        sys.stdout.flush()
