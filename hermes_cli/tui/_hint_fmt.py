"""Shared hint formatter for overlays and status bar."""
from __future__ import annotations

_SEP = "  ·  "


def hint_fmt(pairs: list[tuple[str, str]], key_color: str = "") -> str:
    """Format key/verb pairs as a dim hint line with standard separator.

    pairs: list of (key, verb) tuples. Zero-pair guard returns empty string.
    key_color: optional hex color for key badges (uses bold only when empty).
    Standard verbs: navigate, confirm, close (never dismiss/exit).
    """
    if not pairs:
        return ""
    parts = []
    for key, verb in pairs:
        if key_color:
            parts.append(f"[bold {key_color}]{key}[/] [dim]{verb}[/dim]")
        else:
            parts.append(f"[bold]{key}[/bold] [dim]{verb}[/dim]")
    return _SEP.join(parts)
