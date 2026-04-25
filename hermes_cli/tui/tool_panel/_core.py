"""ToolPanel — binary collapse, result wiring, keyboard.

Architecture: tui-tool-panel-spec-binary-collapse.md
"""
from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from ._actions import _ToolPanelActionsMixin
from ._completion import _ToolPanelCompletionMixin
from ._footer import (
    BodyPane,
    FooterPane,
    _CollapsedActionStrip,
)

if TYPE_CHECKING:
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    from hermes_cli.tui.tool_category import ToolCategory
    from hermes_cli.tui.tool_payload import ResultKind


class ToolPanel(_ToolPanelActionsMixin, _ToolPanelCompletionMixin, Widget):
    """Unified tool-call display container — binary collapse.

    Completion event:
    ToolPanel.Completed is posted on set_result_summary so ToolGroup can
    re-aggregate without coupling.

    Compose tree:
        ToolPanel
        ├── BodyPane      (hosts the streaming/static block)
        ├── FooterPane    (shown when result has content and not collapsed)
        └── _hint_row     (focus hint, height=auto, empty when unfocused)
    collapsed reactive:
        False (default) → body + conditional footer visible
        True            → header only (body + footer hidden)
    """

    class Completed(Message):
        """Posted when the panel receives a result summary."""

    class PathFocused(Message):
        """Posted on first focus when block has a clickable path (OSC 8 hint)."""
        def __init__(self, panel: "ToolPanel") -> None:
            super().__init__()
            self.panel = panel

    DEFAULT_CSS = "ToolPanel { height: auto; layout: vertical; }"
    _content_type: str = "tool"
    can_focus = True

    COMPONENT_CLASSES = {
        "tool-panel--accent",
        "tool-panel--error",
        "tool-panel--grouped",
        "tool-panel--focused",
    }

    BINDINGS = [
        Binding("enter", "toggle_collapse",  "Toggle",           show=False),
        Binding("y",     "copy_body",         "Copy output",      show=False),
        Binding("Y",     "copy_input",        "Copy input",       show=False),
        Binding("C",     "copy_ansi",        "Copy +color",      show=False),
        Binding("H",     "copy_html",        "Copy HTML",        show=False),
        Binding("I",     "copy_invocation",  "Copy invocation",  show=False),
        Binding("u",     "copy_urls",        "Copy URLs",        show=False),
        Binding("o",     "open_primary",     "Open",             show=False),
        Binding("e",     "copy_err",         "Copy stderr",      show=False),
        Binding("p",     "copy_paths",       "Copy paths",       show=False),
        Binding("+",     "expand_lines",     "Expand lines",     show=False),
        Binding("-",     "collapse_lines",   "Collapse lines",   show=False),
        Binding("*",     "expand_all_lines", "Expand all",       show=False),
        Binding("r",     "retry",            "Retry",            show=False),
        Binding("E",     "edit_cmd",         "Edit cmd",         show=False),
        Binding("O",     "open_url",         "Open URL",         show=False),
        Binding("f",     "toggle_tail_follow", "tail", show=False),
        Binding("j",     "scroll_body_down",      "↓",    show=False),
        Binding("k",     "scroll_body_up",        "↑",    show=False),
        Binding("J",     "scroll_body_page_down", "↓↓",   show=False),
        Binding("K",     "scroll_body_page_up",   "↑↑",   show=False),
        Binding("<",     "scroll_body_top",        "Top",  show=False),
        Binding(">",     "scroll_body_bottom",     "End",  show=False),
        Binding("f1",            "show_help",         "Help",    show=False),
        Binding("P",     "copy_full_path",   "Copy full path",   show=False),
        Binding("x",     "dismiss_error_banner", "Dismiss",      show=False),
        Binding("question_mark", "show_context_menu", "Menu",    show=False),
    ]

    collapsed: reactive[bool] = reactive(False, layout=False)

    @property
    def detail_level(self) -> int:
        return 0 if self.collapsed else 2

    @detail_level.setter
    def detail_level(self, value: int) -> None:
        self.collapsed = (value == 0)

    def __init__(self, block: Widget, tool_name: str | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._block = block
        self._tool_name = tool_name or ""
        from hermes_cli.tui.tool_category import classify_tool
        self._category = classify_tool(self._tool_name)

        self._auto_collapsed: bool = False
        self._user_collapse_override: bool = False
        self._should_auto_collapse: bool = False
        self._result_summary_v4: "ResultSummaryV4 | None" = None
        self._start_time: float = time.monotonic()
        self._completed_at: float | None = None
        self._header_remediation_hint: str | None = None
        self._result_paths: list[str] = []
        self._last_resize_w: int = 0
        self._saved_visible_start: int | None = None

        self._toggle_hint_shown: bool = False
        self._hint_visible: bool = False

        self._forced_renderer_kind: "ResultKind | None" = None
        self._tool_args: dict | None = None

        self._plan_tool_call_id: str | None = None

        self._collapsed_strip: _CollapsedActionStrip | None = None
        self._body_pane: BodyPane | None = None
        self._footer_pane: FooterPane | None = None
        self._hint_row: Static | None = None

        self._discovery_shown: bool = False

        from hermes_cli.tui.tool_category import ToolCategory
        if self._category == ToolCategory.SHELL and hasattr(block, "_should_strip_cwd"):
            block._should_strip_cwd = True

    def compose(self) -> ComposeResult:
        self._collapsed_strip = _CollapsedActionStrip()
        self._body_pane = BodyPane(self._block, category=self._category)
        self._footer_pane = FooterPane()
        self._hint_row = Static("", classes="--focus-hint")
        yield self._collapsed_strip
        yield self._body_pane
        yield self._footer_pane
        yield self._hint_row

    def on_mount(self) -> None:
        from hermes_cli.tui.tool_category import _CATEGORY_DEFAULTS

        self.add_class(f"category-{self._category.value}")
        self.add_class("tool-panel--accent")

        header = getattr(self._block, "_header", None)
        if header is not None:
            header._panel = self

        if header is not None:
            try:
                from hermes_cli.tui.services.feedback import ToolHeaderAdapter
                self.app.feedback.register_channel(
                    f"tool-header::{self.id}",
                    ToolHeaderAdapter(header),
                )
            except Exception:
                pass

        self.collapsed = False

        if self._result_summary_v4 is not None:
            self._apply_complete_auto_collapse()

    def on_unmount(self) -> None:
        try:
            self.app.feedback.deregister_channel(f"tool-header::{self.id}")
        except Exception:
            pass

    def watch_collapsed(self, old: bool, new: bool) -> None:
        if new:
            if hasattr(self._block, "_visible_start"):
                current = self._block._visible_start
                if self._saved_visible_start is None or current > 0:
                    self._saved_visible_start = current
        else:
            if (self._saved_visible_start is not None and
                    hasattr(self._block, "_visible_start") and
                    hasattr(self._block, "_all_plain")):
                try:
                    saved = int(self._saved_visible_start)
                    total = int(len(self._block._all_plain))
                    visible_cap = int(getattr(self._block, "_visible_cap", 200) or 200)
                    end = min(total, saved + visible_cap)
                    self._block.rerender_window(saved, end)
                except Exception:
                    pass

        body_container = getattr(self._block, "_body", None)
        if body_container is not None:
            body_container.styles.display = "none" if new else "block"

        fp = self._footer_pane
        if fp is None:
            return

        if new and fp._show_all_artifacts:
            fp._show_all_artifacts = False
            fp._rebuild_chips()

        want_fp = (not new) and self._has_footer_content()
        if fp.display != want_fp:
            fp.styles.display = "block" if want_fp else "none"

        if old != new:
            try:
                self.remove_class(f"-l{old}")
                self.add_class(f"-l{new}")
            except AttributeError:
                pass

        header = getattr(self._block, "_header", None)
        if header is not None:
            header.refresh()

        self._refresh_collapsed_strip()

    # ------------------------------------------------------------------
    # AXIS-5: density mirror helpers
    # ------------------------------------------------------------------

    def _lookup_view_state(self) -> "Any | None":
        """Return the ToolCallViewState for this panel's tool_call_id, or None."""
        tool_call_id = getattr(self, "_plan_tool_call_id", None)
        if tool_call_id is None:
            return None
        try:
            svc = self.app._svc_tools
            return svc._tool_views_by_id.get(tool_call_id)
        except Exception:
            return None

    def _mirror_density_to_view_state(self) -> None:
        """AXIS-5: keep view-state.density in sync with self.collapsed.

        Move 1 replaces this with the DensityResolver. Best-effort: silent if
        view lookup fails — UI keeps working, watchers just miss this update.
        """
        from hermes_cli.tui.tool_panel.density import DensityTier
        from hermes_cli.tui.services.tools import set_axis
        view = self._lookup_view_state()
        if view is None:
            return
        tier = DensityTier.COMPACT if self.collapsed else DensityTier.DEFAULT
        set_axis(view, "density", tier)
