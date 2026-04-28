"""SkillPickerOverlay — two-pane modal for $skill invocation.

Trigger paths:
  1. Typing ``$`` at column 0 in InputMode.AGENT → overlay opens with filter
     initialised to whatever fragment followed the ``$``.
  2. ``Alt+$`` chord in InputMode.AGENT → overlay opens, empty filter,
     never auto-dismissed.

Enter dispatches the selected skill and closes.
Tab inserts ``$name `` into the input buffer and closes (no dispatch).
Esc cancels.
"""
from __future__ import annotations

import logging

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

_log = logging.getLogger(__name__)

# Source labels shown as group headers in the left pane.
_SOURCE_LABELS: dict[str, str] = {
    "hermes": "Hermes",
    "claude": "Claude Code",
    "plugin": "Plugins",
    "user": "User",
}


class SkillPickerOverlay(Widget):
    """Two-pane skill picker overlay.

    Mount via ``app._open_skill_picker(seed_filter, trigger_source)``.
    ``trigger_source`` is ``"prefix"`` (typed $) or ``"chord"`` (Alt+$).
    Prefix-triggered pickers are auto-dismissed when the input no longer
    matches ``_SKILL_RE``; chord-triggered pickers stay until Esc/Enter/Tab.
    """

    DEFAULT_CSS = """
    $pane-border: #333333;
    SkillPickerOverlay {
        layer: overlay;
        dock: bottom;
        height: 20;
        width: 1fr;
        background: $surface;
        border: tall $primary 20%;
        border-title-align: left;
        border-title-color: $accent;
    }
    SkillPickerOverlay > Horizontal {
        height: 1fr;
    }
    SkillPickerOverlay #picker-left {
        width: 1fr;
        min-width: 24;
        border-right: solid $pane-border;
    }
    SkillPickerOverlay #picker-filter {
        dock: top;
        width: 1fr;
    }
    SkillPickerOverlay #picker-list {
        height: 1fr;
        overflow-y: auto;
    }
    SkillPickerOverlay #picker-right {
        width: 2fr;
        padding: 0 1;
        overflow-y: auto;
    }
    SkillPickerOverlay #picker-footer {
        dock: bottom;
        height: 1;
        background: $surface-darken-1;
        color: $text-muted;
        padding: 0 1;
    }
    SkillPickerOverlay .picker-source-header {
        color: $accent;
        text-style: bold;
        padding: 0 1;
    }
    SkillPickerOverlay .picker-disabled {
        color: $text-muted;
    }
    SkillPickerOverlay .detail-section-header {
        color: $accent;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_picker", priority=True, show=False),
    ]

    def __init__(
        self,
        seed_filter: str = "",
        trigger_source: str = "prefix",
    ) -> None:
        super().__init__()
        self._filter: str = seed_filter
        self._trigger: str = trigger_source  # "prefix" or "chord"
        self._candidates: list = []  # list[SkillCandidate]

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Vertical(
                Input(
                    value=self._filter,
                    placeholder="Filter skills…",
                    id="picker-filter",
                ),
                OptionList(id="picker-list"),
                id="picker-left",
            ),
            ScrollableContainer(id="picker-right"),
        )
        yield Static(
            "[Enter] invoke · [Tab] insert · [?] open SKILL.md · [Esc] cancel",
            id="picker-footer",
        )

    def on_mount(self) -> None:
        self.border_title = "⚡ Skills  (Alt+$ to toggle)"
        self._load_candidates()
        self._rebuild_list()
        self._refresh_detail()
        try:
            self.query_one("#picker-filter", Input).focus()
        except NoMatches:
            pass

    def _load_candidates(self) -> None:
        """Pull SkillCandidates from HermesInput._skills if available."""
        try:
            from hermes_cli.tui.input_widget import HermesInput as _HI
            inp = self.app.query_one(_HI)
            self._candidates = list(getattr(inp, "_skills", []))
        except Exception:
            self._candidates = []
            _log.debug("Could not load skill candidates from HermesInput", exc_info=True)

    def _filtered_candidates(self) -> list:
        q = self._filter.lower()
        if not q:
            return list(self._candidates)
        return [
            c for c in self._candidates
            if q in c.name.lower() or q in c.description.lower()
        ]

    def _rebuild_list(self) -> None:
        try:
            option_list = self.query_one("#picker-list", OptionList)
        except NoMatches:
            return
        option_list.clear_options()
        filtered = self._filtered_candidates()
        if not filtered:
            q = self._filter or ""
            option_list.add_option(Option(f"no skills match '{q}'", disabled=True))
            return
        # Group by source
        seen_sources: set[str] = set()
        for candidate in sorted(filtered, key=lambda c: (c.source, c.name)):
            src = candidate.source
            if src not in seen_sources:
                seen_sources.add(src)
                label = _SOURCE_LABELS.get(src, src.title())
                option_list.add_option(Option(f"── {label} ──", disabled=True))
            disabled_badge = "  [dim](disabled)[/dim]" if not candidate.enabled else ""
            _desc = candidate.description[:40] if candidate.description else "—"
            option_list.add_option(
                Option(
                    f"${candidate.name}{disabled_badge}  [dim]{_desc}[/dim]",
                    id=candidate.name,
                )
            )

    def _refresh_detail(self) -> None:
        try:
            detail = self.query_one("#picker-right", ScrollableContainer)
        except NoMatches:
            return
        detail.remove_children()

        # Guard: if there are no filtered candidates at all, show empty state.
        filtered = self._filtered_candidates()
        if not filtered:
            if self._filter:
                msg = "[dim]No skills match your filter.[/dim]"
            else:
                msg = "[dim]No skills installed.[/dim]"
            detail.mount(Static(msg, classes="detail-empty", markup=True))
            return

        selected = self._selected_candidate()
        if selected is None:
            # F4: if all filtered candidates are disabled, show a specific message
            if all(not c.enabled for c in filtered):
                detail.mount(Static("[dim]All matching skills are disabled.[/dim]", classes="detail-empty", markup=True))
            else:
                detail.mount(Static("Select a skill to see details.", classes="detail-empty"))
            return
        widgets = []
        widgets.append(Static(f"[bold]${selected.name}[/bold]", classes="detail-section-header"))
        desc_text = selected.description or "[dim](no description)[/dim]"
        widgets.append(Static(desc_text, markup=True))
        if selected.trigger_phrases:
            widgets.append(Static("", classes="detail-spacer"))
            widgets.append(Static("TRIGGER when:", classes="detail-section-header"))
            for phrase in selected.trigger_phrases[:8]:
                widgets.append(Static(f"  • {phrase}"))
        if selected.do_not_trigger:
            widgets.append(Static("", classes="detail-spacer"))
            widgets.append(Static("DO NOT TRIGGER when:", classes="detail-section-header"))
            for phrase in selected.do_not_trigger[:6]:
                widgets.append(Static(f"  • {phrase}"))
        if not selected.enabled:
            widgets.append(Static("", classes="detail-spacer"))
            widgets.append(Static("[dim][d] Skill is disabled[/dim]"))
        if widgets:
            detail.mount(*widgets)

    def _selected_candidate(self):
        """Return the highlighted SkillCandidate, or None."""
        try:
            option_list = self.query_one("#picker-list", OptionList)
            if option_list.highlighted is None or option_list.highlighted < 0:
                return None
            highlighted_id = option_list.get_option_at_index(option_list.highlighted).id
            if not highlighted_id:
                return None
            for c in self._candidates:
                if c.name == highlighted_id:
                    return c
        except Exception:
            pass  # option list not yet rendered or highlighted index invalid; treat as no selection
        return None

    def set_filter(self, seed: str) -> None:
        """Update the filter and rebuild the list (called by _open_skill_picker for idempotency)."""
        self._filter = seed
        try:
            self.query_one("#picker-filter", Input).value = seed
        except NoMatches:
            pass
        self._rebuild_list()
        self._refresh_detail()

    # --- Event handlers ---

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "picker-filter":
            self._filter = event.value
            self._rebuild_list()
            self._refresh_detail()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._refresh_detail()

    def on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop()
            self._dispatch_selected()
        elif event.key == "tab":
            event.stop()
            self._insert_selected_fragment()
        elif event.key == "question_mark":
            event.stop()
            self._open_skill_md()

    def _dispatch_selected(self) -> None:
        """Enter: submit $name and close."""
        candidate = self._selected_candidate()
        if candidate is None:
            return
        self.dismiss()
        try:
            from hermes_cli.tui.input_widget import HermesInput as _HI
            inp = self.app.query_one(_HI)
            inp.focus()
            # Post the $name as a submitted message
            inp.value = f"${candidate.name}"
            inp.action_submit()
        except Exception:
            _log.debug("SkillPickerOverlay._dispatch_selected failed", exc_info=True)

    def _insert_selected_fragment(self) -> None:
        """Tab: replace $fragment in input with $name (trailing space), no dispatch."""
        candidate = self._selected_candidate()
        if candidate is None:
            return
        self.dismiss()
        try:
            from hermes_cli.tui.input_widget import HermesInput as _HI
            inp = self.app.query_one(_HI)
            inp.focus()
            value = inp.value
            # Replace everything from the leading $ to the first space/end
            if value.startswith("$"):
                # Find where the $fragment ends
                space_idx = value.find(" ")
                if space_idx == -1:
                    prefix = ""
                    suffix = ""
                else:
                    prefix = ""
                    suffix = value[space_idx:]
                inp.value = f"${candidate.name} {suffix}".rstrip(" ") + " "
            else:
                inp.value = f"${candidate.name} "
            inp.cursor_position = len(inp.value)
        except Exception:
            _log.debug("SkillPickerOverlay._insert_selected_fragment failed", exc_info=True)

    def _open_skill_md(self) -> None:
        """?: open the skill's SKILL.md in the workspace viewer or flash path."""
        candidate = self._selected_candidate()
        if candidate is None:
            return
        try:
            from hermes_cli.tui.input_widget import HermesInput as _HI
            from agent.skill_commands import get_skill_commands
            cmds = get_skill_commands()
            info = cmds.get(f"/{candidate.name}", {})
            path = info.get("skill_md_path", "")
            if path:
                self.app._flash_hint(f"SKILL.md: {path}", 4.0)
        except Exception:
            _log.debug("SkillPickerOverlay._open_skill_md failed", exc_info=True)

    def action_dismiss_picker(self) -> None:
        """Esc: dismiss without dispatch; input retains whatever fragment it had."""
        self.dismiss()
        try:
            from hermes_cli.tui.input_widget import HermesInput as _HI
            self.app.query_one(_HI).focus()
        except (NoMatches, Exception):
            pass
