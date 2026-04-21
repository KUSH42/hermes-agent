"""SearchRenderer — formats grep/search output with path headers and hit highlights."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, ClassVar

from hermes_cli.tui.body_renderers.base import BodyRenderer

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind, ClassificationResult, ToolPayload

_HIT_RE = re.compile(r"^(\s*)(\d+)[:\-]\s*(.*)")


def _parse_search_output(text: str) -> list[tuple[str, list[tuple[int, str]]]]:
    """Parse search output into [(path, [(line_num, content), ...]), ...]."""
    groups: list[tuple[str, list[tuple[int, str]]]] = []
    current_path: str | None = None
    current_hits: list[tuple[int, str]] = []

    for line in text.splitlines():
        # Check if line is a path header (no line number prefix)
        hit_m = _HIT_RE.match(line)
        if hit_m:
            line_num = int(hit_m.group(2))
            content = hit_m.group(3)
            if current_path is None:
                current_path = "<unknown>"
                current_hits = []
            current_hits.append((line_num, content))
        else:
            # Could be a file path separator
            stripped = line.strip()
            if stripped and not hit_m:
                # Flush current group
                if current_path is not None and current_hits:
                    groups.append((current_path, current_hits))
                current_path = stripped
                current_hits = []

    if current_path is not None and current_hits:
        groups.append((current_path, current_hits))

    return groups


class VirtualSearchList:
    """Placeholder for the VirtualSearchList widget — implemented as a proper Widget below."""
    pass


from textual.widget import Widget
from textual.strip import Strip


class VirtualSearchList(Widget):  # type: ignore[no-redef]
    """Virtual-scrolling search result list for large result sets (>100 hits).

    render_line(y) returns a Strip for the visible row at position y.
    j/k keys shift _scroll_offset by 1.
    """

    DEFAULT_CSS = "VirtualSearchList { height: auto; }"

    def __init__(self, lines_text: list[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self._lines_text: list[str] = lines_text
        self._scroll_offset: int = 0
        self._strips: list[Strip] = []

    def on_mount(self) -> None:
        from rich.text import Text
        from textual.strip import Strip
        from rich.segment import Segment

        self._strips = []
        for line in self._lines_text:
            t = Text.from_ansi(line)
            segs = list(t.render(self.app.console))
            self._strips.append(Strip(segs))

    def render_line(self, y: int) -> Strip:
        from textual.strip import Strip
        idx = y + self._scroll_offset
        if 0 <= idx < len(self._strips):
            return self._strips[idx]
        return Strip([])

    def on_key(self, event) -> None:
        key = getattr(event, "key", None)
        if key == "j":
            max_off = max(0, len(self._strips) - 1)
            self._scroll_offset = min(self._scroll_offset + 1, max_off)
            self.refresh()
        elif key == "k":
            self._scroll_offset = max(0, self._scroll_offset - 1)
            self.refresh()


class SearchRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = False

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        from hermes_cli.tui.tool_payload import ResultKind
        return cls_result.kind == ResultKind.SEARCH

    def build(self):
        """Build Rich Text with path headers and highlighted hits."""
        from rich.text import Text

        raw = self.payload.output_raw or ""
        query = self.cls_result.metadata.get("query") if self.cls_result.metadata else None
        groups = _parse_search_output(raw)

        result = Text()
        for i, (path, hits) in enumerate(groups):
            if i > 0:
                result.append("\n")

            # Path header: bold path right-padded, then right-aligned hit count
            n_matches = len(hits)
            match_str = f"{n_matches} matches"
            path_line = Text()
            path_line.append(path, style="bold")
            path_line.append("  ")
            path_line.append(match_str, style="dim")
            path_line.append("\n")
            result.append_text(path_line)

            for line_num, content in hits:
                line_t = Text()
                # Line number: 6-char right-aligned dim
                line_t.append(f"{line_num:>6}", style="dim")
                line_t.append(" │ ", style="dim")
                # Content with optional query highlight
                content_t = Text(content)
                if query:
                    try:
                        content_t.highlight_regex(re.escape(query), style="bold")
                    except re.error:
                        pass
                line_t.append_text(content_t)
                line_t.append("\n")
                result.append_text(line_t)

        return result

    def _build_lines_list(self) -> list[str]:
        """Build a flat list of formatted lines for VirtualSearchList."""
        raw = self.payload.output_raw or ""
        query = self.cls_result.metadata.get("query") if self.cls_result.metadata else None
        groups = _parse_search_output(raw)

        lines: list[str] = []
        for i, (path, hits) in enumerate(groups):
            if i > 0:
                lines.append("")
            n_matches = len(hits)
            lines.append(f"{path}  ({n_matches} matches)")
            for line_num, content in hits:
                lines.append(f"{line_num:>6} │ {content}")

        return lines

    def build_widget(self):
        """Return VirtualSearchList for >100 hits, else CopyableRichLog."""
        hit_count = 0
        if self.cls_result.metadata:
            hit_count = int(self.cls_result.metadata.get("hit_count", 0))

        if hit_count > 100:
            lines = self._build_lines_list()
            return VirtualSearchList(lines_text=lines)

        from hermes_cli.tui.widgets import CopyableRichLog
        rl = CopyableRichLog(highlight=False, markup=False)
        rl.write(self.build())
        return rl


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    SearchRenderer.kind = ResultKind.SEARCH


_set_kind()
