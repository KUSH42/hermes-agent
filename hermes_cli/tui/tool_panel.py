"""ToolPanel — binary collapse, result wiring, keyboard.

Architecture: tui-tool-panel-spec-binary-collapse.md

collapsed = False  →  header + body + conditional footer  (always at mount)
collapsed = True   →  header only  (auto at completion when body > threshold)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

if TYPE_CHECKING:
    from hermes_cli.tui.tool_result_parse import ResultSummary, ResultSummaryV4
    from hermes_cli.tui.tool_category import ToolCategory


# ---------------------------------------------------------------------------
# BodyPane
# ---------------------------------------------------------------------------


class BodyPane(Widget):
    """Container for the streaming/static block body.

    Full display only — preview path removed (binary collapse spec §2.2).
    """

    DEFAULT_CSS = "BodyPane { height: auto; }"

    def __init__(
        self,
        block: Widget | None = None,
        category: "object | None" = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._block = block
        if category is not None:
            try:
                from hermes_cli.tui.body_renderer import BodyRenderer
                self._renderer = BodyRenderer.for_category(category)
            except Exception:
                self._renderer = None
        else:
            self._renderer = None

    def compose(self) -> ComposeResult:
        if self._block is not None:
            yield self._block


# ---------------------------------------------------------------------------
# FooterPane
# ---------------------------------------------------------------------------


class FooterPane(Widget):
    """Exit-code chip, stat badges, stderr tail, retry hint.

    Shown conditionally based on _has_footer_content() in ToolPanel.
    """

    DEFAULT_CSS = """
    FooterPane {
        height: auto;
        padding: 0 1;
        display: none;
        color: $text-muted;
        layout: vertical;
    }
    FooterPane > .footer-main { height: 1; }
    FooterPane > .footer-stderr {
        height: 1;
        display: none;
        color: $error 80%;
    }
    FooterPane.has-stderr > .footer-stderr { display: block; }
    FooterPane.compact > .footer-stderr { display: none; }
    """

    COMPONENT_CLASSES = {"footer--exit-chip", "footer--badge", "footer--retry-hint"}

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        self._content = Static("", classes="footer-main")
        self._stderr_row = Static("", classes="footer-stderr")
        yield self._content
        yield self._stderr_row

    def update_summary_v4(self, summary: "ResultSummaryV4") -> None:
        """Re-render footer from a ResultSummaryV4 (v4 §4.2)."""
        from rich.text import Text

        parts = Text()

        # Chips row
        for chip in summary.chips:
            tone_style = {
                "success": "bold green",
                "warning": "bold yellow",
                "error": "bold red",
                "accent": "bold cyan",
                "neutral": "dim",
            }.get(chip.tone, "dim")
            parts.append(f" {chip.text} ", style=tone_style)

        # Action row (hotkey hints)
        if summary.actions:
            parts.append("  ")
            for action in summary.actions:
                parts.append(f"[{action.hotkey}]", style="dim")
                parts.append(f" {action.label}", style="dim")
                parts.append("  ", style="")

        # Artifact chips (file/url labels)
        if summary.artifacts:
            for artifact in summary.artifacts:
                icon = "📎" if artifact.kind == "file" else "🔗" if artifact.kind == "url" else "🖼"
                parts.append(f" {icon} {artifact.label} ", style="dim cyan")

        self._content.update(parts)

        # Stderr split row — shown below main row when present
        if summary.stderr_tail:
            stderr_text = Text()
            stderr_text.append("stderr: ", style="dim")
            stderr_text.append(summary.stderr_tail[:120], style="bold")
            self._stderr_row.update(stderr_text)
            self.add_class("has-stderr")
        else:
            self._stderr_row.update("")
            self.remove_class("has-stderr")

    def on_resize(self, event: object) -> None:
        width = getattr(getattr(event, "size", None), "width", 80)
        if width < 60:
            self.add_class("compact")
        else:
            self.remove_class("compact")


# ---------------------------------------------------------------------------
# ToolPanel
# ---------------------------------------------------------------------------


class ToolPanel(Widget):
    """Unified tool-call display container — binary collapse.

    Completion event:
    ToolPanel.Completed is posted on set_result_summary_v4 so ToolGroup can
    re-aggregate without coupling.

    Compose tree:
        ToolPanel
        ├── BodyPane      (hosts the streaming/static block)
        ├── FooterPane    (shown when result has content and not collapsed)
        └── _hint_row     (focus hint, height=auto, empty when unfocused)

    collapsed reactive:
        False (default) → body + conditional footer visible
        True            → header only (body + footer hidden)
    """

    class Completed(Message):
        """Posted when the panel receives a result summary."""

    DEFAULT_CSS = "ToolPanel { height: auto; layout: vertical; }"
    _content_type: str = "tool"
    can_focus = True

    COMPONENT_CLASSES = {
        "tool-panel--accent",
        "tool-panel--error",
        "tool-panel--grouped",
        "tool-panel--focused",
    }

    BINDINGS = [
        Binding("enter", "toggle_collapse", "Toggle", show=False),
        # OmissionBar keyboard (P6)
        Binding("+", "expand_lines", "Expand lines", show=False),
        Binding("-", "collapse_lines", "Collapse lines", show=False),
        Binding("*", "expand_all_lines", "Expand all lines", show=False),
    ]

    # Always start expanded; auto-collapse at completion based on threshold.
    # layout=False: watch_collapsed sets styles.display which already forces a
    # layout refresh — no need for a second one from the reactive itself.
    collapsed: reactive[bool] = reactive(False, layout=False)

    def __init__(self, block: Widget, tool_name: str | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._block = block
        self._tool_name = tool_name or ""
        from hermes_cli.tui.tool_category import classify_tool
        self._category = classify_tool(self._tool_name)

        self._user_collapse_override: bool = False
        self._result_summary_v4: "ResultSummaryV4 | None" = None
        self._start_time: float = time.monotonic()
        self._completed_at: float | None = None
        self._result_paths: list[str] = []

        # Pane refs (set in compose)
        self._body_pane: BodyPane | None = None
        self._footer_pane: FooterPane | None = None
        self._hint_row: Static | None = None

    def compose(self) -> ComposeResult:
        self._body_pane = BodyPane(self._block, category=self._category)
        self._footer_pane = FooterPane()
        self._hint_row = Static("", classes="--focus-hint")
        yield self._body_pane
        yield self._footer_pane
        yield self._hint_row

    def on_mount(self) -> None:
        from hermes_cli.tui.tool_category import _CATEGORY_DEFAULTS

        self.add_class(f"category-{self._category.value}")
        self.add_class("tool-panel--accent")

        # Wire back-ref so ToolHeader can delegate toggle to panel
        header = getattr(self._block, "_header", None)
        if header is not None:
            header._panel = self

        # Always start expanded — auto-collapse fires at completion
        self.collapsed = False

        # Static pre-populated blocks: run auto-collapse immediately if result present
        if self._result_summary_v4 is not None:
            self._apply_complete_auto_collapse()

    # ------------------------------------------------------------------
    # collapsed watcher
    # ------------------------------------------------------------------

    def watch_collapsed(self, old: bool, new: bool) -> None:
        # Hide block._body (ToolBodyContainer) only — ToolHeader stays visible
        # so click-to-expand works on a collapsed block.
        body_container = getattr(self._block, "_body", None)
        if body_container is not None:
            body_container.styles.display = "none" if new else "block"

        fp = self._footer_pane
        if fp is None:
            return
        want_fp = (not new) and self._has_footer_content()
        if fp.display != want_fp:
            fp.styles.display = "block" if want_fp else "none"

    def _has_footer_content(self) -> bool:
        rs = self._result_summary_v4
        if rs is None:
            return False
        return bool(
            rs.chips or rs.stderr_tail or rs.actions or rs.artifacts
            or (rs.exit_code not in (None, 0))
        )

    # ------------------------------------------------------------------
    # Completion flow
    # ------------------------------------------------------------------

    def _body_line_count(self) -> int:
        if self._block is None:
            return 0
        for attr in ("_total_received", "_content_line_count"):
            val = getattr(self._block, attr, None)
            if isinstance(val, int):
                return val
        for attr in ("_plain_lines", "_all_plain", "_content_lines"):
            lines = getattr(self._block, attr, None)
            if isinstance(lines, list):
                return len(lines)
        return 0

    def _apply_complete_auto_collapse(self) -> None:
        from hermes_cli.tui.tool_category import _CATEGORY_DEFAULTS
        rs = self._result_summary_v4
        if self._user_collapse_override:
            # Error override: user collapsed but tool errored → force expand
            if rs is not None and rs.is_error and self.collapsed:
                self.collapsed = False
            return
        total = self._body_line_count()
        threshold = _CATEGORY_DEFAULTS[self._category].default_collapsed_lines
        # Diff special-case: write_file / edit_file / patch use threshold=20
        if rs is not None:
            try:
                from hermes_cli.tui.tool_category import spec_for as _spec_for
                spec = _spec_for(self._tool_name or "")
                if spec.primary_result == "diff":
                    threshold = 20
            except Exception:
                pass
        self.collapsed = total > threshold

    def set_result_summary_v4(self, summary: "ResultSummaryV4") -> None:
        """Call from app at tool completion to populate v4 footer + header hero chip."""
        self._result_summary_v4 = summary
        self._completed_at = time.monotonic()

        # Push primary + promoted chips to ToolHeader
        header = getattr(self._block, "_header", None)
        if header is not None:
            if summary.primary is not None:
                header._primary_hero = summary.primary
            primary_text = summary.primary or ""
            promoted: list[tuple[str, str]] = []
            tone_map = {
                "success": "bold green", "warning": "bold yellow",
                "error": "bold red", "accent": "dim cyan", "neutral": "dim",
            }
            for chip in (summary.chips or [])[:3]:
                if chip.text in primary_text:
                    continue
                style = tone_map.get(chip.tone, "dim")
                promoted.append((chip.text, style))
                if len(promoted) >= 2:
                    break
            header._header_chips = promoted
            header.refresh()

        # Render v4 footer
        if self._footer_pane is not None:
            self._footer_pane.update_summary_v4(summary)

        # Auto-collapse / error promotion
        if summary.is_error and not self._user_collapse_override:
            self.collapsed = False  # always show errors
        elif not self._user_collapse_override:
            self._apply_complete_auto_collapse()

        # Show footer when there's something to display
        if self._footer_pane is not None:
            show = self._has_footer_content() and not self.collapsed
            self._footer_pane.styles.display = "block" if show else "none"

        self.post_message(ToolPanel.Completed())

    def copy_content(self) -> str:
        """Return full plain-text output regardless of collapse state."""
        if self._block is None:
            return ""
        fn = getattr(self._block, "copy_content", None)
        if fn is not None:
            try:
                return str(fn())
            except Exception:
                pass
        for attr in ("_all_plain", "_content_lines", "_plain_lines"):
            lines = getattr(self._block, attr, None)
            if isinstance(lines, list):
                return "\n".join(lines)
        return ""

    # ------------------------------------------------------------------
    # Keyboard bindings
    # ------------------------------------------------------------------

    def action_toggle_collapse(self) -> None:
        self.collapsed = not self.collapsed
        self._user_collapse_override = True

    # Focus styling done via CSS :focus pseudo-class in hermes.tcss.
    # on_focus/on_blur avoided: they trigger layout refreshes that interfere
    # with click hit-testing. watch_has_focus is content-only update.

    def watch_has_focus(self, value: bool) -> None:
        if self._hint_row is None:
            return
        if value:
            self._hint_row.update(self._build_hint_text())
        else:
            self._hint_row.update("")

    def _build_hint_text(self) -> str:
        from rich.text import Text
        t = Text()
        t.append("  Enter", style="bold")
        t.append(" toggle  ", style="dim")
        bar = self._get_omission_bar()
        if bar is not None:
            t.append("+/-", style="bold")
            t.append(" lines  ", style="dim")
            t.append("*", style="bold")
            t.append(" all  ", style="dim")
        t.append("c", style="bold")
        t.append(" copy", style="dim")
        return t

    def _get_omission_bar(self) -> "Any | None":
        try:
            from hermes_cli.tui.tool_blocks import OmissionBar as _OB
            block = self._block
            bar = getattr(block, "_omission_bar", None)
            if isinstance(bar, _OB) and getattr(block, "_omission_bar_mounted", False):
                return bar
        except Exception:
            pass
        return None

    def action_expand_lines(self) -> None:
        bar = self._get_omission_bar()
        if bar is not None:
            bar._do_expand_one()

    def action_collapse_lines(self) -> None:
        bar = self._get_omission_bar()
        if bar is not None:
            bar._do_collapse_one()

    def action_expand_all_lines(self) -> None:
        bar = self._get_omission_bar()
        if bar is not None:
            bar._do_expand_all()
