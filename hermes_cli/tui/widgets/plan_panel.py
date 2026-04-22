"""plan_panel.py — PlanPanel widget (R1).

Bottom-docked, collapsible strip that surfaces the agent's current work queue.

Sections:
  _PlanPanelHeader  — title + collapse chevron
  _NowSection       — currently-executing tool + elapsed timer
  _NextSection      — pending tools (max 5 + "+N more")
  _DoneSection      — completed tools this turn (max 5 + "+N more")
  _BudgetSection    — turn cost/token display, click opens UsageOverlay

TCSS vars required (must also be in hermes.tcss and all skin files):
  $plan-now-fg:     $accent-interactive (default #00bcd4)
  $plan-pending-fg: #777777 60%
"""
from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

from rich.text import Text
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

    def compose(self) -> ComposeResult:
        yield Static("", id="now-line")

    def show_call(self, call: "PlannedCall") -> None:
        """Update the Now line and (re)start the elapsed timer."""
        self._start_monotonic = call.started_at if call.started_at is not None else time.monotonic()
        self._elapsed_s = 0
        self._refresh_display(call)
        self._ensure_timer()

    def clear(self) -> None:
        """Clear the Now line and stop the timer."""
        try:
            self.query_one("#now-line", Static).update("")
        except (NoMatches, Exception):
            pass
        self._stop_timer()

    def _ensure_timer(self) -> None:
        if _DETERMINISTIC:
            return
        if self._timer_handle is None:
            self._timer_handle = self.set_interval(1.0, self._tick)

    def _stop_timer(self) -> None:
        if self._timer_handle is not None:
            try:
                self._timer_handle.stop()
            except Exception:
                pass
            self._timer_handle = None

    def _tick(self) -> None:
        elapsed = int(time.monotonic() - self._start_monotonic)
        self._elapsed_s = elapsed
        # Refresh the label without a full call reference — just update elapsed text
        try:
            static = self.query_one("#now-line", Static)
            current = static.renderable  # type: ignore[attr-defined]
            # Replace elapsed suffix
            text = str(current) if not isinstance(current, str) else current
            # Strip existing elapsed and re-add
            if "  [" in text:
                base = text[:text.rfind("  [")]
            else:
                base = text
            static.update(f"{base}  [{elapsed}s]")
        except (NoMatches, Exception):
            pass

    def _refresh_display(self, call: "PlannedCall") -> None:
        elapsed = 0 if _DETERMINISTIC else int(time.monotonic() - self._start_monotonic)
        label = call.label[:50] if len(call.label) > 50 else call.label
        glyph = _glyph_running()
        text = f"{glyph} {label}  [{elapsed}s]"
        try:
            self.query_one("#now-line", Static).update(
                Text.from_markup(f"[$plan-now-fg]{text}[/$plan-now-fg]")
                if False  # Rich can't use TCSS vars — use plain text with inline style
                else text
            )
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
    _expanded: reactive[bool] = reactive(False)

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

        limit = len(pending) if self._expanded else self._MAX_VISIBLE
        visible = pending[:limit]
        overflow = len(pending) - limit

        new_children: list[Static] = []
        for call in visible:
            indent = "  " * call.depth
            glyph = _glyph_pending()
            label = call.label[:50] if len(call.label) > 50 else call.label
            new_children.append(Static(f"  {indent}{glyph} {label}", classes="plan-pending-line"))

        if overflow > 0:
            more = Static(f"  … +{overflow} more", classes="plan-more-line", id="next-more")
            new_children.append(more)

        if new_children:
            container.mount(*new_children)


# ---------------------------------------------------------------------------
# _DoneSection
# ---------------------------------------------------------------------------

class _DoneSection(Vertical):
    """Shows completed tools this turn (up to 5 + overflow indicator)."""

    DEFAULT_CSS = """
    _DoneSection {
        height: auto;
        width: 1fr;
        display: none;
    }
    _DoneSection.--visible { display: block; }
    """

    _MAX_VISIBLE = 5
    _expanded: reactive[bool] = reactive(False)

    def compose(self) -> ComposeResult:
        yield Static("", id="done-header")

    def update_calls(self, calls: "list[PlannedCall]") -> None:
        """Rebuild the done section content."""
        from hermes_cli.tui.plan_types import PlanState
        done = [c for c in calls if c.state in (PlanState.DONE, PlanState.ERROR, PlanState.CANCELLED, PlanState.SKIPPED)]
        container = self
        for child in list(container.children):
            if child.id != "done-header":
                child.remove()

        if not done:
            try:
                self.query_one("#done-header", Static).update("")
            except NoMatches:
                pass
            return

        try:
            self.query_one("#done-header", Static).update("Done:")
        except NoMatches:
            pass

        limit = len(done) if self._expanded else self._MAX_VISIBLE
        visible = done[:limit]
        overflow = len(done) - limit

        new_children: list[Static] = []
        for call in visible:
            indent = "  " * call.depth
            if call.state == PlanState.ERROR:
                glyph = _glyph_error()
            else:
                glyph = _glyph_done()
            label = call.label[:50] if len(call.label) > 50 else call.label
            dur_str = ""
            if call.started_at is not None and call.ended_at is not None:
                dur_ms = int((call.ended_at - call.started_at) * 1000)
                dur_str = f" ({dur_ms}ms)"
            new_children.append(Static(f"  {indent}{glyph} {label}{dur_str}", classes="plan-done-line"))

        if overflow > 0:
            new_children.append(Static(f"  … +{overflow} more", classes="plan-more-line", id="done-more"))

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
# _PlanPanelHeader
# ---------------------------------------------------------------------------

class _PlanPanelHeader(Horizontal):
    """Title bar with collapse/expand chevron."""

    DEFAULT_CSS = """
    _PlanPanelHeader {
        height: 1;
        width: 1fr;
    }
    _PlanPanelHeader:hover {
        background: $accent 5%;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("", id="plan-header-label")

    def update_header(self, collapsed: bool, running: int, pending: int, done: int) -> None:
        """Refresh the header line."""
        chevron = "▸" if collapsed else "▾"
        if collapsed:
            label = f"Plan {chevron}  {running}▶ · {pending}▸ · {done}✓"
        else:
            label = f"Plan {chevron}"
        try:
            self.query_one("#plan-header-label", Static).update(label)
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

    Composed of four subsections: Now, Next, Done, Budget.
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

    _collapsed: reactive[bool] = reactive(False)

    def compose(self) -> ComposeResult:
        yield _PlanPanelHeader()
        yield _NowSection()
        yield _NextSection()
        yield _DoneSection()
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
        try:
            if has_any:
                self.add_class("--active")
            else:
                self.remove_class("--active")
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
        for sec_cls in (_NowSection, _NextSection, _DoneSection, _BudgetSection):
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
        self._rebuild_done(calls)

    def _rebuild_header(self) -> None:
        try:
            calls: list = getattr(self.app, "planned_calls", [])
        except Exception:
            calls = []
        from hermes_cli.tui.plan_types import PlanState
        running = sum(1 for c in calls if c.state == PlanState.RUNNING)
        pending = sum(1 for c in calls if c.state == PlanState.PENDING)
        done = sum(1 for c in calls if c.state in (PlanState.DONE, PlanState.ERROR))
        try:
            header = self.query_one(_PlanPanelHeader)
            header.update_header(self._collapsed, running, pending, done)
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

    def _rebuild_done(self, calls: list) -> None:
        try:
            done_sec = self.query_one(_DoneSection)
            done_sec.update_calls(calls)
        except (NoMatches, Exception):
            pass
