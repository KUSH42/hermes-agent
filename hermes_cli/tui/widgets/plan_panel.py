"""plan_panel.py — PlanPanel widget (R1).

Bottom-docked, collapsible strip that surfaces the agent's current work queue.

Sections:
  _PlanPanelHeader  — title + collapse chevron
  _NowSection       — currently-executing tool + elapsed timer
  _NextSection      — pending tools (max 5 + "+N more")
  _BudgetSection    — turn cost/token display, click opens UsageOverlay

TCSS vars required (must also be in hermes.tcss and all skin files):
  $plan-now-fg:     #ffb454 (warm amber — "in-flight")
  $plan-pending-fg: #888888
"""
from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

from rich.text import Text as RichText
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
    from hermes_cli.tui.plan_types import PlannedCall

# ---------------------------------------------------------------------------
# Deterministic mode guard
# ---------------------------------------------------------------------------

_DETERMINISTIC = bool(os.environ.get("HERMES_DETERMINISTIC"))


def _accessibility_mode() -> bool:
    """True when HERMES_ACCESSIBILITY=1 env var is set."""
    return bool(os.environ.get("HERMES_ACCESSIBILITY"))


# ---------------------------------------------------------------------------
# Glyph helpers (accessibility-aware)
# ---------------------------------------------------------------------------

def _glyph_running() -> str:
    return "*" if _accessibility_mode() else "●"


def _glyph_pending() -> str:
    return ">" if _accessibility_mode() else "▸"


def _glyph_done() -> str:
    return "[ok]" if _accessibility_mode() else "✓"


def _glyph_error() -> str:
    return "[X]" if _accessibility_mode() else "✗"


# ---------------------------------------------------------------------------
# Pure-function helper for testing (no widget needed)
# ---------------------------------------------------------------------------

def _format_plan_line(call: "PlannedCall", width: int = 60) -> str:
    """Format a single PlannedCall as a plain-text line.

    Pure function — safe to call from tests without mounting.
    """
    from hermes_cli.tui.plan_types import PlanState
    if call.state == PlanState.RUNNING:
        glyph = _glyph_running()
    elif call.state == PlanState.PENDING:
        glyph = _glyph_pending()
    elif call.state == PlanState.DONE:
        glyph = _glyph_done()
    elif call.state in (PlanState.ERROR, PlanState.CANCELLED, PlanState.SKIPPED):
        glyph = _glyph_error()
    else:
        glyph = "?"
    label = call.label[:width - 4] if len(call.label) > width - 4 else call.label
    return f"{glyph} {label}"


# ---------------------------------------------------------------------------
# _PlanEntry  (focusable plan line — P1-1)
# ---------------------------------------------------------------------------

class _PlanEntry(Static, can_focus=True):
    """Focusable plan entry line that links to its ToolPanel."""

    DEFAULT_CSS = """
    _PlanEntry {
        height: 1;
    }
    _PlanEntry:focus {
        background: $accent 10%;
    }
    _PlanEntry:hover {
        background: $accent 6%;
    }
    """

    def __init__(self, text: str, tool_call_id: str | None = None, **kwargs: object) -> None:
        super().__init__(text, **kwargs)
        self._tool_call_id = tool_call_id

    def on_click(self) -> None:
        self._jump()

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter" and self._tool_call_id:
            self._jump()
            event.stop()
        elif event.key == "escape":
            try:
                self.app.query_one("#input-area").focus()
            except Exception:
                pass
            event.stop()

    def _jump(self) -> None:
        if not self._tool_call_id:
            return
        try:
            svc = getattr(self.app, "_svc_browse", None)
            if svc is not None:
                svc.scroll_to_tool(self._tool_call_id)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# _NowSection
# ---------------------------------------------------------------------------

