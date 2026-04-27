"""SubAgentPanel — collapsible tree container for AGENT-category tool calls."""
from __future__ import annotations

import logging
import time as _time
from typing import Any

_log = logging.getLogger(__name__)

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.widgets.utils import _format_elapsed_compact
from hermes_cli.tui.tool_panel.density import DensityTier


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

    def update(self, child_count: int, error_count: int, elapsed_ms: int, done: bool,
               error_kinds: "list[str] | None" = None) -> None:
        elapsed_s = elapsed_ms / 1000.0
        elapsed_str = _format_elapsed_compact(elapsed_s)
        if _accessibility_mode():
            badge = f"calls:{child_count} err:{error_count} dur:{elapsed_str}"
            if error_count > 0 and error_kinds:
                badge += f" err-kinds:{','.join(error_kinds[:3])}"
            if not done and error_count == 0:
                badge = f"[running] {badge}"
            self._badges.update(badge)
        else:
            from rich.text import Text as _Text
            segments = [("calls", _Text(f"  {child_count} calls", style="dim"))]
            if not done and error_count == 0:
                segments.insert(0, ("running", _Text("● ", style="bold green")))
            if error_count > 0:
                err_word = "error" if error_count == 1 else "errors"
                try:
                    warn_color = self.app.get_css_variables().get("status-warn-color", "#FFA726")
                except Exception:
                    _log.debug("SubAgentPanel: css var lookup failed", exc_info=True)
                    warn_color = "#FFA726"
                segments.append(("errors", _Text(f"  {error_count} {err_word}", style=f"bold {warn_color}")))
                # D-2: show up to 3 distinct error_kind glyphs (canonical via _ERROR_DISPLAY)
                if error_kinds:
                    from hermes_cli.tui.tool_result_parse import error_glyph
                    glyphs = "".join(error_glyph(k) for k in error_kinds[:3])
                    segments.append(("error-kinds", _Text(f" {glyphs}", style=f"bold {warn_color}")))
            segments.append(("duration", _Text(f"  {elapsed_str}", style="dim")))
            try:
                w = self.app.size.width if self.app else 80
            except Exception:
                _log.debug("SubAgentPanel: app.size.width failed", exc_info=True)
                w = 80
            budget = max(0, w - 20)
            from hermes_cli.tui.tool_panel.layout_resolver import default_resolver, DensityTier as _DT
            trimmed = default_resolver().trim_header_tail(segments, budget, _DT.DEFAULT)
            tail = _Text()
            for _, seg in trimmed:
                tail.append_text(seg)
            self._badges.update(tail)
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
            self.parent.action_toggle_collapse()

    def set_error(self, error_kind: str | None) -> None:
        self._error_kind: str | None = error_kind
        self.add_class("--error")
        self.refresh()

    def _set_gutter(self, is_child_last: bool) -> None:
        """Update gutter prefix. Called only by SubAgentPanel.add_child_panel for depth≥1 panels.
        False = non-last child (├─). True = last child (└─).
        Gutter is 4 cells wide for column alignment with top-level ToolHeader.
        """
        acc = _accessibility_mode()
        if is_child_last:
            self._gutter.update(" └─ " if not acc else " \\- ")
        else:
            self._gutter.update(" ├─ " if not acc else " +- ")


