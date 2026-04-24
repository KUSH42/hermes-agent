"""Tool panel grouping — v2 CSS-class virtual grouping + v4 ToolGroup widget.

Architecture: tui-tool-panel-v2-spec.md §7 (CSS virtual grouping, always active).
             tui-tool-panel-v4-D-toolgroup.md (widget grouping, behind config flag).

Virtual grouping (v2 path, always on):
  CSS classes `group-id-{hex}` + `tool-panel--grouped` tagged on sibling ToolPanels.
  No DOM containers, no reparenting.

Widget grouping (v4 path, `display.tool_group_widget: true`):
  ToolGroup(Widget) wraps grouped panels with a GroupHeader + GroupBody.
  Async reparenting via @work(exclusive=False) on MessagePanel after initial mount.
  Reparenting is the one permitted place where ToolPanels are moved between containers
  (sub-spec D §3.2 invariant). Only fires for completed (non-streaming) panels.

Rules (first match wins):
  1. Diff attachment: patch/write_file/create_file ← diff
  2. Search + open: SEARCH ← FILE whose path ∈ result_paths
  3. Shell pipeline: consecutive SHELL panels within 250ms or chained
  3b. Search batch: consecutive SEARCH panels
  Rule 4 (same-path chain) DROPPED in v4 widget path (kept in v2 CSS path).
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widget import Widget

from hermes_cli.tui.tool_accent import ToolAccent

from hermes_cli.tui.resize_utils import THRESHOLD_TOOL_NARROW, crosses_threshold

from hermes_cli.tui.resize_utils import THRESHOLD_TOOL_NARROW, crosses_threshold

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)

# Summary rule constants
RULE_DIFF_ATTACH = 1
RULE_SEARCH_OPEN = 2
RULE_SHELL_PIPE = 3
RULE_SEARCH_BATCH = 31  # "3b" in spec


# ---------------------------------------------------------------------------
# Semantic label helpers (v3 Phase B — §5.7)
# ---------------------------------------------------------------------------


def group_semantic_label(members: list) -> str:
    """Derive a semantic label from member tool names (dedup + count).

    Examples:
      patch × 2
      patch+diff · input_widget.py
      search+patch+write
    """
    labels = sorted({getattr(m, "_tool_name", "") for m in members if getattr(m, "_tool_name", "")})
    if not labels:
        return f"{len(members)} tools"
    if len(labels) == 1:
        count = len(members)
        return f"{labels[0]} × {count}" if count > 1 else labels[0]
    joined = "+".join(labels[:3])
    return joined if len(labels) <= 3 else joined + "+…"


def group_path_hint(members: list) -> str | None:
    """Return a single common basename if all members share the same file path."""
    paths: list[str] = []
    for m in members:
        args = getattr(m, "_tool_args", None) or {}
        p = args.get("path") or args.get("file_path") or args.get("target")
        if p:
            paths.append(str(p))
    if not paths:
        return None
    basenames = {os.path.basename(p) for p in paths}
    if len(basenames) == 1:
        return basenames.pop()
    return None


# ---------------------------------------------------------------------------
# Config guards
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
# GroupBody
# ---------------------------------------------------------------------------


class GroupBody(Widget):
    """Container for child ToolPanels. Indented 2 cells. Shown/hidden with group."""

    DEFAULT_CSS = """
    GroupBody {
        height: auto;
        padding-left: 2;
        layout: vertical;
    }
    """
    _content_type: str = "tool-group"


# ---------------------------------------------------------------------------
# GroupHeader
# ---------------------------------------------------------------------------


class GroupHeader(Widget):
    """Single-line group header: '  ┊ ▾/▸ {summary}  {+N -N}  {N.Ns}  {N ops}'"""

    DEFAULT_CSS = """
    GroupHeader {
        height: 1;
    }
    GroupHeader:focus {
        background: $boost;
    }
    """
    can_focus = False

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._summary_text = ""
        self._diff_add = 0
        self._diff_del = 0
        self._duration_ms = 0
        self._child_count = 0
        self._collapsed = False
        self._error_count: int = 0  # B2: child error count for header chip

    def update(
        self,
        summary_text: str,
        diff_add: int,
        diff_del: int,
        duration_ms: int,
        child_count: int,
        collapsed: bool,
        error_count: int = 0,  # B2: number of errored child panels
    ) -> None:
        self._summary_text = summary_text
        self._diff_add = diff_add
        self._diff_del = diff_del
        self._duration_ms = duration_ms
        self._child_count = child_count
        self._collapsed = collapsed
        self._error_count = error_count  # B2
        self.refresh()

    def render(self) -> Text:
        t = Text()
        t.append("  ┊ ", style="dim")
        toggle = "▸" if self._collapsed else "▾"
        t.append(toggle + " ", style="bold")

        # Summary text — truncate to terminal width budget
        term_w = self.size.width if self.size.width > 0 else 80
        tail_reserve = 30
        label_max = max(8, term_w - 9 - tail_reserve)
        summary = self._summary_text
        if len(summary) > label_max:
            summary = summary[: label_max - 1] + "…"
        t.append(summary)

        # Aggregate chips
        if self._diff_add:
            t.append(f"  +{self._diff_add}", style="green")
        if self._diff_del:
            t.append(f"  -{self._diff_del}", style="red")

        # Duration (v4 §2.2 rule)
        ms = self._duration_ms
        if ms >= 50:
            if ms < 5000:
                t.append(f"  {int(ms)}ms", style="dim")
            else:
                t.append(f"  {ms / 1000:.1f}s", style="dim")

        # B2: error count chip — shown before op count for prominence
        if self._error_count > 0:
            t.append(f"  {self._error_count} err", style="bold red")

        # Op count (drop first if narrow)
        if self._child_count > 1 and term_w >= 60:
            t.append(f"  {self._child_count} ops", style="dim")

        return t


# ---------------------------------------------------------------------------
# ToolGroup
# ---------------------------------------------------------------------------


class ToolGroup(Widget):
    """Real widget wrapping grouped ToolPanels (v4 §5, sub-spec D).

    Compose tree:
        ToolGroup
        ├── GroupHeader     (single-line toggle + aggregate chips)
        └── GroupBody       (indented container for ToolPanel children)

    Default: `display.tool_group_widget = false` — not created unless opted in.
    """

    DEFAULT_CSS = """
    ToolGroup {
        height: auto;
        layout: vertical;
    }
    ToolGroup.--collapsed GroupBody {
        display: none;
    }
    ToolGroup.--narrow GroupBody {
        display: none;
    }
    ToolGroup:focus > GroupHeader {
        background: $boost;
    }
    """

    _content_type: str = "tool-group"
    can_focus = True

    collapsed: reactive[bool] = reactive(False, layout=True)

    BINDINGS = [
        Binding("shift+enter", "peek_focused", "peek focused", show=False),
    ]

    def __init__(
        self,
        group_id: str,
        summary_rule: int,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._group_id = group_id
        self._summary_rule = summary_rule
        self._user_collapsed = False
        self._header: GroupHeader | None = None
        self._body: GroupBody | None = None
        self._last_resize_w: int = 0

    def compose(self) -> ComposeResult:
        header = GroupHeader()
        body = GroupBody()
        self._header = header
        self._body = body
        yield header
        yield body

    def watch_collapsed(self, value: bool) -> None:
        if not self.is_mounted:
            return
        if value:
            self.add_class("--collapsed")
        else:
            self.remove_class("--collapsed")

        # Focus safety: if a descendant has focus, move focus to ToolGroup
        try:
            focused = self.app.focused
            if focused is not None and focused is not self:
                for ancestor in focused.ancestors:
                    if ancestor is self:
                        self.focus()
                        break
        except Exception:
            pass

        # Sync header toggle glyph
        if self._header is not None:
            self._header._collapsed = value
            self._header.refresh()

        # Rebuild browse anchors so hidden children are skipped
        try:
            self.app._svc_browse.rebuild_browse_anchors()
        except Exception:
            pass

    def on_click(self, event: object) -> None:
        """Toggle collapsed on left-click only (button 1)."""
        if getattr(event, "button", 1) != 1:
            return
        self._user_collapsed = not self.collapsed
        self.collapsed = self._user_collapsed
        if hasattr(event, "stop"):
            event.stop()

    def on_resize(self, event: object) -> None:
        width = getattr(getattr(event, "size", None), "width", 80)
        if crosses_threshold(self._last_resize_w, width, THRESHOLD_TOOL_NARROW):
            self.set_class(width < THRESHOLD_TOOL_NARROW, "--narrow")
        self._last_resize_w = width

    def focus_first_child(self) -> None:
        if self._body is not None:
            children = list(self._body.children)
            if children:
                children[0].focus()

    def focus_last_child(self) -> None:
        if self._body is not None:
            children = list(self._body.children)
            if children:
                children[-1].focus()

    def action_peek_focused(self) -> None:
        """Expand only the focused child panel; collapse all others."""
        from hermes_cli.tui.tool_panel import ToolPanel as _TP
        if self._body is None:
            return
        panels = [c for c in self._body.children if isinstance(c, _TP)]
        if not panels:
            return
        # Expand group if collapsed
        if self.collapsed:
            self.collapsed = False
        focused = [
            p for p in panels
            if p.has_focus or any(c.has_focus for c in p.walk_children())
        ]
        if not focused:
            focused = panels[:1]  # fallback: expand first
        for p in panels:
            p.collapsed = (p not in focused)

    def recompute_aggregate(self) -> None:
        """Recompute header from children's result data (v4 §4.3)."""
        from hermes_cli.tui.tool_panel import ToolPanel as _TP

        if self._header is None or self._body is None:
            return

        children = [c for c in self._body.children if isinstance(c, _TP)]
        if len(children) > 20:
            _log.debug("toolgroup: skip recompute, %d children > 20 bound", len(children))
            return

        diff_add = 0
        diff_del = 0
        error_count = 0  # E4: track child error count for group header styling
        earliest: float | None = None
        latest: float | None = None

        for panel in children:
            # v2 result summary badges
            rs = getattr(panel, "_result_summary", None)
            if rs is not None:
                for badge in getattr(rs, "stat_badges", []):
                    if badge.startswith("+"):
                        try:
                            diff_add += int(badge[1:])
                        except ValueError:
                            pass
                    elif badge.startswith("-"):
                        try:
                            diff_del += int(badge[1:])
                        except ValueError:
                            pass
            # v4 chips + error count
            rs_v4 = getattr(panel, "_result_summary_v4", None)
            if rs_v4 is not None:
                from hermes_cli.tui.tool_result_parse import Chip
                # E4: accumulate error count
                if getattr(rs_v4, "is_error", False):
                    error_count += 1
                for chip in getattr(rs_v4, "chips", ()):
                    if chip.kind == "diff+":
                        try:
                            diff_add += int(chip.text.lstrip("+"))
                        except (ValueError, AttributeError):
                            pass
                    elif chip.kind == "diff-":
                        try:
                            diff_del += int(chip.text.lstrip("-"))
                        except (ValueError, AttributeError):
                            pass

            t0 = getattr(panel, "_start_time", None)
            t1 = getattr(panel, "_completed_at", None)
            if t0 is not None:
                if earliest is None or t0 < earliest:
                    earliest = t0
            if t1 is not None:
                if latest is None or t1 > latest:
                    latest = t1

        # Wall-clock duration
        if earliest is not None and latest is not None:
            duration_ms = int((latest - earliest) * 1000)
        elif earliest is not None:
            duration_ms = int((time.monotonic() - earliest) * 1000)
        else:
            duration_ms = 0

        summary_text = _build_summary_text(self._summary_rule, children)

        # E4: toggle CSS class on group header to indicate child errors
        try:
            self._header.set_class(error_count > 0, "--group-has-error")
        except Exception:
            pass

        self._header.update(
            summary_text=summary_text,
            diff_add=diff_add,
            diff_del=diff_del,
            duration_ms=duration_ms,
            child_count=len(children),
            collapsed=self.collapsed,
            error_count=error_count,  # B2: pass error count for chip rendering
        )

    def on_tool_panel_completed(self, event: object) -> None:
        """Re-aggregate when any child ToolPanel completes."""
        try:
            from hermes_cli.tui.tool_panel import ToolPanel as _TP
            if isinstance(event, _TP.Completed):
                event.stop()
                self.recompute_aggregate()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Group helpers
