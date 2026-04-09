"""
stream_effects.py — Streaming token reveal effects for Hermes CLI.

Activated via display.stream_effect in config.yaml (requires display.streaming: true).

Effects:
  none          — no effect (default)
  flash         — most recent token in accent+bold, reverts when next token arrives
  gradient_tail — each incoming token rendered as accent→text brightness gradient
  glow_settle   — tokens glow bright then dim to text color (background thread)
  decrypt       — completed words briefly scramble before resolving (background worker)
  shimmer       — a bright wave sweeps left→right across the partial line, repeating
  breathe       — entire partial line pulses between text and accent color (sine wave)

All effects:
  - Only apply to the current partial line (no cursor movement past a newline)
  - Revert/settle cleanly at on_line_complete() — no accent colors left at EOL
  - Reset on wrap (when visual width >= terminal width)
  - No-op on reasoning content
  - Compatible with both _RICH_RESPONSE=True and False branches
"""

from __future__ import annotations

import colorsys
import math
import random
import re
import shutil
import string
import sys
import threading
import time
import unicodedata
from typing import NamedTuple

_ANSI_RE = re.compile(r"\033\[[^m]*m")
_SCRAMBLE_CHARS = string.ascii_letters + string.digits + "!#$%&*@^~"

VALID_EFFECTS = frozenset({"none", "flash", "gradient_tail", "glow_settle", "decrypt", "shimmer", "breathe"})


# ── Utility helpers ───────────────────────────────────────────────────────────

