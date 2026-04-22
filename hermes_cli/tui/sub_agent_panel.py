"""SubAgentPanel — collapsible tree container for AGENT-category tool calls."""
from __future__ import annotations

import time as _time
from enum import IntEnum
from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class CollapseState(IntEnum):
    EXPANDED  = 0
    COMPACT   = 1
    COLLAPSED = 2


class SubAgentBody(Vertical):
    """Named subclass so TCSS type selectors (SubAgentBody { ... }) match correctly."""
    pass


def _accessibility_mode() -> bool:
    import os
    return bool(os.environ.get("HERMES_NO_UNICODE") or os.environ.get("HERMES_ACCESSIBLE"))


class SubAgentHeader(Widget):
    DEFAULT_CSS = "SubAgentHeader { height: 1; layout: horizontal; }"

    def compose(self) -> ComposeResult:
        # _gutter initialized with depth-0 text directly; _set_gutter(bool) called by add_child_panel for depth≥1
        self._gutter = Static("  ┃ ", classes="--gutter")
        yield self._gutter
        self._label = Static("", classes="--label")
        yield self._label
        self._badges = Static("", classes="--badges")
        yield self._badges

    def update(self, child_count: int, error_count: int, elapsed_ms: int, done: bool) -> None:
        s = elapsed_ms / 1000
        if _accessibility_mode():
            badge = f"calls:{child_count} err:{error_count} dur:{s:.1f}s"
        elif self.app and self.app.size.width < 80:
            badge = f"{child_count}c {error_count}e {elapsed_ms // 1000}.{(elapsed_ms % 1000) // 100}s"
        else:
            err_label = "error" if error_count == 1 else "errors"
            badge = f"{child_count} calls  {error_count} {err_label}  {s:.1f}s"
        self._badges.update(badge)
        if error_count > 0:
            self._badges.add_class("--has-errors")
            self._badges.remove_class("--done")
        elif done:
            self._badges.remove_class("--has-errors")
            self._badges.add_class("--done")
        else:
            self._badges.remove_class("--has-errors")
            self._badges.remove_class("--done")

    def on_click(self, event: events.Click) -> None:
        if isinstance(self.parent, SubAgentPanel):
            self.parent.action_cycle_collapse()

    def set_error(self, error_kind: str | None) -> None:
        self._error_kind: str | None = error_kind
        self.add_class("--error")
        self.refresh()

    def _set_gutter(self, is_child_last: bool) -> None:
        """Update gutter prefix. Called only by SubAgentPanel.add_child_panel for depth≥1 panels.
        False = non-last child (├─). True = last child (└─).
        """
        acc = _accessibility_mode()
        if is_child_last:
            self._gutter.update("  └─ " if not acc else "  \\- ")
        else:
            self._gutter.update("  ├─ " if not acc else "  +- ")