# ---------------------------------------------------------------------------


def _get_group_id(panel: Widget) -> str | None:
    for cls in panel.classes:
        if cls.startswith("group-id-"):
            return cls[9:]
    return None


def _is_category(panel: Widget, *cats: object) -> bool:
    cat = getattr(panel, "_category", None)
    return cat in cats


def _get_header_label(panel: Widget) -> str:
    try:
        from hermes_cli.tui.tool_blocks import ToolHeader as _TH
        header = next(iter(panel.query(_TH)), None)
        if header is not None:
            return str(getattr(header, "_label", ""))
    except Exception:
        pass
    return ""


def _share_dir_prefix(path_a: str, path_b: str, depth: int = 2) -> bool:
    if not path_a or not path_b:
        return False
    dir_a = path_a.rstrip("/").split("/")[:-1]
    dir_b = path_b.rstrip("/").split("/")[:-1]
    if len(dir_a) < depth or len(dir_b) < depth:
        return False
    return sum(1 for a, b in zip(dir_a, dir_b) if a == b) >= depth


def _find_diff_target(siblings: list[Widget]) -> Widget | None:
    diff_tools = {"patch", "write_file", "create_file"}
    now = time.monotonic()
    try:
        from hermes_cli.config import read_raw_config
        attach_window = float(read_raw_config().get("display", {}).get("diff_attach_window_s", 15.0))
    except Exception:
        attach_window = 15.0
    for panel in reversed(siblings):
        tool_name = getattr(panel, "_tool_name", "")
        if tool_name in diff_tools:
            completed = getattr(panel, "_completed_at", None)
            if completed is None or (now - completed) < attach_window:
                return panel
    return None


