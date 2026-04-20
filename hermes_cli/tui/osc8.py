"""OSC 8 hyperlink injection for Hermes TUI.

OSC 8 (hyperlinks) are terminal escape sequences that make text clickable.
Format: ESC]8;;URL ST TEXT ESC]8;; ST  (where ST = ESC backslash)

This module:
1. Detects whether the terminal supports OSC 8 (capability check).
2. Injects OSC 8 hyperlinks into ANSI-escaped strings where file paths and
   URLs appear.

See also: hermes_cli/tui/osc52_probe.py for OSC 52 clipboard capability detection.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

# Pattern matching absolute and relative file paths in text
_PATH_RE = re.compile(
    r"(?<![=:\w/])"                     # not preceded by = or word char or : or / (avoids key=path, https://path)
    r"(/[\w./\-_]+|\.{1,2}/[\w./\-_]+)" # /abs/path or ./rel/path or ../rel
    r"(?![\w])"                          # not followed by word char
)

# Pattern matching http/https URLs; trailing punctuation stripped separately
_URL_RE = re.compile(r'https?://[^\s<>"\']+')
_URL_TRAIL_RE = re.compile(r'[.,;:!?)\]>]+$')

# OSC 8 escape sequence builder
_OSC8_OPEN  = "\033]8;;{url}\033\\"
_OSC8_CLOSE = "\033]8;;\033\\"


@lru_cache(maxsize=1)
def _osc8_supported() -> bool:
    """Return True if the terminal is likely to support OSC 8 hyperlinks.

    Checks (in priority order):
    1. HERMES_OSC8 env var override ("1" = force on, "0" = force off).
    2. TERM_PROGRAM / VTE_VERSION / COLORTERM heuristics for known-good terminals.
    3. Falls back to False (safe default — plain text is always legible).

    Note: There is no reliable runtime probe for OSC 8 without controlling the
    terminal output pipeline (unlike OSC 52 which has a read-back mechanism).
    """
    override = os.environ.get("HERMES_OSC8", "").strip()
    if override == "1":
        return True
    if override == "0":
        return False

    # Known-good terminal programs
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    if term_program in ("iterm.app", "hyper", "wezterm", "ghostty", "vscode"):
        return True

    # VTE-based terminals (GNOME Terminal, Tilix, Kitty etc.)
    if os.environ.get("VTE_VERSION"):
        return True

    # Kitty
    if os.environ.get("KITTY_WINDOW_ID"):
        return True

    # Foot (Wayland)
    if term_program == "foot":
        return True

    return False


def inject_osc8(text: str, *, _enabled: bool | None = None) -> str:
    """Inject OSC 8 hyperlink sequences around file paths and URLs in *text*.

    *text* may contain ANSI colour/style codes — OSC 8 sequences are inserted
    around any detected path/URL span without disturbing existing codes.

    Args:
        text: ANSI-escaped string (from Rich console output or similar).
        _enabled: Override capability check (used in tests / write_with_source).

    Returns:
        String with OSC 8 sequences injected, or *text* unchanged if disabled
        or no paths/URLs found.
    """
    enabled = _enabled if _enabled is not None else _osc8_supported()
    if not enabled:
        return text

    def _path_replace(m: re.Match) -> str:
        path = m.group(0)
        url = f"file://{path}" if path.startswith("/") else f"file://{os.getcwd()}/{path}"
        return _OSC8_OPEN.format(url=url) + path + _OSC8_CLOSE

    def _url_replace(m: re.Match) -> str:
        raw = m.group(0)
        url = _URL_TRAIL_RE.sub("", raw)
        suffix = raw[len(url):]  # stripped trailing punctuation re-appended outside link
        return _OSC8_OPEN.format(url=url) + url + _OSC8_CLOSE + suffix

    text = _URL_RE.sub(_url_replace, text)
    text = _PATH_RE.sub(_path_replace, text)
    return text
