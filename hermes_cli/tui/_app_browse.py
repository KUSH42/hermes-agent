"""_BrowseMixin — browse mode navigation methods for HermesApp."""
from __future__ import annotations

from typing import Any

from textual.css.query import NoMatches

from hermes_cli.tui._browse_types import (
    BrowseAnchor,
    BrowseAnchorType,
    _BROWSE_TYPE_GLYPH,
    _is_in_reasoning,
)


class _BrowseMixin:
    """Browse-mode navigation, anchor management, pip chrome.

    Extracted from HermesApp to reduce file size.  Self is always a HermesApp
    instance at runtime — all attribute access on self is valid.
    """

    def _apply_browse_focus(self) -> None:
        """Update .focused CSS class on all ToolHeaders based on browse state."""
        from hermes_cli.tui.tool_blocks import ToolHeader as _TH
        from hermes_cli.tui.tool_panel import ToolPanel as _TP
        headers = list(self.query(_TH))  # type: ignore[attr-defined]
        for i, h in enumerate(headers):
            if self.browse_mode and i == self.browse_index:  # type: ignore[attr-defined]
                h.add_class("focused")
                p = h.parent
                while p is not None and not isinstance(p, _TP):
                    p = p.parent
                if isinstance(p, _TP):
                    self.browse_detail_level = p.detail_level  # type: ignore[attr-defined]
            else:
                h.remove_class("focused")

    def watch_browse_mode(self, value: bool) -> None:
        if value:
            self._browse_uses += 1  # type: ignore[attr-defined]
            self._browse_cursor = 0  # type: ignore[attr-defined]
            self.add_class("--browse-active")  # type: ignore[attr-defined]
            self._rebuild_browse_anchors()
            self._apply_browse_pips()
            if self._browse_minimap_default and not self._browse_minimap:  # type: ignore[attr-defined]
                self.call_after_refresh(self._mount_minimap_default)  # type: ignore[attr-defined]
        else:
            self._browse_hint = ""  # type: ignore[attr-defined]
            self._clear_browse_highlight()
            self.remove_class("--browse-active")  # type: ignore[attr-defined]
            self._clear_browse_pips()
        try:
            inp = self.query_one("#input-area")  # type: ignore[attr-defined]
            inp.disabled = value
            if not value:
                inp.display = True
                inp.focus()
        except NoMatches:
            pass
        self._apply_browse_focus()
        self._set_hint_phase("browse" if value else self._compute_hint_phase())  # type: ignore[attr-defined]

    def _mount_minimap_default(self) -> None:
        """Auto-mount minimap on browse enter when minimap_default=True."""
        from hermes_cli.tui.widgets import OutputPanel
        try:
            from hermes_cli.tui.browse_minimap import BrowseMinimap as _BM
            output = self.query_one(OutputPanel)  # type: ignore[attr-defined]
            self.call_later(output.mount, _BM())  # type: ignore[attr-defined]
            self._browse_minimap = True  # type: ignore[attr-defined]
        except Exception:
            pass

    async def action_toggle_minimap(self) -> None:
        """Toggle the BrowseMinimap widget inside OutputPanel."""
        from hermes_cli.tui.widgets import OutputPanel
        from hermes_cli.tui.browse_minimap import BrowseMinimap as _BM
        if not self.browse_mode or not self._browse_markers_enabled:  # type: ignore[attr-defined]
            return
        try:
            existing = self.query_one(_BM)  # type: ignore[attr-defined]
            await existing.remove()
            self._browse_minimap = False  # type: ignore[attr-defined]
        except NoMatches:
            try:
                output = self.query_one(OutputPanel)  # type: ignore[attr-defined]
                await output.mount(_BM())
                self._browse_minimap = True  # type: ignore[attr-defined]
            except Exception:
                pass

    def watch_browse_index(self, _value: int) -> None:
        self._apply_browse_focus()

    # --- Unified browse anchor navigation ---

    def _rebuild_browse_anchors(self) -> None:
        """Rebuild anchor list in DOM (document) order. Clamp cursor to valid range."""
        from hermes_cli.tui.tool_blocks import ToolHeader as _TH
        from hermes_cli.tui.widgets import OutputPanel, StreamingCodeBlock, UserMessagePanel
        try:
            output = self.query_one(OutputPanel)  # type: ignore[attr-defined]
        except NoMatches:
            self._browse_anchors = []  # type: ignore[attr-defined]
            self._browse_cursor = 0  # type: ignore[attr-defined]
            return
        anchors: list[BrowseAnchor] = []
        turn_id = 0
        _tool_group_cls = None
        try:
            from hermes_cli.tui.tool_group import ToolGroup as _TG, GroupBody as _GB
            _tool_group_cls = _TG
            _group_body_cls = _GB
        except Exception:
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
                                pass
                        anchors.append(BrowseAnchor(
                            anchor_type=BrowseAnchorType.SUBAGENT_ROOT,
                            widget=widget,
                            label=f"Agent · {hdr_text}" if hdr_text else "Agent",
                            turn_id=turn_id,
                        ))
                        # Skip walking into body when collapsed
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
                    pass
        self._browse_anchors = anchors  # type: ignore[attr-defined]
        if anchors:
            self._browse_cursor = min(self._browse_cursor, len(anchors) - 1)  # type: ignore[attr-defined]
        else:
            self._browse_cursor = 0  # type: ignore[attr-defined]
        if self.browse_mode and not anchors:  # type: ignore[attr-defined]
            self._flash_hint("No turns to browse — start a conversation first", 2.0)  # type: ignore[attr-defined]
        if self.browse_mode:  # type: ignore[attr-defined]
            self._apply_browse_pips()

    def _jump_anchor(
        self,
        direction: int,
        filter_type: "BrowseAnchorType | None" = None,
    ) -> None:
        """Jump to next/previous anchor, optionally filtered by type."""
        if not self._browse_anchors:  # type: ignore[attr-defined]
            self._rebuild_browse_anchors()
        if not self._browse_anchors:  # type: ignore[attr-defined]
            return
        candidates = [
            (i, a) for i, a in enumerate(self._browse_anchors)  # type: ignore[attr-defined]
            if filter_type is None or a.anchor_type == filter_type
        ]
        if not candidates:
            return
        if direction == 1:
            for idx, anchor in candidates:
                if idx > self._browse_cursor:  # type: ignore[attr-defined]
                    self._focus_anchor(idx, anchor)
                    return
            self._focus_anchor(*candidates[0])
        else:
            for idx, anchor in reversed(candidates):
                if idx < self._browse_cursor:  # type: ignore[attr-defined]
                    self._focus_anchor(idx, anchor)
                    return
            self._focus_anchor(*candidates[-1])

    def _focus_anchor(self, idx: int, anchor: "BrowseAnchor", *, _retry: bool = True) -> None:
        """Scroll to and highlight the given anchor."""
        from hermes_cli.tui.widgets import OutputPanel
        w = anchor.widget
        if not getattr(w, "is_mounted", False):
            if _retry:
                self._rebuild_browse_anchors()
                for new_idx, new_anchor in enumerate(self._browse_anchors):  # type: ignore[attr-defined]
                    if new_anchor.anchor_type == anchor.anchor_type:
                        self._focus_anchor(new_idx, new_anchor, _retry=False)
                        return
            return
        self._browse_cursor = idx  # type: ignore[attr-defined]
        try:
            self.query_one(OutputPanel).scroll_to_widget(w, animate=True, center=True)  # type: ignore[attr-defined]
        except NoMatches:
            pass
        self._clear_browse_highlight()
        w.add_class("--browse-focused")  # type: ignore[union-attr]
        self._update_browse_status(anchor)

    def _clear_browse_highlight(self) -> None:
        """Remove --browse-focused CSS class from all widgets."""
        for w in self.query(".--browse-focused"):  # type: ignore[attr-defined]
            w.remove_class("--browse-focused")

    def _clear_browse_pips(self) -> None:
        """Remove all pip CSS classes and clear badge attrs from tracked widgets."""
        for w in self.query(".--has-pip"):  # type: ignore[attr-defined]
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
                pass
        for w in self._browse_badge_widgets:  # type: ignore[attr-defined]
            try:
                w._browse_badge = ""
            except Exception:
                pass
        self._browse_badge_widgets = []  # type: ignore[attr-defined]

    def _apply_browse_pips(self) -> None:
        """Apply pip CSS classes and badge attrs to all anchored widgets."""
        if not self._browse_markers_enabled:  # type: ignore[attr-defined]
            return
        self._clear_browse_pips()
        code_anchors = [a for a in self._browse_anchors if a.anchor_type == BrowseAnchorType.CODE_BLOCK]  # type: ignore[attr-defined]
        total_code = len(code_anchors)
        code_seq: dict[int, int] = {id(a.widget): i + 1 for i, a in enumerate(code_anchors)}
        for anchor in self._browse_anchors:  # type: ignore[attr-defined]
            w = anchor.widget
            try:
                if not w.is_mounted:  # type: ignore[union-attr]
                    continue
            except Exception:
                continue
            in_reasoning = _is_in_reasoning(w)
            if in_reasoning and not self._browse_reasoning_markers:  # type: ignore[attr-defined]
                continue
            if anchor.anchor_type == BrowseAnchorType.TURN_START:
                pip_cls = "--anchor-pip-turn"
            elif anchor.anchor_type == BrowseAnchorType.CODE_BLOCK:
                pip_cls = "--anchor-pip-code"
            elif anchor.anchor_type == BrowseAnchorType.TOOL_BLOCK:
                try:
                    pip_cls = "--anchor-pip-diff" if w.has_class("--diff-header") else "--anchor-pip-tool"  # type: ignore[union-attr]
                except Exception:
                    pip_cls = "--anchor-pip-tool"
            elif anchor.anchor_type == BrowseAnchorType.MEDIA:
                pip_cls = "--anchor-pip-media"
            else:
                continue
            try:
                w.add_class("--has-pip", pip_cls)  # type: ignore[union-attr]
            except Exception:
                continue
            if anchor.anchor_type == BrowseAnchorType.CODE_BLOCK and len(self._browse_badge_widgets) < 200:  # type: ignore[attr-defined]
                seq = code_seq.get(id(w), 0)
                lang = getattr(w, "_lang", "") or "text"
                badge = f"{lang} · {seq}/{total_code}"
                try:
                    w._browse_badge = badge  # type: ignore[union-attr]
                    self._browse_badge_widgets.append(w)  # type: ignore[attr-defined]
                except Exception:
                    pass
            elif pip_cls == "--anchor-pip-diff" and len(self._browse_badge_widgets) < 200:  # type: ignore[attr-defined]
                try:
                    w._browse_badge = "± diff"  # type: ignore[union-attr]
                    self._browse_badge_widgets.append(w)  # type: ignore[attr-defined]
                    w.refresh()  # type: ignore[union-attr]
                except Exception:
                    pass

    def _update_browse_status(self, anchor: "BrowseAnchor") -> None:
        """Update _browse_hint reactive with current anchor context."""
        anchors = self._browse_anchors  # type: ignore[attr-defined]
        typed = [a for a in anchors if a.anchor_type == anchor.anchor_type]
        pos = next((i + 1 for i, a in enumerate(typed) if a is anchor), 1)
        total = len(typed)
        glyph = _BROWSE_TYPE_GLYPH.get(anchor.anchor_type.value, "")
        prefix = f"{glyph} " if glyph else ""
        hint = f"{prefix}{anchor.label} {pos}/{total} · Turn {anchor.turn_id}"
        if self._browse_markers_enabled:  # type: ignore[attr-defined]
            hint += "  \\ map"
        self._browse_hint = hint  # type: ignore[attr-defined]

    # --- SubAgent browse navigation ---

    def action_jump_subagent_prev(self) -> None:
        self._jump_anchor(-1, BrowseAnchorType.SUBAGENT_ROOT)

    def action_jump_subagent_next(self) -> None:
        self._jump_anchor(+1, BrowseAnchorType.SUBAGENT_ROOT)

    # --- ToolPanel J/K navigation ---

    def _focus_tool_panel(self, direction: int) -> None:
        """Focus the next (direction=+1) or prev (direction=-1) ToolPanel."""
        from hermes_cli.tui.tool_panel import ToolPanel as _TP
        try:
            navigable = [w for w in self.query(_TP) if w.is_attached]  # type: ignore[attr-defined]
        except Exception:
            return
        if not navigable:
            return
        focused = self.focused  # type: ignore[attr-defined]
        try:
            idx = navigable.index(focused)
            next_idx = (idx + direction) % len(navigable)
        except ValueError:
            next_idx = 0 if direction > 0 else len(navigable) - 1
        navigable[next_idx].focus()