class SubAgentPanel(Widget):
    DEFAULT_CSS = "SubAgentPanel { height: auto; layout: vertical; }"
    can_focus = True

    BINDINGS = [
        Binding("space",        "toggle_collapse",  show=False),
        Binding("c",            "toggle_compact",   show=False),
        Binding("ctrl+e",       "expand_all",       show=False),
        Binding("ctrl+shift+k", "compact_all",      show=False),
        Binding("ctrl+x",       "collapse_subtree", show=False),
    ]

    child_count:    reactive[int]           = reactive(0)
    error_count:    reactive[int]           = reactive(0)
    elapsed_ms:     reactive[int]           = reactive(0)
    subtree_done:   reactive[bool]          = reactive(False)
    collapse_state: reactive[CollapseState] = reactive(CollapseState.EXPANDED)

    def __init__(self, depth: int = 0, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._depth: int = depth
        self._has_children: bool = False
        self._open_time: float = _time.monotonic()
        self._completed_child_count: int = 0
        self._initial_collapse: CollapseState = (
            CollapseState.COMPACT if depth >= 1 else CollapseState.EXPANDED
        )
        if depth >= 1:
            self.add_class(f"--depth-{min(depth, 3)}")

    def compose(self) -> ComposeResult:
        self._header = SubAgentHeader()
        yield self._header
        self._body = SubAgentBody(id="subagent-body")
        yield self._body

    def on_mount(self) -> None:
        if self._initial_collapse != CollapseState.EXPANDED:
            self.collapse_state = self._initial_collapse
        if _accessibility_mode():
            self._body.add_class("-accessible")

    # --- Reactive watchers ---

    def watch_child_count(self, v: int) -> None:
        self._header.update(v, self.error_count, self.elapsed_ms, self.subtree_done)

    def watch_error_count(self, v: int) -> None:
        self._header.update(self.child_count, v, self.elapsed_ms, self.subtree_done)

    def watch_elapsed_ms(self, v: int) -> None:
        self._header.update(self.child_count, self.error_count, v, self.subtree_done)

    def watch_subtree_done(self, v: bool) -> None:
        self._header.update(self.child_count, self.error_count, self.elapsed_ms, v)

    def watch_collapse_state(self, state: CollapseState) -> None:
        if not self.is_mounted:
            return
        if state == CollapseState.COLLAPSED:
            self.add_class("--collapsed")
        else:
            self.remove_class("--collapsed")
        self._body.display = (state != CollapseState.COLLAPSED) and self._has_children
        for child in self._body.children:
            from hermes_cli.tui.child_panel import ChildPanel
            if isinstance(child, ChildPanel):
                child.set_compact(state == CollapseState.COMPACT)

    # --- Child management ---

    def _header_widget(self, panel: Any) -> "SubAgentHeader | Any | None":
        from hermes_cli.tui.child_panel import ChildPanel
        if isinstance(panel, ChildPanel):
            return panel._tool_header
        if isinstance(panel, SubAgentPanel):
            return panel._header
        return None

    def add_child_panel(self, panel: Any) -> None:
        if self._body.children:
            prev_last = self._body.children[-1]
            hdr = self._header_widget(prev_last)
            if hdr is not None:
                hdr._is_child_last = False
                if isinstance(hdr, SubAgentHeader):
                    hdr._set_gutter(False)
                hdr.refresh()
        hdr = self._header_widget(panel)
        if hdr is not None:
            hdr._is_child_last = True
            if isinstance(hdr, SubAgentHeader):
                hdr._set_gutter(True)
            hdr.refresh()
        self._body.mount(panel)
        if not self._has_children:
            self._has_children = True
            self.add_class("--has-children")
        self.child_count += 1

    def _notify_child_complete(
        self,
        tool_call_id: str,
        is_error: bool,
        dur_ms: int | None,
    ) -> None:
        if is_error:
            self.error_count += 1
        self._completed_child_count += 1
        self.elapsed_ms = int((_time.monotonic() - self._open_time) * 1000)
        if self._completed_child_count >= self.child_count > 0:
            self.subtree_done = True

    # --- Actions ---

    def action_toggle_collapse(self) -> None:
        if self.collapse_state == CollapseState.COLLAPSED:
            self.collapse_state = CollapseState.EXPANDED
        else:
            self.collapse_state = CollapseState.COLLAPSED

    def action_toggle_compact(self) -> None:
        if self.collapse_state == CollapseState.COMPACT:
            self.collapse_state = CollapseState.EXPANDED
        else:
            self.collapse_state = CollapseState.COMPACT

    def action_expand_all(self) -> None:
        from hermes_cli.tui.child_panel import ChildPanel
        for child in self._body.children:
            if isinstance(child, ChildPanel):
                child.set_compact(False)

    def action_compact_all(self) -> None:
        from hermes_cli.tui.child_panel import ChildPanel
        for child in self._body.children:
            if isinstance(child, ChildPanel):
                child.set_compact(True)

    def action_collapse_subtree(self) -> None:
        self.collapse_state = CollapseState.COLLAPSED

    # --- Completion ---

    def set_result_summary_v4(self, summary: Any) -> None:
        self.subtree_done = True
        if getattr(summary, "is_error", False):
            self._header.set_error(getattr(summary, "error_kind", None))

    set_result_summary = set_result_summary_v4
