"""Info overlay widgets for slash command TUI integration.

HelpOverlay, UsageOverlay, CommandsOverlay, WorkspaceOverlay have been migrated
to hermes_cli.tui.overlays.reference (R3 Phase C).  This file retains
SessionOverlay and ToolPanelHelpOverlay.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from textual import work
from textual.app import ComposeResult

_log = logging.getLogger(__name__)
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Button, Checkbox, ContentSwitcher, Input, OptionList, Static
from textual.widgets.option_list import Option


try:
    from hermes_cli.config import (
        _set_nested as _cfg_set_nested,
        get_hermes_home as _cfg_get_hermes_home,
        read_raw_config as _cfg_read_raw_config,
        save_config as _cfg_save_config,
    )
except ImportError:
    def _cfg_read_raw_config():  # type: ignore[misc]
        return {}

    def _cfg_save_config(cfg):  # type: ignore[misc]
        pass

    def _cfg_set_nested(cfg, key, value):  # type: ignore[misc]
        pass

    def _cfg_get_hermes_home():  # type: ignore[misc]
        from pathlib import Path
        return Path.home() / ".hermes"


class _SessionResumedBanner(Widget):
    """Single-line banner displayed after /resume clears OutputPanel."""

    DEFAULT_CSS = """
    _SessionResumedBanner {
        height: 1;
        width: 1fr;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self, session_title: str, turn_count: int) -> None:
        super().__init__()
        self._session_title = session_title
        self._turn_count = turn_count

    def render(self) -> str:
        label = self._session_title or ""
        turns = self._turn_count
        turn_word = "turn" if turns == 1 else "turns"
        return f"╌╌  resumed: {label}  ·  {turns} previous {turn_word}  ╌╌"


class SessionOverlay(Widget):
    """Session browser overlay. Open with /sessions or Ctrl+Shift+H."""

    DEFAULT_CSS = """
    SessionOverlay {
        display: none;
        layer: overlay;
        dock: top;
        height: auto;
        max-height: 60%;
        min-height: 10;
        width: 1fr;
        max-width: 80;
        margin: 1 2;
        padding: 0 1;
        background: $surface;
        border: tall $primary 15%;
        border-title-align: left;
        border-title-color: $accent;
        border-subtitle-align: right;
        border-subtitle-color: $text-muted;
    }
    SessionOverlay.--visible { display: block; }
    SessionOverlay #sess-scroll { height: auto; max-height: 50%; overflow-y: auto; }
    SessionOverlay ._SessionRow { height: 1; padding: 0 1; }
    SessionOverlay ._SessionRow.--selected { background: $accent 20%; }
    SessionOverlay ._SessionRow:hover { background: $accent 10%; }
    SessionOverlay ._SessionRow.--current { color: $accent; }
    """

    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        Binding("up",     "move_up",   priority=True),
        Binding("down",   "move_down", priority=True),
        Binding("ctrl+p", "move_up",   priority=True),
        Binding("ctrl+n", "move_down", priority=True),
        Binding("enter",  "select",    priority=True),
        Binding("n",      "new_session", priority=True),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._sessions: list[dict] = []
        self._selected_idx: int = 0

    def compose(self) -> "ComposeResult":
        yield Static("", id="sess-header")
        yield ScrollableContainer(id="sess-scroll")
        yield Static("[dim]↑↓ navigate  Enter resume  N new session  Esc close[/dim]", id="sess-footer")

    def open_sessions(self) -> None:
        """Show overlay and load sessions in background worker."""
        self.border_title = "Sessions"
        self.add_class("--visible", "--modal")
        self._selected_idx = 0
        try:
            self.query_one("#sess-scroll", ScrollableContainer).remove_children()
            self.query_one("#sess-scroll", ScrollableContainer).mount(Static("[dim]Loading…[/dim]", id="sess-loading"))
        except NoMatches:
            pass
        self._load_sessions()
        # C3: take keyboard focus so ↑↓ navigation works immediately after opening.
        self.focus()

    @work(thread=True)
    def _load_sessions(self) -> None:
        """Fetch session list from DB in worker thread."""
        try:
            db = getattr(self.app.cli, "_session_db", None) if hasattr(self, "app") else None
            if db is None:
                sessions: list[dict] = []
            else:
                sessions = db.list_sessions_rich(limit=20)
        except Exception:
            _log.warning("_load_sessions: session DB read failed", exc_info=True)
            sessions = []
        self.call_from_thread(self._render_rows, sessions)

    def _render_rows(self, sessions: list[dict]) -> None:
        """Render session rows after worker completes (event-loop only)."""
        self._sessions = sessions
        try:
            scroll = self.query_one("#sess-scroll", ScrollableContainer)
        except NoMatches:
            return
        scroll.remove_children()
        current_id = getattr(getattr(self.app, "cli", None), "session_id", None)
        rows: list["_SessionRow"] = []
        for i, s in enumerate(sessions):
            is_current = (s.get("id") == current_id)
            row = _SessionRow(s, is_current=is_current, idx=i)
            rows.append(row)
        if rows:
            scroll.mount(*rows)
        else:
            scroll.mount(Static("[dim]No sessions found[/dim]"))
        # Update header
        current_label = ""
        for s in sessions:
            if s.get("id") == current_id:
                current_label = s.get("title") or (s.get("id", "")[-8:] if s.get("id") else "")
                break
        try:
            self.query_one("#sess-header", Static).update(
                f"[bold]Sessions[/bold]  [dim]Current: {current_label}[/dim]"
            )
        except NoMatches:
            pass
        self._selected_idx = 0
        self._update_selection()

    def _update_selection(self) -> None:
        try:
            rows = list(self.query(_SessionRow))
        except Exception:
            _log.debug("SessionOverlay._update_selection: query failed", exc_info=True)
            return
        for i, row in enumerate(rows):
            row.set_class(i == self._selected_idx, "--selected")
        # C2: scroll to keep selected row visible
        if 0 <= self._selected_idx < len(rows):
            try:
                self.query_one("#sess-scroll", ScrollableContainer).scroll_to_widget(
                    rows[self._selected_idx], animate=False
                )
            except NoMatches:
                pass

    def action_move_up(self) -> None:
        self._selected_idx = max(0, self._selected_idx - 1)
        self._update_selection()

    def action_move_down(self) -> None:
        count = len(self._sessions)
        self._selected_idx = min(max(count - 1, 0), self._selected_idx + 1)
        self._update_selection()

    def action_select(self) -> None:
        if not self._sessions:
            self.action_dismiss()
            return
        idx = max(0, min(self._selected_idx, len(self._sessions) - 1))
        session = self._sessions[idx]
        current_id = getattr(getattr(self.app, "cli", None), "session_id", None)
        sid = session.get("id", "")
        self.action_dismiss()
        if sid == current_id:
            return
        try:
            self.app.action_resume_session(sid)
        except Exception:
            _log.warning("SessionOverlay.action_select: action_resume_session failed", exc_info=True)

    def action_new_session(self) -> None:
        self.action_dismiss()
        try:
            self.app._svc_commands.handle_tui_command("/new")
        except Exception:
            _log.warning("SessionOverlay.action_new_session: handle_tui_command failed", exc_info=True)

    def action_dismiss(self) -> None:
        self.remove_class("--visible", "--modal")
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass


