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
from textual.widgets import Button, ContentSwitcher, Input, Static


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
        try:
            self.query_one("#help-search", Input).focus()
        except NoMatches:
            pass

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
        self.remove_class("--visible")
        self.remove()

    def on_key(self, event: "object") -> None:
        key = getattr(event, "key", None)
        if key in ("escape", "question_mark"):
            self.hide_overlay()
            getattr(event, "stop", lambda: None)()
