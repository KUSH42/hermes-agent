"""ResultPill widget — conditional kind indicator in ToolHeaderBar (§5.3).

Not mounted when kind == TEXT (avoids visual clutter for plain text output).
set_kind() transitions via add/remove class — never remounted.
"""
from __future__ import annotations

from textual.widgets import Static

from hermes_cli.tui.tool_payload import ResultKind

PILL_LABELS: dict[ResultKind, str] = {
    ResultKind.CODE:   "code",
    ResultKind.DIFF:   "diff",
    ResultKind.SEARCH: "search",
    ResultKind.LOG:    "log",
    ResultKind.JSON:   "json",
    ResultKind.TABLE:  "table",
    ResultKind.BINARY: "bin",
    ResultKind.EMPTY:  "empty",
}

# TEXT is intentionally absent — ResultPill is hidden for TEXT kind.


class ResultPill(Static):
    """Kind chip; display:none by default; shown when kind != TEXT."""

    DEFAULT_CSS = """
    ResultPill {
        width: auto;
        height: 1;
        padding: 0 1;
        text-style: bold;
        display: none;
    }
    ResultPill.-code   { background: $accent 20%;          color: $accent; }
    ResultPill.-diff   { background: $warning 20%;         color: $warning; }
    ResultPill.-search { background: $primary 20%;         color: $primary; }
    ResultPill.-log    { background: $surface-lighten-1;   color: $text-muted; }
    ResultPill.-json   { background: $accent 15%;          color: $accent; }
    ResultPill.-table  { background: $primary 15%;         color: $primary; }
    ResultPill.-binary { background: $error 20%;           color: $error; }
    ResultPill.-empty  { background: $surface-lighten-1;   color: $text-muted; }
    """

    def set_kind(self, kind: ResultKind) -> None:
        """Transition to new kind: remove old class, add new, update label."""
        for k in ResultKind:
            self.remove_class(f"-{k.value}")
        if kind == ResultKind.TEXT:
            self.display = False
            return
        self.add_class(f"-{kind.value}")
        self.update(PILL_LABELS[kind])
        self.display = True
