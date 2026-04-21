"""Info overlay widgets for slash command TUI integration.

HelpOverlay, UsageOverlay, CommandsOverlay, ModelOverlay are all info overlays:
- layer: overlay; dock: top; display: none by default
- shown by adding --visible class, hidden by removing it
- dismiss with Esc/q; action_dismiss restores focus to HermesInput
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import work
from textual.app import ComposeResult
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


class HelpOverlay(Widget):
    """Slash command reference. Shown by /help; dismissed with Esc/q."""

    DEFAULT_CSS = """
    HelpOverlay {
        layer: overlay;
        dock: top;
        display: none;
        height: auto;
        max-height: 30;
        width: 1fr;
        max-width: 80;
        margin: 1 2;
        padding: 1 2;
        background: $surface;
        border: tall $primary 15%;
    }
    HelpOverlay.--visible { display: block; }
    HelpOverlay > #help-content {
        height: auto;
        max-height: 26;
        overflow-y: auto;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        # priority=False: when #help-search Input has focus, q inserts normally.
        # When the overlay itself has focus, q fires dismiss.
        Binding("q", "dismiss", priority=False),
    ]

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Filter commands...", id="help-search")
        yield Vertical(id="help-content")

    def on_mount(self) -> None:
        self._refresh_commands_cache()

    def _refresh_commands_cache(self) -> None:
        """Rebuild command cache from current COMMANDS_BY_CATEGORY and repopulate."""
        from hermes_cli.commands import COMMANDS_BY_CATEGORY
        self._commands_cache: list[tuple[str, str, str]] = [
            (cat, cmd, desc)
            for cat, cmds in COMMANDS_BY_CATEGORY.items()
            for cmd, desc in cmds.items()
        ]
        self._populate(self._commands_cache)

    def show_overlay(self) -> None:
        """Show overlay and focus the filter input."""
        self.add_class("--visible")
        # C1: clear previous search query so the list always opens unfiltered
        try:
            inp = self.query_one("#help-search", Input)
            inp.value = ""
            inp.focus()
        except NoMatches:
            pass
        self._populate(self._commands_cache)

    def _populate(self, entries: list[tuple[str, str, str]]) -> None:
        """Rebuild content list with a single batched mount to avoid per-item repaint."""
        container = self.query_one("#help-content", Vertical)
        container.remove_children()
        children: list[Static] = []
        current_cat: str | None = None
        for cat, cmd, desc in entries:
            if cat != current_cat:
                children.append(Static(f"── {cat} ──", classes="category-header"))
                current_cat = cat
            children.append(Static(f"  [bold]{cmd}[/bold]  {desc}"))
        if children:
            container.mount(*children)

    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.lower().strip()
        if not query:
            self._populate(self._commands_cache)
            return
        filtered = [
            (cat, cmd, desc) for cat, cmd, desc in self._commands_cache
            if query in cmd.lower() or query in desc.lower()
        ]
        self._populate(filtered)

    def action_dismiss(self) -> None:
        self.remove_class("--visible")
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass


