"""Shared constants used by app.py and its mixin modules."""
from __future__ import annotations

KNOWN_SLASH_COMMANDS: frozenset[str] = frozenset([
    "/loop", "/schedule", "/anim", "/yolo", "/verbose",
    "/model", "/reasoning", "/skin", "/fast", "/easteregg",
    "/help", "/queue", "/btw", "/clear",
])
