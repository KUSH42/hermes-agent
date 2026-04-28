"""Reference modal overlays for R3 Phase C pane-fallback migration.

ReferenceModal is a shared base class for the 4 "reference" overlays:
  HelpOverlay, UsageOverlay, CommandsOverlay, WorkspaceOverlay

All use the --visible toggle pattern (no ModalScreen switch).
When R2's PaneManager lands, subclasses flip to pane targets; external API
(show_overlay, hide_overlay, action_dismiss, class names, IDs) is unchanged.
"""

from __future__ import annotations

import logging

from textual import events

_log = logging.getLogger(__name__)
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Button, ContentSwitcher, Input, Static
from textual.widgets.option_list import Option


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class ReferenceModal(Widget):
    """Base class for all reference modal overlays.

    Subclasses declare:
        _modal_id: str        — CSS id (also used as the Widget id at mount time)
        _modal_title: str     — border-title text shown on show_overlay()

    Shared behaviour:
        show_overlay()        — add --visible + set border_title + optional focus
        hide_overlay()        — remove --visible
        action_dismiss()      — hide_overlay() + restore HermesInput focus
    """

    _modal_id: str = ""
    _modal_title: str = ""

    DEFAULT_CSS = """
    ReferenceModal {
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
        border-title-align: left;
        border-title-color: $accent;
        border-subtitle-align: right;
        border-subtitle-color: $text-muted;
    }
    ReferenceModal.--visible { display: block; }
    """

    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
    ]

    def on_mount(self) -> None:
        self.add_class("--modal")
        if self._modal_title and self.is_mounted:
            self.border_title = self._modal_title

    def show_overlay(self) -> None:
        if self._modal_title:
            self.border_title = self._modal_title
        self.add_class("--visible")

    def hide_overlay(self) -> None:
        self.remove_class("--visible", "--modal")

    def action_dismiss(self) -> None:
        self.hide_overlay()
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass


# ---------------------------------------------------------------------------
# HelpOverlay
# ---------------------------------------------------------------------------

class HelpOverlay(ReferenceModal):
    """Slash command reference. Shown by /help; dismissed with Esc/q."""

    _modal_id = "help-overlay"
    _modal_title = "Commands"

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
        border-title-align: left;
        border-title-color: $accent;
        border-subtitle-align: right;
        border-subtitle-color: $text-muted;
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
        self.border_title = self._modal_title
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


# ---------------------------------------------------------------------------
# UsageOverlay
# ---------------------------------------------------------------------------

