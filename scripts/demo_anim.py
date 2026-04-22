#!/usr/bin/env python3
"""Drawbraille animation showcase.

Renders every engine (or a subset) to the terminal with optional
gradient and hue-shift coloring.

Usage examples:
  python scripts/demo_anim.py
  python scripts/demo_anim.py --engines aurora_ribbon,plasma,matrix_rain
  python scripts/demo_anim.py --gradient --color "#00ffaa" --color2 "#ff00cc"
  python scripts/demo_anim.py --multi-color "#ff0050,#ffaa00,#00ffcc,#8800ff" --hue-shift 1.2
  python scripts/demo_anim.py --duration 6 --fps 20
"""
from __future__ import annotations

import argparse
import math
import os
import shutil
import signal
import sys
import time

# ── ANSI helpers ──────────────────────────────────────────────────────────────

def _ansi_fg(r: int, g: int, b: int) -> str:
    return f"\033[38;2;{r};{g};{b}m"

_RESET = "\033[0m"
_BOLD  = "\033[1m"
_HIDE_CURSOR = "\033[?25l"
_SHOW_CURSOR = "\033[?25h"
_CLEAR       = "\033[2J"
_HOME        = "\033[H"


def _parse_hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _lerp_rgb(c1: tuple[int,int,int], c2: tuple[int,int,int], t: float) -> tuple[int,int,int]:
    return (
        round(c1[0] + (c2[0] - c1[0]) * t),
        round(c1[1] + (c2[1] - c1[1]) * t),
        round(c1[2] + (c2[2] - c1[2]) * t),
    )


def _lerp_hex(h1: str, h2: str, t: float) -> tuple[int,int,int]:
    return _lerp_rgb(_parse_hex(h1), _parse_hex(h2), t)


# ── Colorize modes ────────────────────────────────────────────────────────────

def _colorize_flat(frame: str, color: str) -> str:
    r, g, b = _parse_hex(color)
    return f"{_ansi_fg(r,g,b)}{frame}{_RESET}"


def _colorize_gradient(frame: str, color1: str, color2: str) -> str:
    """Row-based linear gradient from color1 (top) to color2 (bottom)."""
    rows = frame.split("\n")
    n = max(len(rows), 1)
    out: list[str] = []
    for i, row in enumerate(rows):
        r, g, b = _lerp_hex(color1, color2, i / n)
        out.append(f"{_ansi_fg(r,g,b)}{row}")
    return "\n".join(out) + _RESET


def _colorize_multi(
    frame: str,
    stops: list[tuple[int,int,int]],
    t: float,
    hue_shift_speed: float,
) -> str:
    """Per-character N-stop gradient with sinusoidal hue-shift drift.

    Mirrors DrawbrailleOverlay._render_multi_color() but outputs raw ANSI.
    """
    n_stops = len(stops)
    drift = math.sin(t * hue_shift_speed) * 0.25
    rows = frame.split("\n")
    out_rows: list[str] = []

    for row in rows:
        row_len = len(row)
        if row_len == 0:
            out_rows.append("")
            continue
        row_inv = 1.0 / max(row_len - 1, 1)
        # build per-char color
        chars_colored: list[str] = []
        prev_rgb: tuple[int,int,int] | None = None
        run: list[str] = []

        def _flush(rgb: tuple[int,int,int]) -> None:
            chars_colored.append(f"{_ansi_fg(*rgb)}{''.join(run)}")
            run.clear()

        for idx, ch in enumerate(row):
            pos = idx * row_inv + drift
            pos = abs(pos % 2.0)
            if pos > 1.0:
                pos = 2.0 - pos

            if n_stops == 1:
                rgb = stops[0]
            else:
                seg = pos * (n_stops - 1)
                si = min(int(seg), n_stops - 2)
                rgb = _lerp_rgb(stops[si], stops[si + 1], seg - si)

            if rgb != prev_rgb and prev_rgb is not None:
                _flush(prev_rgb)
            run.append(ch)
            prev_rgb = rgb

        if run and prev_rgb is not None:
            _flush(prev_rgb)

        out_rows.append("".join(chars_colored))

    return "\n".join(out_rows) + _RESET


# ── Engine map ────────────────────────────────────────────────────────────────