class _SessionRow(Static):
    """Single row in SessionOverlay."""

    def __init__(self, session_meta: dict, is_current: bool, idx: int, **kwargs: object) -> None:
        self._meta = session_meta
        self._is_current = is_current
        self._idx = idx
        super().__init__(self._build_label(), **kwargs)
        if is_current:
            self.add_class("--current")

    def _build_label(self) -> str:
        import time as _time
        from datetime import datetime as _datetime
        meta = self._meta
        title = meta.get("title") or ""
        sid = meta.get("id") or ""
        label = title if title else f"[dim]untitled[/dim]"
        bullet = "●" if self._is_current else " "
        last_active = meta.get("last_active") or meta.get("started_at") or 0
        turn_count = meta.get("message_count") or 0
        # Relative time
        now = _time.time()
        diff = now - float(last_active) if last_active else 0
        if diff < 3600:
            rel = f"{int(diff/60)}m ago" if diff >= 60 else "just now"
        elif diff < 86400:
            rel = f"{int(diff/3600)}h ago"
        elif diff < 604800:
            rel = f"{int(diff/86400)}d ago"
        elif diff < 4838400:  # < 56 days (8 weeks)
            rel = f"{int(diff/604800)}w ago"
        else:
            rel = _datetime.fromtimestamp(float(last_active)).strftime("%Y-%m-%d") if last_active else "?"
        turn_word = "turn" if turn_count == 1 else "turns"
        return f"{bullet} {label:<32}  {rel:<10}  {turn_count} {turn_word}"


