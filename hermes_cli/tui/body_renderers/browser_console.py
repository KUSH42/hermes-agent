"""BrowserConsoleRenderer — phase-C display for browser_console tool output."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, ClassVar

from hermes_cli.tui.body_renderers.base import BodyRenderer

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload

_CONSOLE_TOOLS = frozenset({"browser_console"})

_LEVEL_STYLES = {
    "log":     "dim",
    "debug":   "dim",
    "info":    "cyan",
    "warning": "yellow",
    "warn":    "yellow",
    "error":   "bold red",
    "assert":  "bold red",
}
_DEFAULT_LEVEL_STYLE = "default"


class BrowserConsoleRenderer(BodyRenderer):
    kind: ClassVar
    kind_icon: ClassVar[str] = "⬛"
    supports_streaming: ClassVar[bool] = False
    truncation_bias: ClassVar[str] = "tail"

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        return getattr(payload, "tool_name", "") in _CONSOLE_TOOLS

    def build(self):
        from rich.console import Group
        from rich.text import Text

        raw = getattr(self.payload, "output_raw", "") or ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return Text(raw)

        messages = data.get("console_messages") or []
        js_errors = data.get("js_errors") or []

        if not messages and not js_errors:
            return Text("(no console output)", style="dim")

        group = []

        for msg in messages:
            level = (msg.get("type") or msg.get("level") or "log").lower()
            style = _LEVEL_STYLES.get(level, _DEFAULT_LEVEL_STYLE)
            text = msg.get("text") or msg.get("message") or ""
            line = Text(no_wrap=False)
            line.append(f"{level:7} ", style=style)
            line.append(text, style=style)
            group.append(line)

        if js_errors:
            group.append(Text("──", style="dim red"))
            badge = Text()
            badge.append(f" {len(js_errors)} JS error(s) ", style="bold white on red")
            group.append(badge)
            for err in js_errors:
                msg = err.get("message") or err.get("text") or str(err)
                line = Text(no_wrap=False)
                line.append("  " + msg, style="red")
                stack = err.get("stack") or ""
                if stack:
                    for frame in stack.splitlines()[:4]:
                        line.append("\n    " + frame.strip(), style="dim red")
                group.append(line)

        return Group(*group)

    def summary_line(self, *, density=None, cls_result=None) -> str:
        raw = getattr(self.payload, "output_raw", "") or ""
        try:
            data = json.loads(raw)
        except Exception:  # json.JSONDecodeError and others: render gracefully in summary_line
            return "(console)"
        messages = data.get("console_messages") or []
        js_errors = data.get("js_errors") or []
        err_count = data.get("total_errors", 0) or sum(
            1 for m in messages
            if (m.get("type") or m.get("level") or "").lower() in {"error", "assert"}
        ) + len(js_errors)
        warn_count = sum(
            1 for m in messages
            if (m.get("type") or m.get("level") or "").lower() in {"warning", "warn"}
        )
        total = len(messages) + len(js_errors)

        if err_count:
            return f"✗ {err_count} error(s), {warn_count} warn(s) — {total} total"
        if warn_count:
            return f"⚠ {warn_count} warn(s) — {total} messages"
        return f"✓ {total} message(s)"


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    BrowserConsoleRenderer.kind = ResultKind.JSON


_set_kind()