class _NowSection(Vertical):
    """Shows the currently-executing tool with an elapsed timer."""

    DEFAULT_CSS = """
    _NowSection {
        height: auto;
        width: 1fr;
        display: none;
    }
    _NowSection.--visible { display: block; }
    """

    _elapsed_s: int = 0
    _timer_handle: Any = None
    _start_monotonic: float = 0.0
    _base_text: str = ""

    def compose(self) -> ComposeResult:
        yield Static("", id="now-line")

    def show_call(self, call: "PlannedCall") -> None:
        """Update the Now line and (re)start the elapsed timer."""
        self._start_monotonic = call.started_at if call.started_at is not None else time.monotonic()
        self._elapsed_s = 0
        label = call.label[:50] if len(call.label) > 50 else call.label
        self._base_text = f"{_glyph_running()} {label}"
        try:
            old = self.query_one("#now-line")
            old.remove()
        except (NoMatches, Exception):
            pass
        elapsed = 0 if _DETERMINISTIC else int(time.monotonic() - self._start_monotonic)
        entry = _PlanEntry(
            self._base_text if elapsed < 3 else f"{self._base_text}  [{elapsed}s]",
            tool_call_id=call.tool_call_id,
            id="now-line",
        )
        self.mount(entry)
        self._ensure_timer()

    def clear(self) -> None:
        """Clear the Now line and stop the timer."""
        self._base_text = ""
        try:
            self.query_one("#now-line", Static).update("")
        except (NoMatches, Exception):
            pass
        self._stop_timer()

    def _ensure_timer(self) -> None:
        if _DETERMINISTIC:
            return
        if self._timer_handle is None:
            self._timer_handle = self.set_interval(2.0, self._tick)

    def _stop_timer(self) -> None:
        if self._timer_handle is not None:
            try:
                self._timer_handle.stop()
            except Exception:
                pass
            self._timer_handle = None

    def _tick(self) -> None:
        if _DETERMINISTIC:
            return
        elapsed = int(time.monotonic() - self._start_monotonic)
        self._elapsed_s = elapsed
        self._update_now_line(elapsed)

    def _refresh_display(self, call: "PlannedCall") -> None:
        label = call.label[:50] if len(call.label) > 50 else call.label
        glyph = _glyph_running()
        self._base_text = f"{glyph} {label}"
        elapsed = 0 if _DETERMINISTIC else int(time.monotonic() - self._start_monotonic)
        self._update_now_line(elapsed)

    def _update_now_line(self, elapsed: int) -> None:
        """Apply current elapsed to the Now line. Uses _base_text — never string-parses."""
        if elapsed >= 3:
            text = f"{self._base_text}  [{elapsed}s]"
        else:
            text = self._base_text
        try:
            self.query_one("#now-line", Static).update(text)
        except (NoMatches, Exception):
            pass


# ---------------------------------------------------------------------------
# _NextSection
# ---------------------------------------------------------------------------

class _NextSection(Vertical):
    """Shows pending tools (up to 5 + overflow indicator)."""

    DEFAULT_CSS = """
    _NextSection {
        height: auto;
        width: 1fr;
        display: none;
    }
    _NextSection.--visible { display: block; }
    """

    _MAX_VISIBLE = 5

    def compose(self) -> ComposeResult:
        yield Static("", id="next-header")

    def update_calls(self, calls: "list[PlannedCall]") -> None:
        """Rebuild the next section content."""
        from hermes_cli.tui.plan_types import PlanState
        pending = [c for c in calls if c.state == PlanState.PENDING]
        container = self
        # Remove all children except the header
        for child in list(container.children):
            if child.id != "next-header":
                child.remove()

        if not pending:
            try:
                self.query_one("#next-header", Static).update("")
            except NoMatches:
                pass
            return

        try:
            self.query_one("#next-header", Static).update("Next:")
        except NoMatches:
            pass

        limit = self._MAX_VISIBLE
        visible = pending[:limit]
        overflow = len(pending) - limit

        new_children: list[Widget] = []
        for call in visible:
            indent = "  " * call.depth
            glyph = _glyph_pending()
            label = call.label[:50] if len(call.label) > 50 else call.label
            new_children.append(_PlanEntry(
                f"  {indent}{glyph} {label}",
                tool_call_id=call.tool_call_id,
                classes="plan-pending-line",
            ))

        if overflow > 0:
            more = Static(f"  … +{overflow} more", classes="plan-more-line", id="next-more")
            new_children.append(more)

        if new_children:
            container.mount(*new_children)


# ---------------------------------------------------------------------------
# _BudgetSection
# ---------------------------------------------------------------------------

