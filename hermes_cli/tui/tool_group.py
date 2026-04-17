"""GroupHeader widget and _maybe_start_group heuristic.

Architecture: tui-tool-panel-v2-spec.md §7.

Virtual grouping — no DOM containers, no reparenting.
A "group" is:
  - A GroupHeader widget mounted as a sibling before the first member.
  - All member ToolPanels tagged with class `group-id-<hex>` + `tool-panel--grouped`.

No widget is ever removed or remounted. Grouping is achieved via:
  1. mount(GroupHeader, before=anchor_panel)
  2. anchor_panel.add_class("group-id-<hex>")  # no lifecycle hook
"""

from __future__ import annotations

import os
import time
import uuid
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Opt-out check
# ---------------------------------------------------------------------------


def _grouping_enabled() -> bool:
    """Return False when HERMES_TOOL_GROUPING=0 or display.tool_grouping: false."""
    env = os.environ.get("HERMES_TOOL_GROUPING", "1").lower().strip()
    if env in ("0", "false", "no"):
        return False
    try:
        from hermes_cli.config import read_raw_config
        cfg = read_raw_config()
        return bool(cfg.get("display", {}).get("tool_grouping", True))
    except Exception:
        return True


# ---------------------------------------------------------------------------
# GroupHeader widget
# ---------------------------------------------------------------------------


