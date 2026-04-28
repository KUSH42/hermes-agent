"""SearchRenderer — formats grep/search output with path headers and hit highlights.

R-Sr1: hit vs context line distinction
R-Sr2: grammar path header (▸ path · N hits)
R-Sr3: unified 4-tuple line model + query highlight at build time
R-Sr4: full keyboard nav, Enter-to-open, scrollbar, footer
R-Sr5: sticky group header past 100 hits
"""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

import json
import os
import re
import shlex
from typing import TYPE_CHECKING, ClassVar

from rich.text import Text

from textual.app import ComposeResult
from textual.binding import Binding
from textual.strip import Strip
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.body_renderers._grammar import (
    SkinColors,
    build_gutter_line_num,
    build_path_header,
    build_rule,
    glyph,
)
from hermes_cli.tui.body_renderers.base import BodyRenderer
from hermes_cli.tui.io_boundary import safe_edit_cmd

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ClassificationResult, ToolPayload

# ---------------------------------------------------------------------------
# Parse regexes — R-Sr1: separate hit (:) from context (-) lines
# ---------------------------------------------------------------------------

_HIT_RE     = re.compile(r"^(\s*)(\d+)[:]\s*(.*)")
_CONTEXT_RE = re.compile(r"^(\s*)(\d+)[\-]\s*(.*)")

_LINK_COLOR_FALLBACK = "#7fa8d8"


# ---------------------------------------------------------------------------
# Query highlight helper — R-Sr3
# ---------------------------------------------------------------------------

def _ansi_highlight(text: str, query: str) -> str:
    """Bold-highlight all occurrences of query in text via ANSI escapes.

    Assumes input contains no prior ANSI escape sequences. If syntax
    highlighting is later added to search lines, replace with Rich
    Text.assemble() approach to avoid mangling existing escapes.
    """
    if not query or not query.strip():
        return text
    try:
        return re.sub(
            re.escape(query),
            lambda m: f"\x1b[1m{m.group(0)}\x1b[0m",
            text,
            flags=re.IGNORECASE,
        )
    except re.error:  # noqa: bare-except
        return text  # re.escape() should never produce invalid regex; defensive fallback


# ---------------------------------------------------------------------------
# Parse functions — R-Sr1: inner tuples are (line_num, content, is_hit)
# ---------------------------------------------------------------------------

def _build_web_hit_text(
    title: "str | None",
    url: "str | None",
    desc: "str | None",
    link_color: str = _LINK_COLOR_FALLBACK,
) -> "Text":
    """Build a styled Rich Text for a single web/extract result item.

    Layout: [title]  [url underlined link-color]  [description dim]
    """
    from rich.text import Text as _Text
    t = _Text()
    if title:
        t.append(str(title))
    if url:
        if t.plain:
            t.append("  ", style="dim")
        t.append(str(url), style=f"underline {link_color}")
    if desc:
        if t.plain:
            t.append("  ")
        elif url:
            t.append("  ", style="dim")
        t.append(str(desc), style="dim")
    return t


def _parse_web_hit(item: dict, idx: int, link_color: str = _LINK_COLOR_FALLBACK) -> "tuple[int, object, bool]":
    """Convert a single web/news item dict into a (line_num, styled_Text, is_hit) tuple."""
    title = item.get("title")
    url = item.get("url")
    desc = item.get("description") or item.get("snippet")
    desc_s = str(desc)[:180] if desc else None
    return (idx, _build_web_hit_text(title, url, desc_s, link_color), True)


def _parse_extract_hit(item: dict, idx: int, link_color: str = _LINK_COLOR_FALLBACK) -> "tuple[int, object, bool]":
    """Convert a single extract result dict into a (line_num, styled_Text, is_hit) tuple."""
    title = item.get("title")
    url = item.get("url")
    raw_content = item.get("content")
    desc_s: "str | None" = None
    if raw_content:
        lines = str(raw_content).splitlines()
        desc_s = (lines[0] if lines else str(raw_content))[:180]
    return (idx, _build_web_hit_text(title, url, desc_s, link_color), True)


