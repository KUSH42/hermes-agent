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
import re
import time
import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from hermes_cli.tui.resize_utils import THRESHOLD_TOOL_NARROW, crosses_threshold
from hermes_cli.tui.services.tools import ToolCallState
from hermes_cli.tui.tool_panel.layout_resolver import THRESHOLDS, DensityTier

if TYPE_CHECKING:
    pass

_log = logging.getLogger(__name__)

# Summary rule constants
RULE_DIFF_ATTACH  = 1
RULE_SEARCH_OPEN  = 2
RULE_SHELL_PIPE   = 3
RULE_SEARCH_BATCH = 31  # "3b" in spec
RULE_SHELL_BATCH  = 32  # temporal cluster without pipeline operators
RULE_FILE_EDIT    = 4   # read followed by write on the same path

# H2: pipeline-operator detection (single | but not ||)
_PIPELINE_OPS_RE = re.compile(r"(?:&&|\|\||;|(?<!\|)\|(?!\|))")

# H3: tool name sets for file-edit pairing
_FILE_WRITE_TOOLS = frozenset({"patch", "write_file", "create_file", "edit_file", "str_replace_editor"})
_FILE_READ_TOOLS  = frozenset({"read_file", "view"})

# PG-3: heuristic regex for streaming error lines (advisory; overwritten at terminal)
_STREAMING_ERR_RE = re.compile(
    r"^(Error|error|Traceback \(most recent call last\)|FATAL|Exception)[:( ]"
)


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
    except Exception:  # il-ex-1-exempt: config unavailable (e.g. test environment); grouping defaults to enabled
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
        self._terminal_at: float | None = None
        self._group_state_value: str = ""

    def update(
        self,
        summary_text: str,
        diff_add: int,
        diff_del: int,
        duration_ms: int,
        child_count: int,
        collapsed: bool,
        error_count: int = 0,  # B2: number of errored child panels
        terminal_at: float | None = None,
        group_state: str = "",
    ) -> None:
        self._summary_text = summary_text
        self._diff_add = diff_add
        self._diff_del = diff_del
        self._duration_ms = duration_ms
        self._child_count = child_count
        self._collapsed = collapsed
        self._error_count = error_count  # B2
        self._terminal_at = terminal_at
        self._group_state_value = group_state
        self.refresh()

    def render(self) -> Text:
        from hermes_cli.tui.body_renderers._grammar import GLYPH_GUTTER_GROUP
        t = Text()
        t.append(f"  {GLYPH_GUTTER_GROUP} ", style="dim")
        toggle = "▸" if self._collapsed else "▾"
        t.append(toggle + " ", style="bold")
        glyph_char, glyph_style = _OUTCOME_GLYPH.get(self._group_state_value, ("", ""))
        if glyph_char:
            t.append(f"{glyph_char} ", style=glyph_style)

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
            t.append(f"  +{self._diff_add}", style="green")  # il-tok-1-exempt: semantic diff color; green=added lines
        if self._diff_del:
            t.append(f"  -{self._diff_del}", style="red")  # il-tok-1-exempt: semantic diff color; red=deleted lines

        # Duration / terminal chip (GHF-H1 + v4 §2.2 rule)
        if self._terminal_at is not None:
            # GHF-H1: frozen terminal summary chip
            from hermes_cli.tui.tool_blocks._group_header_stats import terminal_stats, _clock_hhmm
            chip = terminal_stats(
                tool_count=self._child_count,
                total_span_s=self._duration_ms / 1000.0,
                clock_hhmm=_clock_hhmm(self._terminal_at),
            )
            t.append(f"  {chip}", style="dim")
        elif self._duration_ms >= 50:
            # live duration while still running
            if self._duration_ms < 5000:
                t.append(f"  {int(self._duration_ms)}ms", style="dim")
            else:
                t.append(f"  {self._duration_ms / 1000:.1f}s", style="dim")

        # B2: error count chip — shown before op count for prominence
        if self._error_count > 0:
            t.append(f"  {self._error_count} err", style="bold red")  # il-tok-1-exempt: semantic error color; no SkinColors token for error state in this chip

        # Op count — compact form at narrow widths
        if self._child_count > 1:
            if term_w >= 60:
                t.append(f"  {self._child_count} ops", style="dim")
            elif term_w >= 40:
                t.append(f"  ×{self._child_count}", style="dim")
            # below 40: omit (header already truncated hard)

        return t


