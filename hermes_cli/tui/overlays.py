"""Info overlay widgets for slash command TUI integration.

HelpOverlay, UsageOverlay, CommandsOverlay, ModelOverlay are all info overlays:
- layer: overlay; dock: top; display: none by default
- shown by adding --visible class, hidden by removing it
- dismiss with Esc/q; action_dismiss restores focus to HermesInput
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Input, Static


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
        Binding("q", "dismiss", priority=True),
    ]

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Filter commands...", id="help-search")
        yield Vertical(id="help-content")

    def on_mount(self) -> None:
        from hermes_cli.commands import COMMANDS_BY_CATEGORY
        self._commands_cache: list[tuple[str, str, str]] = [
            (cat, f"/{cmd}", desc)
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
        Binding("q", "dismiss", priority=True),
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
        Binding("q", "dismiss", priority=True),
    ]

    def compose(self) -> ComposeResult:
        yield Static("[bold]Commands[/bold]  (Esc / q to dismiss)", id="commands-title")
        yield Vertical(id="commands-content")

    def on_mount(self) -> None:
        self._refresh_content()

    def _refresh_content(self) -> None:
        from hermes_cli.commands import gateway_help_lines
        lines = gateway_help_lines()
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
    """Current model info display. Shown by /model (no args); dismissed with Esc/q."""

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
        Binding("q", "dismiss", priority=True),
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
    """Live session file-change summary. Shown by w / /workspace; dismissed with Esc/q."""

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
    WorkspaceOverlay #ws-scroll { height: auto; max-height: 16; overflow-y: auto; }
    WorkspaceOverlay .ws-file { color: $text; }
    WorkspaceOverlay .ws-file-dirty { color: $warning; }
    WorkspaceOverlay .ws-complexity { color: $warning; }
    WorkspaceOverlay .ws-added { color: $success; }
    WorkspaceOverlay .ws-removed { color: $error; }
    """

    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        Binding("q", "dismiss", priority=True),
    ]

    def compose(self) -> ComposeResult:
        yield Static("", id="ws-header")
        yield Static("", id="ws-summary")
        with ScrollableContainer(id="ws-scroll"):
            yield Vertical(id="ws-files")
            yield Vertical(id="ws-complexity")
        yield Static("[dim]w / esc to close[/dim]", id="ws-footer")

    def show_overlay(self) -> None:
        self.add_class("--visible")

    def action_dismiss(self) -> None:
        self.remove_class("--visible")
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass

    def refresh_data(self, tracker: object, snapshot: object | None) -> None:
        """Rebuild header, summary, and file list from tracker + optional snapshot.

        tracker: WorkspaceTracker instance
        snapshot: GitSnapshot | None — None before first git poll completes
        """
        from hermes_cli.tui.workspace_tracker import GitSnapshot

        try:
            header_widget = self.query_one("#ws-header", Static)
            summary_widget = self.query_one("#ws-summary", Static)
            files_widget = self.query_one("#ws-files", Vertical)
            complexity_widget = self.query_one("#ws-complexity", Vertical)
        except NoMatches:
            return

        # Header
        if snapshot is not None and isinstance(snapshot, GitSnapshot):
            dirty_chip = f" ● {snapshot.dirty_count} dirty" if snapshot.dirty_count else ""
            header_widget.update(
                f"[bold]Workspace[/bold]  [dim]{snapshot.branch}[/dim]{dirty_chip}"
            )
        else:
            header_widget.update("[bold]Workspace[/bold]")

        # Summary row
        added, removed = tracker.session_totals()
        counts = tracker.counts_by_status()
        modified = counts.get("M", 0)
        new_files = counts.get("A", 0) + counts.get("?", 0)
        deleted = counts.get("D", 0)
        summary_widget.update(
            f"Session  [green]+{added}[/green] [red]-{removed}[/red]"
            f"  ·  {modified} modified  ·  {new_files} new  ·  {deleted} deleted"
        )

        # File rows
        entries = tracker.entries()
        files_widget.remove_children()
        file_children: list[Static] = []
        for e in entries:
            if e.git_staged:
                indicator = "○"
            elif e.git_status not in (" ", ""):
                indicator = "●"
            else:
                indicator = " "
            staged_note = " staged" if e.git_staged else ""
            css_class = "ws-file-dirty" if indicator == "●" else "ws-file"
            line = (
                f"[bold]{e.git_status or ' '}[/bold]  {e.rel_path or e.path}"
                f"  [green]+{e.session_added}[/green] [red]-{e.session_removed}[/red]"
                f"   {indicator}{staged_note}"
            )
            file_children.append(Static(line, classes=css_class))
        if file_children:
            files_widget.mount(*file_children)

        # Complexity rows
        complexity_widget.remove_children()
        warnings = [
            (e.rel_path or e.path, e.complexity_warning)
            for e in entries if e.complexity_warning
        ]
        if warnings:
            complexity_widget.mount(Static(""))  # blank separator
            for rel, warn in warnings:
                complexity_widget.mount(Static(f"⚠  {rel}  ·  {warn}", classes="ws-complexity"))


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
