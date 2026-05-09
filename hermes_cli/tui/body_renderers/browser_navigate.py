"""BrowserNavigateRenderer — phase-C display for browser navigation and action tools."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, ClassVar

from hermes_cli.tui.body_renderers.base import BodyRenderer

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload

_NAV_TOOLS = frozenset({
    "browser_navigate",
    "browser_back",
})

_ACTION_TOOLS = frozenset({
    "browser_click",
    "browser_type",
    "browser_scroll",
    "browser_press",
})

_STATUS_COLORS: dict = {
    range(200, 300): "green",
    range(300, 400): "yellow",
    range(400, 500): "red",
    range(500, 600): "bright_red",
}


class BrowserNavigateRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    kind_icon: ClassVar[str] = "🌐"
    supports_streaming: ClassVar[bool] = False
    footer_entries: ClassVar[tuple] = (("y", "copy"),)
    truncation_bias: ClassVar[str] = "tail"

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        return getattr(payload, "tool_name", "") in (_NAV_TOOLS | _ACTION_TOOLS)

    def build(self):
        raw = getattr(self.payload, "output_raw", "") or ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            from rich.text import Text
            return Text(raw)

        success = bool(data.get("success", True))
        tool_name = getattr(self.payload, "tool_name", "")

        if tool_name in _NAV_TOOLS:
            return self._build_nav(data, success)
        return self._build_action(data, success, tool_name)

    def _build_nav(self, data: dict, success: bool):
        from rich.text import Text
        url = data.get("final_url") or data.get("url") or ""
        title = data.get("title") or data.get("page_title") or ""
        raw_status = data.get("status_code") or data.get("status") or (200 if success else 0)
        try:
            status = int(raw_status)
        except (TypeError, ValueError):
            status = 200 if success else 0

        status_color = "red"
        for r, color in _STATUS_COLORS.items():
            if status in r:
                status_color = color
                break

        result = Text()
        result.append(f" {status} ", style=f"bold {status_color} on default")
        result.append("  ")
        result.append(url, style="link")

        if title:
            result.append(f"\n  {title}", style="bold")

        if not success and data.get("error"):
            result.append(f"\n  {data['error']}", style="red")

        return result

    def _build_action(self, data: dict, success: bool, tool_name: str):
        from rich.text import Text
        verb_map = {
            "browser_click":  "Clicked",
            "browser_type":   "Typed",
            "browser_scroll": "Scrolled",
            "browser_press":  "Pressed",
        }
        verb = verb_map.get(tool_name, tool_name)
        target = (
            data.get("element")
            or data.get("ref")
            or data.get("key")
            or data.get("text", "")[:40]
            or ""
        )
        icon = "✓" if success else "✗"
        color = "green" if success else "red"
        line = Text()
        line.append(f"{icon} {verb}", style=f"bold {color}")
        if target:
            line.append(f"  {target}", style="default")
        if not success and data.get("error"):
            line.append(f"\n  {data['error']}", style="red")
        return line

    def summary_line(self, *, density=None, cls_result=None) -> str:
        raw = getattr(self.payload, "output_raw", "") or ""
        tool_name = getattr(self.payload, "tool_name", "")
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            # non-JSON output is expected when the browser tool crashes or returns plain text
            return f"({tool_name})"
        if tool_name in _ACTION_TOOLS:
            success = bool(data.get("success", True))
            icon = "✓" if success else "✗"
            target = data.get("element") or data.get("ref") or data.get("text", "")[:30] or ""
            verb_map = {"browser_click": "click", "browser_type": "type",
                        "browser_scroll": "scroll", "browser_press": "press"}
            verb = verb_map.get(tool_name, tool_name)
            return f"{icon} {verb} {target}".strip()
        title = data.get("title") or data.get("page_title") or ""
        url = data.get("url") or ""
        return (title or url or "(navigate)")[:60]


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    BrowserNavigateRenderer.kind = ResultKind.JSON


_set_kind()
