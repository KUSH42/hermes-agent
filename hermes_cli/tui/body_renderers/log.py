"""LogRenderer — log line formatter with level token colorization."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, ClassVar

from hermes_cli.tui.body_renderers.base import BodyRenderer

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload

_LEVEL_RE = re.compile(
    r"\b(INFO|WARN(?:ING)?|ERROR|DEBUG|TRACE|FATAL)\b"
)

_LEVEL_STYLES = {
    "INFO": "$primary",
    "WARN": "$warning",
    "WARNING": "$warning",
    "ERROR": "$error",
    "DEBUG": "$text-muted",
    "TRACE": "$text-muted",
    "FATAL": "bold $error",
}

# Fallback colors for when CSS vars not available
_LEVEL_COLORS = {
    "INFO": "blue",
    "WARN": "yellow",
    "WARNING": "yellow",
    "ERROR": "red",
    "DEBUG": "dim",
    "TRACE": "dim",
    "FATAL": "bold red",
}

_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})"
)


class LogRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = False
    _timestamps_visible: bool = True

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        from hermes_cli.tui.tool_payload import ResultKind
        return cls_result.kind == ResultKind.LOG

    def build(self):
        """Build Rich Text with colorized log levels and dim timestamps."""
        from rich.text import Text

        raw = self.payload.output_raw or ""
        result = Text()

        for line in raw.splitlines():
            line_t = Text()
            rest = line

            # Timestamp prefix
            ts_m = _TS_RE.match(rest)
            if ts_m:
                ts = ts_m.group(1)
                if self._timestamps_visible:
                    line_t.append(ts[:19], style="dim")
                    line_t.append(" ")
                rest = rest[len(ts_m.group(0)):].lstrip()

            # Find level token
            level_m = _LEVEL_RE.search(rest)
            if level_m:
                before = rest[:level_m.start()]
                level_token = level_m.group(0)
                after = rest[level_m.end():]
                style = _LEVEL_COLORS.get(level_token, "")
                if before:
                    line_t.append(before)
                line_t.append(level_token, style=style)
                line_t.append(after)
            else:
                line_t.append(rest)

            line_t.append("\n")
            result.append_text(line_t)

        return result


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    LogRenderer.kind = ResultKind.LOG


_set_kind()