class UsageOverlay(Widget):
    """Token usage and rate limit display. Shown by /usage; dismissed with Esc/q."""

    DEFAULT_CSS = """
    UsageOverlay {
        layer: overlay;
        dock: top;
        display: none;
        height: auto;
        max-height: 20;
        width: 1fr;
        max-width: 60;
        margin: 1 2;
        padding: 1 2;
        background: $surface;
        border: tall $primary 15%;
    }
    UsageOverlay.--visible { display: block; }
    """

    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        # q removed: UsageOverlay does not capture focus (HermesInput retains it).
        # With priority=True, q would insert into HermesInput instead of dismissing.
        # Dismiss via Escape (handled by on_key Priority -2 in HermesApp).
    ]

    def compose(self) -> ComposeResult:
        yield Static(id="usage-content")

    def refresh_data(self, agent: object) -> None:
        """Pull current usage from agent, update the inner Static."""
        from agent.usage_pricing import CanonicalUsage, estimate_usage_cost

        input_tokens = getattr(agent, "session_input_tokens", 0) or 0
        output_tokens = getattr(agent, "session_output_tokens", 0) or 0
        cache_read = getattr(agent, "session_cache_read_tokens", 0) or 0
        cache_write = getattr(agent, "session_cache_write_tokens", 0) or 0
        total = getattr(agent, "session_total_tokens", 0) or 0
        calls = getattr(agent, "session_api_calls", 0) or 0
        model = getattr(agent, "model", "unknown")

        compressor = getattr(agent, "context_compressor", None)
        last_prompt = getattr(compressor, "last_prompt_tokens", 0) if compressor else 0
        ctx_len = getattr(compressor, "context_length", 0) if compressor else 0
        pct = min(100, last_prompt / ctx_len * 100) if ctx_len else 0
        compressions = getattr(compressor, "compression_count", 0) if compressor else 0

        cost_result = estimate_usage_cost(
            model,
            CanonicalUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
            ),
            provider=getattr(agent, "provider", None),
            base_url=getattr(agent, "base_url", None),
        )

        lines = [
            f"[bold]Model:[/bold] {model}",
            f"Input:        {input_tokens:>12,}",
            f"Cache read:   {cache_read:>12,}",
            f"Cache write:  {cache_write:>12,}",
            f"Output:       {output_tokens:>12,}",
            f"Total tokens: {total:>12,}",
            f"API calls:    {calls:>12,}",
        ]

        if cost_result.amount_usd is not None:
            prefix = "~" if cost_result.status == "estimated" else ""
            lines.append(f"Cost:     {prefix}${float(cost_result.amount_usd):>12.4f}")
        elif cost_result.status == "included":
            lines.append("Cost:         included")

        rl_state = None
        if hasattr(agent, "get_rate_limit_state"):
            try:
                rl_state = agent.get_rate_limit_state()
            except Exception:
                pass
        if rl_state and getattr(rl_state, "has_data", False):
            from agent.rate_limit_tracker import format_rate_limit_display
            lines.append("")
            lines.append(format_rate_limit_display(rl_state))

        lines += [
            "",
            f"Context: {last_prompt:,} / {ctx_len:,} ({pct:.0f}%)",
            f"Compressions: {compressions}",
        ]

        try:
            self.query_one("#usage-content", Static).update("\n".join(lines))
        except NoMatches:
            pass

    def action_dismiss(self) -> None:
        self.remove_class("--visible")
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass


class CommandsOverlay(Widget):
    """Full command + skill + plugin browse. Shown by /commands; dismissed with Esc/q."""

    DEFAULT_CSS = """
    CommandsOverlay {
        layer: overlay;
        dock: top;
        display: none;
        height: auto;
        max-height: 30;
        width: 1fr;
        margin: 1 2;
        padding: 1 2;
        background: $surface;
        border: tall $primary 15%;
    }
    CommandsOverlay.--visible { display: block; }
    CommandsOverlay > #commands-content {
        height: auto;
        max-height: 26;
        overflow-y: auto;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        # q removed: CommandsOverlay does not capture focus (HermesInput retains it).
        # Dismiss via Escape (handled by on_key Priority -2 in HermesApp).
    ]

    def compose(self) -> ComposeResult:
        yield Static("[bold]Commands[/bold]  (Esc to dismiss)", id="commands-title")
        yield Vertical(id="commands-content")

    def on_mount(self) -> None:
        self._refresh_content()

    def _refresh_content(self) -> None:
        from hermes_cli.commands import tui_help_lines
        lines = tui_help_lines()
        try:
            container = self.query_one("#commands-content", Vertical)
        except NoMatches:
            return
        container.remove_children()
        children = [Static(line) for line in lines] if lines else [Static("(no commands available)")]
        container.mount(*children)

    def action_dismiss(self) -> None:
        self.remove_class("--visible")
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass


class ModelOverlay(Widget):
    """Current model info display. Shown by /model (no args); dismissed with Esc."""

    DEFAULT_CSS = """
    ModelOverlay {
        layer: overlay;
        dock: top;
        display: none;
        height: auto;
        max-height: 16;
        width: 1fr;
        max-width: 70;
        margin: 1 2;
        padding: 1 2;
        background: $surface;
        border: tall $primary 15%;
    }
    ModelOverlay.--visible { display: block; }
    """

    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        # q removed: ModelOverlay does not capture focus (HermesInput retains it).
        # Dismiss via Escape (handled by on_key Priority -2 in HermesApp).
    ]

    def compose(self) -> ComposeResult:
        yield Static(id="model-content")

    def refresh_data(self, cli: object) -> None:
        """Pull current model/provider info from CLI object."""
        agent = getattr(cli, "agent", None)
        model = getattr(agent, "model", None) or getattr(cli, "model", "unknown")
        provider = getattr(agent, "provider", None) or getattr(cli, "provider", "unknown")
        base_url = getattr(agent, "base_url", None) or ""

        lines = [
            f"[bold]Current model:[/bold] {model}",
            f"Provider:      {provider}",
        ]
        if base_url:
            lines.append(f"Base URL:      {base_url}")
        lines += [
            "",
            "Use [bold]/model <name>[/bold] to switch.",
        ]

        try:
            self.query_one("#model-content", Static).update("\n".join(lines))
        except NoMatches:
            pass

    def action_dismiss(self) -> None:
        self.remove_class("--visible")
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass


class WorkspaceOverlay(Widget):
    """Live working-tree summary. Shown by w / /workspace; dismissed with Esc/q."""

    DEFAULT_CSS = """
    WorkspaceOverlay {
        display: none;
        layer: overlay;
        dock: top;
        height: auto;
        max-height: 22;
        width: 1fr;
        max-width: 80;
        margin: 1 2;
        padding: 0 1;
        background: $surface;
        border: tall $primary 15%;
    }
    WorkspaceOverlay.--visible { display: block; }
    WorkspaceOverlay #ws-tab-bar { height: 1; }
    WorkspaceOverlay #ws-tab-bar > Button { width: auto; min-width: 14; }
    WorkspaceOverlay #ws-tab-bar .--tab-active { background: $primary 20%; color: $accent; }
    WorkspaceOverlay #ws-git-pane { height: auto; }
    WorkspaceOverlay #ws-scroll { height: auto; max-height: 14; overflow-y: auto; }
    WorkspaceOverlay .ws-file { color: $text; }
    WorkspaceOverlay .ws-file-dirty { color: $warning; }
    WorkspaceOverlay .ws-complexity { color: $warning; }
    WorkspaceOverlay .ws-added { color: $success; }
    WorkspaceOverlay .ws-removed { color: $error; }
    WorkspaceOverlay #ws-switcher { height: auto; }
    """

    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        # q removed: WorkspaceOverlay does not capture focus (HermesInput retains it).
        # Dismiss via Escape or press w (action_toggle_workspace in HermesApp).
    ]

    def compose(self) -> ComposeResult:
        with Horizontal(id="ws-tab-bar"):
            yield Button("[ Git Status ]", id="ws-tab-git", classes="--tab-active")
            yield Button("[ Sessions ]", id="ws-tab-sessions")
        with ContentSwitcher(initial="ws-git-pane", id="ws-switcher"):
            with Vertical(id="ws-git-pane"):
                yield Static("", id="ws-header")
                yield Static("", id="ws-summary")
                with ScrollableContainer(id="ws-scroll"):
                    yield Vertical(id="ws-files")
                    yield Vertical(id="ws-complexity")
            from hermes_cli.tui.session_widgets import _SessionsTab
            yield _SessionsTab(id="ws-sessions-pane")
        yield Static("[dim]w / esc to close[/dim]", id="ws-footer")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "ws-tab-git":
            event.stop()
            self._switch_tab("ws-git-pane")
        elif btn_id == "ws-tab-sessions":
            event.stop()
            self._switch_tab("ws-sessions-pane")
            self._refresh_sessions_tab()

    def _switch_tab(self, pane_id: str) -> None:
        try:
            sw = self.query_one("#ws-switcher", ContentSwitcher)
            sw.current = pane_id
        except Exception:
            pass
        # Update tab button active class
        try:
            git_btn = self.query_one("#ws-tab-git", Button)
            sess_btn = self.query_one("#ws-tab-sessions", Button)
            if pane_id == "ws-git-pane":
                git_btn.add_class("--tab-active")
                sess_btn.remove_class("--tab-active")
            else:
                sess_btn.add_class("--tab-active")
                git_btn.remove_class("--tab-active")
        except Exception:
            pass

    def _refresh_sessions_tab(self) -> None:
        try:
            from hermes_cli.tui.session_widgets import _SessionsTab
            tab = self.query_one(_SessionsTab)
            records = []
            active_id = ""
            try:
                records = self.app._get_session_records()
                active_id = self.app._get_active_session_id()
            except Exception:
                pass
            tab.refresh_sessions(records, active_id)
        except Exception:
            pass

    def show_overlay(self) -> None:
        self.add_class("--visible")
        # C4: focus first tab button so keyboard tab-through works from the start
        try:
            self.query_one("#ws-tab-git", Button).focus()
        except NoMatches:
            pass

    def action_dismiss(self) -> None:
        self.remove_class("--visible")
        try:
            self.app._sync_workspace_polling_state()
        except Exception:
            pass
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass

    def refresh_data(self, tracker: object, snapshot: object | None) -> None:
        """Rebuild header, summary, and file list from tracker + optional snapshot."""
        from hermes_cli.tui.workspace_tracker import GitSnapshot

        try:
            header_widget = self.query_one("#ws-header", Static)
            summary_widget = self.query_one("#ws-summary", Static)
            files_widget = self.query_one("#ws-files", Vertical)
            complexity_widget = self.query_one("#ws-complexity", Vertical)
        except NoMatches:
            return

        files_widget.remove_children()
        complexity_widget.remove_children()

        if not getattr(tracker, "is_git_repo", True):
            header_widget.update("[bold]Workspace[/bold]")
            summary_widget.update("[dim]Workspace view requires a Git repository[/dim]")
            return

        if snapshot is not None and isinstance(snapshot, GitSnapshot):
            dirty_chip = f" ● {snapshot.dirty_count} dirty" if snapshot.dirty_count else ""
            branch = f"  [dim]{snapshot.branch}[/dim]" if snapshot.branch else ""
            header_widget.update(f"[bold]Workspace[/bold]{branch}{dirty_chip}")
            summary_widget.update(
                f"Git  {snapshot.modified_count} modified"
                f"  ·  {snapshot.deleted_count} deleted"
                f"  ·  {snapshot.staged_count} staged"
                f"  ·  {snapshot.untracked_count} untracked"
            )
        else:
            header_widget.update("[bold]Workspace[/bold]")
            summary_widget.update("[dim]Loading git status...[/dim]")

        entries = tracker.entries()
        file_children: list[Static] = []
        for e in entries:
            tags: list[str] = []
            if e.git_staged:
                tags.append("staged")
            if e.git_untracked:
                tags.append("untracked")
            if e.hermes_touched:
                tags.append("Hermes")
            if e.git_conflicted:
                tags.append("conflict")
            tag_text = f"  [dim]{' · '.join(tags)}[/dim]" if tags else ""
            rename_text = f"  [dim]← {e.git_renamed_from}[/dim]" if e.git_renamed_from else ""
            delta_text = ""
            if e.hermes_touched or e.session_added or e.session_removed:
                delta_text = (
                    f"  [green]+{e.session_added}[/green] [red]-{e.session_removed}[/red]"
                )
            css_class = "ws-file-dirty" if e.git_status not in (" ", "") else "ws-file"
            line = f"[bold]{e.git_xy or e.git_status or ' '}[/bold]  {e.rel_path or e.path}{rename_text}{delta_text}{tag_text}"
            file_children.append(Static(line, classes=css_class))
        if file_children:
            files_widget.mount(*file_children)

        warnings = [(e.rel_path or e.path, e.complexity_warning) for e in entries if e.complexity_warning]
        if warnings:
            complexity_widget.mount(Static(""))
            for rel, warn in warnings:
                complexity_widget.mount(
                    Static(f"⚠  {rel}  ·  {warn}", classes="ws-complexity")
                )


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
        self.add_class("--visible")
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
            pass

    def action_new_session(self) -> None:
        self.action_dismiss()
        try:
            self.app._handle_tui_command("/new")
        except Exception:
            pass

    def action_dismiss(self) -> None:
        self.remove_class("--visible")
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
        else:
            rel = f"{int(diff/604800)}w ago"
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
        dock: right;
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
"""

    def compose(self) -> ComposeResult:
        yield Static(self._BINDINGS_TABLE, markup=True)

    def show_overlay(self) -> None:
        self.add_class("--visible")

    def hide_overlay(self) -> None:
        # C1: overlay is pre-mounted at app compose time; just hide it, don't remove.
        self.remove_class("--visible")

    def on_key(self, event: "object") -> None:
        key = getattr(event, "key", None)
        if key in ("escape", "question_mark"):
            self.hide_overlay()
            getattr(event, "stop", lambda: None)()