class UsageOverlay(ReferenceModal):
    """Token usage and rate limit display. Shown by /usage; dismissed with Esc/q."""

    _modal_id = "usage-overlay"
    _modal_title = "Token Usage"

    DEFAULT_CSS = """
    UsageOverlay {
        layer: overlay;
        dock: top;
        display: none;
        height: auto;
        max-height: 26;
        width: 1fr;
        max-width: 60;
        margin: 1 2;
        padding: 1 2;
        background: $surface;
        border: tall $primary 15%;
        border-title-align: left;
        border-title-color: $accent;
        border-subtitle-align: right;
        border-subtitle-color: $text-muted;
    }
    UsageOverlay.--visible { display: block; }
    """

    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        # q removed: UsageOverlay does not capture focus (HermesInput retains it).
        # With priority=True, q would insert into HermesInput instead of dismissing.
        # Dismiss via Escape (handled by on_key Priority -2 in HermesApp).
        # c copy: handled in _app_key_handler.py on_key, gated on --visible — same
        # pattern as Escape dismissal.  overlay-level on_key never fires while
        # HermesInput holds focus.
    ]

    _BAR_WIDTH: int = 30

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._last_plain_text: str = ""

    def compose(self) -> ComposeResult:
        yield Static(id="usage-content")

    # ------------------------------------------------------------------
    # Chart / stats helpers
    # ------------------------------------------------------------------

    def _build_chart(self, inp: int, cr: int, cw: int, out: int) -> str:
        """Return Rich-markup horizontal bar chart section, or no-data note."""
        total = inp + cr + cw + out
        if total == 0:
            return "  (no token data yet)"
        buckets = [
            ("Input      ", inp),
            ("Cache Read ", cr),
            ("Cache Write", cw),
            ("Output     ", out),
        ]
        header = "[dim]── Token Breakdown " + "─" * 35 + "[/dim]"
        rows = [header]
        for label, count in buckets:
            if count == 0:
                continue
            pct = count / total * 100
            filled = round(pct / 100 * self._BAR_WIDTH)
            filled = max(0, min(self._BAR_WIDTH, filled))
            bar = "█" * filled + " " * (self._BAR_WIDTH - filled)
            rows.append(f"{label} {bar} {count:,} ({pct:.0f}%)")
        return "\n".join(rows)

    def _build_sparkline(self, turn_log: list[int]) -> str:
        """Return sparkline line or empty string if fewer than 1 entry."""
        SPARKS = "▁▂▃▄▅▆▇█"
        n = len(turn_log)
        if n == 0:
            return ""
        window = turn_log[-40:]  # cap at 40 entries
        wn = len(window)
        if wn == 1:
            return "Context growth: █ (1 call)"
        lo, hi = min(window), max(window)

        def _spark(v: int) -> str:
            if hi == lo:
                return "█"
            idx = int((v - lo) / (hi - lo) * 7)
            return SPARKS[min(7, idx)]

        chars = "".join(_spark(v) for v in window)
        return f"Context growth: {chars} ({n} calls)"

    def _build_stats(
        self,
        inp: int,
        cr: int,
        cw: int,
        out: int,
        total: int,
        calls: int,
        cost_result: object,
        compressor: object | None,
        agent: object,
    ) -> str:
        """Return numeric stats block as a Rich-markup string."""
        last_prompt = getattr(compressor, "last_prompt_tokens", 0) if compressor else 0
        ctx_len = getattr(compressor, "context_length", 0) if compressor else 0
        pct = min(100, last_prompt / ctx_len * 100) if ctx_len else 0
        compressions = getattr(compressor, "compression_count", 0) if compressor else 0
        model = getattr(agent, "model", "unknown")

        lines = [
            f"[bold]Model:[/bold] {model}",
            "",
            f"Input:        {inp:>12,}",
            f"Cache Read:   {cr:>12,}",
            f"Cache Write:  {cw:>12,}",
            f"Output:       {out:>12,}",
            f"Total tokens: {total:>12,}",
            f"API calls:    {calls:>12,}",
        ]

        if getattr(cost_result, "amount_usd", None) is not None:
            prefix = "~" if getattr(cost_result, "status", "") == "estimated" else ""
            lines.append(f"Cost:        {prefix}${float(cost_result.amount_usd):>10.4f}")
        elif getattr(cost_result, "status", "") == "included":
            lines.append("Cost:         included")

        rl_state = None
        if hasattr(agent, "get_rate_limit_state"):
            try:
                rl_state = agent.get_rate_limit_state()
            except Exception:
                _log.debug("get_rate_limit_state failed; omitting rate-limit row", exc_info=True)
        if rl_state and getattr(rl_state, "has_data", False):
            from agent.rate_limit_tracker import format_rate_limit_display
            lines.append("")
            lines.append(format_rate_limit_display(rl_state))

        lines += [
            "",
            f"Context: {last_prompt:,} / {ctx_len:,} ({pct:.0f}%)",
            f"Compressions: {compressions}",
        ]
        return "\n".join(lines)

    def _build_plain_text(
        self,
        inp: int,
        cr: int,
        cw: int,
        out: int,
        total: int,
        calls: int,
        cost_result: object,
        compressor: object | None,
        agent: object,
        turn_log: list[int],
    ) -> str:
        """Plain-text copy (no Rich markup, no bar chart rows)."""
        last_prompt = getattr(compressor, "last_prompt_tokens", 0) if compressor else 0
        ctx_len = getattr(compressor, "context_length", 0) if compressor else 0
        pct = min(100, last_prompt / ctx_len * 100) if ctx_len else 0
        compressions = getattr(compressor, "compression_count", 0) if compressor else 0
        model = getattr(agent, "model", "unknown")

        lines = [
            f"Model: {model}",
            f"Input:        {inp:>12,}",
            f"Cache Read:   {cr:>12,}",
            f"Cache Write:  {cw:>12,}",
            f"Output:       {out:>12,}",
            f"Total tokens: {total:>12,}",
            f"API calls:    {calls:>12,}",
        ]

        if getattr(cost_result, "amount_usd", None) is not None:
            prefix = "~" if getattr(cost_result, "status", "") == "estimated" else ""
            lines.append(f"Cost:        {prefix}${float(cost_result.amount_usd):>10.4f}")
        elif getattr(cost_result, "status", "") == "included":
            lines.append("Cost:         included")

        lines += [
            f"Context:      {last_prompt:,} / {ctx_len:,} ({pct:.0f}%)",
            f"Compressions: {compressions}",
        ]

        # Sparkline text IS included in plain-text copy (sparkline chars copy cleanly)
        sparkline = self._build_sparkline(turn_log)
        if sparkline:
            lines.append(sparkline)

        return "\n".join(lines)

    def _do_copy(self) -> None:
        """Copy last-rendered plain-text stats to clipboard via app helper."""
        try:
            self.app._copy_text_with_hint(self._last_plain_text)  # type: ignore[attr-defined]
        except Exception as exc:
            try:
                self.app.set_status_error(f"copy failed: {exc}")  # type: ignore[attr-defined]
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Main refresh
    # ------------------------------------------------------------------

    def show_usage(self) -> None:
        """Set border title and show the overlay."""
        self.border_title = self._modal_title
        self.add_class("--visible")

    # Keep show_overlay() as alias for consistency with ReferenceModal API
    def show_overlay(self) -> None:  # type: ignore[override]
        self.show_usage()

    def refresh_data(self, agent: object) -> None:
        """Pull current usage from agent, rebuild chart + stats, update Static."""
        from agent.usage_pricing import CanonicalUsage, estimate_usage_cost

        input_tokens = getattr(agent, "session_input_tokens", 0) or 0
        output_tokens = getattr(agent, "session_output_tokens", 0) or 0
        cache_read = getattr(agent, "session_cache_read_tokens", 0) or 0
        cache_write = getattr(agent, "session_cache_write_tokens", 0) or 0
        total = getattr(agent, "session_total_tokens", 0) or 0
        calls = getattr(agent, "session_api_calls", 0) or 0

        # Defensive read of turn log — absent on old agents (graceful degradation)
        turn_log: list[int] = list(getattr(agent, "session_turn_token_log", []))

        compressor = getattr(agent, "context_compressor", None)

        cost_result = estimate_usage_cost(
            getattr(agent, "model", "unknown"),
            CanonicalUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read,
                cache_write_tokens=cache_write,
            ),
            provider=getattr(agent, "provider", None),
            base_url=getattr(agent, "base_url", None),
        )

        chart_section = self._build_chart(input_tokens, cache_read, cache_write, output_tokens)
        stats_section = self._build_stats(
            input_tokens, cache_read, cache_write, output_tokens,
            total, calls, cost_result, compressor, agent,
        )
        sparkline = self._build_sparkline(turn_log)
        hint_line = "[dim]c copy · Esc dismiss[/dim]"

        parts = [chart_section, "", stats_section]
        if sparkline:
            parts.append(sparkline)
        parts.append(hint_line)
        content = "\n".join(parts)

        try:
            self.query_one("#usage-content", Static).update(content)
        except NoMatches:
            pass

        self._last_plain_text = self._build_plain_text(
            input_tokens, cache_read, cache_write, output_tokens,
            total, calls, cost_result, compressor, agent, turn_log,
        )

    def action_dismiss(self) -> None:
        self.remove_class("--visible")
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass


