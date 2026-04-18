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


@dataclass(frozen=True, slots=True)
class CompletionTrigger:
    context: CompletionContext
    fragment: str   # the typed portion after the trigger character
    start: int      # index of the first char of the fragment in value


# ``[\w-]`` so commands like /review-pr, /commit-msg, /skill-scan match.
# The character class explicitly includes hyphen, which ``\w`` does not.
_SLASH_RE = re.compile(r"^/([\w-]*)$")
_PATH_RE = re.compile(r"(?:^|\s)@([\w./\-]*)$")     # anchored to cursor head
_PLAIN_PATH_RE = re.compile(r"(?:^|\s)((?:\.\.?|~)(?:/[\w./\-]*)?)$")  # ./x, ../x, ~/x, ., ..
_ABS_PATH_RE = re.compile(r"(?:^|\s)(/[\w.\-]+(?:/[\w./\-]*)?)$")


def detect_context(value: str, cursor: int) -> CompletionTrigger:
    """Return the ``CompletionTrigger`` active at *cursor* in *value*.

    Only the text to the left of the cursor is inspected so mid-word
    completions work correctly (e.g. ``detect_context("hello @s world", 8)``
    picks up the ``@s`` fragment even though more text follows).
    """
    head = value[:cursor]

    m = _SLASH_RE.match(head)
    if m:
        return CompletionTrigger(CompletionContext.SLASH_COMMAND, m.group(1), 1)

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
        if not head.startswith(full_path):
            return CompletionTrigger(
                context=CompletionContext.ABSOLUTE_PATH_REF,
                fragment=full_path,
                start=m.start(1),
            )

    # NATURAL has no fragment — it's the absence of a completion context,
    # not a 0-length match against the whole head.
    return CompletionTrigger(CompletionContext.NATURAL, "", 0)