class _BudgetSection(Horizontal):
    """Shows turn cost and token counts. Click opens UsageOverlay."""

    DEFAULT_CSS = """
    _BudgetSection {
        height: 1;
        width: 1fr;
        display: none;
    }
    _BudgetSection.--visible { display: block; }
    _BudgetSection:hover {
        background: $accent 8%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="budget-line")

    def update_budget(self, cost_usd: float, tokens_in: int, tokens_out: int) -> None:
        """Refresh the budget display."""
        cost_str = f"${cost_usd:.2f}" if cost_usd > 0 else "$0.00"
        in_k = f"{tokens_in / 1000:.1f}k" if tokens_in >= 1000 else str(tokens_in)
        out_k = f"{tokens_out / 1000:.1f}k" if tokens_out >= 1000 else str(tokens_out)
        text = f"{cost_str} · {in_k}↑ {out_k}↓"
        try:
            self.query_one("#budget-line", Static).update(text)
        except (NoMatches, Exception):
            pass

    def on_click(self) -> None:
        """Open UsageOverlay on click."""
        try:
            app = self.app
            from hermes_cli.tui.overlays import UsageOverlay
            ov = app.query_one(UsageOverlay)
            if hasattr(ov, "show_overlay"):
                ov.show_overlay()
            else:
                ov.add_class("--visible")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# _ChipSegment  (P1-2)
# ---------------------------------------------------------------------------

class _ChipSegment(Static, can_focus=False):
    """One clickable chip segment inside the collapsed plan header."""

    DEFAULT_CSS = """
    _ChipSegment {
        height: 1;
        width: auto;
        padding: 0 1;
    }
    _ChipSegment:hover {
        background: $accent 10%;
        color: $text;
    }
    """

    def __init__(self, text: str, action: str = "", **kwargs: object) -> None:
        super().__init__(text, **kwargs)
        self._chip_action = action  # "jump_running", "jump_first_error", "usage"

    def on_click(self) -> None:
        if self._chip_action == "jump_running":
            self._jump_running()
        elif self._chip_action == "jump_first_error":
            self._jump_first_error()
        elif self._chip_action == "usage":
            self._open_usage()

    def _jump_running(self) -> None:
        try:
            calls = getattr(self.app, "planned_calls", [])
            from hermes_cli.tui.plan_types import PlanState
            running = next((c for c in calls if c.state == PlanState.RUNNING), None)
            if running:
                self.app._svc_browse.scroll_to_tool(running.tool_call_id)
        except Exception:
            pass

    def _jump_first_error(self) -> None:
        try:
            calls = getattr(self.app, "planned_calls", [])
            from hermes_cli.tui.plan_types import PlanState
            err = next((c for c in calls if c.state == PlanState.ERROR), None)
            if err:
                self.app._svc_browse.scroll_to_tool(err.tool_call_id)
        except Exception:
            pass

    def _open_usage(self) -> None:
        try:
            from hermes_cli.tui.overlays import UsageOverlay
            ov = self.app.query_one(UsageOverlay)
            if hasattr(ov, "show_overlay"):
                ov.show_overlay()
            else:
                ov.add_class("--visible")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# _PlanPanelHeader
# ---------------------------------------------------------------------------

class _PlanPanelHeader(Horizontal):
    """Title bar with collapse/expand chevron and segmented chip (P1-2/P1-3)."""

    DEFAULT_CSS = """
    _PlanPanelHeader {
        height: 1;
        width: 1fr;
    }
    _PlanPanelHeader:hover {
        background: $accent 5%;
    }
    _PlanPanelHeader #plan-f9-badge {
        dock: right;
        width: auto;
        color: $text-muted 50%;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="plan-header-label")        # expanded: full label
        yield Static("", id="plan-chip-title")           # collapsed: "Plan ▸ "
        # chip segments (hidden when expanded)
        yield _ChipSegment("", id="chip-running",  action="jump_running")
        yield _ChipSegment("", id="chip-done",     action="")            # no action
        yield _ChipSegment("", id="chip-errors",   action="jump_first_error")
        yield _ChipSegment("", id="chip-cost",     action="usage")
        yield Static("[F9]", id="plan-f9-badge")         # P1-3

    def update_header(self, collapsed: bool, running: int, pending: int,
                      done: int, errors: int = 0, cost_usd: float = 0.0) -> None:
        """Refresh the header line."""
        chevron = "▸" if collapsed else "▾"
        if collapsed:
            self._show_chip(chevron, running, pending, done, errors, cost_usd)
        else:
            self._show_full(chevron)

    def _show_full(self, chevron: str) -> None:
        try:
            self.query_one("#plan-header-label", Static).update(f"Plan {chevron}")
            self.query_one("#plan-header-label").display = True
            for seg_id in ("plan-chip-title", "chip-running", "chip-done",
                           "chip-errors", "chip-cost"):
                self.query_one(f"#{seg_id}").display = False
            self.query_one("#plan-f9-badge").display = True
        except (NoMatches, Exception):
            pass

    def _show_chip(self, chevron: str, running: int, pending: int,
                   done: int, errors: int, cost_usd: float) -> None:
        try:
            self.query_one("#plan-header-label").display = False

            # pending shown in title (not a separate segment — no scroll target)
            title_text = f"Plan {chevron} "
            if pending:
                title_text += f"{pending}▸ "
            self.query_one("#plan-chip-title", Static).update(title_text)
            self.query_one("#plan-chip-title").display = True

            r_seg = self.query_one("#chip-running", _ChipSegment)
            r_seg.display = running > 0
            if running:
                r_seg.update(f"{running}▶")

            d_seg = self.query_one("#chip-done", _ChipSegment)
            d_seg.display = done > 0
            if done:
                d_seg.update(f"{done}✓")

            e_seg = self.query_one("#chip-errors", _ChipSegment)
            e_seg.display = errors > 0
            if errors:
                e_seg.update(RichText.from_markup(f"[bold red]{errors}✗[/bold red]"))

            c_seg = self.query_one("#chip-cost", _ChipSegment)
            c_seg.display = cost_usd > 0
            if cost_usd > 0:
                c_seg.update(f"${cost_usd:.2f}")

            self.query_one("#plan-f9-badge").display = True
        except (NoMatches, Exception):
            pass

    def on_click(self) -> None:
        """Toggle collapse via the app reactive."""
        try:
            app = self.app
            app.plan_panel_collapsed = not app.plan_panel_collapsed
        except Exception:
            pass


