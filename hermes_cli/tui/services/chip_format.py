"""Canonical chip-label formatter.

Rules:
- Single ASCII letters → lowercase  (c, y, r, …)
- F-keys (f1..f12)    → uppercase   (F1, F2, …)
- Named word-keys      → Title-Case  (Enter, Esc, Tab, Space)
- Symbols / modifiers  → verbatim    (*, ?, ^c, shift+d, …)
"""
from __future__ import annotations

WORD_KEYS: frozenset[str] = frozenset({
    "enter", "esc", "tab", "space", "backspace", "delete",
    "up", "down", "left", "right",
    "home", "end", "pageup", "pagedown",
    "insert",
    "f1", "f2", "f3", "f4", "f5", "f6",
    "f7", "f8", "f9", "f10", "f11", "f12",
})

_SINGLE_LETTERS: frozenset[str] = frozenset("abcdefghijklmnopqrstuvwxyz")


def format_chip(key: str, label: str) -> str:
    """Return the canonical chip string for (key, label)."""
    k = key.strip()
    lk = k.lower()
    if lk in WORD_KEYS:
        if lk.startswith("f") and lk[1:].isdigit():
            return f"{lk.upper()} {label}"   # F1, F2, …
        return f"{lk.title()} {label}"       # Enter, Esc, Tab, …
    if len(lk) == 1 and lk in _SINGLE_LETTERS:
        return f"{lk} {label}"               # c, r, y, …
    # Symbols (*, ?, +), modifiers (^c), chords (shift+d) — verbatim.
    return f"{k} {label}"