# ---------------------------------------------------------------------------
# PG-4: ToolGroupState + helper
# ---------------------------------------------------------------------------


class ToolGroupState(StrEnum):
    PENDING   = "pending"
    RUNNING   = "running"
    DONE      = "done"        # all children DONE
    ERR       = "err"         # any child ERR (sticky once latched)
    CANCELLED = "cancelled"   # no ERR; ≥1 CANCEL; rest DONE/CANCEL


_TERMINAL_GROUP_STATES = frozenset({
    ToolGroupState.DONE,
    ToolGroupState.ERR,
    ToolGroupState.CANCELLED,
})

# GHF-M1: group-state → (glyph, style) for left-side outcome column.
# Colors use hardcoded Rich names — il-tok-1-exempt: semantic outcome colors,
# no SkinColors token defined for group-level outcome glyphs.
_OUTCOME_GLYPH: dict[str, tuple[str, str]] = {
    "done":      ("✓", "green"),    # il-tok-1-exempt
    "err":       ("✗", "bold red"), # il-tok-1-exempt
    "cancelled": ("–", "dim"),
    # "pending" and "running": no entry → falls through to ("", "")
}


def _recompute_group_state(
    children: list,
    *,
    current_state: ToolGroupState | None = None,
) -> ToolGroupState:
    """Derive group terminal state from child _view_state values.

    Implements concept §ToolGroup transition graph (lines 821–832) including
    sticky-ERR aggregation (829–831) and terminal absorbing (832).

    NOTE: `ToolCallState.ERROR` below refers to the child-level PHASE enum
    (not renamed). `ToolGroupState.ERR` is the group-level aggregate state
    (renamed from `ToolGroupState.ERROR` by this spec).
    """
    # Terminal absorbing: once latched, do not unwind on late events.
    if current_state in _TERMINAL_GROUP_STATES:
        return current_state

    raw_states = [
        getattr(getattr(c, "_view_state", None), "state", None)
        for c in children
    ]
    states = {s for s in raw_states if s is not None}
    if not states:
        return ToolGroupState.PENDING

    # ERR is sticky: any child ToolCallState.ERROR latches the group to
    # ToolGroupState.ERR regardless of sibling DONEs (concept lines 829–831).
    if ToolCallState.ERROR in states:
        return ToolGroupState.ERR

    terminal = {ToolCallState.DONE, ToolCallState.ERROR, ToolCallState.CANCELLED}
    if not states <= terminal:
        if any(s in (ToolCallState.STARTED, ToolCallState.STREAMING,
                     ToolCallState.COMPLETING) for s in states):
            return ToolGroupState.RUNNING
        return ToolGroupState.PENDING

    # All children terminal, no ERR: CANCELLED if ≥1 CANCEL, else DONE.
    if ToolCallState.CANCELLED in states:
        return ToolGroupState.CANCELLED
    return ToolGroupState.DONE


# ---------------------------------------------------------------------------
# Group tier constants (TB-MED-2)
# ---------------------------------------------------------------------------

_GROUP_STATE_TO_TOOL_STATE: "dict[ToolGroupState, ToolCallState]" = {
    ToolGroupState.PENDING:   ToolCallState.STARTED,
    ToolGroupState.RUNNING:   ToolCallState.STREAMING,
    ToolGroupState.DONE:      ToolCallState.DONE,
    ToolGroupState.ERR:       ToolCallState.ERROR,
    ToolGroupState.CANCELLED: ToolCallState.DONE,
}

