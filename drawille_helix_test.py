#!/usr/bin/env python3
"""Triple helix animations using drawille braille canvas.

Run each animation standalone:
    python drawille_helix_test.py              # menu
    python drawille_helix_test.py classic      # classic 3-strand helix
    python drawille_helix_test.py rotating     # helix rotates around axis
    python drawille_helix_test.py morph        # amplitude morphs
    python drawille_helix_test.py dna          # helix with cross-bars
    python drawille_helix_test.py vortex       # zooming vortex helix
    python drawille_helix_test.py wave         # sine-wave interference
    python drawille_helix_test.py all          # loop through all

Requires: pip install drawille
Terminal: needs Unicode braille support (most modern terminals).
"""

import math
import os
import sys
import time

from drawille import Canvas


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clear_screen():
    os.system("cls" if os.name == "nt" else "printf '\\033[2J\\033[H'")


def wait_for_exit():
    """Block until user presses Ctrl+C or Enter."""
    print("\n[Ctrl+C or Enter to exit]")
    try:
        input()
    except KeyboardInterrupt:
        pass


def get_terminal_dims():
    """Return (cols, rows) from drawille's helper or fallback."""
    try:
        from drawille import getTerminalSize
        w, h = getTerminalSize()
        return w, h
    except Exception:
        return 80, 24


# ---------------------------------------------------------------------------
# Animation 1 — Classic Triple Helix
# ---------------------------------------------------------------------------

def classic_triple_helix(duration=10, fps=30, amplitude=15, wavelength=0.08):
    """Three sine waves offset 120° apart, scrolled horizontally.

    Strands are drawn with trail effect (previous frames dim by clearing
    fewer old cells each frame).
    """
    canvas = Canvas()
    w, h = get_terminal_dims()
    cx, cy = w, h * 2  # braille coords are 2x col, 4x row
    phases = [0, 2 * math.pi / 3, 4 * math.pi / 3]
    chars = ["⠿", "⠶", "⠧"]  # different density for each strand

    frames = duration * fps
    for f in range(frames):
        canvas.clear()
        t = f / fps * 2  # horizontal scroll speed

        for strand, phase in enumerate(phases):
            for x in range(0, cx, 1):
                y_raw = amplitude * math.sin(wavelength * x + t + phase)
                y = int(cy / 2 + y_raw)
                canvas.set(x, y)
                # draw a small vertical bar for thickness
                canvas.set(x, y + 1)

        clear_screen()
        print(canvas.frame())
        time.sleep(1 / fps)


# ---------------------------------------------------------------------------
# Animation 2 — Rotating Triple Helix (3D projection)
# ---------------------------------------------------------------------------

