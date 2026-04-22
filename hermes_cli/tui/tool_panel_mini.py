"""ToolPanelMini — single-row compact variant for qualifying SHELL tool calls (§5.10).

Auto-select criteria (evaluated at set_result_summary finalize time):
  - category == SHELL
  - exit_code == 0
  - line_count <= 3
  - stderr_raw empty or None

Mounted as a sibling to ToolPanel (same DOM depth) by ToolPanel._activate_mini().
Click or Enter → expand back to the full ToolPanel.

Mini-mode toast: shown once per session (tracked via app._mini_toast_shown).
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.tool_accent import ToolAccent


def meets_mini_criteria(
    category: object,
    exit_code: int | None,
    line_count: int,
    stderr_raw: str | None,
) -> bool:
    """Return True when all mini-mode criteria are satisfied."""
    from hermes_cli.tui.tool_category import ToolCategory
    if category != ToolCategory.SHELL:
        return False
    if exit_code != 0:
        return False
    if line_count > 3:
        return False
    if stderr_raw:
        return False
    return True


class ToolPanelMini(Widget):
    """Single-row compact shell panel — ToolAccent + truncated command + duration.

    Replaces the originating ToolPanel visually; the full ToolPanel is hidden
    (display=False) but kept in DOM for lazy expansion.

    Layout (horizontal):
        ToolAccent (1 cell) | mini-content Static (1fr)
    """

    DEFAULT_CSS = """
    ToolPanelMini {
        height: 1;
        layout: horizontal;
    }
    ToolPanelMini > ._mini-content {
        width: 1fr;
        height: 1;
        color: $text-muted;
    }
    """

    can_focus = True

    def __init__(
        self,
        source_panel: Widget,
        command: str = "",
        duration_s: float = 0.0,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._source_panel = source_panel
        self._command = command
        self._duration_s = duration_s
        self._accent: ToolAccent | None = None
        self._content: Static | None = None

    def compose(self) -> ComposeResult:
        self._accent = ToolAccent()
        self._accent.state = "ok"
        label = self._build_label()
        self._content = Static(label, classes="_mini-content")
        yield self._accent
        yield self._content

    def _build_label(self) -> str:
        dur = f"  {self._duration_s:.1f}s" if self._duration_s > 0 else ""
        return f"  {self._command}{dur}"

    def on_click(self) -> None:
        self._expand()

    def on_key(self, event: object) -> None:
        key = getattr(event, "key", None)
        if key == "enter":
            self._expand()
            getattr(event, "stop", lambda: None)()

    def watch_mouse_hover(self, value: bool) -> None:
        src = self._source_panel  # pre-existing: set in __init__ from source_panel param
        if src is not None and src.is_mounted:
            if value:
                src.remove_class("--minified")
            else:
                src.add_class("--minified")

    def _expand(self) -> None:
        """Show the originating ToolPanel and remove this mini widget."""
        self._show_toast_once()
        self._source_panel.remove_class("--minified")  # pre-existing attr; was: display=True
        self.remove()

    def _show_toast_once(self) -> None:
        app = getattr(self, "app", None)
        if app is None:
            return
        if getattr(app, "_mini_toast_shown", False):
            return
        app._mini_toast_shown = True  # type: ignore[attr-defined]
        try:
            app.notify(
                "Mini mode: compact shell output — Enter to expand",
                timeout=3,
            )
        except Exception:
            pass