def _is_diff_panel(panel: Widget) -> bool:
    block = getattr(panel, "_block", None)
    if block is not None:
        return getattr(block, "_label", "") == "diff"
    try:
        from hermes_cli.tui.tool_blocks import ToolBlock as _TB
        blk = next(iter(panel.query(_TB)), None)
        return blk is not None and getattr(blk, "_label", "") == "diff"
    except Exception:
        return False


def _is_streaming(panel: Widget) -> bool:
    """Return True if the panel's inner block is still streaming."""
    block = getattr(panel, "_block", None)
    if block is None:
        return False
    return bool(getattr(block, "_streaming", False) or
                getattr(block, "_completed", None) is False)


def _get_tool_group(panel: Widget) -> "ToolGroup | None":
    """Return the ToolGroup containing panel, or None."""
    parent = getattr(panel, "parent", None)
    if isinstance(parent, GroupBody):
        grandparent = getattr(parent, "parent", None)
        if isinstance(grandparent, ToolGroup):
            return grandparent
    return None


def _get_effective_tp_siblings(message_panel: Widget) -> list[Widget]:
    """All ToolPanels in message_panel including those inside ToolGroups."""
    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    result: list[Widget] = []
    for child in message_panel.children:
        if isinstance(child, _TP):
            result.append(child)
        elif isinstance(child, ToolGroup) and child._body is not None:
            for grandchild in child._body.children:
                if isinstance(grandchild, _TP):
                    result.append(grandchild)
    return result