class ToolPanelHelpOverlay(Widget):
    """Binding reference for focused ToolPanel. Shown by '?', dismissed by Esc/'?'."""

    DEFAULT_CSS = """
    ToolPanelHelpOverlay {
        layer: overlay;
        display: none;
        height: auto;
        max-height: 24;
        width: 50;
        margin: 2 4;
        padding: 1 2;
        background: $surface;
        border: tall $primary 20%;
        border-title-align: left;
        border-title-color: $accent;
        dock: right;
        overflow-y: auto;
        scrollbar-gutter: stable;
    }
    ToolPanelHelpOverlay.--visible { display: block; }
    ToolPanelHelpOverlay > Static { height: auto; }
    """

    _BINDINGS_TABLE = """\
[bold]ToolPanel key reference[/bold]

[bold]Enter[/bold]   toggle collapse
[bold]j / k[/bold]   scroll 1 line
[bold]J / K[/bold]   scroll page
[bold]< / >[/bold]   scroll top / end
[bold]c[/bold]       copy plain text
[bold]C[/bold]       copy ANSI colors
[bold]H[/bold]       copy HTML
[bold]I[/bold]       copy invocation
[bold]u[/bold]       copy URLs
[bold]o[/bold]       open file/URL
[bold]p[/bold]       copy file paths
[bold]e[/bold]       copy stderr
[bold]E[/bold]       edit command
[bold]O[/bold]       open URL
[bold]r[/bold]       retry on error
[bold]+/-/*[/bold]   expand/collapse/all lines
[bold]?[/bold]       this help

[bold]Header chips[/bold]

…STARTING    tool is initialising
STREAMING    output arriving
…FINALIZING  wrapping up
DONE         completed successfully
CANCELLED    cancelled by user
ERR          exited with error
2m 3s        elapsed time after finish
✓            action confirmed (copy/retry)
HERO         full detail view
TRACE        condensed view
COMPACT      minimal view
"""

    def compose(self) -> ComposeResult:
        yield Static(self._BINDINGS_TABLE, markup=True)

    def show_overlay(self) -> None:
        self.border_title = "Tool keys"
        self.add_class("--visible")

    def hide_overlay(self) -> None:
        self.remove_class("--visible")

    def action_dismiss(self) -> None:
        self.remove_class("--visible")
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except Exception:
            _log.debug("ToolPanelHelpOverlay.action_dismiss: focus restore failed", exc_info=True)

    def on_key(self, event: "object") -> None:
        key = getattr(event, "key", None)
        if key in ("escape", "question_mark"):
            self.remove_class("--visible")
            getattr(event, "stop", lambda: None)()



def _dismiss_overlay_and_focus_input(overlay: Widget) -> None:
    """Remove --visible and restore focus to HermesInput."""
    overlay.remove_class("--visible")
    try:
        from hermes_cli.tui.input_widget import HermesInput
        overlay.app.query_one(HermesInput).focus()
    except (NoMatches, ImportError):
        pass


FIXTURE_CODE = """\
def fibonacci(n):
    if n <= 1:  # base case
        return n
    return fibonacci(n-1) + fibonacci(n-2)

result = [fibonacci(i) for i in range(10)]
print(f"sequence: {result}")  # [0,1,1,2,3...]
"""

_FIXTURE_BY_LANG: dict[str, str] = {
    "python": FIXTURE_CODE,
    "javascript": """\
function fibonacci(n) {
  if (n <= 1) return n;  // base case
  return fibonacci(n - 1) + fibonacci(n - 2);
}
console.log([...Array(10).keys()].map(fibonacci));
""",
    "typescript": """\
function fibonacci(n: number): number {
  if (n <= 1) return n;  // base case
  return fibonacci(n - 1) + fibonacci(n - 2);
}
console.log(Array.from({length: 10}, (_, i) => fibonacci(i)));
""",
    "go": """\
func fibonacci(n int) int {
    if n <= 1 { return n }  // base case
    return fibonacci(n-1) + fibonacci(n-2)
}
""",
    "rust": """\
fn fibonacci(n: u64) -> u64 {
    if n <= 1 { return n; }  // base case
    fibonacci(n - 1) + fibonacci(n - 2)
}
""",
    "ruby": """\
def fibonacci(n)
  return n if n <= 1  # base case
  fibonacci(n - 1) + fibonacci(n - 2)
end
puts (0..9).map { |i| fibonacci(i) }.inspect
""",
    "bash": """\
fibonacci() {
  local n=$1
  [ "$n" -le 1 ] && echo $n && return  # base case
  echo $(( $(fibonacci $((n-1))) + $(fibonacci $((n-2))) ))
}
""",
    "java": """\
static int fibonacci(int n) {
    if (n <= 1) return n;  // base case
    return fibonacci(n - 1) + fibonacci(n - 2);
}
""",
    "cpp": """\
int fibonacci(int n) {
    if (n <= 1) return n;  // base case
    return fibonacci(n-1) + fibonacci(n-2);
}
""",
    "c": """\
int fibonacci(int n) {
    if (n <= 1) return n;  /* base case */
    return fibonacci(n-1) + fibonacci(n-2);
}
""",
    "markdown": """\
# Fibonacci

A sequence where each number is the sum of the two preceding ones.

- Starts with: `0, 1, 1, 2, 3, 5, 8, 13...`
- Formula: `F(n) = F(n-1) + F(n-2)`
""",
}

