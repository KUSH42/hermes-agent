"""DiffRenderer — unified diff format renderer with widget collapse affordance."""
from __future__ import annotations

import logging

_log = logging.getLogger(__name__)

import difflib
import re as _re
from typing import TYPE_CHECKING, ClassVar

from rich.style import Style
from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.body_renderers._grammar import (
    SkinColors,
    build_path_header,
    build_rule,
    diff_gutter,
    glyph,
)
from hermes_cli.tui.body_renderers.base import BodyRenderer

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ClassificationResult, ToolPayload

_TOK = _re.compile(r"\s+|\w+|[^\w\s]")


def _tokenise(s: str) -> list[str]:
    return _TOK.findall(s)


def _word_diff(removed: str, added: str) -> tuple[Text, Text]:
    """Apply word-level diff without altering the original plain strings."""
    rem_tok = _tokenise(removed)
    add_tok = _tokenise(added)
    sm = difflib.SequenceMatcher(None, rem_tok, add_tok, autojunk=False)
    rem_t, add_t = Text(), Text()

    emphasis = Style(bold=True, underline=True)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        rem_chunk = "".join(rem_tok[i1:i2])
        add_chunk = "".join(add_tok[j1:j2])
        if tag == "equal":
            rem_t.append(rem_chunk)
            add_t.append(add_chunk)
        elif tag == "replace":
            rem_t.append(rem_chunk, style=emphasis)
            add_t.append(add_chunk, style=emphasis)
        elif tag == "delete":
            rem_t.append(rem_chunk, style=emphasis)
        elif tag == "insert":
            add_t.append(add_chunk, style=emphasis)
    return rem_t, add_t


def _parse_file_stats(lines: list[str]) -> list[tuple[str, int, int]]:
    """Return [(path, added_count, removed_count), ...] for each valid file pair."""
    results: list[tuple[str, int, int]] = []
    current_path: str | None = None
    added = removed = 0
    for idx, line in enumerate(lines):
        if line.startswith("--- "):
            if current_path is not None:
                results.append((current_path, added, removed))
            current_path = None
            added = removed = 0
            if idx + 1 < len(lines) and lines[idx + 1].startswith("+++ "):
                current_path = lines[idx + 1][4:].removeprefix("b/")
        elif line.startswith("+++ "):
            pass
        elif line.startswith("@@"):
            pass
        elif current_path is not None:
            if line.startswith("+"):
                added += 1
            elif line.startswith("-"):
                removed += 1
    if current_path is not None:
        results.append((current_path, added, removed))
    return results


def _build_stat_text(added: int, removed: int, colors: SkinColors) -> Text:
    t = Text()
    t.append(f"+{added}", style=Style(color=colors.success))
    t.append(" ")
    t.append(f"-{removed}", style=Style(color=colors.error))
    return t


def _next_hunk_boundary(lines: list[str], hunk_start: int) -> int:
    return next(
        (
            i
            for i in range(hunk_start + 1, len(lines))
            if lines[i].startswith("@@") or lines[i].startswith("--- ")
        ),
        len(lines),
    )


def _style_entire_text(text: Text, style: Style) -> Text:
    if text.plain:
        text.stylize(style, 0, len(text.plain))
    return text


def _line_text(diff_line: str, colors: SkinColors, *, context_dim: bool = False) -> Text:
    if diff_line.startswith("+"):
        content = Text(diff_line[1:])
        _style_entire_text(content, Style(bgcolor=colors.diff_add_bg))
        line = diff_gutter("+", colors=colors)
        line.append_text(content)
        return line
    if diff_line.startswith("-") and not diff_line.startswith("--- "):
        content = Text(diff_line[1:])
        _style_entire_text(content, Style(bgcolor=colors.diff_del_bg))
        line = diff_gutter("-", colors=colors)
        line.append_text(content)
        return line
    if diff_line.startswith("@@"):
        line = diff_gutter(" ", colors=colors)
        line.append(diff_line, style=Style(color=colors.muted))
        return line

    content = diff_line[1:] if diff_line.startswith(" ") else diff_line
    line = diff_gutter(" ", colors=colors)
    style = Style(color=colors.muted) if context_dim else None
    line.append(content, style=style)
    return line


