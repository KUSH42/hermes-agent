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
from dataclasses import dataclass

_log = logging.getLogger(__name__)

# Terminals imposing a conservative base64 limit (e.g. xterm default: 74994 bytes).
# 50 000 UTF-8 bytes → ≤ 68 000 base64 bytes — stays under the xterm cap.
_MAX_RAW_BYTES = 50_000


@dataclass(frozen=True)
class CopyResult:
    """Structured outcome of an OSC 52 or clipboard write attempt."""

    success: bool
    bytes_written: int
    bytes_input: int
    truncated: bool

    @property
    def truncation_ratio(self) -> float:
        """Fraction of input bytes that were written.

        Returns 1.0 when bytes_input == 0 (empty string; nothing to truncate).
        """
        return self.bytes_written / self.bytes_input if self.bytes_input else 1.0


def write(text: str) -> CopyResult:
    """Emit OSC 52 clipboard-write sequence for *text*.

    Returns a CopyResult describing success, byte counts, and whether the
    payload was truncated to _MAX_RAW_BYTES.  Never raises.

    Truncates to _MAX_RAW_BYTES and logs a WARNING if the payload is larger.
    """
    input_bytes = text.encode("utf-8", errors="replace")
    truncated = len(input_bytes) > _MAX_RAW_BYTES
    raw = input_bytes
    if truncated:
        _log.warning(
            "OSC 52 payload truncated: %d bytes → %d (terminal base64 cap)",
            len(input_bytes),
            _MAX_RAW_BYTES,
        )
        # Decode with errors="ignore" to drop any incomplete tail codepoint
        # before re-encoding, so the result is valid UTF-8 rather than a
        # byte sequence that straddles a multi-byte character boundary.
        raw = input_bytes[:_MAX_RAW_BYTES].decode("utf-8", errors="ignore").encode("utf-8")

    b64 = base64.b64encode(raw).decode("ascii")
    seq = f"\033]52;c;{b64}\a"

    # tmux requires DCS passthrough so the sequence reaches the outer terminal.
    if os.environ.get("TMUX"):
        seq = f"\033Ptmux;\033{seq}\033\\"

    try:
        os.write(sys.stdout.fileno(), seq.encode("ascii"))
        return CopyResult(
            success=True,
            bytes_written=len(raw),
            bytes_input=len(input_bytes),
            truncated=truncated,
        )
    except OSError:
        # OSC 52 write failures are best-effort; log and report failure to caller.
        _log.debug("OSC 52 write failed", exc_info=True)
        return CopyResult(success=False, bytes_written=0, bytes_input=len(input_bytes), truncated=False)