def _build_summary_text(rule: int, children: list[Widget]) -> str:
    if rule == RULE_DIFF_ATTACH:
        for panel in children:
            label = _get_header_label(panel)
            if label and label != "diff":
                return f"edited {label}"
        return "edited"
    elif rule == RULE_SEARCH_OPEN:
        from hermes_cli.tui.tool_category import classify_tool, ToolCategory
        for panel in children:
            tool_name = getattr(panel, "_tool_name", "") or ""
            if classify_tool(tool_name) == ToolCategory.FILE:
                label = _get_header_label(panel)
                if label:
                    return f"searched and opened {os.path.basename(label)}"
        return "searched and opened"
    elif rule == RULE_SHELL_PIPE:
        if children:
            cmd = _get_header_label(children[0])
            if cmd:
                return f"shell pipeline · {cmd[:40]}"
        return "shell pipeline"
    elif rule == RULE_SEARCH_BATCH:
        return f"searched · {len(children)} patterns"
    return "grouped"


# ---------------------------------------------------------------------------
# Widget grouping helpers below
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Rule evaluation
# ---------------------------------------------------------------------------


def _find_rule_match(
    message_panel: Widget,
    new_panel: Widget,
) -> tuple[Widget, int] | None:
    """Evaluate grouping rules 1-3b. Returns (existing_panel, rule) or None.

    Rules 1-3b from v2, with Rule 4 dropped for the widget path (kept in CSS path).
    existing_panel may be inside a ToolGroup already (detected by caller).
    """
    from hermes_cli.tui.tool_panel import ToolPanel as _TP
    from hermes_cli.tui.tool_category import ToolCategory

    if not isinstance(new_panel, _TP):
        return None

    # Effective siblings: ToolPanels in message_panel or inside its ToolGroups
    siblings = _get_effective_tp_siblings(message_panel)
    # Filter out new_panel itself (may already be in message_panel after initial mount)
    siblings = [s for s in siblings if s is not new_panel]
    if not siblings:
        return None

    prev = siblings[-1]

    # Rule 1: Diff attachment
    if _is_diff_panel(new_panel):
        target = _find_diff_target(siblings)
        if target is not None:
            return target, RULE_DIFF_ATTACH

    # Rule 2: Search + open
    if (
        _is_category(new_panel, ToolCategory.FILE)
        and _is_category(prev, ToolCategory.SEARCH)
    ):
        new_path = _get_header_label(new_panel)
        prev_paths: list[str] = getattr(prev, "_result_paths", [])
        if new_path and prev_paths and any(
            new_path.endswith(p) or p.endswith(new_path) for p in prev_paths
        ):
            return prev, RULE_SEARCH_OPEN

    # Rule 3: Shell pipeline
    if (
        _is_category(new_panel, ToolCategory.SHELL)
        and _is_category(prev, ToolCategory.SHELL)
    ):
        prev_cmd = _get_header_label(prev)
        chained = any(m in prev_cmd for m in ("&&", "||", ";", "|"))
        prev_start = getattr(prev, "_start_time", None)
        new_start = getattr(new_panel, "_start_time", None)
        try:
            from hermes_cli.config import read_raw_config
            pipeline_ms = int(read_raw_config().get("display", {}).get("shell_pipeline_ms", 500))
        except Exception:
            pipeline_ms = 500
        within_window = (
            prev_start is not None
            and new_start is not None
            and abs(new_start - prev_start) < pipeline_ms / 1000.0
        )
        if within_window or chained:
            return prev, RULE_SHELL_PIPE

    # Rule 3b: Search batch
    if (
        _is_category(new_panel, ToolCategory.SEARCH)
        and _is_category(prev, ToolCategory.SEARCH)
    ):
        return prev, RULE_SEARCH_BATCH

    return None



