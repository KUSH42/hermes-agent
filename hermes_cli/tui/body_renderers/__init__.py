"""Body renderer registry — unified Phase C + streaming.

pick_renderer() selects the most appropriate BodyRenderer subclass
based on ClassificationResult, ToolPayload, phase, and density.

Registry order (most to least specific):
  Phase C:   DiffRenderer, JsonRenderer, SearchRenderer, TableRenderer,
             CodeRenderer, LogRenderer, ShellOutputRenderer, EmptyStateRenderer,
             FallbackRenderer
  Streaming: ShellRenderer, StreamingCodeRenderer, FileRenderer,
             StreamingSearchRenderer, WebRenderer, AgentRenderer,
             TextRenderer, MCPBodyRenderer
  (PlainBodyRenderer is NOT in REGISTRY — can_render always False; reached
  only via force-return in the streaming branch after the walk exhausts.)

pick_renderer() phase argument selects the renderer tier, not the
lifecycle position of the caller. Streaming-tier callers that invoke
pick_renderer after streaming ends (e.g. finalize_code, _rehighlight_body)
should pass phase=STREAMING to stay in the streaming tier.
"""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

class RendererKind(str, Enum):
    """User-selectable renderer kind for `t` / `Shift+T` keybinds (LL-4).

    Definition order determines cycle order for _do_cycle_kind: DIFF → CODE → PLAIN → DIFF.
    """
    DIFF  = "diff"
    CODE  = "code"
    PLAIN = "plain"


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

# Streaming-tier renderers — now BodyRenderer subclasses
from hermes_cli.tui.body_renderers.streaming import (
    StreamingBodyRenderer,
    PlainBodyRenderer,
    ShellRenderer,
    StreamingCodeRenderer,
    FileRenderer,
    StreamingSearchRenderer,
    WebRenderer,
    AgentRenderer,
    TextRenderer,
    MCPBodyRenderer,
    _STREAMING_PHASES,
)

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ClassificationResult, ToolPayload
    from hermes_cli.tui.services.tools import ToolCallState
    from hermes_cli.tui.tool_panel.density import DensityTier

REGISTRY: list[type[BodyRenderer]] = [
    # Phase C — high-specificity first
    DiffRenderer,
    JsonRenderer,
    SearchRenderer,
    TableRenderer,
    CodeRenderer,
    LogRenderer,
    ShellOutputRenderer,
    EmptyStateRenderer,
    FallbackRenderer,
    # Streaming-tier — category-keyed; order does not matter (no two match same category)
    ShellRenderer,
    StreamingCodeRenderer,
    FileRenderer,
    StreamingSearchRenderer,
    WebRenderer,
    AgentRenderer,
    TextRenderer,
    MCPBodyRenderer,
    # PlainBodyRenderer intentionally NOT in REGISTRY: its can_render always
    # returns False, so the walk never selects it. The streaming branch
    # force-returns it directly after exhausting the walk. Phase C never
    # reaches it because accepted_phases excludes COMPLETING/DONE.
]

# Sentinel ClassificationResult for streaming call sites where no classification
# has fired yet. The streaming branch in pick_renderer ignores classification
# and keys on payload.category, so any valid value works here.
def _make_streaming_empty_cls() -> "ClassificationResult":
    from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind
    return ClassificationResult(kind=ResultKind.TEXT, confidence=0.0)

# Eagerly created — ClassificationResult is a simple frozen dataclass with no
# circular import risk at this point in the import chain.
_STREAMING_EMPTY_CLS = _make_streaming_empty_cls()


