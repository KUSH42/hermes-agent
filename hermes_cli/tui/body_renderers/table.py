"""TableRenderer — pipe/tab delimited table renderer using rich.table.Table."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, ClassVar

from hermes_cli.tui.body_renderers.base import BodyRenderer

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload

_SEP_ROW_RE = re.compile(r"^[\s|:\-+]+$")


def _is_numeric(s: str) -> bool:
    """Return True if s looks like a number."""
    try:
        float(s.replace(",", "").replace("%", ""))
        return True
    except (ValueError, AttributeError):
        return False


def _detect_delimiter(lines: list[str]) -> str:
    """Detect whether pipe or tab is the primary delimiter."""
    pipe_count = sum(1 for l in lines if "|" in l)
    tab_count = sum(1 for l in lines if "\t" in l)
    return "|" if pipe_count >= tab_count else "\t"


def _split_row(line: str, delim: str) -> list[str]:
    """Split a row by delimiter, stripping outer pipes and whitespace."""
    if delim == "|":
        # Strip outer pipes
        stripped = line.strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        return [c.strip() for c in stripped.split("|")]
    else:
        return [c.strip() for c in line.split("\t")]


class TableRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = False

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        from hermes_cli.tui.tool_payload import ResultKind
        return cls_result.kind == ResultKind.TABLE

    def build(self):
        """Build a rich.table.Table from delimited output."""
        from rich.table import Table
        from rich import box

        raw = self.payload.output_raw or ""
        lines = [l for l in raw.splitlines() if l.strip()]

        if not lines:
            from rich.text import Text
            return Text("(empty table)")

        delim = _detect_delimiter(lines)
        table = Table(box=box.HORIZONTALS, show_header=False, padding=(0, 1))

        # Detect header row
        has_header = False
        data_start = 0
        if len(lines) >= 2:
            # Check if second row is a separator row (---|---)
            second = lines[1].strip()
            if _SEP_ROW_RE.match(second) or re.match(r"^[\-|+:]+$", second):
                has_header = True
                data_start = 2  # skip header and separator
            elif len(lines) >= 1:
                # Check if first row looks like headers (non-numeric)
                first_cols = _split_row(lines[0], delim)
                if first_cols and all(not _is_numeric(c) and c for c in first_cols):
                    has_header = True
                    data_start = 1

        # Get column count from header or first data row
        header_cols: list[str] = []
        if has_header:
            header_cols = _split_row(lines[0], delim)
            ncols = len(header_cols)
        else:
            ncols = len(_split_row(lines[0], delim)) if lines else 0

        if ncols == 0:
            from rich.text import Text
            return Text(raw)

        # Detect numeric columns from data rows
        data_rows = [_split_row(l, delim) for l in lines[data_start:]]
        numeric_cols: set[int] = set()
        for row in data_rows:
            for j, cell in enumerate(row):
                if j < ncols and _is_numeric(cell):
                    numeric_cols.add(j)

        # Build table columns
        table = Table(box=box.HORIZONTALS, padding=(0, 1))
        for j in range(ncols):
            justify = "right" if j in numeric_cols else "left"
            header = header_cols[j] if has_header and j < len(header_cols) else f"Col{j+1}"
            table.add_column(header, justify=justify)

        # Add data rows
        for row in data_rows:
            # Pad/trim to ncols
            padded = (row + [""] * ncols)[:ncols]
            table.add_row(*padded)

        return table


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    TableRenderer.kind = ResultKind.TABLE


_set_kind()