def _parse_search_json(
    text: str,
) -> "list[tuple[str, list[tuple[int, str, bool]]]] | None":
    """Parse JSON search output into groups.

    Handles:
    - {matches:[{path,line,content}]} — rg-style
    - {data:{web:[...]}} or {data:{news:[...]}} — web/news search
    - {results:[{url,title,content}]} — extraction results
    """
    s = text.lstrip()
    if not s or s[0] != "{":
        return None
    try:
        data = json.loads(text)
    except (ValueError, MemoryError):  # noqa: bare-except
        return None
    if not isinstance(data, dict):
        return None

    # rg-style search: {matches:[{path,line,content}]}
    matches = data.get("matches")
    if isinstance(matches, list):
        by_path: dict[str, list[tuple[int, str, bool]]] = {}
        order: list[str] = []
        for m in matches:
            if not isinstance(m, dict):
                continue
            path = m.get("path") or m.get("file") or "<unknown>"
            path = str(path)
            line_no = m.get("line") or m.get("line_number") or 0
            try:
                line_no = int(line_no)
            except (TypeError, ValueError):  # noqa: bare-except
                line_no = 0
            content = str(m.get("content") or m.get("text") or "").rstrip("\n")
            # JSON "type":"context" marks surrounding lines; everything else is a hit
            is_hit = m.get("type", "match") != "context"
            if path not in by_path:
                by_path[path] = []
                order.append(path)
            by_path[path].append((line_no, content, is_hit))
        return [(p, by_path[p]) for p in order]

    # Web/news search: {data:{web:[...]} or data:{news:[...]}}
    data_inner = data.get("data")
    if isinstance(data_inner, dict):
        for source_key, group_name in (("web", "web results"), ("news", "news results")):
            items = data_inner.get(source_key)
            if isinstance(items, list):
                hits = [
                    _parse_web_hit(item, i)
                    for i, item in enumerate(items, 1)
                    if isinstance(item, dict)
                ]
                return [(group_name, hits)]

    # Extraction results: {results:[{url,title,content}]}
    results = data.get("results")
    if isinstance(results, list):
        hits = [
            _parse_extract_hit(item, i)
            for i, item in enumerate(results, 1)
            if isinstance(item, dict)
        ]
        return [("extracted results", hits)]

    return None


def _parse_search_output(
    text: str,
) -> "list[tuple[str, list[tuple[int, str, bool]]]]":
    """Parse search output into [(path, [(line_num, content, is_hit), ...]), ...]."""
    json_groups = _parse_search_json(text)
    if json_groups is not None:
        return json_groups
    groups: list[tuple[str, list[tuple[int, str, bool]]]] = []
    current_path: str | None = None
    current_hits: list[tuple[int, str, bool]] = []

    for line in text.splitlines():
        hit_m = _HIT_RE.match(line)
        if hit_m:
            line_num = int(hit_m.group(2))
            content = hit_m.group(3)
            if current_path is None:
                current_path = "<unknown>"
                current_hits = []
            current_hits.append((line_num, content, True))
            continue
        ctx_m = _CONTEXT_RE.match(line)
        if ctx_m:
            line_num = int(ctx_m.group(2))
            content = ctx_m.group(3)
            if current_path is None:
                current_path = "<unknown>"
                current_hits = []
            current_hits.append((line_num, content, False))
            continue
        # Not a numbered line — treat as file path separator
        stripped = line.strip()
        if stripped:
            if current_path is not None and current_hits:
                groups.append((current_path, current_hits))
            current_path = stripped
            current_hits = []

    if current_path is not None and current_hits:
        groups.append((current_path, current_hits))

    return groups


# ---------------------------------------------------------------------------
# VirtualSearchList child widgets — R-Sr4 / R-Sr5
# ---------------------------------------------------------------------------

class _StickyGroupHeader(Static, can_focus=False):
    DEFAULT_CSS = "_StickyGroupHeader { dock: top; height: 1; display: none; color: $text-muted; }"


class _SearchFooter(Static, can_focus=False):
    DEFAULT_CSS = "_SearchFooter { dock: bottom; height: 1; }"


# ---------------------------------------------------------------------------
# VirtualSearchList — R-Sr3 / R-Sr4 / R-Sr5
# ---------------------------------------------------------------------------