class GroupHeader(Widget):
    """Virtual group header — one per group, mounted before first member.

    Carries `_group_id` used by on_click to find and toggle member visibility.
    No DOM children relationship — members are siblings sharing a CSS class.
    """

    can_focus = True

    DEFAULT_CSS = """
    GroupHeader {
        height: 1;
        layout: horizontal;
        color: $text-muted;
        padding: 0 1;
    }
    GroupHeader:focus { background: $accent 10%; }
    GroupHeader > .group-glyph { width: 1; margin-right: 1; }
    GroupHeader > .group-label { width: auto; }
    """

    COMPONENT_CLASSES = {"group-header--focused"}

    def __init__(self, group_id: str, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._group_id = group_id
        self._collapsed = False
        self._member_count = 0

    def compose(self) -> ComposeResult:
        self._glyph_widget = Static("▾", classes="group-glyph")
        self._label_widget = Static("0 tools", classes="group-label")
        yield self._glyph_widget
        yield self._label_widget

    def update_count(self, count: int) -> None:
        self._member_count = count
        suffix = "tools" if count != 1 else "tool"
        label = getattr(self, "_label_widget", None)
        if label is not None and label.parent is not None:
            label.update(f"{count} {suffix}")

    def on_mount(self) -> None:
        # Render any count that arrived before compose() ran.
        suffix = "tools" if self._member_count != 1 else "tool"
        label = getattr(self, "_label_widget", None)
        if label is not None:
            label.update(f"{self._member_count} {suffix}")

    def on_click(self) -> None:
        self._collapsed = not self._collapsed
        parent = self.parent
        if parent is None:
            return
        self._glyph_widget.update("▸" if self._collapsed else "▾")
        class_name = f"group-id-{self._group_id}"
        for child in parent.children:
            if child.has_class(class_name):
                if self._collapsed:
                    child.add_class("group-hidden")
                else:
                    child.remove_class("group-hidden")

    def on_focus(self) -> None:
        self.add_class("group-header--focused")

    def on_blur(self) -> None:
        self.remove_class("group-header--focused")


# ---------------------------------------------------------------------------
# Group helpers
# ---------------------------------------------------------------------------


def _get_group_id(panel: Widget) -> str | None:
    """Return the group_id hex string from a panel's CSS classes, or None."""
    for cls in panel.classes:
        if cls.startswith("group-id-"):
            return cls[9:]
    return None


def _find_group_header(message_panel: Widget, group_id: str) -> GroupHeader | None:
    for child in message_panel.children:
        if isinstance(child, GroupHeader) and child._group_id == group_id:
            return child
    return None


def _is_category(panel: Widget, *cats: object) -> bool:
    cat = getattr(panel, "_category", None)
    return cat in cats


def _get_header_label(panel: Widget) -> str:
    """Extract the display label from a ToolPanel's inner ToolHeader."""
    try:
        from hermes_cli.tui.tool_blocks import ToolHeader as _TH
        header = next(iter(panel.query(_TH)), None)
        if header is not None:
            return str(getattr(header, "_label", ""))
    except Exception:
        pass
    return ""


def _share_dir_prefix(path_a: str, path_b: str, depth: int = 2) -> bool:
    """Return True if path_a and path_b share at least *depth* directory components."""
    if not path_a or not path_b:
        return False
    dir_a = path_a.rstrip("/").split("/")[:-1]
    dir_b = path_b.rstrip("/").split("/")[:-1]
    if len(dir_a) < depth or len(dir_b) < depth:
        return False
    common = sum(1 for a, b in zip(dir_a, dir_b) if a == b)
    return common >= depth


def _find_diff_target(siblings: list[Widget]) -> Widget | None:
    """Rule 1 walkback: find most-recent patch/write_file/create_file within 10s."""
    diff_tools = {"patch", "write_file", "create_file"}
    now = time.monotonic()
    for panel in reversed(siblings):
        tool_name = getattr(panel, "_tool_name", "")
        if tool_name in diff_tools:
            completed = getattr(panel, "_completed_at", None)
            if completed is None or (now - completed) < 10.0:
                return panel
    return None


def _is_diff_panel(panel: Widget) -> bool:
    # Check _block directly — compose() hasn't run yet on unattached panels,
    # so DOM queries return nothing. _block is set in ToolPanel.__init__.
    block = getattr(panel, "_block", None)
    if block is not None:
        return getattr(block, "_label", "") == "diff"
    # Fallback for already-mounted panels
    try:
        from hermes_cli.tui.tool_blocks import ToolBlock as _TB
        blk = next(iter(panel.query(_TB)), None)
        return blk is not None and getattr(blk, "_label", "") == "diff"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Core grouping function
# ---------------------------------------------------------------------------


def _maybe_start_group(message_panel: Widget, new_panel: Widget) -> None:
    """Evaluate grouping rules and apply virtual grouping if a rule fires.

    Called from MessagePanel._mount_nonprose_block BEFORE new_panel is mounted,
    so new_panel is not yet in message_panel.children.
    Mutates: may call message_panel.mount(GroupHeader) and add CSS classes.

    Rules (§7.1, first match wins):
      1. Diff attachment — patch/write_file/create_file ← diff
      2. Search + open  — search tool ← file tool whose path ∈ result_paths
      3. Shell pipeline — two consecutive shell tools (within 250ms or chained)
      4. Same-path chain — consecutive file tools sharing dir prefix depth≥2
    """
    if not _grouping_enabled():
        return

    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    from hermes_cli.tui.tool_category import ToolCategory

    if not isinstance(new_panel, _TP):
        return

    # Collect only ToolPanel siblings from THIS message_panel (no cross-message)
    siblings = [
        c for c in message_panel.children
        if isinstance(c, _TP)
    ]
    if not siblings:
        return

    prev = siblings[-1]

    # --- Rule 1: Diff attachment ---
    if _is_diff_panel(new_panel):
        target = _find_diff_target(siblings)
        if target is not None:
            _apply_group(message_panel, target, new_panel)
            return

    # --- Rule 2: Search + open ---
    if (
        _is_category(new_panel, ToolCategory.FILE)
        and _is_category(prev, ToolCategory.SEARCH)
    ):
        new_path = _get_header_label(new_panel)
        prev_paths: list[str] = getattr(prev, "_result_paths", [])
        if new_path and prev_paths and any(
            new_path.endswith(p) or p.endswith(new_path) for p in prev_paths
        ):
            _apply_group(message_panel, prev, new_panel)
            return

    # --- Rule 3: Shell pipeline ---
    if (
        _is_category(new_panel, ToolCategory.SHELL)
        and _is_category(prev, ToolCategory.SHELL)
    ):
        prev_cmd = _get_header_label(prev)
        chained = any(m in prev_cmd for m in ("&&", "||", ";", "|"))
        prev_start = getattr(prev, "_start_time", None)
        new_start = getattr(new_panel, "_start_time", None)
        within_250ms = (
            prev_start is not None
            and new_start is not None
            and abs(new_start - prev_start) < 0.250
        )
        if within_250ms or chained:
            _apply_group(message_panel, prev, new_panel)
            return

    # --- Rule 4: Same-path chain ---
    if (
        _is_category(new_panel, ToolCategory.FILE)
        and _is_category(prev, ToolCategory.FILE)
    ):
        if _share_dir_prefix(_get_header_label(new_panel), _get_header_label(prev), depth=2):
            _apply_group(message_panel, prev, new_panel)
            return


def _apply_group(
    message_panel: Widget,
    existing_panel: Widget,
    new_panel: Widget,
) -> None:
    """Mint or reuse a group_id; tag both panels; mount GroupHeader if new."""
    group_id = _get_group_id(existing_panel)
    if group_id is None:
        group_id = uuid.uuid4().hex[:8]
        header = GroupHeader(group_id=group_id)
        message_panel.mount(header, before=existing_panel)
        existing_panel.add_class(f"group-id-{group_id}")
        existing_panel.add_class("tool-panel--grouped")

    new_panel.add_class(f"group-id-{group_id}")
    new_panel.add_class("tool-panel--grouped")

    # Update GroupHeader member count
    gh = _find_group_header(message_panel, group_id)
    if gh is not None:
        # new_panel not yet in message_panel.children (mounts after this returns),
        # so add +1 to get the correct member count.
        count = sum(
            1 for c in message_panel.children
            if c.has_class(f"group-id-{group_id}")
        ) + 1
        gh.update_count(count)