class SubAgentPanel(Widget):
    DEFAULT_CSS = "SubAgentPanel { height: auto; layout: vertical; }"
    can_focus = True

    BINDINGS = [
        Binding("space",        "toggle_collapse",  show=False),
        Binding("ctrl+e",       "expand_all",       show=False),
        Binding("ctrl+shift+k", "compact_all",      show=False),
        Binding("ctrl+x",       "collapse_subtree", show=False),
    ]

    child_count:  reactive[int]        = reactive(0)
    error_count:  reactive[int]        = reactive(0)
    elapsed_ms:   reactive[int]        = reactive(0)
    subtree_done: reactive[bool]       = reactive(False)
    collapsed:    reactive[bool]       = reactive(False)
    density_tier: reactive[DensityTier] = reactive(DensityTier.DEFAULT, layout=False)

    def __init__(self, depth: int = 0, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._depth: int = depth
        self._has_children: bool = False
        self._open_time: float = _time.monotonic()
        self._completed_child_count: int = 0
        # D-2: track distinct error kinds across child panels
        self._child_error_kinds: list[str] = []
        if depth >= 1:
            self.add_class(f"--depth-{min(depth, 3)}")

    def compose(self) -> ComposeResult:
        self._header = SubAgentHeader()
        yield self._header
        self._body = SubAgentBody(id="subagent-body")
        yield self._body

    def on_mount(self) -> None:
        if self._depth >= 1:
            self.collapsed = True
        if _accessibility_mode():
            self._body.add_class("-accessible")

    # --- Reactive watchers ---

    def watch_child_count(self, v: int) -> None:
        self._header.update(v, self.error_count, self.elapsed_ms, self.subtree_done,
                            error_kinds=self._child_error_kinds)

    def watch_error_count(self, v: int) -> None:
        self._header.update(self.child_count, v, self.elapsed_ms, self.subtree_done,
                            error_kinds=self._child_error_kinds)

    def watch_elapsed_ms(self, v: int) -> None:
        self._header.update(self.child_count, self.error_count, v, self.subtree_done,
                            error_kinds=self._child_error_kinds)

    def watch_subtree_done(self, v: bool) -> None:
        self._header.update(self.child_count, self.error_count, self.elapsed_ms, v,
                            error_kinds=self._child_error_kinds)

    def watch_collapsed(self, v: bool) -> None:
        if not self.is_mounted:
            return
        if v:
            self.add_class("--collapsed")
        else:
            self.remove_class("--collapsed")
        self._body.display = (not v) and self._has_children
        self.density_tier = DensityTier.COMPACT if v else DensityTier.DEFAULT

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
            # D-2: extract and track distinct error kind
            _ek = self._extract_error_kind(tool_call_id)
            if _ek and _ek not in self._child_error_kinds:
                self._child_error_kinds.append(_ek)
            self.error_count += 1
        self._completed_child_count += 1
        self.elapsed_ms = int((_time.monotonic() - self._open_time) * 1000)
        if self._completed_child_count >= self.child_count > 0:
            self.subtree_done = True

    def _extract_error_kind(self, tool_call_id: str) -> "str | None":
        """D-2: extract error_kind from the ChildPanel with the given tool_call_id."""
        for child in self._body.children:
            child_id = getattr(getattr(child, "_block", None), "_tool_call_id", None)
            if child_id == tool_call_id:
                rs = getattr(child, "_result_summary_v4", None)
                if rs is not None:
                    return getattr(rs, "error_kind", None)
        return None

    # --- Actions ---

    def action_toggle_collapse(self) -> None:
        self.collapsed = not self.collapsed

    def action_expand_all(self) -> None:
        from hermes_cli.tui.child_panel import ChildPanel
        for child in self.query(ChildPanel):
            child._parent_clamp_tier = None
            if child._result_summary_v4 is not None:  # type: ignore[attr-defined]
                child._apply_complete_auto_collapse()  # type: ignore[attr-defined]
            else:
                child.set_compact(False)

    def action_compact_all(self) -> None:
        from hermes_cli.tui.child_panel import ChildPanel
        for child in self.query(ChildPanel):
            child._parent_clamp_tier = DensityTier.COMPACT
            if child._result_summary_v4 is not None:  # type: ignore[attr-defined]
                child._apply_complete_auto_collapse()  # type: ignore[attr-defined]
            else:
                child.set_compact(True)

    def action_collapse_subtree(self) -> None:
        self.collapsed = True

    # --- Completion ---

    def set_result_summary_v4(self, summary: Any) -> None:
        self.subtree_done = True
        if getattr(summary, "is_error", False):
            self._header.set_error(getattr(summary, "error_kind", None))

    set_result_summary = set_result_summary_v4