def _vlen(s: str) -> int:
    """Visual column width after stripping ANSI escapes (EAW-aware)."""
    s = _ANSI_RE.sub("", s)
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def _hex_to_ansi(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return ""
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"\033[38;2;{r};{g};{b}m"
    except ValueError:
        return ""


def _lerp_color(hex_a: str, hex_b: str, t: float) -> str:
    """Linearly interpolate between two #RRGGBB colors, return ANSI escape."""
    ha, hb = hex_a.lstrip("#"), hex_b.lstrip("#")
    try:
        ra, ga, ba = int(ha[0:2], 16), int(ha[2:4], 16), int(ha[4:6], 16)
        rb, gb, bb = int(hb[0:2], 16), int(hb[2:4], 16), int(hb[4:6], 16)
    except (ValueError, IndexError):
        return ""
    r = int(ra + (rb - ra) * t)
    g = int(ga + (gb - ga) * t)
    b = int(ba + (bb - ba) * t)
    return f"\033[38;2;{r};{g};{b}m"


def _hex_from_ansi(text_ansi: str) -> str:
    """Extract #rrggbb from \\033[38;2;R;G;Bm, fallback to grey."""
    m = re.match(r"\033\[38;2;(\d+);(\d+);(\d+)m", text_ansi)
    if m:
        return "#{:02x}{:02x}{:02x}".format(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return "#aaaaaa"


def _get_accent_hex() -> str:
    try:
        from hermes_cli.skin_engine import get_active_skin
        return get_active_skin().get_color("ui_accent", "#FFBF00")
    except Exception:
        return "#FFBF00"


def _raw_write(s: str) -> None:
    sys.stdout.write(s)
    sys.stdout.flush()


def _hue_shifted_char(ch: str, base_hex: str, hue_offset: float, sat: float = 0.9, val: float = 1.0) -> str:
    """Return ch wrapped in an ANSI color whose hue is base_hex's hue + hue_offset."""
    h = base_hex.lstrip("#")
    try:
        r, g, b = int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255
    except (ValueError, IndexError):
        r, g, b = 1.0, 0.75, 0.0
    base_h, base_s, base_v = colorsys.rgb_to_hsv(r, g, b)
    nh = (base_h + hue_offset) % 1.0
    nr, ng, nb = colorsys.hsv_to_rgb(nh, sat, val)
    return f"\033[1m\033[38;2;{int(nr*255)};{int(ng*255)};{int(nb*255)}m{ch}\033[0m"


# ── Base class ────────────────────────────────────────────────────────────────

class StreamEffectRenderer:
    """Base (no-op) renderer — also used for effect='none'."""

    def __init__(self, cfg: dict, stream_lock: threading.Lock):
        self._lock = stream_lock
        self._effect = cfg.get("stream_effect", "none")
        if self._effect not in VALID_EFFECTS:
            print(
                f"[hermes] Unknown stream_effect {self._effect!r}, falling back to 'none'",
                file=sys.stderr,
            )
            self._effect = "none"
        color_hex = cfg.get("stream_effect_color", "").strip()
        self._accent_hex: str | None = color_hex if color_hex else None

    @property
    def active(self) -> bool:
        return self._effect != "none"

    def _accent(self) -> str:
        if self._accent_hex is None:
            self._accent_hex = _get_accent_hex()
        return self._accent_hex

    def _accent_ansi(self) -> str:
        return _hex_to_ansi(self._accent())

    def on_token(self, text: str, stream_raw_buf: str, vis_len: int,
                 text_ansi: str, term_width: int) -> None:
        """Called with lock held for each incoming token on the partial line."""

    def on_line_complete(self) -> None:
        """Called (with lock held by caller) when newline arrives.

        Must leave the terminal in a clean state — no accent/glow colors
        remaining on screen.  The caller will print \\n immediately after.
        """

    def on_turn_end(self) -> None:
        """Called at turn boundary (stream_delta(None)). Stop threads, flush."""

    def shutdown(self) -> None:
        """Called at CLI exit."""


# ── flash ─────────────────────────────────────────────────────────────────────

class _FlashEffect(StreamEffectRenderer):
    """Most recent token in accent+bold; reverts to text color when next token arrives.

    on_line_complete reverts the last token before the newline so no accent
    color bleeds onto the next line.
    """

    def __init__(self, cfg: dict, stream_lock: threading.Lock):
        super().__init__(cfg, stream_lock)
        self._prev_vlen: int = 0
        self._prev_raw: str = ""
        self._text_ansi: str = ""

    def _revert_prev(self) -> None:
        """Cursor-back and reprint previous token in text color."""
        if self._prev_vlen > 0 and self._prev_raw and self._text_ansi:
            _raw_write(
                f"\033[{self._prev_vlen}D"
                f"{self._text_ansi}{self._prev_raw}\033[0m"
            )
        self._prev_vlen = 0
        self._prev_raw = ""

    def on_token(self, text: str, stream_raw_buf: str, vis_len: int,
                 text_ansi: str, term_width: int) -> None:
        self._text_ansi = text_ansi
        incoming_vlen = _vlen(text)

        # Revert previously accented token (only if still on same line)
        if self._prev_vlen > 0 and vis_len > 0:
            self._revert_prev()
        else:
            self._prev_vlen = 0
            self._prev_raw = ""

        # Wrap guard
        if vis_len + incoming_vlen >= term_width - 1:
            _raw_write(f"{text_ansi}{text}\033[0m")
            return

        _raw_write(f"\033[1m{self._accent_ansi()}{text}\033[0m")
        self._prev_vlen = incoming_vlen
        self._prev_raw = text

    def on_line_complete(self) -> None:
        # Revert last accent token before the newline character is printed
        self._revert_prev()

    def on_turn_end(self) -> None:
        self._revert_prev()


# ── gradient_tail ─────────────────────────────────────────────────────────────

class _GradientTailEffect(StreamEffectRenderer):
    """Sliding accent gradient over the last N chars of the partial line.

    On every token arrival the full partial line is re-rendered: chars outside
    the tail window are in text color; chars inside the window lerp from text
    (oldest) to accent (newest).  The bright region slides forward with the
    stream — no background thread needed.

    Cursor model: cursor-back vis_len → clear → re-render.  One cursor, always
    relative to end of line.
    """

    def __init__(self, cfg: dict, stream_lock: threading.Lock):
        super().__init__(cfg, stream_lock)
        self._length: int = int(cfg.get("stream_effect_length", 12))
        self._full_line: str = ""
        self._vis_len: int = 0
        self._text_ansi: str = ""

    def _render(self, text_ansi: str, instant_settle: bool = False) -> str:
        """Render _full_line with gradient on the last _length chars."""
        if not self._full_line:
            return ""
        text_hex = _hex_from_ansi(text_ansi)
        accent_hex = self._accent()
        n = len(self._full_line)
        tail_start = max(0, n - self._length)
        out = []
        for i, ch in enumerate(self._full_line):
            if instant_settle or i < tail_start:
                out.append(f"{text_ansi}{ch}\033[0m")
            else:
                # position within tail: 0 = oldest (text color), 1 = newest (accent)
                t = (i - tail_start) / max(self._length - 1, 1)
                color = _lerp_color(text_hex, accent_hex, t)
                out.append(f"{color}{ch}\033[0m")
        return "".join(out)

    def on_token(self, text: str, stream_raw_buf: str, vis_len: int,
                 text_ansi: str, term_width: int) -> None:
        tok_vlen = _vlen(text)
        if vis_len + tok_vlen >= term_width - 1:
            _raw_write(f"{text_ansi}{text}\033[0m")
            return
        self._text_ansi = text_ansi
        self._full_line += text
        self._vis_len = vis_len + tok_vlen
        rendered = self._render(text_ansi)
        _raw_write(f"\033[{self._vis_len}D\033[K{rendered}")

    def on_line_complete(self) -> None:
        # Instant-settle: re-render in text color before \n
        if self._vis_len > 0 and self._full_line:
            rendered = self._render(self._text_ansi, instant_settle=True)
            _raw_write(f"\033[{self._vis_len}D\033[K{rendered}")
        self._full_line = ""
        self._vis_len = 0

    def on_turn_end(self) -> None:
        self.on_line_complete()


# ── glow_settle ───────────────────────────────────────────────────────────────

class _Span(NamedTuple):
    start: int    # visual column start within the line
    end: int      # visual column end (exclusive)
    born: int     # frame number when token was added


class _GlowSettleEffect(StreamEffectRenderer):
    """Each token glows at full accent brightness then dims to text color.

    State model:
      _full_line  — complete raw text of the current partial line (all tokens)
      _spans      — (start, end, born) for each active glow span within _full_line
      _vis_len    — current visual length of _full_line
      _frame      — monotonically increasing frame counter (incremented by worker)

    Worker re-renders the full partial line from _full_line each tick,
    coloring each character based on the span it falls in and the span age.

    on_line_complete does a final instant-settle re-render (all chars in text
    color) before the newline is printed, so nothing bleeds.
    """

    def __init__(self, cfg: dict, stream_lock: threading.Lock):
        super().__init__(cfg, stream_lock)
        self._speed: float = float(cfg.get("stream_effect_speed", 0.06))
        self._settle: int = int(cfg.get("stream_effect_settle_frames", 6))

        self._full_line: str = ""
        self._spans: list[_Span] = []
        self._vis_len: int = 0
        self._frame: int = 0
        self._text_ansi: str = ""

        self._stop_evt = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="glow-settle")
        self._thread.start()

    def _render_line(self, instant_settle: bool = False) -> str:
        """Build the full re-render of _full_line with glow coloring.

        instant_settle=True → ignore span ages, render everything in text color.
        Returns the complete ANSI string to write (does NOT include cursor movement).
        """
        if not self._full_line:
            return ""

        RST = "\033[0m"
        text_ansi = self._text_ansi
        accent = self._accent()
        text_hex = _hex_from_ansi(text_ansi)

        # Build a list of (char, col) pairs from _full_line
        # For each char, find its glow level from active spans
        out = []
        col = 0
        for ch in self._full_line:
            ch_vlen = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1

            if instant_settle:
                color = text_ansi
            else:
                # Find the most recent span that covers this col
                glow_t = 0.0  # 0=no glow, 1=full accent
                for span in self._spans:
                    if span.start <= col < span.end:
                        age = self._frame - span.born
                        t = min(age / max(self._settle, 1), 1.0)
                        glow_t = max(glow_t, 1.0 - t)  # newer = brighter
                if glow_t > 0.001:
                    color = _lerp_color(text_hex, accent, glow_t)
                    out.append(f"\033[1m{color}{ch}{RST}")
                    col += ch_vlen
                    continue
                else:
                    color = text_ansi

            out.append(f"{color}{ch}{RST}")
            col += ch_vlen

        return "".join(out)

    def _worker(self) -> None:
        while not self._stop_evt.wait(self._speed):
            with self._lock:
                if not self._spans or self._vis_len == 0:
                    continue
                self._frame += 1

                # Wrap guard
                tw = shutil.get_terminal_size((80, 24)).columns
                if self._vis_len >= tw - 1:
                    self._spans.clear()
                    continue

                # Expire fully settled spans
                self._spans = [
                    s for s in self._spans
                    if (self._frame - s.born) / max(self._settle, 1) < 1.0
                ]

                if not self._spans:
                    # All settled — one final re-render in plain text color
                    rendered = self._render_line(instant_settle=True)
                    _raw_write(f"\033[{self._vis_len}D\033[K{rendered}")
                    continue

                rendered = self._render_line()
                _raw_write(f"\033[{self._vis_len}D\033[K{rendered}")

    def on_token(self, text: str, stream_raw_buf: str, vis_len: int,
                 text_ansi: str, term_width: int) -> None:
        tok_vlen = _vlen(text)
        if vis_len + tok_vlen >= term_width - 1:
            # Wrap: instant-settle everything and print plain
            self._spans.clear()
            self._full_line = ""
            self._vis_len = 0
            _raw_write(f"{text_ansi}{text}\033[0m")
            return

        # Defensive: new line signal — reset any stale state from a missed on_line_complete
        if vis_len == 0:
            self._spans.clear()
            self._full_line = ""
            self._vis_len = 0

        self._text_ansi = text_ansi
        start_col = vis_len
        end_col = vis_len + tok_vlen
        self._spans.append(_Span(start=start_col, end=end_col, born=self._frame))
        self._full_line += text
        self._vis_len = end_col
        # Print the token in accent — worker will start dimming from here
        _raw_write(f"\033[1m{self._accent_ansi()}{text}\033[0m")

    def on_line_complete(self) -> None:
        # Called with lock held by caller.
        # Instant-settle: re-render full line in text color before the \n.
        if self._vis_len > 0 and self._full_line:
            rendered = self._render_line(instant_settle=True)
            _raw_write(f"\033[{self._vis_len}D\033[K{rendered}")
        self._spans.clear()
        self._full_line = ""
        self._vis_len = 0

    def on_turn_end(self) -> None:
        with self._lock:
            self.on_line_complete()

    def shutdown(self) -> None:
        self._stop_evt.set()
        self._thread.join(timeout=1.0)


# ── decrypt ───────────────────────────────────────────────────────────────────

class _DecryptEffect(StreamEffectRenderer):
    """Sliding-window per-character scramble effect.

    Each incoming character enters a scramble window (_window_size wide).
    The worker re-renders the full partial line every tick: chars inside the
    window show a fresh random glyph each tick with a brightness shift that
    starts at ±10% and proportionally approaches 0 over _frames ticks, then
    resolves to real text.  When the window is full a new char pushes the
    oldest one out (it resolves immediately).

    Every char is animated independently — no grouping or queuing.
    on_line_complete releases the lock so remaining window chars finish their
    natural animation for up to _settle_time seconds before forcing resolution.
    """

    def __init__(self, cfg: dict, stream_lock: threading.Lock):
        super().__init__(cfg, stream_lock)
        self._speed: float = float(cfg.get("stream_effect_speed", 0.06))
        self._frames: int = int(cfg.get("stream_effect_scramble_frames", 6))
        self._window_size: int = int(cfg.get("stream_effect_scramble_length", 8))
        self._settle_time: float = float(cfg.get("stream_effect_settle_time", 3.0))

        self._full_line: str = ""
        self._vis_len: int = 0
        self._text_ansi: str = ""
        # Each entry: [char_idx_in_full_line, real_char, age_in_ticks]
        # Oldest entry is at index 0; newest at the end.
        self._window: list[list] = []

        self._stop_evt = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="decrypt-fx")
        self._thread.start()

    def _render_line(self, text_ansi: str, instant_settle: bool = False) -> str:
        """Re-render _full_line; chars in the window show scrambled glyphs."""
        if not self._full_line:
            return ""
        if instant_settle or not self._window:
            return f"{text_ansi}{self._full_line}\033[0m"
        # Build per-char scramble map from current window state
        scramble: dict[int, float] = {
            entry[0]: 0.1 * (1.0 - min(entry[2] / max(self._frames, 1), 1.0))
            for entry in self._window
        }
        out = []
        for i, ch in enumerate(self._full_line):
            if i in scramble:
                bshift = scramble[i]
                val = min(1.0, max(0.5, 1.0 + random.uniform(-bshift, bshift)))
                out.append(_hue_shifted_char(
                    random.choice(_SCRAMBLE_CHARS),
                    self._accent(), random.uniform(-0.05, 0.05), val=val,
                ))
            else:
                out.append(f"{text_ansi}{ch}\033[0m")
        return "".join(out)

    def _worker(self) -> None:
        while not self._stop_evt.wait(self._speed):
            with self._lock:
                if not self._window or self._vis_len == 0:
                    continue
                tw = shutil.get_terminal_size((80, 24)).columns
                if self._vis_len >= tw - 1:
                    self._window.clear()
                    continue
                # Age all entries; evict those that have completed their animation
                for entry in self._window:
                    entry[2] += 1
                self._window = [e for e in self._window if e[2] < self._frames]
                rendered = self._render_line(self._text_ansi)
                _raw_write(f"\033[{self._vis_len}D\033[K{rendered}")

    def on_token(self, text: str, stream_raw_buf: str, vis_len: int,
                 text_ansi: str, term_width: int) -> None:
        self._text_ansi = text_ansi
        if vis_len >= term_width - 2:
            _raw_write(f"{text_ansi}{text}\033[0m")
            self._window.clear()
            return
        for ch in text:
            char_idx = len(self._full_line)
            self._full_line += ch
            self._vis_len += 1
            _raw_write(f"{text_ansi}{ch}\033[0m")
            self._window.append([char_idx, ch, 0])
            if len(self._window) > self._window_size:
                self._window.pop(0)   # oldest char resolved, evict it

    def on_line_complete(self) -> None:
        # Called (with lock held) for each mid-response newline — settle immediately,
        # no wait.  Next line is about to be printed; can't leave animation running.
        if self._window and self._vis_len > 0:
            _raw_write(f"\033[{self._vis_len}D\033[K{self._text_ansi}{self._full_line}\033[0m")
        self._window.clear()
        self._full_line = ""
        self._vis_len = 0

    def on_turn_end(self) -> None:
        # Called (without lock) at end of turn.  Let the worker age out any remaining
        # window chars naturally for up to _settle_time, then force-settle and clear.
        deadline = time.monotonic() + self._settle_time
        while time.monotonic() < deadline:
            time.sleep(0.05)
            with self._lock:
                if not self._window:
                    break
        with self._lock:
            if self._window and self._vis_len > 0:
                _raw_write(f"\033[{self._vis_len}D\033[K{self._text_ansi}{self._full_line}\033[0m")
            self._window.clear()
            self._full_line = ""
            self._vis_len = 0

    def shutdown(self) -> None:
        self._stop_evt.set()
        self._thread.join(timeout=1.0)



