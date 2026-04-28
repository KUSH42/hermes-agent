"""Browse mode, anchors, pips, minimap service extracted from _app_browse.py."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from textual.css.query import NoMatches

from hermes_cli.tui._browse_types import (
    BrowseAnchor,
    BrowseAnchorType,
    _BROWSE_TYPE_GLYPH,
    _is_in_reasoning,
)
from hermes_cli.tui.widgets import ScrollState
from .base import AppService

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp

_log = logging.getLogger(__name__)


class BrowseService(AppService):
    """Browse mode, anchors, pips, minimap."""

    def __init__(self, app: "HermesApp") -> None:
        super().__init__(app)
        # Service-owned browse state
        self._browse_anchors: list[BrowseAnchor] = []
        self._browse_cursor: int = 0

    # --- browse_mode watcher target ---

    def on_browse_mode(self, value: bool) -> None:
        """Called by App.watch_browse_mode — full logic lives here."""
        app = self.app
        if value:
            app._browse_uses += 1
            self._browse_cursor = 0
            app.add_class("--browse-active")
            self.rebuild_browse_anchors()
            self.apply_browse_pips()
            if app._browse_minimap_default and not app._browse_minimap:
                app.call_after_refresh(self.mount_minimap_default)
        else:
            app._browse_hint = ""
            self.clear_browse_highlight()
            app.remove_class("--browse-active")
            self.clear_browse_pips()
        try:
            inp = app.query_one("#input-area")
            inp.disabled = value
            if not value:
                inp.display = True
                inp.focus()
        except NoMatches:
            pass
        self.apply_browse_focus()
        app._svc_spinner.set_hint_phase("browse" if value else app._svc_spinner.compute_hint_phase())

    def mount_minimap_default(self) -> None:
        """Auto-mount minimap on browse enter when minimap_default=True."""
        app = self.app
        from hermes_cli.tui.widgets import OutputPanel
        try:
            from hermes_cli.tui.browse_minimap import BrowseMinimap as _BM
            output = app.query_one(OutputPanel)
            app.call_later(output.mount, _BM())
            app._browse_minimap = True
        except Exception:
            _log.debug("mount_minimap_default: failed to mount BrowseMinimap", exc_info=True)

    async def action_toggle_minimap(self) -> None:
        """Toggle the BrowseMinimap widget inside OutputPanel."""
        app = self.app
        from hermes_cli.tui.widgets import OutputPanel
        from hermes_cli.tui.browse_minimap import BrowseMinimap as _BM
        if not app.browse_mode or not app._browse_markers_enabled:
            return
        try:
            existing = app.query_one(_BM)
            await existing.remove()
            app._browse_minimap = False
        except NoMatches:
            try:
                output = app.query_one(OutputPanel)
                await output.mount(_BM())
                app._browse_minimap = True
            except Exception:
                _log.debug("action_toggle_minimap: mount failed", exc_info=True)

    def on_browse_index(self, _value: int) -> None:
        """Called by App.watch_browse_index."""
        self.apply_browse_focus()

    # --- Core browse methods ---

    def apply_browse_focus(self) -> None:
        """Update .focused CSS class on all ToolHeaders based on browse state."""
        app = self.app
        from hermes_cli.tui.tool_blocks import ToolHeader as _TH
        from hermes_cli.tui.tool_panel import ToolPanel as _TP
        headers = list(app.query(_TH))
        for i, h in enumerate(headers):
            if app.browse_mode and i == app.browse_index:
                h.add_class("focused")
                p = h.parent
                while p is not None and not isinstance(p, _TP):
                    p = p.parent
                if isinstance(p, _TP):
                    app.browse_detail_level = p.detail_level
            else:
                h.remove_class("focused")

    def rebuild_browse_anchors(self) -> None:
        """Rebuild anchor list in DOM (document) order. Clamp cursor to valid range."""
        app = self.app
        from hermes_cli.tui.tool_blocks import ToolHeader as _TH
        from hermes_cli.tui.widgets import OutputPanel, StreamingCodeBlock, UserMessagePanel
        try:
            output = app.query_one(OutputPanel)
        except NoMatches:
            self._browse_anchors = []
            self._browse_cursor = 0
            return
        anchors: list[BrowseAnchor] = []
        turn_id = 0
        _tool_group_cls = None
        try:
            from hermes_cli.tui.tool_group import ToolGroup as _TG, GroupBody as _GB
            _tool_group_cls = _TG
            _group_body_cls = _GB
        except Exception:
            _log.debug("rebuild_browse_anchors: ToolGroup import failed", exc_info=True)
            _group_body_cls = None
        for widget in output.walk_children(with_self=False):
            if isinstance(widget, UserMessagePanel):
                turn_id += 1
                anchors.append(BrowseAnchor(
                    anchor_type=BrowseAnchorType.TURN_START,
                    widget=widget,
                    label=f"Turn {turn_id}",
                    turn_id=turn_id,
                ))
            elif _tool_group_cls is not None and isinstance(widget, _tool_group_cls):
                header = widget._header
                label_text = (header._summary_text if header is not None else "") or "Group"
                child_count = 0
                if widget._body is not None:
                    try:
                        from hermes_cli.tui.tool_panel import ToolPanel as _TP
                        child_count = sum(1 for c in widget._body.children if isinstance(c, _TP))
                    except Exception:
                        # child_count is best-effort; zero is a safe fallback for display
                        pass
                collapsed_mark = " ▸" if widget.collapsed else " ▾"
                anchors.append(BrowseAnchor(
                    anchor_type=BrowseAnchorType.TOOL_BLOCK,
                    widget=widget,
                    label=f"Group{collapsed_mark} · {label_text} ({child_count})",
                    turn_id=turn_id,
                ))
            elif isinstance(widget, StreamingCodeBlock):
                if widget.is_mounted and widget._state != "STREAMING":
                    anchors.append(BrowseAnchor(
                        anchor_type=BrowseAnchorType.CODE_BLOCK,
                        widget=widget,
                        label=f"Code · {widget._lang or 'text'}",
                        turn_id=turn_id,
                    ))
            elif isinstance(widget, _TH):
                if _group_body_cls is not None and _tool_group_cls is not None:
                    parent = getattr(widget, "parent", None)
                    grandparent = getattr(parent, "parent", None)
                    if isinstance(grandparent, _tool_group_cls) and grandparent.collapsed:
                        continue
                label = widget._label or "Tool"
                if widget.has_class("--diff-header"):
                    label = f"Diff · {label}"
                anchors.append(BrowseAnchor(
                    anchor_type=BrowseAnchorType.TOOL_BLOCK,
                    widget=widget,
                    label=label,
                    turn_id=turn_id,
                ))
            else:
                try:
                    from hermes_cli.tui.sub_agent_panel import SubAgentPanel as _SAP, CollapseState as _CS
                    if isinstance(widget, _SAP) and widget._depth == 0:
                        hdr_label = getattr(getattr(widget, "_header", None), "_label", None)
                        hdr_text = ""
                        if hdr_label is not None:
                            try:
                                hdr_text = str(hdr_label.renderable)
                            except Exception:
                                # hdr_text string conversion failed; empty label is a safe display fallback
                                pass
                        anchors.append(BrowseAnchor(
                            anchor_type=BrowseAnchorType.SUBAGENT_ROOT,
                            widget=widget,
                            label=f"Agent · {hdr_text}" if hdr_text else "Agent",
                            turn_id=turn_id,
                        ))
                        if widget.collapse_state == _CS.COLLAPSED:
                            continue
                except Exception:
                    pass
                try:
                    from hermes_cli.tui.widgets import InlineMediaWidget as _IMW
                    from hermes_cli.tui.media_player import _short_url as _su
                    if isinstance(widget, _IMW):
                        anchors.append(BrowseAnchor(
                            anchor_type=BrowseAnchorType.MEDIA,
                            widget=widget,
                            label=f"Media · {widget._kind} · {_su(widget._url)}",
                            turn_id=turn_id,
                        ))
                except Exception:
                    _log.debug("rebuild_browse_anchors: InlineMediaWidget import failed", exc_info=True)
        self._browse_anchors = anchors
        # Keep app-level alias in sync
        app._browse_anchors = anchors
        if anchors:
            cur = getattr(app, "_browse_cursor", self._browse_cursor)
            self._browse_cursor = min(cur, len(anchors) - 1)
        else:
            self._browse_cursor = 0
        app._browse_cursor = self._browse_cursor
        if app.browse_mode and not anchors:
            app._flash_hint("No turns to browse — start a conversation first", 2.0)
        if app.browse_mode:
            self.apply_browse_pips()

    def jump_anchor(
        self,
        direction: int,
        filter_type: "BrowseAnchorType | None" = None,
    ) -> None:
        """Jump to next/previous anchor, optionally filtered by type."""
        if not self._browse_anchors:
            self.rebuild_browse_anchors()
        if not self._browse_anchors:
            return
        candidates = [
            (i, a) for i, a in enumerate(self._browse_anchors)
            if filter_type is None or a.anchor_type == filter_type
        ]
        if not candidates:
            return
        cur = getattr(self.app, "_browse_cursor", self._browse_cursor)
        if direction == 1:
            for idx, anchor in candidates:
                if idx > cur:
                    self.focus_anchor(idx, anchor)
                    return
            self.focus_anchor(*candidates[0])
        else:
            for idx, anchor in reversed(candidates):
                if idx < cur:
                    self.focus_anchor(idx, anchor)
                    return
            self.focus_anchor(*candidates[-1])

    def focus_anchor(self, idx: int, anchor: "BrowseAnchor", *, _retry: bool = True) -> None:
        """Scroll to and highlight the given anchor."""
        from hermes_cli.tui.widgets import OutputPanel
        app = self.app
        w = anchor.widget
        if not getattr(w, "is_mounted", False):
            if _retry:
                self.rebuild_browse_anchors()
                for new_idx, new_anchor in enumerate(self._browse_anchors):
                    if new_anchor.anchor_type == anchor.anchor_type:
                        self.focus_anchor(new_idx, new_anchor, _retry=False)
                        return
            return
        self._browse_cursor = idx
        app._browse_cursor = idx
        try:
            output = app.query_one(OutputPanel)
            output._last_scroll_origin = "browse_jump"
            output.scroll_state = ScrollState.JUMPED
            output.scroll_to_widget(w, animate=True, center=True)
        except NoMatches:
            pass
        self.clear_browse_highlight()
        w.add_class("--browse-focused")
        self.update_browse_status(anchor)

    def clear_browse_highlight(self) -> None:
        """Remove --browse-focused CSS class from all widgets."""
        for w in self.app.query(".--browse-focused"):
            w.remove_class("--browse-focused")

    def clear_browse_pips(self) -> None:
        """Remove all pip CSS classes and clear badge attrs from tracked widgets."""
        app = self.app
        for w in app.query(".--has-pip"):
            try:
                w.remove_class(
                    "--has-pip",
                    "--anchor-pip-turn",
                    "--anchor-pip-code",
                    "--anchor-pip-tool",
                    "--anchor-pip-diff",
                    "--anchor-pip-media",
                )
            except Exception:
                # Widget unmounted between is_mounted check and mutation; skip safely
                pass
        for w in app._browse_badge_widgets:
            try:
                w._browse_badge = ""
            except Exception:
                # Widget unmounted between is_mounted check and mutation; skip safely
                pass
        app._browse_badge_widgets = []

    def apply_browse_pips(self) -> None:
        """Apply pip CSS classes and badge attrs to all anchored widgets."""
        app = self.app
        if not app._browse_markers_enabled:
            return
        self.clear_browse_pips()
        anchors = getattr(app, "_browse_anchors", None) or self._browse_anchors
        code_anchors = [a for a in anchors if a.anchor_type == BrowseAnchorType.CODE_BLOCK]
        total_code = len(code_anchors)
        code_seq: dict[int, int] = {id(a.widget): i + 1 for i, a in enumerate(code_anchors)}
        for anchor in anchors:
            w = anchor.widget
            try:
                if not w.is_mounted:
                    continue
            except Exception:
                # Widget unmounted between is_mounted check and mutation; skip safely
                continue
            in_reasoning = _is_in_reasoning(w)
            if in_reasoning and not app._browse_reasoning_markers:
                continue
            if anchor.anchor_type == BrowseAnchorType.TURN_START:
                pip_cls = "--anchor-pip-turn"
            elif anchor.anchor_type == BrowseAnchorType.CODE_BLOCK:
                pip_cls = "--anchor-pip-code"
            elif anchor.anchor_type == BrowseAnchorType.TOOL_BLOCK:
                try:
                    pip_cls = "--anchor-pip-diff" if w.has_class("--diff-header") else "--anchor-pip-tool"
                except Exception:
                    pip_cls = "--anchor-pip-tool"
            elif anchor.anchor_type == BrowseAnchorType.MEDIA:
                pip_cls = "--anchor-pip-media"
            else:
                continue
            try:
                w.add_class("--has-pip", pip_cls)
            except Exception:
                # Widget unmounted between is_mounted check and mutation; skip safely
                continue
            if anchor.anchor_type == BrowseAnchorType.CODE_BLOCK and len(app._browse_badge_widgets) < 200:
                seq = code_seq.get(id(w), 0)
                lang = getattr(w, "_lang", "") or "text"
                badge = f"{lang} · {seq}/{total_code}"
                try:
                    w._browse_badge = badge
                    app._browse_badge_widgets.append(w)
                except Exception:
                    # Widget unmounted between is_mounted check and mutation; skip safely
                    pass
            elif pip_cls == "--anchor-pip-diff" and len(app._browse_badge_widgets) < 200:
                try:
                    w._browse_badge = "± diff"
                    app._browse_badge_widgets.append(w)
                    w.refresh()
                except Exception:
                    # Widget unmounted between is_mounted check and mutation; skip safely
                    pass

    def update_browse_status(self, anchor: "BrowseAnchor") -> None:
        """Update _browse_hint reactive with current anchor context."""
        app = self.app
        anchors = self._browse_anchors
        typed = [a for a in anchors if a.anchor_type == anchor.anchor_type]
        pos = next((i + 1 for i, a in enumerate(typed) if a is anchor), 1)
        total = len(typed)
        glyph = _BROWSE_TYPE_GLYPH.get(anchor.anchor_type.value, "")
        prefix = f"{glyph} " if glyph else ""
        hint = f"{prefix}{anchor.label} {pos}/{total} · Turn {anchor.turn_id}"
        if app._browse_markers_enabled:
            hint += "  \\ map"
        app._browse_hint = hint

    # --- Plan panel tool scroll ---

    def scroll_to_tool(self, tool_call_id: str) -> bool:
        """Scroll and highlight the ToolPanel with the given tool_call_id.

        Returns True if found, False if not mounted yet.
        """
        from hermes_cli.tui.tool_panel import ToolPanel
        from hermes_cli.tui.widgets import OutputPanel
        try:
            output = self.app.query_one(OutputPanel)
            for panel in output.query(ToolPanel):
                if getattr(panel, "_plan_tool_call_id", None) == tool_call_id:
                    output._last_scroll_origin = "browse_jump"
                    output.scroll_state = ScrollState.JUMPED
                    output.scroll_to_widget(panel, animate=True, center=True)
                    self.clear_browse_highlight()
                    # F-2 contract (concept v0.7 FA-4): scroll_to_tool flashes --browse-focused, does NOT call panel.focus().
                    panel.add_class("--browse-focused")
                    return True
        except NoMatches:
            # OutputPanel not mounted; scroll unavailable — correct to skip
            pass
        except Exception:
            _log.debug("scroll_to_tool: scroll failed for tool_call_id=%r", tool_call_id, exc_info=True)
        return False

    # --- SubAgent browse navigation ---

    def action_jump_subagent_prev(self) -> None:
        self.jump_anchor(-1, BrowseAnchorType.SUBAGENT_ROOT)

    def action_jump_subagent_next(self) -> None:
        self.jump_anchor(+1, BrowseAnchorType.SUBAGENT_ROOT)

    # --- ToolPanel J/K navigation ---

    def focus_tool_panel(self, direction: int) -> None:
        """Focus the next (direction=+1) or prev (direction=-1) ToolPanel."""
        app = self.app
        from hermes_cli.tui.tool_panel import ToolPanel as _TP
        try:
            navigable = [w for w in app.query(_TP) if w.is_attached]
        except Exception:
            return
        if not navigable:
            return
        focused = app.focused
        try:
            idx = navigable.index(focused)
            next_idx = (idx + direction) % len(navigable)
        except ValueError:
            next_idx = 0 if direction > 0 else len(navigable) - 1
        navigable[next_idx].focus()
