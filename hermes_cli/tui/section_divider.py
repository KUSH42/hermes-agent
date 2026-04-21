"""SectionDivider — single-row decorative border line.

Renders ╭─ title ──── meta ──╮ (top edge) or ╰──────────────────╯ (bottom).
Used in Phase D of Tool Panel v3 to separate InputSection from BodyPane.
"""
from __future__ import annotations

from typing import Literal

from rich.segment import Segment
from rich.style import Style
from textual.strip import Strip
from textual.widget import Widget


class SectionDivider(Widget):
    """Single-row decorative divider line.

    Top edge:    ╭─ {title} ──── {meta} ──╮
    Bottom edge: ╰──────────────────────────╯
    """

    COMPONENT_CLASSES = {"section-divider--title", "section-divider--meta"}

    DEFAULT_CSS = "SectionDivider { height: 1; }"

    def __init__(
        self,
        title: str = "",
        meta: str = "",
        edge: Literal["top", "bottom"] = "top",
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._meta = meta
        self._edge = edge

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        if width <= 0:
            return Strip.blank(0)

        dim = Style.parse("dim")
        accent = Style.parse("bold")
        meta_style = Style.parse("dim")

        if self._edge == "bottom":
            fill = "─" * max(0, width - 2)
            line = f"╰{fill}╯"
            return Strip([Segment(line[:width], dim)])

        # Top edge: ╭─ {title} ──── {meta} ──╮
        # Structure: "╭─" (2) + title_part + fill + meta_part + "╮" (1)
        title_part = f" {self._title} " if self._title else " "
        meta_part = f" {self._meta} " if self._meta else ""

        # Fixed overhead: "╭─" (2) + title_part + "╮" (1) minimum
        min_overhead = 2 + len(title_part) + 1
        available_for_fill_and_meta = width - min_overhead

        if available_for_fill_and_meta < 0:
            # Very narrow: just ╭╮
            return Strip([Segment("╭" + "─" * max(0, width - 2) + "╯", dim)])

        # Check if meta fits
        if meta_part and len(meta_part) > available_for_fill_and_meta - 2:
            # Truncate meta to leave 2 chars for fill
            max_meta_len = available_for_fill_and_meta - 2
            if max_meta_len <= 3:
                meta_part = ""
            else:
                # trim: keep " " prefix, truncate content, add "… "
                inner = self._meta[: max_meta_len - 3]
                meta_part = f" {inner}… "

        fill_len = max(0, width - 2 - len(title_part) - len(meta_part) - 1)
        fill = "─" * fill_len

        segs: list[Segment] = [
            Segment("╭─", dim),
            Segment(title_part, accent),
            Segment(fill, dim),
        ]
        if meta_part:
            segs.append(Segment(meta_part, meta_style))
        segs.append(Segment("╮", dim))
        return Strip(segs)

    def set_title(self, title: str) -> None:
        self._title = title
        self.refresh()

    def set_meta(self, meta: str) -> None:
        self._meta = meta
        self.refresh()