# ---------------------------------------------------------------------------
# Config picker overlays — /verbose, /yolo, /reasoning, /model, /skin
# ---------------------------------------------------------------------------


def _dismiss_overlay_and_focus_input(overlay: Widget) -> None:
    """Remove --visible and restore focus to HermesInput."""
    overlay.remove_class("--visible")
    try:
        from hermes_cli.tui.input_widget import HermesInput
        overlay.app.query_one(HermesInput).focus()
    except (NoMatches, ImportError):
        pass


class VerbosePickerOverlay(Widget):
    """Tool progress mode picker. Shown by /verbose; dismissed with Esc or selection.

    Config key: display.tool_progress — values: off | new | all | verbose
    """

    DEFAULT_CSS = """
    VerbosePickerOverlay {
        layer: overlay;
        dock: top;
        display: none;
        height: auto;
        max-height: 12;
        width: 1fr;
        max-width: 80;
        margin: 1 2;
        padding: 1 2;
        background: $surface;
        border: tall $primary 15%;
    }
    VerbosePickerOverlay.--visible { display: block; }
    VerbosePickerOverlay > #vpo-header { color: $accent; }
    """

    BINDINGS = [Binding("escape", "dismiss", priority=True)]

    _OPTIONS: list[tuple[str, str]] = [
        ("off",     "off      — no streaming tool output"),
        ("new",     "new      — stream output for new tools only"),
        ("all",     "all      — stream all tool output"),
        ("verbose", "verbose  — stream + expanded collapse thresholds"),
    ]

    def compose(self) -> ComposeResult:
        yield Static("  Tool progress", id="vpo-header")
        ol = OptionList(
            *[Option(label, id=f"vpo-opt-{key}") for key, label in self._OPTIONS],
            id="vpo-list",
        )
        yield ol

    def refresh_data(self, cli: object) -> None:
        """Pre-select the current tool_progress value and add ● active marker."""
        cfg = _cfg_read_raw_config()
        current = cfg.get("display", {}).get("tool_progress", "all")
        try:
            ol = self.query_one("#vpo-list", OptionList)
            ol.clear_options()
            keys = [k for k, _ in self._OPTIONS]
            for key, label in self._OPTIONS:
                # C4: prefix active option with ● so it's immediately visible
                marker = "● " if key == current else "  "
                ol.add_option(Option(f"{marker}{label}", id=f"vpo-opt-{key}"))
            idx = keys.index(current) if current in keys else 2  # default "all"
            ol.highlighted = idx
        except (NoMatches, ValueError):
            pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Apply the selected tool_progress mode and dismiss."""
        event.stop()
        opt_id = event.option_id or ""
        if opt_id.startswith("vpo-opt-"):
            mode = opt_id[len("vpo-opt-"):]
            self._apply_and_dismiss(mode)

    def _apply_and_dismiss(self, mode: str) -> None:
        try:
            cfg = _cfg_read_raw_config()
            _cfg_set_nested(cfg, "display.tool_progress", mode)
            _cfg_save_config(cfg)
        except Exception:
            pass
        try:
            self.app._flash_hint(f"  Tool progress → {mode}", 2.0)
        except Exception:
            pass
        _dismiss_overlay_and_focus_input(self)

    def action_dismiss(self) -> None:
        _dismiss_overlay_and_focus_input(self)


class YoloConfirmOverlay(Widget):
    """YOLO mode confirmation overlay. Shown by /yolo; dismissed with Esc or button.

    Reads/writes approvals.mode in config + os.environ[HERMES_YOLO_MODE] +
    app.yolo_mode reactive for immediate live effect.
    """

    DEFAULT_CSS = """
    YoloConfirmOverlay {
        layer: overlay;
        dock: top;
        display: none;
        height: auto;
        max-height: 12;
        width: 1fr;
        max-width: 80;
        margin: 1 2;
        padding: 1 2;
        background: $surface;
        border: tall $primary 15%;
    }
    YoloConfirmOverlay.--visible { display: block; }
    YoloConfirmOverlay > #yco-header { color: $accent; }
    YoloConfirmOverlay > #yco-state { color: $warning; }
    YoloConfirmOverlay > #yco-desc { color: $text-muted; }
    YoloConfirmOverlay > #yco-buttons { height: auto; margin-top: 1; }
    YoloConfirmOverlay > #yco-buttons > Button { margin-right: 1; }
    """

    BINDINGS = [Binding("escape", "dismiss", priority=True)]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._previous_mode: str = "manual"

    def compose(self) -> ComposeResult:
        yield Static("  YOLO mode", id="yco-header")
        yield Static("", id="yco-state")
        yield Static(
            "YOLO skips all tool approval prompts.\nAll tool calls run without confirmation.",
            id="yco-desc",
        )
        with Horizontal(id="yco-buttons"):
            yield Button("Enable",  id="yco-enable",  variant="warning")
            yield Button("Disable", id="yco-disable", variant="success")
            yield Button("Cancel",  id="yco-cancel",  variant="default")

    def refresh_data(self, cli: object) -> None:
        """Sync overlay state from config."""
        cfg = _cfg_read_raw_config()
        mode = cfg.get("approvals", {}).get("mode", "manual")
        is_active = (mode == "off")
        if not is_active:
            self._previous_mode = mode  # remember non-yolo mode for restore
        try:
            state_w = self.query_one("#yco-state", Static)
            state_w.update("ACTIVE ⚡" if is_active else "inactive")
        except NoMatches:
            pass
        # Show/hide buttons
        try:
            self.query_one("#yco-enable", Button).display = not is_active
            self.query_one("#yco-disable", Button).display = is_active
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        btn_id = event.button.id or ""
        if btn_id == "yco-enable":
            self._set_yolo(True)
        elif btn_id == "yco-disable":
            self._set_yolo(False)
        elif btn_id == "yco-cancel":
            _dismiss_overlay_and_focus_input(self)

    def _set_yolo(self, enable: bool) -> None:
        import os as _os
        try:
            cfg = _cfg_read_raw_config()
            if enable:
                _cfg_set_nested(cfg, "approvals.mode", "off")
            else:
                _cfg_set_nested(cfg, "approvals.mode", self._previous_mode)
            _cfg_save_config(cfg)
        except Exception:
            pass
        # Update env var for live session effect
        if enable:
            _os.environ["HERMES_YOLO_MODE"] = "1"
        else:
            _os.environ["HERMES_YOLO_MODE"] = ""
        # Update app reactive
        try:
            self.app.yolo_mode = enable
        except Exception:
            pass
        # Flash
        try:
            msg = "⚡  YOLO mode enabled" if enable else "  YOLO mode disabled"
            self.app._flash_hint(msg, 2.0)
        except Exception:
            pass
        _dismiss_overlay_and_focus_input(self)

    def action_dismiss(self) -> None:
        _dismiss_overlay_and_focus_input(self)


class ReasoningPickerOverlay(Widget):
    """Reasoning level + display toggle overlay. Shown by /reasoning (bare).

    Level buttons inject /reasoning <level> through the submit path.
    Checkboxes persist display.show_reasoning / display.rich_reasoning to config.
    """

    DEFAULT_CSS = """
    ReasoningPickerOverlay {
        layer: overlay;
        dock: top;
        display: none;
        height: auto;
        max-height: 16;
        width: 1fr;
        max-width: 80;
        margin: 1 2;
        padding: 1 2;
        background: $surface;
        border: tall $primary 15%;
    }
    ReasoningPickerOverlay.--visible { display: block; }
    ReasoningPickerOverlay > #rpo-header { color: $accent; }
    ReasoningPickerOverlay > #rpo-levels { height: auto; margin-bottom: 1; }
    ReasoningPickerOverlay > #rpo-levels > Button { margin-right: 1; }
    ReasoningPickerOverlay > #rpo-toggles { height: auto; margin-bottom: 1; }
    ReasoningPickerOverlay > #rpo-toggles > Checkbox { margin-right: 2; }
    ReasoningPickerOverlay > #rpo-hint { color: $text-muted; }
    """

    BINDINGS = [Binding("escape", "dismiss", priority=True)]

    _LEVELS: list[str] = ["none", "low", "minimal", "medium", "high", "xhigh"]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._current_level: str = "medium"

    def compose(self) -> ComposeResult:
        yield Static("  Reasoning", id="rpo-header")
        with Horizontal(id="rpo-levels"):
            for lvl in self._LEVELS:
                variant = "primary" if lvl == self._current_level else "default"
                yield Button(lvl, id=f"rpo-btn-{lvl}", variant=variant)
        with Horizontal(id="rpo-toggles"):
            yield Checkbox("Show panel", id="rpo-show", value=False)
            yield Checkbox("Rich mode",  id="rpo-rich", value=True)
        yield Static("[dim]Select a level to set reasoning effort. Esc to close.[/dim]", id="rpo-hint")

    def refresh_data(self, cli: object) -> None:
        """Sync checkbox state from config."""
        cfg = _cfg_read_raw_config()
        show = bool(cfg.get("display", {}).get("show_reasoning", False))
        rich = bool(cfg.get("display", {}).get("rich_reasoning", True))
        try:
            self.query_one("#rpo-show", Checkbox).value = show
        except NoMatches:
            pass
        try:
            self.query_one("#rpo-rich", Checkbox).value = rich
        except NoMatches:
            pass
        self._update_level_highlights()

    def _update_level_highlights(self) -> None:
        for lvl in self._LEVELS:
            try:
                btn = self.query_one(f"#rpo-btn-{lvl}", Button)
                btn.variant = "primary" if lvl == self._current_level else "default"
            except NoMatches:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        btn_id = event.button.id or ""
        if btn_id.startswith("rpo-btn-"):
            level = btn_id[len("rpo-btn-"):]
            if level in self._LEVELS:
                self._current_level = level
                self._update_level_highlights()
                self._inject_level_command(level)

    def _inject_level_command(self, level: str) -> None:
        """Forward /reasoning <level> to CLI via HermesInput submit path, then dismiss."""
        try:
            from hermes_cli.tui.input_widget import HermesInput
            inp = self.app.query_one(HermesInput)
            inp.value = f"/reasoning {level}"
            inp.action_submit()
        except (NoMatches, ImportError):
            pass
        _dismiss_overlay_and_focus_input(self)

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        event.stop()
        cb_id = event.checkbox.id or ""
        value = event.value
        try:
            cfg = _cfg_read_raw_config()
            if cb_id == "rpo-show":
                _cfg_set_nested(cfg, "display.show_reasoning", value)
            elif cb_id == "rpo-rich":
                _cfg_set_nested(cfg, "display.rich_reasoning", value)
            else:
                return
            _cfg_save_config(cfg)
        except Exception:
            pass

    def action_dismiss(self) -> None:
        _dismiss_overlay_and_focus_input(self)


class ModelPickerOverlay(Widget):
    """Interactive model picker. Shown by /model (bare); /model <name> bypasses.

    On Enter, injects /model <name> back through HermesInput.action_submit()
    so the CLI handles the actual model switch.
    """

    DEFAULT_CSS = """
    ModelPickerOverlay {
        layer: overlay;
        dock: top;
        display: none;
        height: auto;
        max-height: 24;
        width: 1fr;
        max-width: 80;
        margin: 1 2;
        padding: 1 2;
        background: $surface;
        border: tall $primary 15%;
    }
    ModelPickerOverlay.--visible { display: block; }
    ModelPickerOverlay > #mpo-header { color: $accent; }
    ModelPickerOverlay > #mpo-current { color: $text-muted; }
    ModelPickerOverlay > #mpo-list { height: auto; max-height: 18; }
    """

    BINDINGS = [Binding("escape", "dismiss", priority=True)]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._models: list[str] = []
        self._current_model: str = ""

    def compose(self) -> ComposeResult:
        yield Static("  Model", id="mpo-header")
        yield Static("", id="mpo-current")
        yield OptionList(id="mpo-list")

    def refresh_data(self, cli: object) -> None:
        """Populate model list and pre-select the current model."""
        cfg = _cfg_read_raw_config()
        models = list(cfg.get("models", {}).keys())
        current = (
            getattr(getattr(cli, "agent", None), "model", None)
            or getattr(cli, "model", None)
            or "unknown"
        )
        if current and current not in models:
            models.insert(0, current)
        self._models = models
        self._current_model = current

        try:
            self.query_one("#mpo-current", Static).update(f"Current: {current}")
        except NoMatches:
            pass

        try:
            ol = self.query_one("#mpo-list", OptionList)
            ol.clear_options()
            for m in models:
                ol.add_option(Option(m, id=f"mpo-opt-{m}"))
            # Pre-select current
            if current in models:
                ol.highlighted = models.index(current)
        except NoMatches:
            pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        opt_id = event.option_id or ""
        if opt_id.startswith("mpo-opt-"):
            name = opt_id[len("mpo-opt-"):]
            self._select_model(name)

    def _select_model(self, name: str) -> None:
        try:
            from hermes_cli.tui.input_widget import HermesInput
            inp = self.app.query_one(HermesInput)
            inp.value = f"/model {name}"
            inp.action_submit()
        except (NoMatches, ImportError):
            pass
        try:
            self.app._flash_hint(f"  Model → {name}", 2.0)
        except Exception:
            pass
        _dismiss_overlay_and_focus_input(self)

    def action_dismiss(self) -> None:
        _dismiss_overlay_and_focus_input(self)


class SkinPickerOverlay(Widget):
    """Skin picker with live preview. Shown by /skin (bare); /skin <name> bypasses.

    Arrow navigation previews skins live. Escape reverts to original skin.
    Enter persists to display.skin in config.
    """

    DEFAULT_CSS = """
    SkinPickerOverlay {
        layer: overlay;
        dock: top;
        display: none;
        height: auto;
        max-height: 24;
        width: 1fr;
        max-width: 80;
        margin: 1 2;
        padding: 1 2;
        background: $surface;
        border: tall $primary 15%;
    }
    SkinPickerOverlay.--visible { display: block; }
    SkinPickerOverlay > #spo-header { color: $accent; }
    SkinPickerOverlay > #spo-current { color: $text-muted; }
    SkinPickerOverlay > #spo-list { height: auto; max-height: 18; }
    """

    BINDINGS = [Binding("escape", "dismiss", priority=True)]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._skins: list[str] = []
        self._original_skin: str = "default"
        self._original_css_vars: dict[str, str] = {}
        self._original_component_vars: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Static("  Skin", id="spo-header")
        yield Static("", id="spo-current")
        yield OptionList(id="spo-list")

    def refresh_data(self, cli: object) -> None:
        """Populate skin list, snapshot current skin, pre-select current."""
        cfg = _cfg_read_raw_config()
        current = cfg.get("display", {}).get("skin", "default")
        self._original_skin = current

        # Snapshot current theme vars for escape-revert
        tm = getattr(self.app, "_theme_manager", None)
        if tm is not None:
            self._original_css_vars = dict(getattr(tm, "_css_vars", {}))
            self._original_component_vars = dict(getattr(tm, "_component_vars", {}))

        # Discover skins
        skins_dir = _cfg_get_hermes_home() / "skins"
        names: list[str] = []
        if skins_dir.is_dir():
            names = sorted(
                p.stem for p in skins_dir.iterdir()
                if p.suffix in (".json", ".yaml", ".yml")
            )
        if "default" not in names:
            names.insert(0, "default")
        self._skins = names

        try:
            self.query_one("#spo-current", Static).update(f"Current: {current}")
        except NoMatches:
            pass

        try:
            ol = self.query_one("#spo-list", OptionList)
            ol.clear_options()
            for name in names:
                ol.add_option(Option(name, id=f"spo-opt-{name}"))
            if current in names:
                ol.highlighted = names.index(current)
        except NoMatches:
            pass

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """Live preview as user navigates with arrow keys."""
        event.stop()
        opt_id = event.option_id or ""
        if opt_id.startswith("spo-opt-"):
            name = opt_id[len("spo-opt-"):]
            self._apply_skin_preview(name)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        opt_id = event.option_id or ""
        if opt_id.startswith("spo-opt-"):
            name = opt_id[len("spo-opt-"):]
            self._confirm_skin(name)

    def _apply_skin_preview(self, name: str) -> None:
        try:
            if name == "default":
                self.app.apply_skin({})
                return
            skins_dir = _cfg_get_hermes_home() / "skins"
            skin_path = skins_dir / f"{name}.yaml"
            if not skin_path.exists():
                skin_path = skins_dir / f"{name}.json"
            if skin_path.exists():
                self.app.apply_skin(skin_path)
        except Exception:
            pass

    def _confirm_skin(self, name: str) -> None:
        # Persist to config
        try:
            cfg = _cfg_read_raw_config()
            _cfg_set_nested(cfg, "display.skin", name)
            _cfg_save_config(cfg)
        except Exception:
            pass
        try:
            self.app._flash_hint(f"  Skin → {name}", 2.0)
        except Exception:
            pass
        _dismiss_overlay_and_focus_input(self)

    def action_dismiss(self) -> None:
        """Revert to original skin on escape."""
        # C2: apply_skin() → ThemeManager.load_dict() pops "component_vars" and treats
        # all remaining keys as flat CSS variable overrides (_css_vars). The original
        # skin data is saved as separate _css_vars + _component_vars dicts so we must
        # merge them with the component_vars key preserved.
        combined = {**self._original_css_vars, "component_vars": self._original_component_vars}
        try:
            self.app.apply_skin(combined)
        except Exception:
            pass
        _dismiss_overlay_and_focus_input(self)
