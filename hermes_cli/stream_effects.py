"""
hermes_cli/stream_effects.py — Token reveal FX for streaming output.

Two operating modes:
  Terminal mode: on_token() rewrites the current line to stdout via \\r + ANSI.
  TUI mode:      render_tui() returns a Rich Text for LiveLineWidget.render().

Public API (matches demo_stream_effects.py imports):
  make_stream_effect(cfg, lock=None) -> StreamEffectRenderer
  VALID_EFFECTS: list[str]
  _lerp_color(hex1, hex2, t) -> str
  _get_accent_hex() -> str
"""
from __future__ import annotations

import math
import random
import sys
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.text import Text

# ---------------------------------------------------------------------------
# Re-exports matching demo imports
# ---------------------------------------------------------------------------

from hermes_cli.tui.animation import lerp_color as _lerp_color  # noqa: F401

ERASE_EOL = "\033[K"

VALID_EFFECTS: list[str] = [
    "none",
    "flash",
    "gradient_tail",
    "glow_settle",
    "decrypt",
    "shimmer",
    "breathe",
]


def _get_accent_hex() -> str:
    try:
        from pathlib import Path
        from hermes_cli.tui.skin_loader import load_skin
        from hermes_cli.config import read_raw_config
        skin_path = read_raw_config().get("display", {}).get("skin", None)
        if skin_path:
            vars_ = load_skin(Path(skin_path))
            return vars_.get("accent", "#FFD700")
    except Exception:
        pass
    return "#FFD700"


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class StreamEffectRenderer:
    """Protocol base for all stream effect renderers."""

    active: bool = True
    needs_clock: bool = False

    def __init__(self, cfg: dict, lock: threading.Lock | None = None) -> None:
        self._lock = lock

    # -- Terminal mode -------------------------------------------------------

    def on_token(
        self,
        token: str,
        raw_buf: str,
        vis_len: int,
        text_ansi: str,
        term_width: int,
    ) -> None:
        """Write the styled token to stdout (full line rewrite via \\r)."""
        self._register_terminal(token, raw_buf)
        line = self._build_ansi_line(raw_buf + token, text_ansi)
        sys.stdout.write(f"\r{line}{ERASE_EOL}")
        sys.stdout.flush()

    def _register_terminal(self, token: str, raw_buf: str) -> None:
        """Pre-write hook — update any terminal-mode state before building the line."""

    def _build_ansi_line(self, full_text: str, text_ansi: str) -> str:
        """Return the full rewritten line as an ANSI string."""
        return f"{text_ansi}{full_text}\033[0m"

    def on_line_complete(self) -> None:
        """Newline received — reset per-line state."""

    def on_turn_end(self) -> None:
        """End of turn — reset all state."""

    # -- TUI mode ------------------------------------------------------------

    def register_token_tui(self, token: str) -> None:
        """Called by LiveLineWidget when a new token arrives."""

    def render_tui(self, buf: str, accent_hex: str, text_hex: str) -> "Text":
        """Return Rich Text for LiveLineWidget.render()."""
        from rich.text import Text
        return Text.from_ansi(buf)

    def tick_tui(self) -> bool:
        """Called at 15 Hz from AnimationClock. Return True if repaint needed."""
        return False

    def clear_tui(self) -> None:
        """Called when a line commits — reset per-line state."""


# ---------------------------------------------------------------------------
# NoneEffect
# ---------------------------------------------------------------------------

class NoneEffect(StreamEffectRenderer):
    active = False
    needs_clock = False


# ---------------------------------------------------------------------------
# FlashEffect
# ---------------------------------------------------------------------------

class FlashEffect(StreamEffectRenderer):
    """Most recent token rendered in accent+bold; prior text is text color."""

    active = True
    needs_clock = False

    def __init__(self, cfg: dict, lock: threading.Lock | None = None) -> None:
        super().__init__(cfg, lock)
        self._last_token_start: int = 0
        self._buf_len: int = 0

    def _register_terminal(self, token: str, raw_buf: str) -> None:
        self._last_token_start = len(raw_buf)

    def _build_ansi_line(self, full_text: str, text_ansi: str) -> str:
        prior = full_text[:self._last_token_start]
        token_part = full_text[self._last_token_start:]
        accent = _get_accent_hex()
        return (
            f"{text_ansi}\033[2m{prior}\033[0m"
            f"\033[1m\033[38;2;{_hex_to_rgb_ansi(accent)}m{token_part}\033[0m"
        )

    def on_line_complete(self) -> None:
        self._last_token_start = 0
        self._buf_len = 0

    def on_turn_end(self) -> None:
        self.on_line_complete()

    # TUI ----------------------------------------------------------------

    def register_token_tui(self, token: str) -> None:
        self._last_token_start = self._buf_len
        self._buf_len += len(token)

    def render_tui(self, buf: str, accent_hex: str, text_hex: str) -> "Text":
        from rich.text import Text
        t = Text()
        t.append(buf[:self._last_token_start], style=text_hex)
        t.append(buf[self._last_token_start:], style=f"bold {accent_hex}")
        return t

    def clear_tui(self) -> None:
        self._last_token_start = 0
        self._buf_len = 0


