"""BrowserSnapshotRenderer — phase-C display for browser_snapshot accessibility-tree output."""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, ClassVar

from rich.console import Group
from rich.rule import Rule
from rich.text import Text

from hermes_cli.tui.body_renderers.base import BodyRenderer

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload

_SNAPSHOT_TOOLS = frozenset({"browser_snapshot"})

_LANDMARK_ROLES = frozenset({
    "heading", "button", "link", "textbox", "checkbox", "combobox",
    "listitem", "row", "columnheader",
})

_LEAF_ROLES = frozenset({"text", "StaticText", "img", "image", "LineBreak"})

_MAX_TREE_LINES = 200
_INDENT = "  "


def _walk_tree(node: dict, out: list, depth: int) -> None:
    """Recursively render an a11y tree node into Rich Text lines."""
    role = node.get("role") or node.get("type") or "?"
    name = node.get("name") or node.get("text") or ""
    href = node.get("href") or node.get("url") or ""

    indent = _INDENT * depth
    line = Text(no_wrap=True)
    line.append(indent)

    if role in _LANDMARK_ROLES:
        line.append(f"[{role}]", style="bold cyan")  # il-tok-1-exempt: a11y tree landmark role label; semantic cyan for accessibility output
        if name:
            line.append(f" {name}", style="bold")
    elif role in _LEAF_ROLES:
        if name:
            line.append(name, style="dim")
        else:
            return  # skip invisible leaf
    else:
        line.append(f"[{role}]", style="dim")
        if name:
            line.append(f" {name}")

    if href:
        line.append(f"  → {href}", style="dim link")

    out.append(line)

    if role not in _LEAF_ROLES:
        for child in node.get("children") or []:
            _walk_tree(child, out, depth + 1)


def _count_nodes(node: dict) -> int:
    if not node:
        return 0
    return 1 + sum(_count_nodes(c) for c in (node.get("children") or []))


class BrowserSnapshotRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    kind_icon: ClassVar[str] = "📸"
    supports_streaming: ClassVar[bool] = False
    truncation_bias: ClassVar[str] = "priority"

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        return getattr(payload, "tool_name", "") in _SNAPSHOT_TOOLS

    def build(self):
        raw = getattr(self.payload, "output_raw", "") or ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):  # il-ex-1-exempt: swallow
            # malformed/non-JSON tool output: best-effort fall back to raw text
            return Text(raw)

        success = bool(data.get("success", True))
        url = data.get("url") or ""
        title = data.get("title") or data.get("page_title") or ""
        snapshot = data.get("snapshot") or data.get("tree") or {}

        group = []

        if url or title:
            hdr = Text()
            if url:
                hdr.append(f"🌐 {url}", style="link")
            if title:
                hdr.append(f"  —  {title}" if url else title, style="bold")
            group.append(hdr)
            group.append(Rule(style="dim"))

        if not success:
            from rich.style import Style
            err = data.get("error") or "(snapshot failed)"
            group.append(Text(f"✗ {err}", style=Style(color=self.colors.error)))
            return Group(*group)

        if snapshot:
            lines: list = []
            _walk_tree(snapshot, lines, depth=0)
            group.extend(lines[:_MAX_TREE_LINES])
            if len(lines) > _MAX_TREE_LINES:
                group.append(Text(
                    f"  … {len(lines) - _MAX_TREE_LINES} more nodes",
                    style="dim",
                ))
        elif not group:
            group.append(Text("(empty snapshot)", style="dim"))

        return Group(*group)

    def summary_line(self, *, density=None, cls_result=None) -> str:
        raw = getattr(self.payload, "output_raw", "") or ""
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):  # il-ex-1-exempt: swallow
            # summary_line is display-only; malformed payload is a safe fallback
            return "(snapshot)"
        title = data.get("title") or data.get("page_title") or ""
        url = data.get("url") or ""
        node_count = _count_nodes(data.get("snapshot") or data.get("tree") or {})
        label = title or url or "snapshot"
        if node_count:
            return f"{label[:50]}  ({node_count} nodes)"
        return label[:60]


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    BrowserSnapshotRenderer.kind = ResultKind.JSON


_set_kind()
