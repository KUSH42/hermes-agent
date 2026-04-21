"""ToolBlock widget — collapsible tool output block."""
from __future__ import annotations

from typing import Any, Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.widget import Widget

from hermes_cli.tui.widgets import CopyableRichLog, _boost_layout_caches

from ._shared import (
    COLLAPSE_THRESHOLD,
    _FILE_TOOL_NAMES,
    _DIFF_NEW_RE,
    _DIFF_OLD_RE,
    _DIFF_ARROW_RE,
    _code_lang,
    _word_diff,
    _count_visible_diff_rows,
    ToolHeaderStats,
)
from ._header import ToolHeader, ToolBodyContainer


class ToolBlock(Widget):
    """Collapsible widget pairing a ToolHeader with expandable body content.

    Lines with ≤ COLLAPSE_THRESHOLD are auto-expanded and show no toggle or
    copy affordance.  Lines with > COLLAPSE_THRESHOLD start collapsed.

    Used for post-completion tool output summaries (diff previews, code/file
    previews, terminal output).  Content arrives all-at-once via ``lines`` /
    ``plain_lines`` and can be re-rendered on skin change via ``rerender_fn``.

    For real-time streaming output during tool execution, see
    ``StreamingToolBlock``.
    """

    DEFAULT_CSS = "ToolBlock { height: auto; }"
    _content_type: str = "tool"

    def __init__(
        self,
        label: str,
        lines: list[str],
        plain_lines: list[str],
        tool_name: str | None = None,
        rerender_fn: Callable[[], tuple[list[str], list[str]]] | None = None,
        header_stats: ToolHeaderStats | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        _boost_layout_caches(self)
        self._label = label
        self._tool_name = tool_name
        self._lines = list(lines)
        self._plain_lines = list(plain_lines)
        self._rerender_fn = rerender_fn if callable(rerender_fn) else None
        self._header_stats = header_stats if isinstance(header_stats, ToolHeaderStats) else None
        if self._header_stats is None and label == "diff":
            self._header_stats = _count_visible_diff_rows(self._plain_lines)
        auto_expand = len(lines) <= COLLAPSE_THRESHOLD
        self._header = ToolHeader(label, len(lines), tool_name=tool_name, stats=self._header_stats)
        self._body = ToolBodyContainer()
        if auto_expand:
            self._header.collapsed = False

        if tool_name in ("read_file", "patch"):
            self._header._no_underline = True
        if tool_name in ("read_file", "search_files"):
            self._header._hide_duration = True
        if tool_name in ("search_files", "clarify"):
            self._header._bold_label = True
        if tool_name == "terminal":
            self._header._hidden = True

        if tool_name in _FILE_TOOL_NAMES and label not in ("diff", "code", "output"):
            self._header.set_path(label)

        self._diff_file_path: str | None = None
        if label == "diff":
            _fallback: str | None = None
            for line in self._plain_lines:
                stripped = line.strip()
                m_new = _DIFF_NEW_RE.match(stripped)
                if m_new:
                    new_path = m_new.group(2) or None
                    if new_path:
                        self._diff_file_path = new_path
                        break
                    continue
                m_old = _DIFF_OLD_RE.match(stripped)
                if m_old:
                    old_path = m_old.group(2) or None
                    if old_path and _fallback is None:
                        _fallback = old_path
                    continue
                m2 = _DIFF_ARROW_RE.match(stripped)
                if m2:
                    new_path = m2.group(2).strip()
                    if new_path.startswith("b/"):
                        new_path = new_path[2:]
                    if "/dev/null" not in new_path and new_path:
                        self._diff_file_path = new_path
                        break
            if self._diff_file_path is None:
                self._diff_file_path = _fallback
            if self._diff_file_path:
                self._header.set_path(self._diff_file_path)

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._body

    def on_mount(self) -> None:
        self._render_body()
        if not self._header.collapsed:
            self._body.add_class("expanded")

    def _render_diff_line(self, plain: str) -> "Text | None":
        try:
            from hermes_cli.tui.body_renderers.streaming import StreamingBodyRenderer
            from hermes_cli.tui.tool_category import ToolCategory
            return StreamingBodyRenderer.for_category(ToolCategory.FILE).render_diff_line(plain)
        except Exception:
            return None

    def _diff_bg_colors(self) -> tuple[str, str]:
        try:
            tm = getattr(self.app, "_theme_manager", None)
            if tm is not None:
                cvars: dict[str, str] = getattr(tm, "_component_vars", {})
                return cvars.get("diff-add-bg", "#1a3a1a"), cvars.get("diff-del-bg", "#3a1a1a")
        except Exception:
            pass
        return "#1a3a1a", "#3a1a1a"

    def _render_body(self) -> None:
        try:
            rl = self._body.query_one(CopyableRichLog)
            rl.clear()

            if (
                self._tool_name in _FILE_TOOL_NAMES
                and self._label not in ("diff", "code", "output")
                and self._plain_lines
            ):
                lang = _code_lang(self._label)
                if lang:
                    try:
                        from rich.syntax import Syntax
                        rl.write(Syntax(
                            "\n".join(self._plain_lines),
                            lang,
                            line_numbers=True,
                            theme="monokai",
                        ))
                        return
                    except Exception:
                        pass

            if self._label == "diff":
                add_bg, del_bg = self._diff_bg_colors()
                pending_removed: str | None = None
                for styled, plain in zip(self._lines, self._plain_lines):
                    rich_line = self._render_diff_line(plain)
                    if rich_line is not None:
                        if pending_removed is not None:
                            t = Text("-", style="red")
                            t.append(pending_removed, style=f"on {del_bg}")
                            rl.write(t)
                            pending_removed = None
                        rl.write(rich_line)
                        continue
                    stripped = plain.rstrip("\n")
                    if stripped.startswith("-") and not stripped.startswith("---"):
                        if pending_removed is not None:
                            t = Text("-", style="red")
                            t.append(pending_removed, style=f"on {del_bg}")
                            rl.write(t)
                        pending_removed = stripped[1:]
                    elif stripped.startswith("+") and not stripped.startswith("+++"):
                        content = stripped[1:]
                        if pending_removed is not None:
                            rem_t, add_t = _word_diff(pending_removed, content)
                            rt = Text("-", style="red")
                            rt.append_text(rem_t)
                            rl.write(rt)
                            at = Text("+", style="green")
                            at.append_text(add_t)
                            rl.write(at)
                            pending_removed = None
                        else:
                            t = Text("+", style="green")
                            t.append(content, style=f"on {add_bg}")
                            rl.write(t)
                    else:
                        if pending_removed is not None:
                            t = Text("-", style="red")
                            t.append(pending_removed, style=f"on {del_bg}")
                            rl.write(t)
                            pending_removed = None
                        rl.write_with_source(Text.from_ansi(styled), plain)
                if pending_removed is not None:
                    t = Text("-", style="red")
                    t.append(pending_removed, style=f"on {del_bg}")
                    rl.write(t)
                if self._header_stats and self._header_stats.has_diff_counts and self._lines:
                    rl.write(Text(""))
                return

            for styled, plain in zip(self._lines, self._plain_lines):
                rl.write_with_source(Text.from_ansi(styled), plain)
            if self._header_stats and self._header_stats.has_diff_counts and self._lines:
                rl.write(Text(""))
        except NoMatches:
            pass

    def toggle(self) -> None:
        panel = getattr(self._header, "_panel", None)
        if panel is not None:
            panel.action_toggle_collapse()
            return
        if not self._header._has_affordances:
            return
        self._header.collapsed = not self._header.collapsed
        if self._header.collapsed:
            self._body.remove_class("expanded")
        else:
            self._body.add_class("expanded")
        self._header.refresh()

    def copy_content(self) -> str:
        return "\n".join(self._plain_lines)

    def refresh_skin(self) -> None:
        if self._rerender_fn is not None:
            lines, plain_lines = self._rerender_fn()
            self._lines = list(lines)
            self._plain_lines = list(plain_lines)
        if self._label == "diff" and not isinstance(self._header_stats, ToolHeaderStats):
            self._header_stats = _count_visible_diff_rows(self._plain_lines)
        self._header._stats = self._header_stats
        self._header._line_count = len(self._lines)
        self._header._has_affordances = len(self._lines) > COLLAPSE_THRESHOLD
        self._header._refresh_gutter_color()
        self._header._refresh_tool_icon()
        if not self._header._has_affordances:
            self._header.collapsed = False
            self._body.add_class("expanded")
        self._render_body()
        self._header.refresh()
        self.refresh(layout=True)
