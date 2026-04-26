"""TableRenderer — pipe/tab delimited table renderer using rich.table.Table."""
from __future__ import annotations

import re
from collections import Counter
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
        stripped = line.strip()
        if stripped.startswith("|"):
            stripped = stripped[1:]
        if stripped.endswith("|"):
            stripped = stripped[:-1]
        return [c.strip() for c in stripped.split("|")]
    else:
        return [c.strip() for c in line.split("\t")]


def _looks_like_table(lines: list[str], delim: str) -> bool:
    """Return True when ≥70% of lines share the modal column count and ncols ≥ 2."""
    if not lines:
        return False
    col_counts = [len(_split_row(l, delim)) for l in lines]
    most_common = Counter(col_counts).most_common(1)
    if not most_common:
        return False
    mode_count, mode_freq = most_common[0]
    ratio = mode_freq / len(lines)
    return ratio >= 0.7 and mode_count >= 2


def _column_numeric_stats(rows: list[list[str]], j: int) -> tuple[int, int, bool]:
    """Return (numeric_count, non_numeric_count, is_numeric_col)."""
    num = nonnum = 0
    for r in rows:
        if j >= len(r):
            continue
        cell = r[j].strip()
        if not cell:
            continue
        if _is_numeric(cell):
            num += 1
        else:
            nonnum += 1
    total = num + nonnum
    is_numeric_col = (num / total >= 0.8) if total > 0 else False
    return num, nonnum, is_numeric_col


class TableRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = False

    @classmethod
    def accepts(cls, phase: "ToolCallState", density: "DensityTier") -> bool:
        from hermes_cli.tui.tool_panel.density import DensityTier as _DT
        if density == _DT.COMPACT:
            return False
        return super().accepts(phase, density)

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        from hermes_cli.tui.tool_payload import ResultKind
        return cls_result.kind == ResultKind.TABLE

    def build(self):
        """Build a rich.table.Table from delimited output."""
        from rich.table import Table
        from rich import box
        from rich.text import Text
        from rich.style import Style

        raw = self.payload.output_raw or ""
        lines = [l for l in raw.splitlines() if l.strip()]

        if not lines:
            self._row_count = 0
            self._col_count = 0
            return Text("(empty table)")

        delim = _detect_delimiter(lines)

        if not _looks_like_table(lines, delim):
            self._row_count = 0
            self._col_count = 0
            from hermes_cli.tui.body_renderers.fallback import FallbackRenderer
            return FallbackRenderer(self.payload, self.cls_result, app=self._app).build()

        # Detect header row
        has_header = False
        data_start = 0
        if len(lines) >= 2:
            second = lines[1].strip()
            if _SEP_ROW_RE.match(second) or re.match(r"^[\-|+:]+$", second):
                has_header = True
                data_start = 2
            elif len(lines) >= 1:
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
            self._row_count = 0
            self._col_count = 0
            return Text(raw)

        data_rows = [_split_row(l, delim) for l in lines[data_start:]]

        # Proportional numeric detection per column
        numeric_cols: set[int] = set()
        for j in range(ncols):
            _, _, is_num = _column_numeric_stats(data_rows, j)
            if is_num:
                numeric_cols.add(j)

        # Build table columns; no fake "ColN" headers when has_header is False
        table = Table(box=box.HORIZONTALS, show_header=has_header, padding=(0, 1))
        for j in range(ncols):
            justify = "right" if j in numeric_cols else "left"
            if has_header:
                header = header_cols[j] if j < len(header_cols) else ""
                table.add_column(header, justify=justify)
            else:
                table.add_column(justify=justify)

        colors = self.colors
        for row in data_rows:
            padded = (row + [""] * ncols)[:ncols]
            styled = []
            for j, cell in enumerate(padded):
                if j in numeric_cols and cell.strip() and not _is_numeric(cell):
                    styled.append(Text(cell, style=Style(color=colors.muted)))
                else:
                    styled.append(cell)
            table.add_row(*styled)

        self._row_count = len(data_rows)
        self._col_count = ncols
        return table

    def build_widget(self, density=None):
        from hermes_cli.tui.body_renderers._grammar import build_rule, BodyFooter
        from hermes_cli.tui.body_renderers._frame import BodyFrame

        renderable = self.build()
        rows = getattr(self, "_row_count", 0)
        cols = getattr(self, "_col_count", 0)
        return BodyFrame(
            header=build_rule(f"{rows} rows · {cols} cols", colors=self.colors),
            body=renderable,
            footer=BodyFooter(("y", "copy"), ("c", "csv")),
            density=density,
        )


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    TableRenderer.kind = ResultKind.TABLE


_set_kind()