def _render_word_diff_pair(removed: str, added: str, colors: SkinColors) -> tuple[Text, Text]:
    rem_t, add_t = _word_diff(removed, added)
    _style_entire_text(rem_t, Style(bgcolor=colors.diff_del_bg))
    _style_entire_text(add_t, Style(bgcolor=colors.diff_add_bg))

    rem_line = diff_gutter("-", colors=colors)
    rem_line.append_text(rem_t)
    add_line = diff_gutter("+", colors=colors)
    add_line.append_text(add_t)
    return rem_line, add_line


def _build_body_text(
    hunk_header: str,
    body_lines: list[str],
    colors: SkinColors,
) -> Text:
    result = Text()
    first = _line_text(f"▾ {hunk_header}", colors, context_dim=True)
    result.append_text(first)
    for line in body_lines:
        result.append("\n")
        result.append_text(_line_text(line, colors, context_dim=True))
    return result


def _collapsed_hunk_hint(hunk_header: str, body_line_count: int, colors: SkinColors) -> Text:
    line = diff_gutter(" ", colors=colors)
    line.append_text(
        build_rule(
            f"hunk {hunk_header} {glyph('·')} +{body_line_count} lines "
            f"(c to copy {glyph('·')} space to expand)",
            colors=colors,
        )
    )
    return line


def _render_diff_lines(lines: list[str], colors: SkinColors, *, collapse: bool) -> list[Text]:
    stat_map = {path: (added, removed) for path, added, removed in _parse_file_stats(lines)}
    rendered: list[Text] = []
    pending_removed: str | None = None
    hunk_idx = 0
    i = 0

    while i < len(lines):
        line = lines[i]

        if line.startswith("--- "):
            if pending_removed is not None:
                rendered.append(_line_text("-" + pending_removed, colors))
                pending_removed = None
            if i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                path = lines[i + 1][4:].removeprefix("b/")
                added, removed = stat_map.get(path, (0, 0))
                rendered.append(
                    build_path_header(
                        path,
                        right_meta=_build_stat_text(added, removed, colors),
                        colors=colors,
                    )
                )
                hunk_idx = 0
            i += 1
            continue

        if line.startswith("+++ "):
            i += 1
            continue

        if line.startswith("@@"):
            if pending_removed is not None:
                rendered.append(_line_text("-" + pending_removed, colors))
                pending_removed = None
            next_boundary = _next_hunk_boundary(lines, i)
            body_line_count = next_boundary - i - 1
            is_collapsed = collapse and hunk_idx > 0
            if is_collapsed:
                rendered.append(_collapsed_hunk_hint(line, body_line_count, colors))
                hunk_idx += 1
                i = next_boundary
                continue
            rendered.append(_line_text(line, colors, context_dim=True))
            hunk_idx += 1
            i += 1
            continue

        if line.startswith("-") and not line.startswith("--- "):
            if pending_removed is not None:
                rendered.append(_line_text("-" + pending_removed, colors))
            pending_removed = line[1:]
            i += 1
            continue

        if line.startswith("+"):
            if pending_removed is not None:
                rem_line, add_line = _render_word_diff_pair(pending_removed, line[1:], colors)
                rendered.append(rem_line)
                rendered.append(add_line)
                pending_removed = None
            else:
                rendered.append(_line_text(line, colors))
            i += 1
            continue

        if pending_removed is not None:
            rendered.append(_line_text("-" + pending_removed, colors))
            pending_removed = None

        rendered.append(_line_text(line, colors, context_dim=True))
        i += 1

    if pending_removed is not None:
        rendered.append(_line_text("-" + pending_removed, colors))

    return rendered


