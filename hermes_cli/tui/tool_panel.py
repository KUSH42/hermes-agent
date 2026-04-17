"""ToolPanel — Phase 1 shell widget wrapping existing tool-call blocks.

Architecture: tui-tool-panel-v2-spec.md §3, §9 Phase 1.

Phase 1 delivers:
- ToolPanel thin container with category class + accent class (when flag on)
- ArgsPane, BodyPane, FooterPane composed but hidden (ArgsPane, FooterPane)
- detail_level reactive pinned to L2 (full body) — watcher activation in Phase 3
- ToolCategory classification for every mounted block

Phase 2 adds BodyRenderer dispatch. Phase 3 adds detail levels, ArgsPane, FooterPane.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget


def _tool_panel_v2_enabled() -> bool:
    """Return True if the tool_panel_v2 accent bar is enabled in config."""
    try:
        from hermes_cli.config import read_raw_config
        return bool(read_raw_config().get("display", {}).get("tool_panel_v2", False))
    except Exception:
        return False


class ArgsPane(Widget):
    """Structured key/value argument view (Phase 3). Hidden in Phase 1."""

    DEFAULT_CSS = "ArgsPane { height: auto; padding: 0 2; display: none; }"


class BodyPane(Widget):
    """Container for the streaming/static block body.

    Phase 1: thin pass-through.
    Phase 2: stores _renderer (BodyRenderer singleton for the panel's category).
    Phase 3: uses _renderer for preview mode and perf instrumentation.
    """

    DEFAULT_CSS = "BodyPane { height: auto; }"

    def __init__(
        self,
        block: Widget | None = None,
        category: "object | None" = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._block = block
        # Store renderer singleton for this category (Phase 2+)
        if category is not None:
            try:
                from hermes_cli.tui.body_renderer import BodyRenderer
                self._renderer = BodyRenderer.for_category(category)
            except Exception:
                self._renderer = None
        else:
            self._renderer = None

    def compose(self) -> ComposeResult:
        if self._block is not None:
            yield self._block


class FooterPane(Widget):
    """Exit-code chip, stat badges, stderr tail, retry hint (Phase 3). Hidden in Phase 1."""

    DEFAULT_CSS = "FooterPane { height: 1; padding: 0 1; display: none; color: $text-muted; }"


class ToolPanel(Widget):
    """Unified tool-call display container.

    Phase 1: thin wrapper that adds category classification to existing blocks
    with no user-visible behavior change (when display.tool_panel_v2 is false).

    Compose tree (all phases):
        ToolPanel
        ├── ArgsPane       (display:none in Phase 1+2)
        ├── BodyPane       (always visible; hosts the streaming/static block)
        └── FooterPane     (display:none in Phase 1+2)
    """

    DEFAULT_CSS = "ToolPanel { height: auto; layout: vertical; }"
    _content_type: str = "tool"
    can_focus = True

    COMPONENT_CLASSES = {
        "tool-panel--accent",
        "tool-panel--error",
        "tool-panel--grouped",
        "tool-panel--focused",
    }

    # Pinned to L2 in Phase 1. Watcher + full cycling wired in Phase 3.
    detail_level: reactive[int] = reactive(2, layout=True)

    def __init__(self, block: Widget, tool_name: str | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._block = block
        self._tool_name = tool_name or ""
        from hermes_cli.tui.tool_category import classify_tool
        self._category = classify_tool(self._tool_name)

    def compose(self) -> ComposeResult:
        yield ArgsPane()
        yield BodyPane(self._block, category=self._category)
        yield FooterPane()

    def on_mount(self) -> None:
        self.add_class(f"category-{self._category.value}")
        if _tool_panel_v2_enabled():
            self.add_class("tool-panel--accent")