# ---------------------------------------------------------------------------
# Widget grouping — async reparenting helpers
# ---------------------------------------------------------------------------


async def _do_apply_group_widget(
    message_panel: Widget,
    existing_panel: Widget,
    new_panel: Widget,
    summary_rule: int,
) -> "ToolGroup":
    """Create ToolGroup, reparent existing_panel, mount new_panel (steps A-D).

    Called from MessagePanel._group_reparent_worker only.
    Both panels must still be in message_panel (or existing in a ToolGroup body)
    when this runs; caller must check before calling.

    Steps (sub-spec D §3.2 path 3c):
      A: mount ToolGroup before existing_panel in message_panel
      B: remove existing_panel from its current parent
      C: mount existing_panel into group body
      D: remove new_panel from message_panel, mount into group body
    """
    group_id = uuid.uuid4().hex[:8]
    group = ToolGroup(group_id=group_id, summary_rule=summary_rule)

    # Step A: mount ToolGroup before existing_panel's current position
    existing_parent = existing_panel.parent
    if existing_parent is message_panel:
        await message_panel.mount(group, before=existing_panel)
    elif isinstance(existing_parent, GroupBody):
        # Existing is already in a group — mount new_panel into that group
        tg = _get_tool_group(existing_panel)
        if tg is not None:
            if new_panel.parent is message_panel:
                await new_panel.remove()
            await tg._body.mount(new_panel)
            tg.recompute_aggregate()
            return tg
        # Fallback: mount group in message_panel
        await message_panel.mount(group)
    else:
        await message_panel.mount(group)

    # Step B: remove existing_panel from current parent
    await existing_panel.remove()

    # Step C: mount existing_panel into group body
    await group._body.mount(existing_panel)

    # Step D: remove new_panel from message_panel, mount into group body
    if new_panel.parent is message_panel:
        await new_panel.remove()
    await group._body.mount(new_panel)

    group.recompute_aggregate()

    # Rebuild browse anchors
    try:
        group.app._svc_browse.rebuild_browse_anchors()
    except Exception:
        pass

    return group


async def _do_append_to_group(
    group: "ToolGroup",
    new_panel: Widget,
    message_panel: Widget,
) -> None:
    """Append new_panel to an existing ToolGroup (§3.2 path 3b)."""
    if new_panel.parent is message_panel:
        await new_panel.remove()
    if group._body is not None:
        await group._body.mount(new_panel)
    group.recompute_aggregate()
    try:
        group.app._svc_browse.rebuild_browse_anchors()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def _maybe_start_group(message_panel: Widget, new_panel: Widget) -> None:
    """Sync entry point: evaluate grouping rules and schedule async reparent if matched."""
    if not _grouping_enabled():
        return
    match = _find_rule_match(message_panel, new_panel)
    if match is None:
        return
    existing_panel, rule = match
    existing_group = _get_tool_group(existing_panel)
    if existing_group is not None:
        message_panel.app.call_after_refresh(
            lambda: message_panel.run_worker(
                _do_append_to_group(existing_group, new_panel, message_panel),
                exclusive=False,
            )
        )
    else:
        message_panel.app.call_after_refresh(
            lambda: message_panel.run_worker(
                _do_apply_group_widget(message_panel, existing_panel, new_panel, rule),
                exclusive=False,
            )
        )