# ── shimmer ───────────────────────────────────────────────────────────────────

class _ShimmerEffect(StreamEffectRenderer):
    """A bright wave sweeps left→right across the current partial line, repeating.

    Each character's brightness is a linear falloff from the sweep peak —
    characters near the peak are rendered in accent color, the rest in text
    color.  The sweep restarts after passing off the right edge.

    Config keys:
      stream_effect_speed   — seconds per animation frame (default 0.05 → 20 fps)
      stream_effect_length  — half-width of the shimmer window in columns (default 8)
    """

    def __init__(self, cfg: dict, stream_lock: threading.Lock):
        super().__init__(cfg, stream_lock)
        self._speed: float = float(cfg.get("stream_effect_speed", 0.05))
        self._window: int = int(cfg.get("stream_effect_length", 8))

        self._full_line: str = ""
        self._vis_len: int = 0
        self._text_ansi: str = ""
        self._pos: float = 0.0   # current shimmer peak column (float for smooth movement)

        self._stop_evt = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="shimmer-fx")
        self._thread.start()

    def _render_line(self, text_ansi: str, instant_settle: bool = False) -> str:
        if not self._full_line:
            return ""
        text_hex = _hex_from_ansi(text_ansi)
        accent_hex = self._accent()
        out = []
        col = 0
        for ch in self._full_line:
            ch_vlen = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
            if instant_settle:
                out.append(f"{text_ansi}{ch}\033[0m")
            else:
                dist = abs(col + ch_vlen / 2 - self._pos)
                t = max(0.0, 1.0 - dist / max(self._window, 1))
                if t > 0.001:
                    color = _lerp_color(text_hex, accent_hex, t)
                    out.append(f"\033[1m{color}{ch}\033[0m")
                else:
                    out.append(f"{text_ansi}{ch}\033[0m")
            col += ch_vlen
        return "".join(out)

    def _worker(self) -> None:
        while not self._stop_evt.wait(self._speed):
            with self._lock:
                if self._vis_len == 0:
                    self._pos = 0.0
                    continue

                tw = shutil.get_terminal_size((80, 24)).columns
                if self._vis_len >= tw - 1:
                    continue

                # Advance peak; wrap back past left edge after clearing right edge
                self._pos += 1.5
                if self._pos > self._vis_len + self._window:
                    self._pos = -self._window

                rendered = self._render_line(self._text_ansi)
                _raw_write(f"\033[{self._vis_len}D\033[K{rendered}")

    def on_token(self, text: str, stream_raw_buf: str, vis_len: int,
                 text_ansi: str, term_width: int) -> None:
        tok_vlen = _vlen(text)
        if vis_len + tok_vlen >= term_width - 1:
            self._full_line = ""
            self._vis_len = 0
            _raw_write(f"{text_ansi}{text}\033[0m")
            return
        self._text_ansi = text_ansi
        self._full_line += text
        self._vis_len = vis_len + tok_vlen
        # Print in text color; worker applies shimmer on next frame
        _raw_write(f"{text_ansi}{text}\033[0m")

    def on_line_complete(self) -> None:
        if self._vis_len > 0 and self._full_line:
            rendered = self._render_line(self._text_ansi, instant_settle=True)
            _raw_write(f"\033[{self._vis_len}D\033[K{rendered}")
        self._full_line = ""
        self._vis_len = 0
        self._pos = 0.0

    def on_turn_end(self) -> None:
        with self._lock:
            self.on_line_complete()

    def shutdown(self) -> None:
        self._stop_evt.set()
        self._thread.join(timeout=1.0)


