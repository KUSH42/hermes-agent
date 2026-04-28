"""ToolPanel — binary collapse, result wiring, keyboard.

Architecture: tui-tool-panel-spec-binary-collapse.md
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

import threading
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
from hermes_cli.tui.tool_panel.layout_resolver import (
    ToolBlockLayoutResolver,
    LayoutDecision,
    DensityResult,
    DensityTier,
)

if TYPE_CHECKING:
    from hermes_cli.tui.tool_result_parse import ResultSummaryV4
    from hermes_cli.tui.tool_category import ToolCategory
    from hermes_cli.tui.tool_payload import ResultKind
    from hermes_cli.tui.services.tools import ToolCallViewState
    from textual.events import Key, Click, MouseScrollUp, MouseScrollDown


# ER-3: thin Static subclasses for ERR-phase body; never enter the renderer pipeline.

class StderrTailWidget(Static):
    """Static display for last N stderr lines — clamp-bypassing."""

    DEFAULT_CSS = "StderrTailWidget { color: $text-muted; padding: 0 2; }"

    def __init__(self, lines: "tuple[str, ...]", **kwargs: Any) -> None:
        super().__init__("\n".join(lines), **kwargs)


class PayloadTailWidget(Static):
    """Fallback: tail of stdout payload when no stderr tail is available."""

    DEFAULT_CSS = "PayloadTailWidget { color: $text-muted; padding: 0 2; }"

    def __init__(self, payload: str, **kwargs: Any) -> None:
        super().__init__(payload, **kwargs)


class EmptyOutputWidget(Static):
    """Placeholder rendered when neither stderr nor payload is available."""

    DEFAULT_CSS = "EmptyOutputWidget { color: $text-muted 50%; padding: 0 2; }"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("(no output)", classes="--err-empty", **kwargs)


def pick_err_body_widget(view: "ToolCallViewState") -> Widget:
    """ER-3: select the body widget for an ERR row; never calls the renderer pipeline."""
    if getattr(view, "stderr_tail", None):
        return StderrTailWidget(view.stderr_tail)
    if getattr(view, "payload", None):
        return PayloadTailWidget(view.payload)
    return EmptyOutputWidget()


# LL-1: pure helper — testable without Textual machinery.
_LL1_FLASH_TEXT: dict["DensityTier", str] = {}  # populated lazily to avoid import cycle

# SLR-1: tier CSS class names — one active at a time, toggled in _apply_layout.
_TIER_CLASS_NAMES: dict["DensityTier", str] = {
    DensityTier.HERO:    "tool-panel--tier-hero",
    DensityTier.DEFAULT: "tool-panel--tier-default",
    DensityTier.COMPACT: "tool-panel--tier-compact",
    DensityTier.TRACE:   "tool-panel--tier-trace",
}


def density_flash_text(
    last: "DensityResult | None",
    new_tier: "DensityTier",
    reason: str,
) -> str:
    """Return flash text for an auto tier change, or '' if suppressed.

    Suppression rules (first match wins):
      1. last is None → initial resolve, no flash
      2. last.tier == new_tier → same tier, no flash
      3. reason != "auto" → user/error_override/initial, no flash
      4. Otherwise → flash with tier-specific text
    """
    if last is None:
        return ""
    if last.tier == new_tier:
        return ""
    if reason != "auto":
        return ""
    _map = {
        DensityTier.HERO:    "★ hero view",
        DensityTier.COMPACT: "▤ compact view",
        DensityTier.TRACE:   "≡ trace view",
        DensityTier.DEFAULT: "default view",
    }
    return _map.get(new_tier, "")


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

    DEFAULT_CSS = """
    ToolPanel { height: auto; layout: vertical; }
    ToolPanel FooterPane.has-actions > .action-row { display: none; }
    ToolPanel:focus FooterPane.has-actions > .action-row { display: block; }
    ToolPanel.--browsed FooterPane.has-actions > .action-row { display: block; }
    ToolPanel.--expanded FooterPane.has-actions > .action-row { display: block; }
    ToolPanel StreamingToolBlock.--compact-success ToolBodyContainer.expanded { display: none; }
    ToolPanel:focus StreamingToolBlock.--compact-success ToolBodyContainer.expanded { display: block; }
    ToolPanel.--browsed StreamingToolBlock.--compact-success ToolBodyContainer.expanded { display: block; }
    ToolPanel.--expanded StreamingToolBlock.--compact-success ToolBodyContainer.expanded { display: block; }
    """
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
        Binding("D",       "density_cycle",         "Density ↓",  show=False),
        Binding("shift+d", "density_cycle_reverse", "Density ↑",  show=False),
        Binding("r",     "retry",            "Retry",            show=False),
        Binding("t",     "cycle_kind",       "Render as",        show=False),
        Binding("T",     "kind_revert",      "Revert kind",      show=False),
        Binding("E",     "edit_cmd",         "Edit cmd",         show=False),
        Binding("a",     "edit_args",        "Edit args",        show=False),
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
    density: reactive[DensityTier] = reactive(DensityTier.DEFAULT, layout=False)

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

        self._toggle_hint_shown_at: float = 0.0
        self._hint_visible: bool = False

        self._tool_args: dict | None = None

        self._plan_tool_call_id: str | None = None

        self._collapsed_strip: _CollapsedActionStrip | None = None
        self._body_pane: BodyPane | None = None
        self._footer_pane: FooterPane | None = None
        self._hint_row: Static | None = None

        self._discovery_shown: bool = False

        # Deferred renderer swap: set when _swap_renderer fires before compose().
        # Consumed in on_mount() once _body_pane is available.
        self._pending_renderer_swap: "tuple[type, Any, Any] | None" = None

        self._view_state: "ToolCallViewState | None" = None  # wired by service after mount
        self._resolver = ToolBlockLayoutResolver()
        self._resolver.subscribe(self._on_tier_change)
        # LL-1: track last density result to suppress redundant flashes
        self._last_density_result: DensityResult | None = None
        self._user_override_tier: DensityTier | None = None
        self._parent_clamp_tier: "DensityTier | None" = None  # set by ChildPanel via subscription

        from hermes_cli.tui.tool_category import ToolCategory
        if self._category == ToolCategory.SHELL and hasattr(block, "_should_strip_cwd"):
            block._should_strip_cwd = True

    def compose(self) -> ComposeResult:
        self._collapsed_strip = _CollapsedActionStrip()
        self._body_pane = BodyPane(self._block, category=self._category)
        self._footer_pane = FooterPane()
        self._hint_row = Static("", classes="--focus-hint")
        # Lift the header out of the block so it survives apply_density block replacement.
        header = getattr(self._block, "_header", None)
        if header is not None:
            self._block._header_lifted = True
            yield header
        yield self._collapsed_strip
        yield self._body_pane
        yield self._footer_pane
        yield self._hint_row

    def toggle(self) -> None:
        """Delegate browse-mode toggle to action_toggle_collapse."""
        self.action_toggle_collapse()

    def on_mount(self) -> None:
        from hermes_cli.tui.tool_category import _CATEGORY_DEFAULTS

        self.add_class(f"category-{self._category.value}")
        self.add_class("tool-panel--accent")

        header = getattr(self._block, "_header", None)
        if header is not None:
            header._panel = self

        if header is not None:
            # Use panel DOM id when available; fall back to object identity so panels
            # created without an explicit id (e.g. via mount_tool_block) still get a channel.
            _panel_key = self.id if self.id is not None else str(id(self))
            try:
                from hermes_cli.tui.services.feedback import ToolHeaderAdapter
                self.app.feedback.register_channel(
                    f"tool-header::{_panel_key}",
                    ToolHeaderAdapter(header),
                )
            except Exception:  # FeedbackService not yet registered; header channel optional
                pass

        self.collapsed = False

        # Flush any renderer swap that arrived before compose() ran.
        if self._pending_renderer_swap is not None:
            renderer_cls, payload, cls_result = self._pending_renderer_swap
            self._pending_renderer_swap = None
            try:
                self._swap_renderer(renderer_cls, payload, cls_result)
            except Exception:
                _log.exception("deferred _swap_renderer failed in on_mount")

        if self._result_summary_v4 is not None:
            self._apply_complete_auto_collapse()

    def on_unmount(self) -> None:
        try:
            _panel_key = self.id if self.id is not None else str(id(self))
            self.app.feedback.deregister_channel(f"tool-header::{_panel_key}")
        except Exception:  # FeedbackService unavailable on unmount; deregistration best-effort, safe
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
                    _log.debug("rerender_window on uncollapse failed", exc_info=True)

        body_container = getattr(self._block, "_body", None)
        if body_container is not None:
            body_container.styles.display = "none" if new else "block"

        if old != new:
            try:
                self.remove_class(f"-l{old}")
                self.add_class(f"-l{new}")
            except AttributeError:  # add/remove_class fails on partially initialized widget; CSS best-effort
                pass

        header = getattr(self._block, "_header", None)
        if header is not None:
            header.refresh()

        self._refresh_collapsed_strip()

    # ------------------------------------------------------------------
    # Density resolver callback and view-state mirror
    # ------------------------------------------------------------------

    def _lookup_view_state(self) -> "Any | None":
        """Return the ToolCallViewState for this panel's tool_call_id, or None."""
        tool_call_id = getattr(self, "_plan_tool_call_id", None)
        if tool_call_id is None:
            return None
        try:
            svc = self.app._svc_tools
            return svc._tool_views_by_id.get(tool_call_id)
        except Exception:  # _svc_tools not yet attached; view-state lookup returns None safely
            return None

    def _on_tier_change(self, decision: LayoutDecision) -> None:
        """Resolver subscriber — receives full LayoutDecision; delegate directly."""
        self._apply_layout(decision)

    def _apply_layout(self, decision: LayoutDecision) -> None:
        """Apply a resolved LayoutDecision atomically (view-state axis first).

        Must run on the Textual message thread. Axis watchers fire synchronously
        before the Reactive watcher chain, so cross-subsystem readers always see
        the new tier when they are invoked.
        """
        try:
            app = self.app
            thread_id = getattr(app, "_thread_id", None)
        except Exception:  # app not yet available pre-mount; thread_id check skipped
            app = None
            thread_id = None
        if thread_id is not None and threading.get_ident() != thread_id:
            raise RuntimeError("_apply_layout must run on Textual message thread")

        # 1. Axis-bus write FIRST — fires synchronous watchers.
        vs = self._view_state or self._lookup_view_state()
        if vs is not None:
            from hermes_cli.tui.services.tools import set_axis
            set_axis(vs, "density", decision.tier)
            # LL-1/LL-3: write density_reason to view so header can read it.
            # Map "parent_clamp" → "user" for the 4-value density_reason type.
            dr = decision.reason
            if dr == "parent_clamp":
                dr = "user"
            vs.density_reason = dr  # type: ignore[assignment]

        # SLR-1: toggle tier class for CSS margin contract; mutual exclusion.
        for _cls in _TIER_CLASS_NAMES.values():
            self.remove_class(_cls)
        self.add_class(_TIER_CLASS_NAMES[decision.tier])

        # LL-1: flash on auto tier change.
        _reason = decision.reason if decision.reason != "parent_clamp" else "user"
        new_result = DensityResult(tier=decision.tier, reason=_reason)  # type: ignore[arg-type]
        flash_text = density_flash_text(self._last_density_result, decision.tier, decision.reason)
        self._last_density_result = new_result
        if flash_text and self.is_attached:
            from hermes_cli.tui.widgets.status_bar import FlashMessage
            self.post_message(FlashMessage(flash_text, duration=1.2))

        # 2. Reactives — Textual schedules watcher dispatch after this returns.
        self.density = decision.tier
        self.collapsed = (decision.tier == DensityTier.COMPACT)
        self._auto_collapsed = (
            decision.tier == DensityTier.COMPACT and not self._user_collapse_override
        )

        # 3. Footer visibility — sole owner; watch_collapsed no longer toggles it.
        if self._footer_pane is not None:
            fp = self._footer_pane
            if decision.tier == DensityTier.COMPACT and fp._show_all_artifacts:
                fp._show_all_artifacts = False
                fp._rebuild_chips()
            self._footer_pane.set_density(decision.tier)
            self._footer_pane.display = decision.footer_visible

        # 4. Header tier mirror.
        header = getattr(self._block, "_header", None)
        if header is not None:
            header._density_tier = decision.tier
            header.refresh()

        # 5. Body pane density delegation.
        if self._body_pane is not None:
            _err_locked = getattr(self._body_pane, "_err_body_locked", False)
            if _err_locked:
                pass  # ER-3: ERR body mounted; never apply_density
            else:
                _vs = self._view_state or self._lookup_view_state()
                if _vs is not None:
                    from hermes_cli.tui.services.tools import ToolCallState
                    if _vs.state == ToolCallState.ERROR:
                        self._body_pane.mount_static(pick_err_body_widget(_vs))
                    else:
                        self._body_pane.apply_density(decision.tier)
                else:
                    self._body_pane.apply_density(decision.tier)

    # ------------------------------------------------------------------
    # KL-2 + KL-6: Keystroke / mouse recorder hooks
    # ------------------------------------------------------------------

    def _ks_context(self) -> "tuple[str, str, str | None]":
        """Return (block_id, phase, kind_val) for keystroke/mouse logging."""
        vs = self._view_state or self._lookup_view_state()
        if vs is not None:
            block_id = vs.tool_call_id or (
                f"gen-{vs.gen_index}" if vs.gen_index is not None else "unknown"
            )
            phase = vs.state.value
            kind_val = vs.kind.kind.value if vs.kind is not None else None
        else:
            block_id = "unknown"
            phase = "unknown"
            kind_val = None
        if block_id == "unknown":
            panel_id = self.id or ""
            if panel_id.startswith("tool-"):
                block_id = panel_id[len("tool-"):]
        return block_id, phase, kind_val

    def on_key(self, event: "Key") -> None:
        """KL-2: Keystroke recorder hook — fires before BINDINGS dispatch."""
        from ._keystroke_log import record, ENABLED
        if not ENABLED:
            return
        block_id, phase, kind_val = self._ks_context()
        record(
            key=event.key,
            block_id=block_id,
            phase=phase,
            kind=kind_val,
            density=self.density.value,
            focused=self.has_focus,
        )

    def on_click(self, event: "Click") -> None:
        """KL-6a: Mouse click recorder."""
        from ._keystroke_log import record_mouse, ENABLED
        if not ENABLED:
            return
        block_id, phase, kind_val = self._ks_context()
        btn = event.button
        button = "left" if btn == 1 else "middle" if btn == 2 else "right" if btn == 3 else "unknown"
        record_mouse(
            button=button,
            x=event.x,
            y=event.y,
            widget=type(event.widget).__name__ if event.widget is not None else "unknown",
            block_id=block_id,
            phase=phase,
            kind=kind_val,
            density=self.density.value,
            focused=self.has_focus,
        )

    def on_mouse_scroll_up(self, event: "MouseScrollUp") -> None:
        """KL-6b: Scroll-up recorder."""
        from ._keystroke_log import record_mouse, ENABLED
        if not ENABLED:
            return
        block_id, phase, kind_val = self._ks_context()
        record_mouse(
            button="scroll_up",
            x=event.x,
            y=event.y,
            widget=type(event.widget).__name__ if event.widget is not None else "unknown",
            block_id=block_id,
            phase=phase,
            kind=kind_val,
            density=self.density.value,
            focused=self.has_focus,
        )

    def on_mouse_scroll_down(self, event: "MouseScrollDown") -> None:
        """KL-6c: Scroll-down recorder."""
        from ._keystroke_log import record_mouse, ENABLED
        if not ENABLED:
            return
        block_id, phase, kind_val = self._ks_context()
        record_mouse(
            button="scroll_down",
            x=event.x,
            y=event.y,
            widget=type(event.widget).__name__ if event.widget is not None else "unknown",
            block_id=block_id,
            phase=phase,
            kind=kind_val,
            density=self.density.value,
            focused=self.has_focus,
        )