class _HunkHeader(Vertical, can_focus=True):
    DEFAULT_CSS = """
_HunkHeader {
    height: auto;
}
_HunkHeader > ._body {
    display: none;
    height: auto;
}
_HunkHeader > ._summary {
    height: 1;
}
_HunkHeader:focus ._summary {
    background: $primary 15%;
}
"""

    class DiffHunkExpanded(Message):
        def __init__(self, hunk_idx: int) -> None:
            super().__init__()
            self.hunk_idx = hunk_idx

    BINDINGS = [
        Binding("space", "toggle_expand", show=False),
        Binding("enter", "toggle_expand", show=False),
        Binding("c", "copy_hunk", show=False),
    ]

    def __init__(
        self,
        hunk_idx: int,
        hunk_header: str,
        raw_hunk: str,
        body_text: Text,
        body_line_count: int,
    ) -> None:
        super().__init__()
        self._hunk_idx = hunk_idx
        self._hunk_header = hunk_header
        self._raw_hunk = raw_hunk
        self._body_text = body_text
        self._expanded = False
        self._summary_base = (
            f"  {hunk_header}  {glyph('·')}  +{body_line_count} lines"
            f"  (c to copy {glyph('·')} space to expand)"
        )
        self._summary = Static(f"▸{self._summary_base}", classes="_summary")
        self._body = Static(self._body_text, classes="_body")
        self._body.display = False

    def compose(self) -> ComposeResult:
        yield self._summary
        yield self._body

    def action_toggle_expand(self) -> None:
        self._expanded = not self._expanded
        self._body.display = self._expanded
        prefix = "▾" if self._expanded else "▸"
        self._summary.update(f"{prefix}{self._summary_base}")
        if self._expanded:
            self.post_message(self.DiffHunkExpanded(self._hunk_idx))

    def action_copy_hunk(self) -> None:
        self.app._svc_theme.copy_text_with_hint(self._raw_hunk)

    def on_click(self, _event) -> None:
        self.action_toggle_expand()


class _DiffContainer(Vertical):
    @on(_HunkHeader.DiffHunkExpanded)
    def _handle_hunk_expanded(self, event: "_HunkHeader.DiffHunkExpanded") -> None:
        self.scroll_visible(event.control, animate=True)