# ── breathe ───────────────────────────────────────────────────────────────────

class _BreatheEffect(StreamEffectRenderer):
    """The entire partial line pulses between text color and accent in unison,
    driven by a sine wave — like a slow, rhythmic breath.

    Config keys:
      stream_effect_speed   — seconds per animation frame (default 0.05 → 20 fps)
      stream_effect_period  — duration of one full breathe cycle in seconds (default 2.0)
    """

    def __init__(self, cfg: dict, stream_lock: threading.Lock):
        super().__init__(cfg, stream_lock)
        self._speed: float = float(cfg.get("stream_effect_speed", 0.05))
        self._period: float = float(cfg.get("stream_effect_period", 2.0))

        self._full_line: str = ""
        self._vis_len: int = 0
        self._text_ansi: str = ""
        self._t0: float = time.monotonic()

        self._stop_evt = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="breathe-fx")
        self._thread.start()

    def _lerp_t(self) -> float:
        """Current blend factor in [0, 1] based on sine wave phase."""
        elapsed = time.monotonic() - self._t0
        # Use a slightly asymmetric curve: spend more time near the dim end
        raw = (math.sin(2 * math.pi * elapsed / self._period) + 1) / 2
        # Scale so minimum is ~15% accent (never fully dim to text color)
        return 0.15 + raw * 0.85

    def _render_line(self, text_ansi: str, instant_settle: bool = False) -> str:
        if not self._full_line:
            return ""
        if instant_settle:
            return "".join(f"{text_ansi}{ch}\033[0m" for ch in self._full_line)
        text_hex = _hex_from_ansi(text_ansi)
        t = self._lerp_t()
        color = _lerp_color(text_hex, self._accent(), t)
        return "".join(f"{color}{ch}\033[0m" for ch in self._full_line)

    def _worker(self) -> None:
        while not self._stop_evt.wait(self._speed):
            with self._lock:
                if self._vis_len == 0:
                    continue
                tw = shutil.get_terminal_size((80, 24)).columns
                if self._vis_len >= tw - 1:
                    continue
                rendered = self._render_line(self._text_ansi)
                _raw_write(f"\033[{self._vis_len}D\033[K{rendered}")

    def on_token(self, text: str, stream_raw_buf: str, vis_len: int,
                 text_ansi: str, term_width: int) -> None:
        tok_vlen = _vlen(text)
        if vis_len + tok_vlen >= term_width - 1:
            self._full_line = ""
            self._vis_len = 0
            _raw_write(f"{text_ansi}{text}\033[0m")
            return
        self._text_ansi = text_ansi
        self._full_line += text
        self._vis_len = vis_len + tok_vlen
        # Print in text color; worker applies breathe on next frame
        _raw_write(f"{text_ansi}{text}\033[0m")

    def on_line_complete(self) -> None:
        if self._vis_len > 0 and self._full_line:
            rendered = self._render_line(self._text_ansi, instant_settle=True)
            _raw_write(f"\033[{self._vis_len}D\033[K{rendered}")
        self._full_line = ""
        self._vis_len = 0

    def on_turn_end(self) -> None:
        with self._lock:
            self.on_line_complete()

    def shutdown(self) -> None:
        self._stop_evt.set()
        self._thread.join(timeout=1.0)


# ── Factory ───────────────────────────────────────────────────────────────────

def make_stream_effect(cfg: dict, stream_lock: threading.Lock) -> StreamEffectRenderer:
    effect = cfg.get("stream_effect", "none")
    if effect == "flash":
        return _FlashEffect(cfg, stream_lock)
    if effect == "gradient_tail":
        return _GradientTailEffect(cfg, stream_lock)
    if effect == "glow_settle":
        return _GlowSettleEffect(cfg, stream_lock)
    if effect == "decrypt":
        return _DecryptEffect(cfg, stream_lock)
    if effect == "shimmer":
        return _ShimmerEffect(cfg, stream_lock)
    if effect == "breathe":
        return _BreatheEffect(cfg, stream_lock)
    return StreamEffectRenderer(cfg, stream_lock)
