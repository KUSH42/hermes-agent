"""OSC 52 clipboard write — emits escape sequence to the terminal device.

Write-only: sets the terminal's clipboard without any readback.  Compatible
with kitty, WezTerm, Ghostty, iTerm2, alacritty, xterm ≥203, tmux (requires
set-clipboard on), and Windows Terminal.

Must only be called from the Textual event loop thread
(os.write to stdout.fileno() is safe during TUI operation).
"""
from __future__ import annotations

import base64
import logging
import os
import sys

_log = logging.getLogger(__name__)

# Terminals imposing a conservative base64 limit (e.g. xterm default: 74994 bytes).
# 50 000 UTF-8 bytes → ≤ 68 000 base64 bytes — stays under the xterm cap.
_MAX_RAW_BYTES = 50_000


def write(text: str) -> bool:
    """Emit OSC 52 clipboard-write sequence for *text*.

    Returns True if the sequence was written to the terminal fd.  Returns False
    (and logs at DEBUG) if the fd write fails for any reason.  Never raises.

    Truncates to _MAX_RAW_BYTES and logs a WARNING if the payload is larger.
    """
    raw = text.encode("utf-8", errors="replace")
    if len(raw) > _MAX_RAW_BYTES:
        _log.warning(
            "OSC 52 payload truncated: %d bytes → %d (terminal base64 cap)",
            len(raw),
            _MAX_RAW_BYTES,
        )
        # Decode with errors="ignore" to drop any incomplete tail codepoint
        # before re-encoding, so the result is valid UTF-8 rather than a
        # byte sequence that straddles a multi-byte character boundary.
        raw = raw[:_MAX_RAW_BYTES].decode("utf-8", errors="ignore").encode("utf-8")

    b64 = base64.b64encode(raw).decode("ascii")
    seq = f"\033]52;c;{b64}\a"

    # tmux requires DCS passthrough so the sequence reaches the outer terminal.
    if os.environ.get("TMUX"):
        seq = f"\033Ptmux;\033{seq}\033\\"

    try:
        os.write(sys.stdout.fileno(), seq.encode("ascii"))
        return True
    except Exception:  # fd closed, redirect, unsupported OS — silently skip
        _log.debug("OSC 52 write failed", exc_info=True)
        return False