# ---------------------------------------------------------------------------
# CommandsOverlay
# ---------------------------------------------------------------------------

class CommandsOverlay(ReferenceModal):
    """Full command + skill + plugin browse. Shown by /commands; dismissed with Esc/q."""

    _modal_id = "commands-overlay"
    _modal_title = "Commands"

    DEFAULT_CSS = """
    CommandsOverlay {
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
        border-title-align: left;
        border-title-color: $accent;
        border-subtitle-align: right;
        border-subtitle-color: $text-muted;
    }
    CommandsOverlay.--visible { display: block; }
    CommandsOverlay > #commands-search {
        height: 1;
        margin-bottom: 1;
    }
    CommandsOverlay > #commands-content {
        height: auto;
        max-height: 24;
        overflow-y: auto;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        # priority=False: when #commands-search Input has focus, q inserts normally.
        # When the overlay itself has focus, q fires dismiss.
        Binding("q", "dismiss", priority=False),
    ]

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Filter commands...", id="commands-search")
        yield Vertical(id="commands-content")

    def on_mount(self) -> None:
        self._lines_cache: list[str] = []
        self._refresh_content()

    def _refresh_content(self) -> None:
        from hermes_cli.commands import tui_help_lines
        self._lines_cache = tui_help_lines()
        self._populate(self._lines_cache)

    def _populate(self, lines: list[str]) -> None:
        """Rebuild content list with a single batched mount."""
        try:
            container = self.query_one("#commands-content", Vertical)
        except NoMatches:
            return
        container.remove_children()
        children = [Static(line) for line in lines] if lines else [Static("(no commands available)")]
        container.mount(*children)

    def show_overlay(self) -> None:
        """Show overlay and focus the filter input."""
        self.border_title = self._modal_title
        self.add_class("--visible")
        try:
            inp = self.query_one("#commands-search", Input)
            inp.value = ""
            inp.focus()
        except NoMatches:
            pass
        self._populate(self._lines_cache)

    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.lower().strip()
        if not query:
            self._populate(self._lines_cache)
            return
        filtered = [line for line in self._lines_cache if query in line.lower()]
        self._populate(filtered)

    def action_dismiss(self) -> None:
        self.remove_class("--visible")
        try:
            from hermes_cli.tui.input_widget import HermesInput
            self.app.query_one(HermesInput).focus()
        except (NoMatches, ImportError):
            pass


# ---------------------------------------------------------------------------
# WorkspaceOverlay
# ---------------------------------------------------------------------------

class WorkspaceOverlay(ReferenceModal):
    """Live working-tree summary. Shown by w / /workspace; dismissed with Esc/q."""

    _modal_id = "workspace-overlay"
    _modal_title = "Workspace"

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
        border-title-align: left;
        border-title-color: $accent;
        border-subtitle-align: right;
        border-subtitle-color: $text-muted;
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
        with ContentSwitcher(initial="ws-git-pane", id="ws-switcher"):
            with Vertical(id="ws-git-pane"):
                yield Static("", id="ws-header")
                yield Static("", id="ws-summary")
                with ScrollableContainer(id="ws-scroll"):
                    yield Vertical(id="ws-files")
                    yield Vertical(id="ws-complexity")
        yield Static("[dim]w / esc to close[/dim]", id="ws-footer")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id == "ws-tab-git":
            event.stop()
            self._switch_tab("ws-git-pane")

    def _switch_tab(self, pane_id: str) -> None:
        try:
            sw = self.query_one("#ws-switcher", ContentSwitcher)
            sw.current = pane_id
        except Exception:
            _log.debug("workspace tab switch to %r failed", pane_id, exc_info=True)
        # Update tab button active class
        try:
            git_btn = self.query_one("#ws-tab-git", Button)
            git_btn.add_class("--tab-active")
        except Exception:
            pass  # tab button not yet in DOM or already removed; styling update is best-effort

    def show_overlay(self) -> None:
        self.border_title = self._modal_title
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