# ---------------------------------------------------------------------------
# GradientTailEffect
# ---------------------------------------------------------------------------

class GradientTailEffect(StreamEffectRenderer):
    """Last `length` chars rendered as a text→accent gradient (head→tail)."""

    active = True
    needs_clock = False

    def __init__(self, cfg: dict, lock: threading.Lock | None = None) -> None:
        super().__init__(cfg, lock)
        self._length: int = cfg.get("stream_effect_length", 16)

    def _build_ansi_line(self, full_text: str, text_ansi: str) -> str:
        length = self._length
        accent = _get_accent_hex()
        tail_start = max(0, len(full_text) - length)
        parts = [f"{text_ansi}{full_text[:tail_start]}\033[0m"]
        tail = full_text[tail_start:]
        n = max(len(tail), 1)
        for i, ch in enumerate(tail):
            frac = (i + 1) / n
            color = _lerp_color("#808080", accent, frac)  # dim→accent
            parts.append(f"\033[38;2;{_hex_to_rgb_ansi(color)}m{ch}\033[0m")
        return "".join(parts)

    # TUI ----------------------------------------------------------------

    def render_tui(self, buf: str, accent_hex: str, text_hex: str) -> "Text":
        from rich.text import Text
        length = self._length
        t = Text()
        tail_start = max(0, len(buf) - length)
        t.append(buf[:tail_start], style=text_hex)
        tail = buf[tail_start:]
        n = max(len(tail), 1)
        for i, ch in enumerate(tail):
            frac = (i + 1) / n
            color = _lerp_color(text_hex, accent_hex, frac)
            t.append(ch, style=color)
        return t


# ---------------------------------------------------------------------------
# GlowSettleEffect
# ---------------------------------------------------------------------------

class GlowSettleEffect(StreamEffectRenderer):
    """Tokens glow at accent on arrival and settle to text color over `settle_frames`."""

    active = True
    needs_clock = True

    def __init__(self, cfg: dict, lock: threading.Lock | None = None) -> None:
        super().__init__(cfg, lock)
        self._settle_frames: int = cfg.get("stream_effect_settle_frames", 6)
        self._tokens: list[tuple[int, int, int]] = []  # (start, end, age)
        self._buf_len: int = 0

    def _register_terminal(self, token: str, raw_buf: str) -> None:
        pass  # terminal mode uses buf reconstruct, not per-token tracking

    def _build_ansi_line(self, full_text: str, text_ansi: str) -> str:
        # Simple terminal: most recent token at accent, rest at text color
        return f"{text_ansi}{full_text}\033[0m"

    def on_line_complete(self) -> None:
        self._tokens.clear()
        self._buf_len = 0

    def on_turn_end(self) -> None:
        self.on_line_complete()

    # TUI ----------------------------------------------------------------

    def register_token_tui(self, token: str) -> None:
        start = self._buf_len
        self._buf_len += len(token)
        self._tokens.append((start, self._buf_len, 0))

    def tick_tui(self) -> bool:
        changed = False
        for i, (s, e, age) in enumerate(self._tokens):
            if age < self._settle_frames:
                self._tokens[i] = (s, e, age + 1)
                changed = True
        return changed

    def render_tui(self, buf: str, accent_hex: str, text_hex: str) -> "Text":
        from rich.text import Text
        t = Text(buf, style=text_hex)
        for start, end, age in self._tokens:
            brightness = max(0.0, 1.0 - age / max(self._settle_frames, 1))
            color = _lerp_color(text_hex, accent_hex, brightness)
            t.stylize(color, start, end)
        return t

    def clear_tui(self) -> None:
        self._tokens.clear()
        self._buf_len = 0


# ---------------------------------------------------------------------------
# DecryptEffect
# ---------------------------------------------------------------------------

_SCRAMBLE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#$%"


class DecryptEffect(StreamEffectRenderer):
    """Words briefly scramble then resolve character-by-character."""

    active = True
    needs_clock = True

    def __init__(self, cfg: dict, lock: threading.Lock | None = None) -> None:
        super().__init__(cfg, lock)
        self._scramble_frames: int = cfg.get("stream_effect_scramble_frames", 14)
        self._words: list[tuple[str, int]] = []  # (original_text, age)
        self._current_partial: str = ""

    def _build_ansi_line(self, full_text: str, text_ansi: str) -> str:
        return f"{text_ansi}{full_text}\033[0m"

    def on_line_complete(self) -> None:
        self._words.clear()
        self._current_partial = ""

    def on_turn_end(self) -> None:
        self.on_line_complete()

    # TUI ----------------------------------------------------------------

    def register_token_tui(self, token: str) -> None:
        self._current_partial += token
        while " " in self._current_partial:
            idx = self._current_partial.index(" ")
            word = self._current_partial[:idx + 1]  # include trailing space
            self._words.append((word, 0))
            self._current_partial = self._current_partial[idx + 1:]

    def tick_tui(self) -> bool:
        changed = False
        for i, (text, age) in enumerate(self._words):
            if age < self._scramble_frames:
                self._words[i] = (text, age + 1)
                changed = True
        return changed

    def render_tui(self, buf: str, accent_hex: str, text_hex: str) -> "Text":
        from rich.text import Text
        t = Text()
        for original, age in self._words:
            if age < self._scramble_frames:
                frac = age / self._scramble_frames
                resolved_n = int(len(original) * frac)
                word_text = original[:resolved_n]
                word_text += "".join(
                    random.choice(_SCRAMBLE_CHARS)
                    for _ in range(len(original) - resolved_n)
                )
                color = _lerp_color(text_hex, accent_hex, 1.0 - frac)
                t.append(word_text, style=color)
            else:
                t.append(original, style=text_hex)
        if self._current_partial:
            t.append(self._current_partial, style=f"bold {accent_hex}")
        return t

    def clear_tui(self) -> None:
        self._words.clear()
        self._current_partial = ""