class DiffRenderer(BodyRenderer):
    kind: ClassVar  # set at module level below
    supports_streaming: ClassVar[bool] = False
    truncation_bias: ClassVar = "hunk-aware"
    kind_icon: ClassVar[str] = "±"

    @classmethod
    def accepts(cls, phase: "ToolCallState", density: "DensityTier") -> bool:
        from hermes_cli.tui.tool_panel.density import DensityTier as _DT
        if density == _DT.COMPACT:
            return False
        return super().accepts(phase, density)

    def __init__(
        self,
        payload: "ToolPayload",
        cls_result: "ClassificationResult",
        *,
        app=None,
        decision=None,
        **kwargs,
    ) -> None:
        super().__init__(payload, cls_result, app=app, decision=decision)
        self._collapsed_hunks: set[int] = set()
        try:
            from hermes_cli.config import read_raw_config

            cfg = read_raw_config()
        except Exception:  # noqa: bare-except
            cfg = {}
        self._cfg_auto_collapse = bool(
            cfg.get("tui", {}).get("diff", {}).get("auto_collapse", True)
        )

    @classmethod
    def can_render(cls, cls_result: "ClassificationResult", payload: "ToolPayload") -> bool:
        from hermes_cli.tui.tool_payload import ResultKind

        return cls_result.kind == ResultKind.DIFF

    @classmethod
    def streaming_kind_hint(cls, first_chunk: str) -> "ResultKind | None":
        from hermes_cli.tui.tool_payload import ResultKind
        chunk = first_chunk[:256]
        if chunk.startswith("diff --git ") or chunk.startswith("@@ "):
            return ResultKind.DIFF
        # unified header pair: "--- a/f\n+++ b/f"
        if chunk.startswith("--- ") and "\n+++ " in chunk:
            return ResultKind.DIFF
        return None

    def build(self):
        raw = self.payload.output_raw or ""
        lines = raw.splitlines()
        total_lines = len(lines)
        hunk_count = sum(1 for line in lines if line.startswith("@@"))
        auto_collapse = (total_lines > 40 or hunk_count > 3) and self._cfg_auto_collapse

        # PG-3: post incremental DiffStatUpdate per +/- line for ToolGroup header
        if self._app is not None:
            from hermes_cli.tui.tool_group import ToolGroup as _TG
            for line in lines:
                if line.startswith("+") and not line.startswith("+++"):
                    self._app.post_message(_TG.DiffStatUpdate(add=1, del_=0))
                elif line.startswith("-") and not line.startswith("---"):
                    self._app.post_message(_TG.DiffStatUpdate(add=0, del_=1))

        result = Text()
        rendered_lines = _render_diff_lines(lines, self.colors, collapse=auto_collapse)
        for idx, line in enumerate(rendered_lines):
            result.append_text(line)
            if idx < len(rendered_lines) - 1:
                result.append("\n")
        return result

    def _count_changed_files(self, lines: list[str]) -> int:
        """Count distinct changed files from diff --git or --- anchors."""
        count = 0
        i = 0
        while i < len(lines):
            if lines[i].startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                count += 1
            i += 1
        return max(count, 1) if any(l.startswith("@@") for l in lines) else count

    def _build_diff_container(self, lines: list[str], auto_collapse: bool) -> Widget:
        file_stats = _parse_file_stats(lines)
        stat_map = {path: (added, removed) for path, added, removed in file_stats}

        children: list[Widget] = []
        hunk_idx = 0
        i = 0
        pending_removed: str | None = None

        while i < len(lines):
            line = lines[i]

            if line.startswith("--- "):
                if pending_removed is not None:
                    children.append(Static(_line_text("-" + pending_removed, self.colors)))
                    pending_removed = None
                if i + 1 < len(lines) and lines[i + 1].startswith("+++ "):
                    path = lines[i + 1][4:].removeprefix("b/")
                    added, removed = stat_map.get(path, (0, 0))
                    children.append(
                        Static(
                            build_path_header(
                                path,
                                right_meta=_build_stat_text(added, removed, self.colors),
                                colors=self.colors,
                            )
                        )
                    )
                    hunk_idx = 0
                i += 1
                continue

            if line.startswith("+++ "):
                i += 1
                continue

            if line.startswith("@@"):
                if pending_removed is not None:
                    children.append(Static(_line_text("-" + pending_removed, self.colors)))
                    pending_removed = None
                next_boundary = _next_hunk_boundary(lines, i)
                body_lines = lines[i + 1:next_boundary]
                body_line_count = len(body_lines)
                raw_hunk = "\n".join(lines[i:next_boundary])
                body_text = _build_body_text(line, body_lines, self.colors)
                if hunk_idx == 0 or not auto_collapse:
                    children.append(Static(_line_text(line, self.colors, context_dim=True)))
                    for body_line in body_lines:
                        children.append(Static(_line_text(body_line, self.colors, context_dim=True)))
                else:
                    self._collapsed_hunks.add(hunk_idx)
                    children.append(
                        _HunkHeader(
                            hunk_idx,
                            line,
                            raw_hunk,
                            body_text,
                            body_line_count,
                        )
                    )
                hunk_idx += 1
                i = next_boundary
                continue

            if line.startswith("-") and not line.startswith("--- "):
                if pending_removed is not None:
                    children.append(Static(_line_text("-" + pending_removed, self.colors)))
                pending_removed = line[1:]
                i += 1
                continue

            if line.startswith("+"):
                if pending_removed is not None:
                    rem_line, add_line = _render_word_diff_pair(pending_removed, line[1:], self.colors)
                    children.append(Static(rem_line))
                    children.append(Static(add_line))
                    pending_removed = None
                else:
                    children.append(Static(_line_text(line, self.colors)))
                i += 1
                continue

            if pending_removed is not None:
                children.append(Static(_line_text("-" + pending_removed, self.colors)))
                pending_removed = None

            children.append(Static(_line_text(line, self.colors, context_dim=True)))
            i += 1

        if pending_removed is not None:
            children.append(Static(_line_text("-" + pending_removed, self.colors)))

        return _DiffContainer(*children)

    def _diff_stats(self) -> "tuple[int, int, int]":
        stats = _parse_file_stats((self.payload.output_raw or "").splitlines())
        files = len(stats)
        plus  = sum(s[1] for s in stats)
        minus = sum(s[2] for s in stats)
        return files, plus, minus

    def summary_line(self) -> str:
        files, plus, minus = self._diff_stats()
        return f"{files} file(s) · +{plus} −{minus}"

    def build_widget(self, density=None, clamp_rows=None) -> Widget:
        from hermes_cli.tui.body_renderers._grammar import BodyFooter
        from hermes_cli.tui.body_renderers._frame import BodyFrame

        raw = self.payload.output_raw or ""
        lines = raw.splitlines()
        total_lines = len(lines)
        hunk_count = sum(1 for line in lines if line.startswith("@@"))
        auto_collapse = (total_lines > 40 or hunk_count > 3) and self._cfg_auto_collapse

        n_files = self._count_changed_files(lines)
        header = build_rule(f"{n_files} file(s) changed", colors=self.colors)
        body_widget = self._build_diff_container(lines, auto_collapse)

        return BodyFrame(
            header=header,
            body=body_widget,
            footer=BodyFooter(("y", "copy")),
            density=density,
        )


def _set_kind() -> None:
    from hermes_cli.tui.tool_payload import ResultKind

    DiffRenderer.kind = ResultKind.DIFF


_set_kind()
