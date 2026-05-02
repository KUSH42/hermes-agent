"""Shared constants used by app.py and its mixin modules.

Skill names are validated against ``KNOWN_SKILLS``, which holds bare names
populated at runtime by ``theme.populate_skills``.  ``KNOWN_SLASH_COMMANDS``
is a registry-derived snapshot used by tests and slash-command metadata; the
submit-time unknown-command gate resolves against the live registry.
"""
from __future__ import annotations

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

# Mutable set updated at runtime after each skill scan.
# Keys are bare names (no / or $ prefix), e.g. "review-pr".
KNOWN_SKILLS: set[str] = set()


def refresh_known_skills(names: Iterable[str]) -> None:
    """Replace KNOWN_SKILLS contents (clear + update, two-op).

    Acceptable race window: keys.py reads KNOWN_SKILLS once per submitted
    user line — not a hot loop.  Worst case during the momentary empty window
    between clear() and update() is a single "Unknown skill" flash for a real
    skill; user retypes and it succeeds.  No data corruption possible.
    """
    new = {n.lstrip("/$") for n in names}
    KNOWN_SKILLS.clear()
    KNOWN_SKILLS.update(new)
    assert _KNOWN_SLASH_BARE.isdisjoint(KNOWN_SKILLS), (
        f"Skill name collides with built-in slash command: "
        f"{_KNOWN_SLASH_BARE & KNOWN_SKILLS}"
    )
