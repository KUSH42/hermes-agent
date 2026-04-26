"""Completion trigger detection — regex-based, runs on every watch_value call.

``detect_context(value, cursor)`` is the hot path: cheap enough to call on
every keystroke.  Returns a ``CompletionTrigger`` describing which context
applies and what fragment the user has typed so far.

Trigger rules
-------------
``/cmd``       → ``SLASH_COMMAND`` when the entire input is a slash followed
                 by ``[\\w-]*``.  Hyphen is explicit so ``/review-pr`` etc.
                 match during typing.  ``foo /h`` does NOT trigger — the slash
                 must be at position 0.

``$fragment``  → ``SKILL_INVOKE`` when the entire input is a dollar sign
                 followed by ``[\\w-]*``, and the input mode is not BASH.
                 The skill picker IS the completion surface; the inline
                 completion overlay does not mount for this context.

``@fragment``  → ``PATH_REF`` when ``@`` appears at a token boundary
                 (start-of-string or preceded by whitespace).  ``foo@bar``
                 does NOT trigger; ``@bar`` or ``hello @bar`` do.

Everything else → ``NATURAL`` (no completion).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class CompletionContext(Enum):
    NONE = 0
    SLASH_COMMAND = 1
    PATH_REF = 2       # triggered by @fragment
    NATURAL = 3
    PLAIN_PATH_REF = 4 # triggered by ./fragment, ../fragment, ~/fragment
    ABSOLUTE_PATH_REF = 5 # triggered by /abs/path after whitespace
    SLASH_SUBCOMMAND = 6  # triggered by "/cmd fragment" — arg completion
    SKILL_INVOKE = 7   # triggered by $fragment in non-BASH mode; picker is the completion surface


@dataclass(frozen=True, slots=True)
class CompletionTrigger:
    context: CompletionContext
    fragment: str   # the typed portion after the trigger character
    start: int      # index of the first char of the fragment in value
    parent_command: str = ""  # populated only for SLASH_SUBCOMMAND context


# ``[\w-]`` so commands like /review-pr, /commit-msg, /skill-scan match.
# The character class explicitly includes hyphen, which ``\w`` does not.
_SLASH_RE = re.compile(r"^/([\w-]*)$")
# Subcommand context: exactly one space after command, then optional fragment.
# Must be checked before _SLASH_RE since it is a strict superset when space is present.
_SLASH_SUBCMD_RE = re.compile(r"^/([\w-]+)\s+([\w-]*)$")
# Skill invocation: $fragment — anchored so "echo $re" does NOT trigger.
# Space after the name breaks the match (e.g. "$foo " → no longer matches).
_SKILL_RE = re.compile(r"^\$([\w-]*)$")
_PATH_RE = re.compile(r"(?:^|\s)@([\w./\-]*)$")     # anchored to cursor head
_PLAIN_PATH_RE = re.compile(r"(?:^|\s)((?:\.\.?|~)(?:/[\w./\-]*)?)$")  # ./x, ../x, ~/x, ., ..
_ABS_PATH_RE = re.compile(r"(?:^|\s)(/[\w.\-]+(?:/[\w./\-]*)?)$")
# Slash-command invocation (e.g. "/caveman /tui") — args are NOT filesystem paths
_SLASH_CMD_INVOCATION_RE = re.compile(r"^/[\w-]+\s")


def detect_context(value: str, cursor: int, *, bash_mode: bool = False) -> CompletionTrigger:
    """Return the ``CompletionTrigger`` active at *cursor* in *value*.

    Only the text to the left of the cursor is inspected so mid-word
    completions work correctly (e.g. ``detect_context("hello @s world", 8)``
    picks up the ``@s`` fragment even though more text follows).

    ``bash_mode=True`` suppresses ``SKILL_INVOKE`` (``$`` is a shell variable
    prefix in BASH mode and must not trigger the skill picker).
    """
    head = value[:cursor]

    # SLASH_SUBCOMMAND must be checked before SLASH_COMMAND so that
    # "/cmd fragment" takes priority over the bare "/cmd" pattern.
    m = _SLASH_SUBCMD_RE.match(head)
    if m:
        parent_cmd = m.group(1)
        fragment = m.group(2)
        start = m.start(2)
        return CompletionTrigger(
            CompletionContext.SLASH_SUBCOMMAND, fragment, start,
            parent_command=parent_cmd,
        )

    m = _SLASH_RE.match(head)
    if m:
        return CompletionTrigger(CompletionContext.SLASH_COMMAND, m.group(1), 1)

    # SKILL_INVOKE: $fragment at column 0, suppressed in BASH mode.
    if not bash_mode:
        m = _SKILL_RE.match(head)
        if m:
            return CompletionTrigger(CompletionContext.SKILL_INVOKE, m.group(1), 1)

    m = _PATH_RE.search(head)
    if m:
        return CompletionTrigger(
            context=CompletionContext.PATH_REF,
            fragment=m.group(1),
            start=m.start(1),
        )

    m = _PLAIN_PATH_RE.search(head)
    if m:
        full_path = m.group(1)              # e.g. "./src/main" or "../foo" or "~/bar" or "." or ".."
        slash_idx = full_path.find("/")
        if slash_idx >= 0:
            fragment = full_path[slash_idx + 1:]  # part after the first "/"
        else:
            fragment = ""  # bare "." or ".." with no slash
        return CompletionTrigger(
            context=CompletionContext.PLAIN_PATH_REF,
            fragment=fragment,
            start=m.start(1),              # position of '.' or '~' in the input
        )

    m = _ABS_PATH_RE.search(head)
    if m:
        full_path = m.group(1)
        if not head.startswith(full_path) and not _SLASH_CMD_INVOCATION_RE.match(head):
            return CompletionTrigger(
                context=CompletionContext.ABSOLUTE_PATH_REF,
                fragment=full_path,
                start=m.start(1),
            )

    # NATURAL has no fragment — it's the absence of a completion context,
    # not a 0-length match against the whole head.
    return CompletionTrigger(CompletionContext.NATURAL, "", 0)