# ---------------------------------------------------------------------------
# ShimmerEffect
# ---------------------------------------------------------------------------

class ShimmerEffect(StreamEffectRenderer):
    """Bright wave sweeps across text — static label animation in the demo."""

    active = True
    needs_clock = False

    def __init__(self, cfg: dict, lock: threading.Lock | None = None) -> None:
        super().__init__(cfg, lock)
        self._pos: float = -8.0
        self._window: int = 8

    def _register_terminal(self, token: str, raw_buf: str) -> None:
        self._pos += 1.5
        full_len = len(raw_buf) + len(token)
        if self._pos > full_len + self._window:
            self._pos = -float(self._window)

    def _build_ansi_line(self, full_text: str, text_ansi: str) -> str:
        accent = _get_accent_hex()
        text_hex = "#FFF8DC"
        parts = []
        for i, ch in enumerate(full_text):
            dist = abs(i - self._pos)
            t = max(0.0, 1.0 - dist / max(self._window, 1))
            if t > 0.001:
                color = _lerp_color(text_hex, accent, t)
                parts.append(f"\033[1m\033[38;2;{_hex_to_rgb_ansi(color)}m{ch}\033[0m")
            else:
                parts.append(f"{text_ansi}{ch}\033[0m")
        return "".join(parts)

    def on_line_complete(self) -> None:
        self._pos = -float(self._window)

    def on_turn_end(self) -> None:
        self.on_line_complete()

    def render_tui(self, buf: str, accent_hex: str, text_hex: str) -> "Text":
        from rich.text import Text
        return Text.from_ansi(buf)


# ---------------------------------------------------------------------------
# BreatheEffect
# ---------------------------------------------------------------------------

class BreatheEffect(StreamEffectRenderer):
    """Text pulses between text and accent color."""

    active = True
    needs_clock = False

    def __init__(self, cfg: dict, lock: threading.Lock | None = None) -> None:
        super().__init__(cfg, lock)
        import time
        self._t0: float = time.monotonic()
        self._period: float = cfg.get("stream_effect_period", 0.75)

    def _build_ansi_line(self, full_text: str, text_ansi: str) -> str:
        import time
        accent = _get_accent_hex()
        text_hex = "#FFF8DC"
        elapsed = time.monotonic() - self._t0
        t = (math.sin(2 * math.pi * elapsed / self._period) + 1) / 2
        t = 0.15 + t * 0.85
        color = _lerp_color(text_hex, accent, t)
        parts = [f"\033[38;2;{_hex_to_rgb_ansi(color)}m{ch}\033[0m" for ch in full_text]
        return "".join(parts)

    def on_line_complete(self) -> None:
        pass

    def on_turn_end(self) -> None:
        pass

    def render_tui(self, buf: str, accent_hex: str, text_hex: str) -> "Text":
        from rich.text import Text
        return Text.from_ansi(buf)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_EFFECT_MAP: dict[str, type[StreamEffectRenderer]] = {
    "none": NoneEffect,
    "flash": FlashEffect,
    "gradient_tail": GradientTailEffect,
    "glow_settle": GlowSettleEffect,
    "decrypt": DecryptEffect,
    "shimmer": ShimmerEffect,
    "breathe": BreatheEffect,
}


def make_stream_effect(
    cfg: dict,
    lock: threading.Lock | None = None,
) -> StreamEffectRenderer:
    """Return a StreamEffectRenderer for the given config dict."""
    name = cfg.get("stream_effect", "none")
    cls = _EFFECT_MAP.get(name, NoneEffect)
    return cls(cfg, lock)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hex_to_rgb_ansi(hex_color: str) -> str:
    """Convert #rrggbb to 'r;g;b' for ANSI 24-bit color sequences."""
    h = hex_color.lstrip("#")
    if len(h) == 6:
        r = int(h[0:2], 16)
        g = int(h[2:4], 16)
        b = int(h[4:6], 16)
        return f"{r};{g};{b}"
    return "255;215;0"  # fallback gold
