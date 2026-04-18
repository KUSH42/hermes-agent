"""InputSection — per-category input summary widget.

Phase D of Tool Panel v3 (tui-tool-panel-v3-spec.md §5.4).

Renders a concise summary of the tool's input arguments based on category.
Only shown at detail level L2+. EXECUTE_CODE / UNKNOWN categories never render.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
    from hermes_cli.tui.tool_category import ToolCategory


class InputSection(Widget):
    """Compact one-line input summary for a tool call.

    Visibility:
    - Only shown when ``-has-input`` class is present (set by refresh_content).
    - display:none by default; ToolPanel.watch_detail_level toggles display.
    """

    COMPONENT_CLASSES = {"input-section--border", "input-section--body"}

    DEFAULT_CSS = """
    InputSection {
        height: auto;
        padding: 0 0 0 2;
        margin-bottom: 1;
        display: none;
    }
    InputSection.-has-input { display: block; }
    """

    def __init__(
        self,
        category: "ToolCategory",
        args: dict | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._category = category
        self._args: dict = args or {}
        self._content: Static | None = None

    def compose(self) -> ComposeResult:
        self._content = Static("", id="input-content")
        yield self._content

    def on_mount(self) -> None:
        # Only refresh if we have args — avoids a spurious layout change
        # at mount time that can interfere with sibling click hit-testing.
        if self._args:
            self.refresh_content(self._args)

    def refresh_content(self, args: dict | None) -> None:
        """Build input summary string for this category + args."""
        self._args = args or {}
        text = self._build_text()
        if text:
            if self._content is not None:
                self._content.update(text)
            self.add_class("-has-input")
        else:
            self.remove_class("-has-input")

    def _build_text(self) -> str:
        from hermes_cli.tui.tool_category import ToolCategory

        cat = self._category
        args = self._args

        # EXECUTE_CODE and UNKNOWN: never render
        if cat == ToolCategory.CODE:
            return ""
        if cat == ToolCategory.UNKNOWN:
            return ""

        if cat == ToolCategory.SHELL:
            return (
                args.get("command")
                or args.get("cmd")
                or args.get("shell_command")
                or ""
            )

        if cat == ToolCategory.FILE:
            # For file ops, show path (+ range for reads)
            path = args.get("path") or args.get("file_path") or ""
            start = args.get("offset") or args.get("start_line")
            end = args.get("limit") or args.get("end_line")
            # Check if it looks like a read (has range args)
            if start is not None and end is not None:
                return f"{path}:{start}-{end}"
            # Edit/patch: show hunk count
            diff = args.get("diff") or args.get("patch") or args.get("new_str") or ""
            hunk_count = diff.count("\n@@") if diff else 0
            if hunk_count > 0:
                return f"{path}  {hunk_count} hunks"
            return path

        if cat == ToolCategory.SEARCH:
            query = (
                args.get("query")
                or args.get("pattern")
                or args.get("regex")
                or ""
            )
            root = args.get("path") or args.get("root") or ""
            if query and root:
                return f"{query}  {root}"
            return query or root

        if cat == ToolCategory.WEB:
            method = args.get("method") or "GET"
            url = args.get("url") or args.get("uri") or ""
            return f"{method} {url}"

        if cat == ToolCategory.AGENT:
            return args.get("thought") or args.get("plan") or ""

        return ""

    @classmethod
    def should_show(cls, category: "ToolCategory") -> bool:
        """Return True if this category ever renders an InputSection."""
        from hermes_cli.tui.tool_category import ToolCategory

        return category not in (ToolCategory.CODE, ToolCategory.UNKNOWN)