def _load_engines() -> tuple[dict, dict]:
    from hermes_cli.tui.anim_engines import ENGINES, ANIMATION_LABELS
    return ENGINES, ANIMATION_LABELS


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Drawbraille animation showcase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--engines", default="all",
        help='Comma-separated engine keys or "all" (default: all)',
    )
    ap.add_argument("--duration", type=float, default=4.0, help="Seconds per engine (default 4)")
    ap.add_argument("--fps", type=int, default=15, help="Frames per second (default 15)")
    ap.add_argument("--color", default="#00d7ff", help="Primary color hex (default #00d7ff)")
    ap.add_argument("--color2", default="#8800ff", help="Secondary color for gradient (default #8800ff)")
    ap.add_argument("--gradient", action="store_true", help="Row-based gradient between --color and --color2")
    ap.add_argument(
        "--multi-color", default="",
        metavar="HEX,HEX,...",
        help="N-stop per-character gradient (overrides --gradient). E.g. #ff0050,#ffaa00,#00ffcc",
    )
    ap.add_argument("--hue-shift", type=float, default=0.8, help="Hue-shift drift speed (default 0.8, 0=static)")
    ap.add_argument("--width", type=int, default=0, help="Override braille pixel width (default: terminal cols × 2)")
    ap.add_argument("--height", type=int, default=0, help="Override braille pixel height (default: (terminal rows - 3) × 4)")
    args = ap.parse_args()

    ts = shutil.get_terminal_size((80, 24))
    cols = args.width  or ts.columns
    rows = args.height or max(4, ts.lines - 3)
    w = cols * 2          # braille pixel width
    h = (rows - 1) * 4   # braille pixel height (reserve 1 row for label)

    from hermes_cli.tui.anim_engines import AnimParams
    _ENGINES, ANIMATION_LABELS = _load_engines()

    if args.engines.strip().lower() == "all":
        engine_keys = list(_ENGINES.keys())
    else:
        engine_keys = [k.strip() for k in args.engines.split(",") if k.strip()]

    # Parse multi-color stops
    multi_stops: list[tuple[int,int,int]] = []
    if args.multi_color:
        for hx in args.multi_color.split(","):
            hx = hx.strip()
            if hx:
                multi_stops.append(_parse_hex(hx))

    # Determine coloring mode
    if multi_stops:
        mode = "multi"
    elif args.gradient:
        mode = "gradient"
    else:
        mode = "flat"

    frame_dt = 1.0 / args.fps
    params = AnimParams(
        width=w, height=h, t=0.0, dt=frame_dt,
        heat=0.5, particle_count=60, trail_decay=0.0,
    )

    interrupted = False

    def _sigint(sig, frame):
        nonlocal interrupted
        interrupted = True

    signal.signal(signal.SIGINT, _sigint)

    sys.stdout.write(f"{_HIDE_CURSOR}{_CLEAR}{_HOME}")
    sys.stdout.flush()

    try:
        total = len(engine_keys)
        for idx, key in enumerate(engine_keys, 1):
            if interrupted:
                break
            cls = _ENGINES.get(key)
            if cls is None:
                continue

            engine = cls()
            label = ANIMATION_LABELS.get(key, key)
            params.t = 0.0
            t_end = time.perf_counter() + args.duration
            frame_num = 0

            while time.perf_counter() < t_end and not interrupted:
                t0 = time.perf_counter()
                frame_str = engine.next_frame(params)

                if mode == "multi":
                    colored = _colorize_multi(frame_str, multi_stops, params.t, args.hue_shift)
                elif mode == "gradient":
                    colored = _colorize_gradient(frame_str, args.color, args.color2)
                else:
                    colored = _colorize_flat(frame_str, args.color)

                progress = f"[{idx}/{total}]"
                header = f"{_BOLD}{label}{_RESET}  {progress}"
                eol = "\033[K"
                cleared = colored.replace("\n", eol + "\n")
                sys.stdout.write(f"{_HOME}{header}{eol}\n{cleared}{eol}\033[J")
                sys.stdout.flush()

                params.t += frame_dt
                frame_num += 1
                elapsed = time.perf_counter() - t0
                sleep = frame_dt - elapsed
                if sleep > 0:
                    time.sleep(sleep)

    finally:
        sys.stdout.write(f"{_SHOW_CURSOR}{_CLEAR}{_HOME}")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
