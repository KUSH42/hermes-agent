"""Shared constants used by app.py and its mixin modules.

Skill names are validated against ``KNOWN_SKILLS``, which holds bare names
populated at runtime by ``theme.populate_skills``. Access via
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

# SVC-9: keep a mutable compatibility surface for tests and older callers,
# but update it under lock so writes remain coherent.
_KNOWN_SKILLS_LOCK = threading.Lock()
KNOWN_SKILLS: set[str] = set()


def get_known_skills() -> frozenset[str]:
    """Return current snapshot; always a complete, consistent set."""
    with _KNOWN_SKILLS_LOCK:
        return frozenset(KNOWN_SKILLS)


def refresh_known_skills(names: Iterable[str]) -> None:
    """Replace known skills atomically. Raises AssertionError on slash-command collision."""
    new_known = frozenset(n.lstrip("/$") for n in names)
    if not _KNOWN_SLASH_BARE.isdisjoint(new_known):
        overlap = sorted(_KNOWN_SLASH_BARE & new_known)
        raise AssertionError(
            f"skill name collides with built-in slash command: {overlap!r}"
        )
    with _KNOWN_SKILLS_LOCK:
        KNOWN_SKILLS.clear()
        KNOWN_SKILLS.update(new_known)
