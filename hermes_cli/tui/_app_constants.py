"""Shared constants used by app.py and its mixin modules.

Skill names are validated against ``_known_skills``, which holds bare names
populated at runtime by ``theme.populate_skills``.  Access via
``get_known_skills()``; update via ``refresh_known_skills()``.

``KNOWN_SLASH_COMMANDS`` is a registry-derived snapshot used by tests and
slash-command metadata; the submit-time unknown-command gate resolves against
the live registry.
"""
from __future__ import annotations

import threading
from typing import Iterable

from hermes_cli.commands import COMMAND_REGISTRY


def _build_known_slash_commands() -> frozenset[str]:
    names = {"/loop"}  # Agent-native slash command not present in COMMAND_REGISTRY.
    for cmd in COMMAND_REGISTRY:
        if cmd.gateway_only:
            continue
        names.add(f"/{cmd.name}")
        names.update(f"/{alias}" for alias in cmd.aliases)
    return frozenset(names)


KNOWN_SLASH_COMMANDS: frozenset[str] = _build_known_slash_commands()

# Bare-name forms of KNOWN_SLASH_COMMANDS, computed once at import.
# Used to guard against skill names colliding with built-in commands.
_KNOWN_SLASH_BARE: frozenset[str] = frozenset(
    c.lstrip("/") for c in KNOWN_SLASH_COMMANDS
)

# SVC-9: thread-safe skill set — replace-not-mutate under lock.
# All readers must use get_known_skills(); direct access to _known_skills
# captures the frozenset reference atomically (single pointer read in CPython).
_KNOWN_SKILLS_LOCK = threading.Lock()
_known_skills: frozenset[str] = frozenset()


def get_known_skills() -> frozenset[str]:
    """Return current snapshot; always a complete, consistent set."""
    return _known_skills


def refresh_known_skills(names: Iterable[str]) -> None:
    """Replace known skills atomically. Raises ValueError on slash-command collision."""
    new_known = frozenset(n.lstrip("/$") for n in names)
    if not _KNOWN_SLASH_BARE.isdisjoint(new_known):
        raise ValueError(
            f"refresh_known_skills: overlap with _KNOWN_SLASH_BARE: "
            f"{_KNOWN_SLASH_BARE & new_known!r}"
        )
    with _KNOWN_SKILLS_LOCK:
        global _known_skills
        _known_skills = new_known
