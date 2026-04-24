"""Body renderer registry — Phase C.

pick_renderer() selects the most appropriate BodyRenderer subclass
based on ClassificationResult and ToolPayload.

Registry order (most to least specific):
  DiffRenderer, JsonRenderer, SearchRenderer, TableRenderer, CodeRenderer,
  LogRenderer, ShellOutputRenderer, EmptyStateRenderer, FallbackRenderer
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from hermes_cli.tui.body_renderers.base import BodyRenderer
from hermes_cli.tui.body_renderers.search import SearchRenderer
from hermes_cli.tui.body_renderers.diff import DiffRenderer
from hermes_cli.tui.body_renderers.json import JsonRenderer
from hermes_cli.tui.body_renderers.table import TableRenderer
from hermes_cli.tui.body_renderers.code import CodeRenderer
from hermes_cli.tui.body_renderers.log import LogRenderer
from hermes_cli.tui.body_renderers.shell import ShellOutputRenderer
from hermes_cli.tui.body_renderers.empty import EmptyStateRenderer
from hermes_cli.tui.body_renderers.fallback import FallbackRenderer

# Streaming (legacy per-line) renderers — first-class module in body_renderers/
from hermes_cli.tui.body_renderers.streaming import (
    StreamingBodyRenderer,
    PlainBodyRenderer,
    ShellRenderer,
    CodeRenderer as _StreamingCodeRenderer,  # noqa: F401 — avoid shadowing ABC CodeRenderer
    FileRenderer,
    SearchRenderer as _LegacySearchRenderer,  # private — avoids two SearchRenderer exports
    WebRenderer,
    AgentRenderer,
    TextRenderer,
    MCPBodyRenderer,
)

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ClassificationResult, ToolPayload

REGISTRY: list[type[BodyRenderer]] = [
    DiffRenderer,
    JsonRenderer,
    SearchRenderer,
    TableRenderer,
    CodeRenderer,
    LogRenderer,
    ShellOutputRenderer,
    EmptyStateRenderer,
    FallbackRenderer,
]


def pick_renderer(
    cls_result: "ClassificationResult",
    payload: "ToolPayload",
) -> type[BodyRenderer]:
    """Select best renderer for cls_result + payload.

    Rules (in order):
    1. SHELL category: TEXT kind or confidence < 0.8 → ShellOutputRenderer.
       High-confidence non-TEXT shell output falls through to specialized REGISTRY.
    2. EMPTY → EmptyStateRenderer.
    3. confidence > 0.5 AND non-TEXT/EMPTY → try specialized renderer.
       0.5–0.7 band: stamp _low_confidence_disclosed flag for renderer notice.
    4. TEXT, low-confidence (≤0.5), or no registry match → FallbackRenderer.
    """
    from hermes_cli.tui.tool_category import ToolCategory
    from hermes_cli.tui.tool_payload import ResultKind

    # Rule 1: SHELL — TEXT always stays; non-TEXT with low confidence stays too
    if payload.category == ToolCategory.SHELL and cls_result.kind != ResultKind.EMPTY:
        if cls_result.kind == ResultKind.TEXT or cls_result.confidence < 0.8:
            return ShellOutputRenderer

    # Rule 2: EMPTY → EmptyStateRenderer
    if cls_result.kind == ResultKind.EMPTY:
        return EmptyStateRenderer

    # Rule 3: confidence > 0.5 AND non-TEXT/EMPTY → try specialized renderer
    if cls_result.confidence > 0.5 and cls_result.kind not in (ResultKind.TEXT, ResultKind.EMPTY):
        if cls_result.confidence < 0.7:
            # Stamp disclosure flag — object.__setattr__ bypasses frozen=True
            object.__setattr__(cls_result, "_low_confidence_disclosed", True)
        for r in REGISTRY:
            if r.can_render(cls_result, payload):
                return r

    # Rule 4: TEXT, low-confidence, or no match → FallbackRenderer
    return FallbackRenderer


__all__ = [
    # ABC (new build API) renderers
    "BodyRenderer",
    "SearchRenderer",
    "DiffRenderer",
    "JsonRenderer",
    "TableRenderer",
    "CodeRenderer",
    "LogRenderer",
    "ShellOutputRenderer",
    "EmptyStateRenderer",
    "FallbackRenderer",
    "REGISTRY",
    "pick_renderer",
    # Streaming (legacy per-line) renderers
    "StreamingBodyRenderer",
    "PlainBodyRenderer",
    "ShellRenderer",
    "FileRenderer",
    "WebRenderer",
    "AgentRenderer",
    "TextRenderer",
    "MCPBodyRenderer",
    # _LegacySearchRenderer is intentionally excluded from __all__
]