_CAP_FOR_TIER: "dict[DensityTier, int | None]" = {
    DensityTier.HERO:    None,                           # unbounded
    DensityTier.DEFAULT: THRESHOLDS["GROUP_CAP_DEFAULT"],
    DensityTier.COMPACT: THRESHOLDS["GROUP_CAP_COMPACT"],
    DensityTier.TRACE:   THRESHOLDS["GROUP_CAP_TRACE"],
}


# ---------------------------------------------------------------------------
# GroupOverflowChip (TB-MED-2)
# ---------------------------------------------------------------------------


class GroupOverflowChip(Widget):
    """Focusable overflow indicator for capped group bodies (concept lines 848-857).

    Enter / Space lifts the parent ToolGroup to HERO tier, lifting the cap.
    """

    DEFAULT_CSS = """
    GroupOverflowChip { height: 1; padding-left: 2; }
    GroupOverflowChip:focus { background: $boost; }
    """
    can_focus = True
    BINDINGS = [
        Binding("enter", "lift_to_hero", "Show all", show=False),
        Binding("space", "lift_to_hero", "Show all", show=False),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._n_more = 0
        self._n_err = 0
        self._n_running = 0
        self._tier = DensityTier.DEFAULT

    def update(self, *, n_more: int, n_err: int, n_running: int,
               tier: "DensityTier") -> None:
        self._n_more = n_more
        self._n_err = n_err
        self._n_running = n_running
        self._tier = tier
        self.refresh()

    def render(self) -> "Text":
        try:
            from hermes_cli.tui.body_renderers._grammar import GLYPH_META_SEP, glyph as _glyph
            sep = f" {_glyph(GLYPH_META_SEP)} "
        except Exception:  # il-ex-1-exempt: swallow
            # grammar module unavailable in test env; use plain separator
            sep = " · "
        if self._tier == DensityTier.TRACE:
            label = f"… {self._n_more} children"
            if self._n_err:
                label += f"{sep}{self._n_err} errors"
        else:
            label = f"…+{self._n_more} more children"
            if self._n_err:
                label += f"{sep}{self._n_err} errors"
            if self._n_running:
                label += f"{sep}{self._n_running} running"
        return Text(label, style="dim")

    def action_lift_to_hero(self) -> None:
        for a in self.ancestors_with_self:
            if isinstance(a, ToolGroup):
                a._user_hero = True
                a.set_group_tier(DensityTier.HERO)
                if a.is_mounted:
                    try:
                        a.focus()
                    except Exception:
                        # focus() may raise if widget is detaching mid-teardown;
                        # HERO lock is already set — the focus failure is cosmetic only.
                        _log.debug("action_lift_to_hero: focus() skipped (widget detaching)",
                                   exc_info=True)
                return


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
    tier: reactive["DensityTier"] = reactive(DensityTier.DEFAULT, layout=True)

    _overflow_chip: "GroupOverflowChip | None" = None

    BINDINGS = [
        Binding("enter",       "toggle_collapse", "Toggle group", show=False),
        Binding("shift+enter", "peek_focused",    "Peek focused", show=False),
    ]

    # PG-3: message posted by StreamingToolBlock per appended line
    class StreamingLineAppended(Message):
        def __init__(self, line: str) -> None:
            super().__init__()
            self.line = line

    # PG-3: message posted by DiffRenderer per diff-stat line
    class DiffStatUpdate(Message):
        def __init__(self, add: int, del_: int) -> None:
            super().__init__()
            self.add = add
            self.del_ = del_

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
        # PG-3: incremental aggregate counters
        self._streaming_err_count: int = 0  # sum across currently-streaming children
        self._terminal_err_count: int = 0   # count of children that completed as ERROR
        self._running_diff_add: int = 0
        self._running_diff_del: int = 0
        self._last_header_kwargs: dict = {}
        # PG-4: group-level terminal state
        self._group_state: ToolGroupState = ToolGroupState.PENDING
        # GHF-H1 + STALL-GC: monotonic timestamp of first transition into terminal state.
        # None means not yet terminal.
        self._group_terminal_at: float | None = None
        # STALL-GC: True once _sweep_abandoned_children has run for this group.
        self._group_swept: bool = False
        # TB-MED-2: group tier cap + HERO lock
        self._user_hero: bool = False
        from hermes_cli.tui.tool_panel.layout_resolver import ToolBlockLayoutResolver
        self._resolver = ToolBlockLayoutResolver()

    def compose(self) -> ComposeResult:
        header = GroupHeader()
        body = GroupBody()
        self._header = header
        self._body = body
        yield header
        yield body

    # ------------------------------------------------------------------
    # TB-MED-2: tier cap methods
    # ------------------------------------------------------------------

    def set_group_tier(self, tier: "DensityTier") -> None:
        """Set the group-level tier. ERR children always bypass cap."""
        if tier != self.tier:
            self.tier = tier  # triggers watch_tier

    def watch_tier(self, old: "DensityTier", new: "DensityTier") -> None:
        self._apply_child_render_cap()

    def _resolve_group_tier(
        self,
        *,
        pressure: float,
        viewport_rows: int,
        is_offscreen: bool,
    ) -> None:
        """Resolve and apply group tier via pressure resolver.

        Does nothing when _user_hero=True (chip-Enter locked HERO).
        kind=None ensures HERO is ineligible via auto-resolve.
        """
        if self._user_hero:
            return
        from hermes_cli.tui.tool_panel.layout_resolver import LayoutInputs
        phase = _GROUP_STATE_TO_TOOL_STATE.get(self._group_state, ToolCallState.DONE)
        is_error = (self._group_state == ToolGroupState.ERR)
        child_count = (
            len([c for c in self._body.children]) if self._body is not None else 0
        )
        inputs = LayoutInputs(
            phase=phase,
            is_error=is_error,
            has_focus=bool(getattr(self, "has_focus", False)),
            user_scrolled_up=False,
            user_override=False,
            user_override_tier=None,
            body_line_count=child_count,
            threshold=THRESHOLDS["GROUP_CAP_DEFAULT"],
            kind=None,
            parent_clamp=None,
            width=getattr(getattr(self, "size", None), "width", 0),
            user_collapsed=bool(getattr(self, "collapsed", False)),
            has_footer_content=False,
            is_streaming=(phase in (ToolCallState.STARTED, ToolCallState.STREAMING)),
            pressure=pressure,
            viewport_rows=viewport_rows,
            is_offscreen=is_offscreen,
        )
        new_tier = self._resolver.resolve(inputs)
        self.set_group_tier(new_tier)

    def _apply_child_render_cap(self) -> None:
        try:
            self._apply_child_render_cap_inner()
        except Exception:
            # Cap state going stale on teardown is harmless; next pressure sweep
            # reapplies it.
            _log.debug("_apply_child_render_cap skipped", exc_info=True)

    def _apply_child_render_cap_inner(self) -> None:
        from hermes_cli.tui.tool_panel import ToolPanel as _TP
        if self._body is None:
            return
        cap = _CAP_FOR_TIER.get(self.tier, None)
        children = [c for c in self._body.children if isinstance(c, _TP)]

        def is_err(p: "_TP") -> bool:
            vs = getattr(p, "_view_state", None)
            return vs is not None and vs.state == ToolCallState.ERROR

        def is_running(p: "_TP") -> bool:
            vs = getattr(p, "_view_state", None)
            return vs is not None and vs.state in (
                ToolCallState.STARTED, ToolCallState.STREAMING, ToolCallState.COMPLETING,
            )

        if cap is None:  # HERO: unbounded
            for c in children:
                c.display = True
            self._set_overflow_chip_visible(False)
            return

        pinned_pred = is_err if self.tier != DensityTier.COMPACT else (
            lambda p: is_err(p) or is_running(p)
        )
        pinned = [c for c in children if pinned_pred(c)]
        rest = [c for c in children if not pinned_pred(c)]
        visible_rest = rest[:max(0, cap - len(pinned))] if cap > 0 else []
        visible = set(id(c) for c in pinned) | set(id(c) for c in visible_rest)

        n_hidden = 0
        n_err = sum(1 for c in children if is_err(c))
        n_running = sum(1 for c in children if is_running(c))
        for c in children:
            shown = id(c) in visible
            c.display = shown
            if not shown:
                n_hidden += 1

        self._set_overflow_chip_visible(n_hidden > 0,
                                        n_more=n_hidden,
                                        n_err=n_err,
                                        n_running=n_running,
                                        tier=self.tier)

    def _set_overflow_chip_visible(self, visible: bool, *,
                                   n_more: int = 0, n_err: int = 0,
                                   n_running: int = 0,
                                   tier: "DensityTier | None" = None) -> None:
        if not visible:
            if self._overflow_chip is not None:
                self._overflow_chip.display = False
            return
        if self._overflow_chip is None:
            self._overflow_chip = GroupOverflowChip()
            chip_mounted = False
            try:
                if self._body is not None and self._body.is_mounted:
                    self._body.mount(self._overflow_chip)
                    chip_mounted = True
            except Exception:
                _log.debug("overflow chip mount deferred (body not mounted)", exc_info=True)
            if not chip_mounted:
                self._overflow_chip = None
                return
        self._overflow_chip.display = True
        self._overflow_chip.update(n_more=n_more, n_err=n_err,
                                   n_running=n_running,
                                   tier=tier if tier is not None else self.tier)

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
        except Exception:  # il-ex-1-exempt: swallow
            # focus may be unparented in test mounts; best-effort walk
            pass

        # Sync header toggle glyph
        if self._header is not None:
            self._header._collapsed = value
            self._header.refresh()

        # Rebuild browse anchors so hidden children are skipped
        try:
            self.app._svc_browse.rebuild_browse_anchors()
        except Exception:  # il-ex-1-exempt: _svc_browse not available; browse-anchor rebuild is best-effort
            pass

    def on_click(self, event: object) -> None:
        """Toggle collapsed on left-click on GroupHeader only.

        Clicks on child ToolPanel body content bubble up uninvited; guard
        against them by checking the originating widget.
        """
        if getattr(event, "button", 1) != 1:
            return
        if not isinstance(getattr(event, "widget", None), GroupHeader):
            return
        self._user_hero = False          # clear HERO lock on explicit collapse/expand
        self._user_collapsed = not self.collapsed
        self.collapsed = self._user_collapsed
        if hasattr(event, "stop"):
            event.stop()

    def action_toggle_collapse(self) -> None:
        """Toggle group collapse via keyboard (parity with on_click)."""
        self._user_hero = False          # clear HERO lock on explicit collapse/expand
        self._user_collapsed = not self.collapsed
        self.collapsed = self._user_collapsed

    def on_descendant_focus(self, event: object) -> None:
        """Prevent focus from entering a collapsed group's body."""
        widget = getattr(event, "widget", None)
        if self.collapsed and widget is not self:
            self.focus()
            if hasattr(event, "stop"):
                event.stop()

    def on_resize(self, event: "events.Resize") -> None:
        width = event.size.width
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
                        except ValueError:  # il-ex-1-exempt: swallow
                            pass
                    elif badge.startswith("-"):
                        try:
                            diff_del += int(badge[1:])
                        except ValueError:  # il-ex-1-exempt: swallow
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
                        except (ValueError, AttributeError):  # il-ex-1-exempt: swallow
                            pass
                    elif chip.kind == "diff-":
                        try:
                            diff_del += int(chip.text.lstrip("-"))
                        except (ValueError, AttributeError):  # il-ex-1-exempt: swallow
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
        except Exception:  # il-ex-1-exempt: swallow
            # header may be unmounted during teardown; --group-has-error is decorative
            pass

        # PG-3: authoritative terminal values replace running diff totals
        self._running_diff_add = 0
        self._running_diff_del = 0

        kwargs = dict(
            summary_text=summary_text,
            diff_add=diff_add,
            diff_del=diff_del,
            duration_ms=duration_ms,
            child_count=len(children),
            collapsed=self.collapsed,
            error_count=error_count + self._terminal_err_count,  # B2 + PG-3
            terminal_at=self._group_terminal_at,
            group_state=self._group_state.value,
        )
        # PG-3: save for _refresh_header_counts partial updates
        self._last_header_kwargs = dict(kwargs)
        self._header.update(**kwargs)
        self._apply_child_render_cap()

    def _refresh_header_counts(self) -> None:
        """PG-3: partial header update with live streaming counters."""
        if not self._last_header_kwargs or self._header is None:
            return
        merged = {
            **self._last_header_kwargs,
            "error_count": self._streaming_err_count + self._terminal_err_count,
            "diff_add": self._running_diff_add,
            "diff_del": self._running_diff_del,
        }
        self._header.update(**merged)

    def on_tool_group_streaming_line_appended(
        self, event: "ToolGroup.StreamingLineAppended"
    ) -> None:
        """PG-3: update streaming error count per line."""
        event.stop()
        if _STREAMING_ERR_RE.match(event.line):
            block = event.control
            current = getattr(block, "_line_err_count", 0)
            try:
                block._line_err_count = current + 1
            except AttributeError:  # il-ex-1-exempt: swallow
                pass
            self._streaming_err_count += 1
            self._refresh_header_counts()

    def on_tool_group_diff_stat_update(
        self, event: "ToolGroup.DiffStatUpdate"
    ) -> None:
        """PG-3: accumulate incremental diff stats from DiffRenderer."""
        event.stop()
        self._running_diff_add += event.add
        self._running_diff_del += event.del_
        self._refresh_header_counts()

    def on_tool_panel_completed(self, event: object) -> None:
        """Re-aggregate when any child ToolPanel completes (PG-3 + PG-4)."""
        try:
            from hermes_cli.tui.tool_panel import ToolPanel as _TP
            if not isinstance(event, _TP.Completed):
                return
            event.stop()
            # PG-3: reconcile streaming error count for this child
            panel = event.control
            block = getattr(panel, "_block", None)
            child_errs = getattr(block, "_line_err_count", 0)
            self._streaming_err_count = max(0, self._streaming_err_count - child_errs)
            vs = getattr(panel, "_view_state", None)
            if vs is not None and vs.state == ToolCallState.ERROR:
                self._terminal_err_count += 1
            # Build children list once for both recompute and group-state
            children = (
                [c for c in self._body.children if isinstance(c, _TP)]
                if self._body is not None else []
            )
            # PG-4: compute new group state BEFORE recompute_aggregate so terminal_at
            # is captured when recompute_aggregate calls _header.update
            self._group_state = _recompute_group_state(children, current_state=self._group_state)
            # GHF-H1 + STALL-GC-H1/H2: capture terminal timestamp; schedule abandonment sweep.
            if self._group_state in _TERMINAL_GROUP_STATES and self._group_terminal_at is None:
                self._group_terminal_at = time.monotonic()
                self.set_timer(2.0, self._sweep_abandoned_children)
            self.recompute_aggregate()
            # Reflect terminal group state on the ToolGroup widget via CSS classes
            # so hermes.tcss can style border-left based on outcome.
            try:
                self.set_class(self._group_state == ToolGroupState.DONE, "--group-done")
                self.set_class(self._group_state == ToolGroupState.ERR, "--group-error")
            except NoMatches:  # il-ex-1-exempt: swallow
                # Widget not fully mounted; CSS group-state class is decorative,
                # missed during early mount is harmless — next recompute will apply it.
                _log.debug("set_class skipped: ToolGroup not fully mounted (state=%s)", self._group_state)
            self._apply_child_render_cap()
        except Exception:
            _log.exception("toolgroup: on_tool_panel_completed failed")

    def _sweep_abandoned_children(self) -> None:
        """Fire 2s after group-terminal: mark non-completed children as abandoned.

        STALL-GC-H2: scheduled by on_tool_panel_completed. Idempotent via _group_swept.
        """
        if self._group_swept:
            return
        self._group_swept = True
        try:
            from hermes_cli.tui.tool_panel import ToolPanel as _TP
            if self._body is None:
                return
            for child in list(self._body.children):
                if not isinstance(child, _TP):
                    continue
                block = getattr(child, "_block", None)
                if block is None:
                    continue
                if getattr(block, "_completed", True):
                    continue  # already completed normally
                block._mark_abandoned()
        except Exception:
            _log.exception(
                "ToolGroup._sweep_abandoned_children failed (group_id=%s)", self._group_id
            )


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
    except Exception:  # il-ex-1-exempt: ToolBlock query failed (partially mounted tree); empty label is safe
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


def _find_diff_targets(siblings: list[Widget], window_s: float) -> list[Widget]:
    """Return all write panels within the attach window sharing the same target path."""
    now = time.monotonic()
    # Use path of the most recent eligible write as anchor
    anchor_path: str | None = None
    out: list[Widget] = []
    for panel in reversed(siblings):
        tool_name = getattr(panel, "_tool_name", "") or ""
        if tool_name not in _FILE_WRITE_TOOLS:
            continue
        completed = getattr(panel, "_completed_at", None)
        if completed is not None and (now - completed) >= window_s:
            break
        panel_path = _get_header_label(panel) or ""
        if anchor_path is None:
            anchor_path = panel_path
        if panel_path == anchor_path:
            out.append(panel)
    return out


def _find_diff_target(siblings: list[Widget]) -> Widget | None:
    try:
        from hermes_cli.config import read_raw_config
        attach_window = float(read_raw_config().get("display", {}).get("diff_attach_window_s", 15.0))
    except Exception:  # il-ex-1-exempt: read_raw_config unavailable; hardcoded default window/threshold is safe
        attach_window = 15.0
    targets = _find_diff_targets(siblings, attach_window)
    return targets[0] if targets else None


def _is_diff_panel(panel: Widget) -> bool:
    block = getattr(panel, "_block", None)
    if block is not None:
        return getattr(block, "_label", "") == "diff"
    try:
        from hermes_cli.tui.tool_blocks import ToolBlock as _TB
        blk = next(iter(panel.query(_TB)), None)
        return blk is not None and getattr(blk, "_label", "") == "diff"
    except Exception:  # il-ex-1-exempt: ToolBlock query failed in partially mounted tree; False is safe default
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
    elif rule == RULE_SHELL_BATCH:
        n = len(children)
        first = (_get_header_label(children[0]) or "")[:24] if children else ""
        last  = (_get_header_label(children[-1]) or "")[:24] if children else ""
        if n > 2 and first and last:
            return f"{n} shell calls · {first} … {last}"
        elif first and last and first != last:
            return f"shell · {first} · {last}"
        return f"{n} shell calls"
    elif rule == RULE_FILE_EDIT:
        label = _get_header_label(children[-1]) if children else None
        basename = os.path.basename(label) if label else ""
        return f"edited {basename}" if basename else "edited file"
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

    # Rule 4: File-edit pairing (read followed by write on same path)
    # Evaluated before Rule 1 so a subsequent patch doesn't diff-attach to the
    # write instead of forming a proper read→write→patch trio under Rule 1.
    prev_name = getattr(prev, "_tool_name", "") or ""
    new_name  = getattr(new_panel, "_tool_name", "") or ""
    if prev_name in _FILE_READ_TOOLS and new_name in _FILE_WRITE_TOOLS:
        prev_path = _get_header_label(prev)
        new_path  = _get_header_label(new_panel)
        if prev_path and new_path and prev_path == new_path:
            prev_start = getattr(prev, "_start_time", None)
            new_start  = getattr(new_panel, "_start_time", None)
            try:
                from hermes_cli.config import read_raw_config
                attach_window = float(
                    read_raw_config().get("display", {}).get("diff_attach_window_s", 15.0)
                )
            except Exception:  # il-ex-1-exempt: read_raw_config unavailable; hardcoded default window/threshold is safe
                attach_window = 15.0
            gap = (
                abs(new_start - prev_start)
                if prev_start is not None and new_start is not None
                else 0.0
            )
            if gap <= attach_window:
                return prev, RULE_FILE_EDIT

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

    # Rule 3: Shell pipeline / batch
    if (
        _is_category(new_panel, ToolCategory.SHELL)
        and _is_category(prev, ToolCategory.SHELL)
    ):
        prev_cmd = _get_header_label(prev) or ""
        new_cmd  = _get_header_label(new_panel) or ""
        has_operator = bool(
            _PIPELINE_OPS_RE.search(prev_cmd) or _PIPELINE_OPS_RE.search(new_cmd)
        )
        prev_start = getattr(prev, "_start_time", None)
        new_start = getattr(new_panel, "_start_time", None)
        try:
            from hermes_cli.config import read_raw_config
            pipeline_ms = int(read_raw_config().get("display", {}).get("shell_pipeline_ms", 500))
        except Exception:  # il-ex-1-exempt: read_raw_config unavailable; hardcoded default window/threshold is safe
            pipeline_ms = 500
        within_window = (
            prev_start is not None
            and new_start is not None
            and abs(new_start - prev_start) < pipeline_ms / 1000.0
        )
        wide_window = (
            prev_start is not None
            and new_start is not None
            and abs(new_start - prev_start) < pipeline_ms * 4 / 1000.0
        )
        if has_operator and (within_window or wide_window):
            return prev, RULE_SHELL_PIPE   # true pipeline
        if within_window:
            return prev, RULE_SHELL_BATCH  # temporal cluster only

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
    except Exception:  # il-ex-1-exempt: _svc_browse not available; browse-anchor rebuild is best-effort
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
    if group.collapsed:
        group.collapsed = False  # reveal the new panel
        if group._header is not None:
            group._header.add_class("--group-appended")
            group.set_timer(0.6, lambda: group._header.remove_class("--group-appended"))
    try:
        group.app._svc_browse.rebuild_browse_anchors()
    except Exception:  # il-ex-1-exempt: swallow
        # _svc_browse may be absent (test mount) or unmounted (teardown);
        # browse-anchor rebuild is best-effort
        pass


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def _do_apply_multi_diff_group(
    message_panel: Widget,
    targets: list[Widget],
    new_panel: Widget,
) -> None:
    """Create a group for all write targets + the diff panel (M3)."""
    # Use oldest write as the anchor for position; newer writes + diff are appended
    anchor = targets[-1]  # oldest (list is most-recent-first)
    group = await _do_apply_group_widget(message_panel, anchor, new_panel, RULE_DIFF_ATTACH)
    # Append remaining writes (all except anchor, newest first)
    for extra in targets[:-1]:
        if extra.parent is not None:
            await _do_append_to_group(group, extra, message_panel)


def _maybe_start_group(message_panel: Widget, new_panel: Widget) -> None:
    """Sync entry point: evaluate grouping rules and schedule async reparent if matched."""
    if not _grouping_enabled():
        return
    match = _find_rule_match(message_panel, new_panel)
    if match is None:
        return
    existing_panel, rule = match

    # M3: when diff attaches, collect all eligible writes into one group
    if rule == RULE_DIFF_ATTACH:
        siblings = _get_effective_tp_siblings(message_panel)
        siblings = [s for s in siblings if s is not new_panel]
        try:
            from hermes_cli.config import read_raw_config
            attach_window = float(read_raw_config().get("display", {}).get("diff_attach_window_s", 15.0))
        except Exception:  # il-ex-1-exempt: read_raw_config unavailable; hardcoded default window/threshold is safe
            attach_window = 15.0
        all_targets = _find_diff_targets(siblings, attach_window)
        if len(all_targets) > 1:
            message_panel.app.call_after_refresh(
                lambda: message_panel.run_worker(
                    _do_apply_multi_diff_group(message_panel, all_targets, new_panel),
                    exclusive=False,
                )
            )
            return

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