class VirtualSearchList(Widget, can_focus=True):
    """Virtual-scrolling search result list for large result sets (>100 hits).

    render_line(y) returns a Strip for the visible row.
    j/k/pgdn/pgup/g/G navigate; Enter opens in $EDITOR.
    """

    BINDINGS = [
        Binding("j,down",      "cursor_down",    "down",   show=False),
        Binding("k,up",        "cursor_up",      "up",     show=False),
        Binding("pagedown",    "page_down",      "pgdn",   show=False),
        Binding("pageup",      "page_up",        "pgup",   show=False),
        Binding("g,home",      "cursor_top",     "top",    show=False),
        Binding("shift+g,end", "cursor_bottom",  "bottom", show=False),
        Binding("enter",       "open_selection", "open",   show=False),
    ]

    def __init__(
        self,
        lines: "list[tuple[str, str, str | None, int | None]]",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._lines = lines               # single source of truth; never mutated after __init__
        self._cursor_idx: int = 0
        self._viewport_height: int = 10  # updated in on_mount; default for __new__-constructed tests
        self._hit_count: int = 0         # computed in on_mount; init for __new__-constructed tests
        self._strips: list[Strip] = []
        self._line_kinds: list[str] = []

    def compose(self) -> ComposeResult:
        yield _StickyGroupHeader(id="sticky-group-header")
        yield _SearchFooter(id="search-footer")

    def on_mount(self) -> None:
        from rich.text import Text
        self._viewport_height = self.size.height
        self._strips = [
            Strip(list(Text.from_ansi(entry[0]).render(self.app.console)))
            for entry in self._lines
        ]
        self._line_kinds = [entry[1] for entry in self._lines]
        self._hit_count = sum(1 for k in self._line_kinds if k == "hit")
        self._update_sticky()
        self._update_footer()

    def render_line(self, y: int) -> Strip:
        from rich.style import Style
        from rich.segment import Segment
        idx = y
        if 0 <= idx < len(self._strips):
            strip = self._strips[idx]
            if idx == self._cursor_idx:
                segs = [
                    Segment(s.text, (s.style or Style()) + Style(reverse=True))
                    for s in strip
                ]
                return Strip(segs)
            return strip
        return Strip([])

    # ------------------------------------------------------------------
    # Scroll actions — R-Sr4
    # ------------------------------------------------------------------

    def _safe_refresh(self) -> None:
        try:
            self.refresh()
        except AttributeError:  # noqa: bare-except
            pass  # __new__-constructed test objects lack Textual's internal state

    def action_cursor_down(self) -> None:
        if not self._strips:
            return
        self._cursor_idx = min(self._cursor_idx + 1, len(self._strips) - 1)
        self._update_sticky()
        self._update_footer()
        self._safe_refresh()

    def action_cursor_up(self) -> None:
        if not self._strips:
            return
        self._cursor_idx = max(self._cursor_idx - 1, 0)
        self._update_sticky()
        self._update_footer()
        self._safe_refresh()

    def action_page_down(self) -> None:
        if not self._strips:
            return
        self._cursor_idx = min(
            self._cursor_idx + self._viewport_height - 1,
            len(self._strips) - 1,
        )
        self._update_sticky()
        self._update_footer()
        self._safe_refresh()

    def action_page_up(self) -> None:
        if not self._strips:
            return
        self._cursor_idx = max(self._cursor_idx - (self._viewport_height - 1), 0)
        self._update_sticky()
        self._update_footer()
        self._safe_refresh()

    def action_cursor_top(self) -> None:
        if not self._strips:
            return
        self._cursor_idx = 0
        self._update_sticky()
        self._update_footer()
        self._safe_refresh()

    def action_cursor_bottom(self) -> None:
        if not self._strips:
            return
        self._cursor_idx = len(self._strips) - 1
        self._update_sticky()
        self._update_footer()
        self._safe_refresh()

    # ------------------------------------------------------------------
    # Open in editor — R-Sr4
    # ------------------------------------------------------------------

    def action_open_selection(self) -> None:
        if not self._line_kinds or self._cursor_idx >= len(self._line_kinds):
            return
        if self._line_kinds[self._cursor_idx] not in {"hit", "context"}:
            return
        _, _kind, path, line_num = self._lines[self._cursor_idx]
        if path is None:
            return
        cmd_argv = shlex.split(os.environ.get("EDITOR", "vi"))
        safe_edit_cmd(self, cmd_argv, path, line=line_num, on_exit=lambda: self.refresh())

    # ------------------------------------------------------------------
    # Sticky header — R-Sr5
    # ------------------------------------------------------------------

    def _update_sticky(self) -> None:
        try:
            sticky = self.query_one(_StickyGroupHeader)
        except Exception:
            return  # not yet mounted; safe to swallow
        if not self._line_kinds:
            sticky.display = False
            return
        # Sticky only provides context when there are multiple groups
        if sum(1 for k in self._line_kinds if k == "header") <= 1:
            sticky.display = False
            return
        if self._line_kinds[self._cursor_idx] == "header":
            sticky.display = False
            return
        # Scan backward from cursor for the nearest header
        for i in range(self._cursor_idx, -1, -1):
            if self._line_kinds[i] == "header":
                sticky.update(self._lines[i][2] or "")  # slot 2 = path
                sticky.display = True
                return
        sticky.display = False

    # ------------------------------------------------------------------
    # Footer — R-Sr4
    # ------------------------------------------------------------------

    def _update_footer(self) -> None:
        total = len(self._strips)
        pos = self._cursor_idx + 1 if total > 0 else 0
        sep = glyph("·")
        hint = f"[j/k scroll {sep} g/G top/bottom {sep} enter open]"
        text = f"{hint} {sep} {pos}/{total} lines {sep} {self._hit_count} hits"
        try:
            self.query_one(_SearchFooter).update(text)
        except Exception:  # noqa: bare-except
            pass  # not yet mounted; on_mount guarantees children exist when called there


# ---------------------------------------------------------------------------
# SearchRenderer — R-Sr1 / R-Sr2 / R-Sr3 / R-Sr5
# ---------------------------------------------------------------------------

class SearchRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = False
    truncation_bias: ClassVar = "priority"
    kind_icon: ClassVar[str] = "🔍"

    @classmethod
    def accepts(cls, phase: "ToolCallState", density: "DensityTier") -> bool:
        # FH-6: COMPACT now accepted; summary_line provides the one-line surface.
        return super().accepts(phase, density)

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        from hermes_cli.tui.tool_payload import ResultKind
        return cls_result.kind == ResultKind.SEARCH

    def build(self):
        """Build Rich Text with grammar path headers and hit/context distinction. R-Sr1/R-Sr2."""
        from rich.style import Style
        from hermes_cli.tui.body_renderers._grammar import build_rule

        raw = self.payload.output_raw or ""
        query = self.cls_result.metadata.get("query") if self.cls_result.metadata else None
        groups = _parse_search_output(raw)
        colors = self.colors

        result = Text()

        # R-P2: low-confidence disclosure header (is True guards against MagicMock attrs)
        if getattr(self.cls_result, "_low_confidence_disclosed", False) is True:
            kind_name = self.cls_result.kind.name.lower()
            result.append_text(build_rule(f"detected: {kind_name} · low confidence", colors=colors))
            result.append("\n")

        for i, (path, hits) in enumerate(groups):
            if i > 0:
                # R-Sr5: rule separator between groups
                result.append_text(build_rule(colors=colors))
                result.append("\n")

            # R-Sr2: grammar path header with "  " icon-column prefix
            header_t = Text("  ")
            header_t.append_text(build_path_header(
                path, right_meta=f"{len(hits)} hits", colors=colors,
            ))
            header_t.append("\n")
            result.append_text(header_t)

            for line_num, content, is_hit in hits:
                line_t = build_gutter_line_num(line_num, colors=colors)
                # R-Sr1: context lines are dim+italic; hit lines are normal
                if is_hit:
                    # Web/extract hits return a pre-styled Text; grep hits return str.
                    if isinstance(content, Text):
                        content_t = content
                    else:
                        content_t = Text(content)
                        if query:
                            try:
                                content_t.highlight_regex(re.escape(query), style="bold")
                            except re.error:  # noqa: bare-except
                                pass
                else:
                    content_t = Text(str(content), style=Style(color=colors.muted, italic=True))
                line_t.append_text(content_t)
                line_t.append("\n")
                result.append_text(line_t)

        return result

    def _build_lines_list(
        self,
    ) -> "list[tuple[str, str, str | None, int | None]]":
        """Build unified 4-tuple list for VirtualSearchList. R-Sr3 / R-Sr5.

        Each entry: (formatted_line, kind, path_or_none, line_num_or_none)
        kind ∈ {"header", "hit", "context", "rule", "blank"}
        """
        raw = self.payload.output_raw or ""
        query = self.cls_result.metadata.get("query") if self.cls_result.metadata else None
        groups = _parse_search_output(raw)
        colors = self.colors

        lines: list[tuple[str, str, str | None, int | None]] = []
        for i, (path, hits) in enumerate(groups):
            # R-Sr5: rule separator between groups (not blank line)
            if i > 0:
                rule_plain = build_rule(colors=colors).plain
                lines.append((rule_plain, "rule", None, None))

            # Group header entry
            header_t = Text("  ")
            header_t.append_text(build_path_header(
                path, right_meta=f"{len(hits)} hits", colors=colors,
            ))
            lines.append((header_t.plain, "header", path, None))

            for line_num, content, is_hit in hits:
                gutter_plain = build_gutter_line_num(line_num, colors=colors).plain
                content_plain = content.plain if isinstance(content, Text) else content
                highlighted = _ansi_highlight(content_plain, query) if query else content_plain
                formatted = gutter_plain + highlighted
                kind = "hit" if is_hit else "context"
                lines.append((formatted, kind, path, line_num))

        return lines

    def copy_text(self) -> str:
        """Return normalized results as plain text, one line per hit."""
        raw = self.payload.output_raw or ""
        groups = _parse_search_output(raw)
        lines = []
        for _group_name, hits in groups:
            for _line_num, content, _is_hit in hits:
                lines.append(content.plain if isinstance(content, Text) else content)
        return "\n".join(lines)

    def hit_count(self) -> int:
        _hc = getattr(self, "_hit_count", 0)
        if _hc:
            return _hc
        # Phase C (non-streaming): _hit_count is only set on VirtualSearchList.
        # Fall back to classifier metadata stamped at COMPLETING.
        if self.cls_result and self.cls_result.metadata:
            return int(self.cls_result.metadata.get("hit_count", 0))
        return 0

    def summary_line(self, *, density=None, cls_result=None) -> str:
        from hermes_cli.tui.tool_panel.layout_resolver import DensityTier
        if density == DensityTier.COMPACT:
            groups = _parse_search_output(self.payload.output_raw or "")
            top_hit_title = None
            if groups:
                _group_name, hits = groups[0]
                if hits:
                    _line_num, content, _is_hit = hits[0]
                    _c = content.plain if isinstance(content, Text) else content
                    top_hit_title = _c.strip() or None
            n_hits = self.hit_count()
            if top_hit_title:
                from hermes_cli.tui.body_renderers._grammar import GLYPH_META_SEP, glyph
                sep = glyph(GLYPH_META_SEP)
                return f"{top_hit_title} {sep} {n_hits} hits"
            return f"{n_hits} hit(s)" if n_hits else "(no matches)"
        hits = self.hit_count()
        return f"{hits} hit(s)" if hits else "(no matches)"

    def build_widget(self, density=None, clamp_rows=None):
        """Return BodyFrame wrapping VirtualSearchList (>100 hits) or CopyableRichLog."""
        from hermes_cli.tui.body_renderers._grammar import BodyFooter
        from hermes_cli.tui.body_renderers._frame import BodyFrame

        hit_count = 0
        if self.cls_result.metadata:
            hit_count = int(self.cls_result.metadata.get("hit_count", 0))

        if hit_count > 100:
            lines = self._build_lines_list()
            body_widget = VirtualSearchList(lines=lines)
        else:
            from hermes_cli.tui.widgets import CopyableRichLog
            rl = CopyableRichLog(highlight=False, markup=False)
            rl.write(self.build())
            body_widget = rl

        return BodyFrame(
            header=None,
            body=body_widget,
            footer=BodyFooter(("y", "copy")),
            density=density,
        )


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind
    SearchRenderer.kind = ResultKind.SEARCH


_set_kind()
