"""InputLegendBar — single-row legend strip above HermesInput.

Shows mode-specific affordance hints (bash, rev-search, completion, ghost text).
Controlled by show_legend(mode) / hide_legend() — safe to call from anywhere;
the widget may not be mounted in compact density mode.
"""
from __future__ import annotations

from typing import ClassVar

from textual.widgets import Static


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

    LEGENDS: ClassVar[dict[str, str]] = {
        "bash":       "shell mode  ·  Tab=path  ·  Enter=run  ·  Ctrl+C=clear",
        "rev_search": "rev-search  ·  ↑↓=cycle  ·  Esc=accept  ·  Ctrl+G=abort",
        "completion": "@file  ·  Tab=accept  ·  Enter=accept  ·  Esc=cancel",
        "ghost":      "suggestion  ·  Tab=accept  ·  →=accept",
    }

    def show_legend(self, mode: str) -> None:
        """Show the legend for the given mode key."""
        text = self.LEGENDS.get(mode, "")
        self.update(text)
        self.add_class("--visible")

    def hide_legend(self) -> None:
        """Hide the legend strip."""
        self.remove_class("--visible")
