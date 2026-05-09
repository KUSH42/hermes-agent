"""InputLegendBar — single-row legend strip above HermesInput.

Shows mode-specific affordance hints (bash, rev-search, completion, ghost text).
Controlled by show_legend(mode) / hide_legend() — safe to call from anywhere;
the widget may not be mounted in compact density mode.
"""
from __future__ import annotations

import logging
from typing import ClassVar

from rich.text import Text
from textual.widgets import Static

_log = logging.getLogger(__name__)

# Each entry: (key, desc) — key=None means plain dim label, key=str means bold+colored key.
_Entry = tuple[str | None, str | None]
_SEP = " [dim]·[/dim] "


class InputLegendBar(Static):
    """Single-row legend above HermesInput showing active input mode affordances."""

    DEFAULT_CSS = """
    InputLegendBar {
        display: none;
        height: 1;
        padding: 0 2;
        color: $text-muted 70%;
        background: $surface;
    }
    InputLegendBar.--visible { display: block; }
    """

    # (key | None, desc | None): key=None → dim label; key=str → bold-colored key + dim desc
    LEGEND_ENTRIES: ClassVar[dict[str, list[_Entry]]] = {
        "bash":       [(None, "shell mode"), ("Tab", "path"), ("Enter", "run"), ("⌃C", "clear")],
        "rev_search": [(None, "rev-search"), ("↑↓", "cycle"), ("Esc", "accept"), ("⌃G", "abort")],
        "completion": [(None, "@file"), ("Tab", "accept"), ("Enter", "accept"), ("Esc", "cancel")],
        "ghost":      [(None, "suggestion"), ("Tab", "accept"), ("→", "accept")],
        "locked":     [("⌃C", "interrupt")],
        "picker":     [("Enter", "run"), ("Tab", "paste"), ("?", "docs"), ("Esc", "cancel")],
    }

    def _key_color(self) -> str:
        try:
            v = self.app.get_css_variables() or {}
            return v.get("accent-interactive", v.get("primary", "#5f87d7"))
        except Exception:
            _log.debug("InputLegendBar: get_css_variables failed", exc_info=True)
            return "#5f87d7"

    def _build_markup(self, entries: list[_Entry]) -> str:
        k = self._key_color()
        parts: list[str] = []
        for key, desc in entries:
            if key is None:
                # plain dim label
                parts.append(f"[dim]{desc}[/dim]" if desc else "")
            elif desc is not None:
                parts.append(f"[bold {k}]{key}[/] [dim]{desc}[/dim]")
            else:
                parts.append(f"[bold {k}]{key}[/]")
        return _SEP.join(p for p in parts if p)

    def show_legend(self, mode: str) -> None:
        """Show the legend for the given mode key."""
        entries = self.LEGEND_ENTRIES.get(mode)
        if entries is not None:
            markup = self._build_markup(entries)
        else:
            markup = ""
        try:
            self.update(Text.from_markup(markup))
        except Exception:
            _log.debug("InputLegendBar markup parse failed for %r", markup, exc_info=True)
            self.update(markup)
        for cls in ("--legend-bash", "--legend-rev-search", "--legend-completion",
                    "--legend-ghost", "--legend-locked"):
            self.remove_class(cls)
        self.add_class(f"--legend-{mode.replace('_', '-')}")
        self.add_class("--visible")

    def hide_legend(self) -> None:
        """Hide the legend strip."""
        self.remove_class("--visible")
