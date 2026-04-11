"""ToolBlock widgets for displaying collapsible tool output in the TUI.

ToolBlock groups a ToolHeader (single-line label with toggle/copy affordances)
and a ToolBodyContainer (collapsible content area). Blocks with ≤3 lines are
auto-expanded with no toggle or copy affordance.
"""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult, RenderResult
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget

from hermes_cli.tui.widgets import CopyableRichLog, _skin_color

COLLAPSE_THRESHOLD = 3  # >N lines → collapsed by default


class ToolHeader(Widget):
    """Single-line header: '  ╌╌ {label}  {N}L  [▸/▾  ⎘]'."""

    DEFAULT_CSS = "ToolHeader { height: 1; }"

    collapsed: reactive[bool] = reactive(True, repaint=True)

    def __init__(self, label: str, line_count: int, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._label = label
        self._line_count = line_count
        # ≤ threshold: always open, no affordances shown
        self._has_affordances = line_count > COLLAPSE_THRESHOLD
        self._copy_flash = False

    def render(self) -> RenderResult:
        focused = self.has_class("focused")
        if focused:
            gutter = Text("  ┃", style=f"bold {_skin_color('banner_title', '#FFD700')}")
        else:
            gutter = Text("  ┊", style="dim")
        t = Text()
        t.append_text(gutter)
        t.append(f"   ╌╌ {self._label}  {self._line_count}L", style="dim")
        if self._has_affordances:
            toggle = "  ▾" if not self.collapsed else "  ▸"
            icon = "  ✓" if self._copy_flash else "  ⎘"
            t.append(toggle, style="dim")
            t.append(icon, style="dim")
        return t

    def flash_copy(self) -> None:
        """Flash ⎘ → ✓ for 1.5 s, then revert."""
        self._copy_flash = True
        self.refresh()
        self.set_timer(1.5, self._end_flash)

    def _end_flash(self) -> None:
        self._copy_flash = False
        self.refresh()


class ToolBodyContainer(Widget):
    """Collapsible container for tool output lines."""

    DEFAULT_CSS = """
    ToolBodyContainer { height: auto; display: none; }
    ToolBodyContainer.expanded { display: block; }
    """

    def compose(self) -> ComposeResult:
        # No explicit ID — query by type inside ToolBodyContainer to avoid
        # duplicate IDs when multiple ToolBlocks exist per MessagePanel.
        yield CopyableRichLog(markup=False, highlight=False, wrap=False)


class ToolBlock(Widget):
    """Collapsible widget pairing a ToolHeader with expandable body content.

    Lines with ≤ COLLAPSE_THRESHOLD are auto-expanded and show no toggle or
    copy affordance. Lines with > COLLAPSE_THRESHOLD start collapsed.
    """

    DEFAULT_CSS = "ToolBlock { height: auto; }"

    def __init__(
        self,
        label: str,
        lines: list[str],       # ANSI display lines
        plain_lines: list[str], # plain text for copy (no ANSI, no gutter)
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._label = label
        self._lines = list(lines)
        self._plain_lines = list(plain_lines)
        auto_expand = len(lines) <= COLLAPSE_THRESHOLD
        self._header = ToolHeader(label, len(lines))
        self._body = ToolBodyContainer()
        if auto_expand:
            self._header.collapsed = False
            # _has_affordances is already False when line_count ≤ threshold

    def compose(self) -> ComposeResult:
        yield self._header
        yield self._body

    def on_mount(self) -> None:
        try:
            log = self._body.query_one(CopyableRichLog)
            for line in self._lines:
                log.write(Text.from_ansi(line))
        except NoMatches:
            pass  # body not yet in DOM — safe to skip
        if not self._header.collapsed:
            self._body.add_class("expanded")

    def toggle(self) -> None:
        """Toggle collapsed ↔ expanded. No-op for ≤3-line blocks."""
        if not self._header._has_affordances:
            return
        self._header.collapsed = not self._header.collapsed
        if self._header.collapsed:
            self._body.remove_class("expanded")
        else:
            self._body.add_class("expanded")
        self._header.refresh()

    def copy_content(self) -> str:
        """Plain-text content for clipboard — no ANSI, no gutter, no line numbers."""
        return "\n".join(self._plain_lines)