# ---------------------------------------------------------------------------
# PlanPanel
# ---------------------------------------------------------------------------

class PlanPanel(Vertical):
    """Bottom-docked plan/action queue panel.

    Composed of three subsections: Now, Next, Budget.
    Collapses to a one-line chip via plan_panel_collapsed reactive.
    """

    DEFAULT_CSS = """
    PlanPanel {
        dock: bottom;
        height: auto;
        max-height: 12;
        width: 1fr;
        background: $surface;
        border-top: solid $panel-border;
        display: none;
    }
    PlanPanel.--active {
        display: block;
    }
    PlanPanel.--collapsed {
        height: 1;
        max-height: 1;
    }
    PlanPanel._now-section {
        display: block;
    }
    """

    _collapsed: reactive[bool] = reactive(True)
    _active_hide_timer: Any = None

    def compose(self) -> ComposeResult:
        yield _PlanPanelHeader()
        yield _NowSection()
        yield _NextSection()
        yield _BudgetSection()

    def on_mount(self) -> None:
        """Register watchers for app-level reactives."""
        app = self.app
        # Watch planned_calls
        try:
            self.watch(app, "planned_calls", self._on_planned_calls_changed)
        except Exception:
            pass
        # Watch budget reactives
        try:
            self.watch(app, "turn_cost_usd", self._on_budget_changed)
            self.watch(app, "turn_tokens_in", self._on_budget_changed)
            self.watch(app, "turn_tokens_out", self._on_budget_changed)
        except Exception:
            pass
        # Watch collapse reactive
        try:
            self.watch(app, "plan_panel_collapsed", self._on_collapse_changed)
        except Exception:
            pass
        # Initial render
        self._rebuild()
        # Sync collapsed state immediately to avoid mount flash
        try:
            self._on_collapse_changed(getattr(self.app, "plan_panel_collapsed", True))
        except Exception:
            pass

    def _on_planned_calls_changed(self, calls: list) -> None:
        self._rebuild()
        from hermes_cli.tui.plan_types import PlanState
        has_active = any(c.state in (PlanState.PENDING, PlanState.RUNNING) for c in calls)
        has_any = bool(calls)
        try:
            app = self.app
            if has_active:
                app.add_class("plan-active")
            else:
                app.remove_class("plan-active")
        except Exception:
            pass
        # Debounced --active hide
        if has_any:
            # Show immediately; cancel any pending hide timer
            if self._active_hide_timer is not None:
                try:
                    self._active_hide_timer.stop()
                except Exception:
                    pass
                self._active_hide_timer = None
            try:
                self.add_class("--active")
            except Exception:
                pass
        else:
            # Defer hide by 3s
            if self._active_hide_timer is None:
                self._active_hide_timer = self.set_timer(3.0, self._do_hide_active)
        # Budget visibility
        self._refresh_budget_visibility(has_active, calls)

    def _do_hide_active(self) -> None:
        self._active_hide_timer = None
        try:
            self.remove_class("--active")
            self.app.remove_class("plan-active")
        except Exception:
            pass

    def _on_budget_changed(self, _: Any = None) -> None:
        try:
            app = self.app
            budget = self.query_one(_BudgetSection)
            budget.update_budget(
                getattr(app, "turn_cost_usd", 0.0),
                getattr(app, "turn_tokens_in", 0),
                getattr(app, "turn_tokens_out", 0),
            )
        except (NoMatches, Exception):
            pass

    def _on_collapse_changed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        if collapsed:
            self.add_class("--collapsed")
        else:
            self.remove_class("--collapsed")
        self._rebuild_header()
        # Show/hide body sections via --visible class
        # Budget section visibility is managed exclusively by _refresh_budget_visibility
        for sec_cls in (_NowSection, _NextSection):
            try:
                sec = self.query_one(sec_cls)
                sec.set_class(not collapsed, "--visible")
            except (NoMatches, Exception):
                pass

    def _rebuild(self) -> None:
        """Rebuild all subsections from current app state."""
        try:
            calls: list = getattr(self.app, "planned_calls", [])
        except Exception:
            calls = []
        self._rebuild_header()
        self._rebuild_now(calls)
        self._rebuild_next(calls)

    def _rebuild_header(self) -> None:
        try:
            calls: list = getattr(self.app, "planned_calls", [])
        except Exception:
            calls = []
        from hermes_cli.tui.plan_types import PlanState
        running = sum(1 for c in calls if c.state == PlanState.RUNNING)
        pending = sum(1 for c in calls if c.state == PlanState.PENDING)
        done = sum(1 for c in calls if c.state == PlanState.DONE)
        errors = sum(1 for c in calls if c.state == PlanState.ERROR)
        try:
            cost_usd: float = getattr(self.app, "turn_cost_usd", 0.0)
        except Exception:
            cost_usd = 0.0
        try:
            header = self.query_one(_PlanPanelHeader)
            header.update_header(self._collapsed, running, pending, done, errors, cost_usd)
        except (NoMatches, Exception):
            pass

    def _rebuild_now(self, calls: list) -> None:
        from hermes_cli.tui.plan_types import PlanState
        running = [c for c in calls if c.state == PlanState.RUNNING]
        try:
            now_sec = self.query_one(_NowSection)
            if running:
                now_sec.show_call(running[0])
            else:
                now_sec.clear()
        except (NoMatches, Exception):
            pass

    def _rebuild_next(self, calls: list) -> None:
        try:
            next_sec = self.query_one(_NextSection)
            next_sec.update_calls(calls)
        except (NoMatches, Exception):
            pass

    def _refresh_budget_visibility(self, has_active: bool, calls: list) -> None:
        # A13: show budget when idle+expanded+non-zero; no timer race
        app = self.app
        cost_usd = getattr(app, "turn_cost_usd", 0.0)
        tokens_in = getattr(app, "turn_tokens_in", 0)
        budget_non_zero = cost_usd > 0 or tokens_in > 0
        show = (
            not has_active
            and not self._collapsed
            and budget_non_zero
        )
        try:
            self.query_one(_BudgetSection).set_class(show, "--visible")
        except (NoMatches, Exception):
            pass
