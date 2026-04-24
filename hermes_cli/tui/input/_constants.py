"""Shared constants and text utilities for the input subsystem."""
from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path

_HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
_HISTORY_FILE = _HERMES_HOME / ".hermes_history"
_MAX_HISTORY = 200

# Slash-command value regex — matches entire input "/cmd" with word+hyphen chars.
_SLASH_FULL_RE = re.compile(r"^/([\w-]*)$")


def _sanitize_input_text(text: str) -> str:
    """Normalize input text for the multiline prompt.

    Keeps newlines (multiline support), strips bare CR, converts tabs to space,
    and strips other Unicode control/format characters.
    """
    sanitized: list[str] = []
    for ch in text:
        if ch == "\r":
            continue
        if ch == "\t":
            sanitized.append(" ")
            continue
        if unicodedata.category(ch).startswith("C") and ch != "\n":
            continue
        sanitized.append(ch)
    return "".join(sanitized)