def pick_renderer(
    cls_result: "ClassificationResult",
    payload: "ToolPayload",
    *,
    phase: "ToolCallState",
    density: "DensityTier",
    user_kind_override: "ResultKind | None" = None,
) -> type[BodyRenderer]:
    """Select best renderer for (cls_result, payload, phase, density).

    The ``phase`` argument selects the renderer *tier*, not the lifecycle
    position of the caller. Callers that run after streaming ends but want
    a streaming-tier renderer (e.g. finalize_code, _rehighlight_body) should
    pass phase=STREAMING explicitly.

    Streaming branch (phase ∈ {STARTED, STREAMING}):
      Walk REGISTRY for the first renderer whose accepts() and can_render()
      both return True. Because streaming renderers key can_render on
      payload.category, giving the same one-class-per-category dispatch.
      If no match, force-return PlainBodyRenderer.

    Phase C branch (phase ∈ {COMPLETING, DONE}):
    1. SHELL category: TEXT kind or confidence < 0.8 → ShellOutputRenderer.
    2. EMPTY → EmptyStateRenderer.
    3. confidence > 0.5 AND non-TEXT/EMPTY → try specialized renderer via accepts().
       0.5–0.7 band: stamp _low_confidence_disclosed flag for renderer notice.
    4. TEXT, low-confidence, or no match → FallbackRenderer.

    KO-2: when ``user_kind_override`` is set and ``phase`` is post-streaming,
    a synthetic high-confidence ClassificationResult replaces ``cls_result``
    for dispatch, AND Rules 1–2 (SHELL / EMPTY short-circuits) are bypassed
    so override→TEXT, override→CODE-on-SHELL, etc. are observable. The
    original ``cls_result`` (and the classifier's verdict on ``view.kind``)
    is left untouched.
    """
    from hermes_cli.tui.tool_category import ToolCategory
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult

    # Streaming branch — runs when phase says we are still receiving lines.
    # Classification is typically empty/UNKNOWN here; key on category instead.
    # Override has no effect here — renderer swap mid-stream would race the
    # render loop; takes effect once phase reaches COMPLETING/DONE.
    if phase in _STREAMING_PHASES:
        for r in REGISTRY:
            if not r.accepts(phase, density):
                continue
            if r.can_render(cls_result, payload):
                return r
        # Exhausted: no streaming renderer matched this category.
        return PlainBodyRenderer

    # KO-2: override path — synthesize high-confidence cls_eff, skip Rules 1–2,
    # walk REGISTRY for specialized renderer; fall through to Fallback for
    # TEXT/EMPTY (intentional) or unmatched kinds.
    if user_kind_override is not None:
        cls_eff = ClassificationResult(
            kind=user_kind_override,
            confidence=1.0,
        )
        # KO-C: annotate user-forced renders so renderers can show disclosure caption
        object.__setattr__(cls_eff, "_user_forced", True)
        # TEXT and EMPTY short-circuit to FallbackRenderer — TEXT because
        # Fallback is the only legitimate plain-text target; EMPTY because
        # rendering an empty-state placeholder over real output on user
        # request would silently overwrite content.
        if cls_eff.kind not in (ResultKind.TEXT, ResultKind.EMPTY):
            for r in REGISTRY:
                # Skip both terminator renderers: FallbackRenderer.can_render
                # always returns True, and ShellOutputRenderer matches any
                # SHELL-category payload. Without this filter, override would
                # be silently caught by one of them.
                if r is FallbackRenderer or r is ShellOutputRenderer:
                    continue
                if not r.accepts(phase, density):
                    continue
                if r.can_render(cls_eff, payload):
                    return r
        return FallbackRenderer

    # Phase C branch — existing R-2A-2 logic, unchanged.
    from hermes_cli.tui.tool_panel.density import DensityTier  # noqa: F401

    # Rule 1: SHELL — TEXT always stays; non-TEXT with low confidence stays too
    if payload.category == ToolCategory.SHELL and cls_result.kind != ResultKind.EMPTY:
        if cls_result.kind == ResultKind.TEXT or cls_result.confidence < 0.8:
            if ShellOutputRenderer.accepts(phase, density):
                return ShellOutputRenderer

    # Rule 2: EMPTY → EmptyStateRenderer
    if cls_result.kind == ResultKind.EMPTY and EmptyStateRenderer.accepts(phase, density):
        return EmptyStateRenderer

    # Rule 3: confidence > 0.5 AND non-TEXT/EMPTY → try specialized renderer
    if cls_result.confidence > 0.5 and cls_result.kind not in (ResultKind.TEXT, ResultKind.EMPTY):
        if cls_result.confidence < 0.7:
            # Stamp disclosure flag — object.__setattr__ bypasses frozen=True
            object.__setattr__(cls_result, "_low_confidence_disclosed", True)
        for r in REGISTRY:
            if not r.accepts(phase, density):
                continue
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
    "RendererKind",
    "_STREAMING_EMPTY_CLS",
    # Streaming-tier renderers
    "StreamingBodyRenderer",
    "PlainBodyRenderer",
    "ShellRenderer",
    "StreamingCodeRenderer",
    "FileRenderer",
    "StreamingSearchRenderer",
    "WebRenderer",
    "AgentRenderer",
    "TextRenderer",
    "MCPBodyRenderer",
]
