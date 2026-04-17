"""DiffRenderer — unified diff format renderer with word-diff support."""
from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING, ClassVar

from hermes_cli.tui.body_renderers.base import BodyRenderer

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload

_FILE_HEADER_RE = re.compile(r"^(---|\+\+\+)\s+")
_HUNK_HEADER_RE = re.compile(r"^@@.*@@")


def _word_diff(removed: str, added: str):
    """Apply word-level diff between removed/added lines. Returns (rem_t, add_t) rich Texts."""
    from rich.text import Text

    rem_words = removed.split()
    add_words = added.split()
    sm = difflib.SequenceMatcher(None, rem_words, add_words, autojunk=False)

    rem_t = Text()
    add_t = Text()

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            rem_t.append(" ".join(rem_words[i1:i2]) + " ")
            add_t.append(" ".join(add_words[j1:j2]) + " ")
        elif tag == "replace":
            rem_t.append(" ".join(rem_words[i1:i2]) + " ", style="bold underline")
            add_t.append(" ".join(add_words[j1:j2]) + " ", style="bold underline")
        elif tag == "delete":
            rem_t.append(" ".join(rem_words[i1:i2]) + " ", style="bold underline")
        elif tag == "insert":
            add_t.append(" ".join(add_words[j1:j2]) + " ", style="bold underline")

    return rem_t, add_t


class DiffRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = False

    def __init__(self, payload: "ToolPayload", cls_result: "ClassificationResult") -> None:
        super().__init__(payload, cls_result)
        self._collapsed_hunks: set[int] = set()

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        from hermes_cli.tui.tool_payload import ResultKind
        return cls_result.kind == ResultKind.DIFF

    def build(self):
        """Parse unified diff and build a Rich Text renderable."""
        from rich.text import Text

        raw = self.payload.output_raw or ""
        lines = raw.splitlines()

        result = Text()
        hunk_idx = -1
        total_lines = len(lines)
        hunk_count = sum(1 for l in lines if _HUNK_HEADER_RE.match(l))

        # Auto-collapse: >40 lines OR >3 hunks
        auto_collapse = total_lines > 40 or hunk_count > 3

        i = 0
        pending_removed: str | None = None

        while i < len(lines):
            line = lines[i]

            # File headers (--- / +++)
            if _FILE_HEADER_RE.match(line):
                # Try to extract path pair
                if line.startswith("---"):
                    # Look ahead for +++ line
                    path_a = re.sub(r"^---\s+(?:[ab]/)?", "", line).strip()
                    result.append(f"{path_a}", style="bold")
                    result.append("\n")
                elif line.startswith("+++"):
                    pass  # skip +++ line (already shown in ---)
                i += 1
                continue

            # Hunk headers
            if _HUNK_HEADER_RE.match(line):
                hunk_idx += 1
                is_collapsed = auto_collapse and hunk_idx > 0
                if is_collapsed:
                    self._collapsed_hunks.add(hunk_idx)

                result.append(f"── hunk {line} ──", style="dim")
                result.append("\n")

                if is_collapsed:
                    # Skip this hunk's content
                    i += 1
                    while i < len(lines) and not _HUNK_HEADER_RE.match(lines[i]) and not _FILE_HEADER_RE.match(lines[i]):
                        i += 1
                    continue

                i += 1
                continue

            # Added lines
            if line.startswith("+"):
                content = line[1:]
                if pending_removed is not None:
                    # Word-diff between pending_removed and this added line
                    rem_t, add_t = _word_diff(pending_removed, content)
                    result.append("-", style="red")
                    result.append_text(rem_t)
                    result.append("\n")
                    result.append("+", style="green")
                    result.append_text(add_t)
                    result.append("\n")
                    pending_removed = None
                else:
                    result.append("+", style="green")
                    result.append(content, style="on #1a3a1a")
                    result.append("\n")
                i += 1
                continue

            # Removed lines
            if line.startswith("-") and not line.startswith("---"):
                if pending_removed is not None:
                    # Flush previous removed without word diff
                    result.append("-", style="red")
                    result.append(pending_removed, style="on #3a1a1a")
                    result.append("\n")
                pending_removed = line[1:]
                i += 1
                continue

            # Context lines — flush any pending removed first
            if pending_removed is not None:
                result.append("-", style="red")
                result.append(pending_removed, style="on #3a1a1a")
                result.append("\n")
                pending_removed = None

            result.append(line, style="dim")
            result.append("\n")
            i += 1

        # Flush any trailing pending_removed
        if pending_removed is not None:
            result.append("-", style="red")
            result.append(pending_removed, style="on #3a1a1a")
            result.append("\n")

        return result


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    DiffRenderer.kind = ResultKind.DIFF


_set_kind()
