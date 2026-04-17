"""DiffAffordance — ╰→ connector row inside FooterPane.

Reparented from loose sibling (D14) into FooterPane of the owning
Write/Edit/Patch block. Hidden by default; shown when set_diff() is called.

Architecture: tui-tool-panel-v3-spec.md §5.9
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class DiffAffordance(Widget):
    """Conditional connector row — only visible when diff metadata available."""

    DEFAULT_CSS = """
    DiffAffordance {
        layout: horizontal;
        height: 1;
        display: none;
    }
    DiffAffordance.-has-diff { display: block; }
    DiffAffordance > .connector { width: auto; color: $text-muted; }
    DiffAffordance > .label    { width: auto; color: $text-muted; }
    DiffAffordance > .added    { width: auto; color: $success; }
    DiffAffordance > .removed  { width: auto; color: $error; }
    DiffAffordance > .chevron  { width: auto; color: $text-muted; }
    """

    def compose(self) -> ComposeResult:
        yield Static("  ╰→ ", classes="connector")
        yield Static("diff", classes="label")
        yield Static("", classes="added")
        yield Static("", classes="removed")
        yield Static(" ▸", classes="chevron")

    def set_diff(self, added: int, removed: int) -> None:
        """Populate diff stats and show affordance."""
        self.query_one(".added").update(f"  +{added}" if added else "")
        self.query_one(".removed").update(f"  −{removed}" if removed else "")
        self.add_class("-has-diff")

    def clear_diff(self) -> None:
        """Hide and reset diff stats."""
        self.query_one(".added").update("")
        self.query_one(".removed").update("")
        self.remove_class("-has-diff")