def rotating_triple_helix(duration=12, fps=30, radius=12, height_factor=0.4):
    """Three strands spiral around a vertical axis, rotating in 3D.

    Uses simple orthographic projection (drop z), with the helix rotating.
    """
    canvas = Canvas()
    w, h = get_terminal_dims()
    cx, cy = w, int(h * 1.5)
    phases = [0, 2 * math.pi / 3, 4 * math.pi / 3]

    total_frames = duration * fps
    for f in range(total_frames):
        canvas.clear()
        angle_offset = (f / fps) * 1.5  # rotation speed

        for strand, phase in enumerate(phases):
            for t_step in range(-cy // 2, cy // 2, 2):
                # helix parametric: angle = height + phase + rotation
                angle = t_step * 0.12 + phase + angle_offset
                px = int(cx / 2 + radius * math.cos(angle))
                py = int(cy / 2 + t_step)
                if 0 <= px < cx and 0 <= py < cy:
                    canvas.set(px, py)
                    canvas.set(px, py + 1)

        clear_screen()
        print(canvas.frame())
        time.sleep(1 / fps)


# ---------------------------------------------------------------------------
# Animation 3 — Morphing Amplitude Helix
# ---------------------------------------------------------------------------

def morph_helix(duration=10, fps=30, max_amp=18):
    """Triple helix whose amplitude oscillates — strands breathe in/out."""
    canvas = Canvas()
    w, h = get_terminal_dims()
    cx, cy = w, h * 2
    phases = [0, 2 * math.pi / 3, 4 * math.pi / 3]

    frames = duration * fps
    for f in range(frames):
        canvas.clear()
        t = f / fps
        amp = max_amp * (0.3 + 0.7 * abs(math.sin(t * 0.8)))

        for phase in phases:
            for x in range(0, cx, 1):
                y_raw = amp * math.sin(0.07 * x + t * 2 + phase)
                y = int(cy / 2 + y_raw)
                if 0 <= y < cy:
                    canvas.set(x, y)
                    canvas.set(x, y + 1)

        clear_screen()
        print(canvas.frame())
        time.sleep(1 / fps)


# ---------------------------------------------------------------------------
# Animation 4 — DNA Double Helix with Cross-bars
# ---------------------------------------------------------------------------

def dna_helix(duration=10, fps=30, radius=10, rung_spacing=8):
    """Classic DNA double helix with cross-bars (base pairs).

    Two strands rotate in 3D; horizontal rungs connect them periodically.
    """
    canvas = Canvas()
    w, h = get_terminal_dims()
    cx, cy = w, int(h * 1.5)

    total_frames = duration * fps
    for f in range(total_frames):
        canvas.clear()
        angle_offset = (f / fps) * 1.2

        for t_step in range(-cy // 2, cy // 2, 2):
            angle = t_step * 0.14 + angle_offset

            # Strand A
            ax = int(cx / 2 + radius * math.cos(angle))
            ay = int(cy / 2 + t_step)

            # Strand B (180° opposite)
            bx = int(cx / 2 + radius * math.cos(angle + math.pi))
            by = ay

            # Draw strands
            if 0 <= ax < cx and 0 <= ay < cy:
                canvas.set(ax, ay)
                canvas.set(ax, ay + 1)
            if 0 <= bx < cx and 0 <= by < cy:
                canvas.set(bx, by)
                canvas.set(bx, by + 1)

            # Cross-bar (rung) every N steps
            if t_step % rung_spacing == 0:
                # Determine which strand is in front (z > 0 = in front)
                z_a = math.sin(angle)
                z_b = math.sin(angle + math.pi)
                for px in range(min(ax, bx), max(ax, bx) + 1):
                    # Only draw rung if at least one strand is "in front"
                    py = ay
                    if 0 <= py < cy and 0 <= px < cx:
                        # Dimmer rungs (every other dot)
                        if px % 2 == 0:
                            canvas.set(px, py)

        clear_screen()
        print(canvas.frame())
        time.sleep(1 / fps)


# ---------------------------------------------------------------------------
# Animation 5 — Vortex Helix (zooming spiral)
# ---------------------------------------------------------------------------

def vortex_helix(duration=12, fps=30, max_radius=20):
    """Triple helix spiraling outward then collapsing inward — vortex effect.

    Radius oscillates with time, creating a breathing vortex pattern.
    """
    canvas = Canvas()
    w, h = get_terminal_dims()
    cx, cy = w, h * 2
    phases = [0, 2 * math.pi / 3, 4 * math.pi / 3]

    frames = duration * fps
    for f in range(frames):
        canvas.clear()
        t = f / fps

        for phase in phases:
            for angle_step in range(0, 360 * 4, 3):
                a = math.radians(angle_step)
                r = max_radius * (0.3 + 0.7 * abs(math.sin(t * 0.5 + a * 0.3 + phase)))
                px = int(cx / 2 + r * math.cos(a + t * 0.8 + phase))
                py = int(cy / 2 + r * math.sin(a + t * 0.8 + phase) * 0.5)
                if 0 <= px < cx and 0 <= py < cy:
                    canvas.set(px, py)

        clear_screen()
        print(canvas.frame())
        time.sleep(1 / fps)


# ---------------------------------------------------------------------------
# Animation 6 — Sine Wave Interference (3 overlapping waves)
# ---------------------------------------------------------------------------

def wave_interference(duration=10, fps=30, amp=12):
    """Three sine waves with slightly different frequencies — interference pattern.

    Creates Moiré-like beats where the waves constructively/destructively
    interfere.
    """
    canvas = Canvas()
    w, h = get_terminal_dims()
    cx, cy = w, h * 2
    freqs = [0.06, 0.075, 0.09]  # slightly different → beating pattern
    phases = [0, 2 * math.pi / 3, 4 * math.pi / 3]

    frames = duration * fps
    for f in range(frames):
        canvas.clear()
        t = f / fps

        for freq, phase in zip(freqs, phases):
            for x in range(0, cx, 1):
                y_raw = amp * math.sin(freq * x + t * 2.5 + phase)
                y = int(cy / 2 + y_raw)
                if 0 <= y < cy:
                    canvas.set(x, y)

        # Also draw the "sum" wave (interference envelope)
        for x in range(0, cx, 1):
            y_sum = sum(
                amp * math.sin(freq * x + t * 2.5 + phase)
                for freq, phase in zip(freqs, phases)
            ) / len(freqs)
            y = int(cy / 2 + y_sum)
            if 0 <= y < cy:
                canvas.toggle(x, y)  # toggle creates bright nodes

        clear_screen()
        print(canvas.frame())
        time.sleep(1 / fps)


# ---------------------------------------------------------------------------
# Animation 7 — Triple Helix with Pulsing Thickness
# ---------------------------------------------------------------------------

def thick_helix(duration=10, fps=30, amplitude=14, wavelength=0.08):
    """Triple helix where strand thickness pulses over time.

    Each strand grows from 1-pixel to 3-pixel thick rhythmically.
    """
    canvas = Canvas()
    w, h = get_terminal_dims()
    cx, cy = w, h * 2
    phases = [0, 2 * math.pi / 3, 4 * math.pi / 3]

    frames = duration * fps
    for f in range(frames):
        canvas.clear()
        t = f / fps * 2
        thickness = 1 + int(2 * abs(math.sin(t * 1.5)))

        for phase in phases:
            for x in range(0, cx, 1):
                y_raw = amplitude * math.sin(wavelength * x + t + phase)
                y_center = int(cy / 2 + y_raw)
                for dy in range(-thickness, thickness + 1):
                    y = y_center + dy
                    if 0 <= y < cy:
                        canvas.set(x, y)

        clear_screen()
        print(canvas.frame())
        time.sleep(1 / fps)


# ---------------------------------------------------------------------------
# Animation 8 — Kaleidoscope Helix
# ---------------------------------------------------------------------------

def kaleidoscope_helix(duration=12, fps=30, arms=3, radius=16):
    """Triple helix arranged radially — kaleidoscope / mandala pattern.

    Each arm traces a sinusoidal radius as it rotates, creating a
    kaleidoscopic triple-spiral.
    """
    canvas = Canvas()
    w, h = get_terminal_dims()
    cx, cy = w, h * 2

    frames = duration * fps
    for f in range(frames):
        canvas.clear()
        t = f / fps * 0.6

        for arm in range(arms):
            base_angle = (2 * math.pi / arms) * arm
            for step in range(0, 720, 2):
                a = math.radians(step) + base_angle + t
                r_mod = radius * (0.5 + 0.5 * math.sin(step * 0.04 + t * 2))
                px = int(cx / 2 + r_mod * math.cos(a))
                py = int(cy / 2 + r_mod * math.sin(a) * 0.5)
                if 0 <= px < cx and 0 <= py < cy:
                    canvas.set(px, py)

        clear_screen()
        print(canvas.frame())
        time.sleep(1 / fps)


# ---------------------------------------------------------------------------
# Static test — just render one frame and dump
# ---------------------------------------------------------------------------

def static_test():
    """Render a single frame of classic helix (for debugging / testing)."""
    canvas = Canvas()
    w, h = get_terminal_dims()
    cx, cy = w, h * 2
    phases = [0, 2 * math.pi / 3, 4 * math.pi / 3]
    amplitude = 15
    wavelength = 0.07

    for phase in phases:
        for x in range(0, cx, 1):
            y_raw = amplitude * math.sin(wavelength * x + phase)
            y = int(cy / 2 + y_raw)
            canvas.set(x, y)
            canvas.set(x, y + 1)

    clear_screen()
    print(canvas.frame())
    print(f"\n[Static test: {cx}x{cy} braille canvas, {len(phases)} strands]")


# ---------------------------------------------------------------------------
# Menu & dispatch
# ---------------------------------------------------------------------------

ANIMATIONS = {
    "classic":    ("Classic Triple Helix",       classic_triple_helix),
    "rotating":   ("Rotating 3D Helix",          rotating_triple_helix),
    "morph":      ("Morphing Amplitude",         morph_helix),
    "dna":        ("DNA Double Helix + Rungs",   dna_helix),
    "vortex":     ("Vortex Spiral",              vortex_helix),
    "wave":       ("Wave Interference",          wave_interference),
    "thick":      ("Pulsing Thickness",          thick_helix),
    "kaleidoscope":("Kaleidoscope Helix",        kaleidoscope_helix),
    "static":     ("Static (single frame)",      static_test),
}


def show_menu():
    print("=" * 50)
    print("  DRAWILLE TRIPLE HELIX ANIMATIONS")
    print("=" * 50)
    print()
    for key, (desc, _) in ANIMATIONS.items():
        print(f"  {key:16s}  {desc}")
    print()
    print(f"  {'all':16s}  Loop through all animations")
    print(f"  {'quit':16s}  Exit")
    print()


def run_animation(name):
    if name not in ANIMATIONS:
        print(f"Unknown animation: {name}")
        return
    desc, fn = ANIMATIONS[name]
    print(f"\n  Playing: {desc}")
    print("  [Ctrl+C to skip]\n")
    time.sleep(0.5)
    try:
        fn()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n  Error: {e}")


def main():
    args = [a.lower() for a in sys.argv[1:]]

    if not args:
        show_menu()
        while True:
            try:
                choice = input("  > ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\nBye!")
                break
            if choice in ("quit", "q", "exit"):
                break
            elif choice == "all":
                for name in ANIMATIONS:
                    run_animation(name)
                show_menu()
            elif choice in ANIMATIONS:
                run_animation(choice)
                show_menu()
            elif choice:
                print(f"  Unknown: {choice}")
    elif args[0] == "all":
        for name in ANIMATIONS:
            run_animation(name)
    else:
        for name in args:
            run_animation(name)


if __name__ == "__main__":
    main()
