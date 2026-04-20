"""ToolPanel — binary collapse, result wiring, keyboard.

Architecture: tui-tool-panel-spec-binary-collapse.md

collapsed = False  →  header + body + conditional footer  (always at mount)
collapsed = True   →  header only  (auto at completion when body > threshold)
"""

from __future__ import annotations

import subprocess
import sys
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


# Footer action kinds that have real BINDINGS wired — deferred kinds are
# silently skipped from footer display until implemented.
_IMPLEMENTED_ACTIONS: frozenset[str] = frozenset({
    "copy_body", "open_first", "copy_err", "copy_paths", "retry",
})


def _artifact_icon(kind: str) -> str:
    """Return the icon character for an artifact kind, respecting tool_icon_mode."""
    from agent.display import get_tool_icon_mode as _gim
    _mode = _gim()
    if _mode in ("auto", "nerdfont"):
        _icons = {"file": "\uf15b", "url": "\uf0c1", "image": "\uf03e"}
    elif _mode == "emoji":
        _icons = {"file": "📎", "url": "🔗", "image": "🖼"}
    else:
        _icons = {"file": "[F]", "url": "[L]", "image": "[I]"}
    return _icons.get(kind, "[?]")


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
                import logging
                logging.getLogger(__name__).debug(
                    "BodyPane renderer init failed for %r", category, exc_info=True
                )
                from hermes_cli.tui.body_renderer import PlainBodyRenderer
                self._renderer = PlainBodyRenderer()
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
        height: auto;
        max-height: 4;
        display: none;
        color: $error 80%;
        padding: 0;
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

    def _render_stderr(self, tail: str) -> "Any":
        from rich.text import Text
        lines = tail.strip().splitlines()
        result = Text()
        for i, line in enumerate(lines):
            if i > 0:
                result.append("\n")
            result.append(f"  {line}", style="dim red")
        return result

    def update_summary_v4(
        self,
        summary: "ResultSummaryV4",
        promoted_chip_texts: "frozenset[str]" = frozenset(),
    ) -> None:
        """Re-render footer from a ResultSummaryV4 (v4 §4.2)."""
        from rich.text import Text

        parts = Text()

        # Chips row (skip chips already promoted to header)
        chips = [c for c in summary.chips if c.text not in promoted_chip_texts]
        for chip in chips:
            tone_style = {
                "success": "bold green",
                "warning": "bold yellow",
                "error": "bold red",
                "accent": "bold cyan",
                "neutral": "dim",
            }.get(chip.tone, "dim")
            parts.append(f" {chip.text} ", style=tone_style)

        # Action row — only implemented actions
        if summary.actions:
            parts.append("  ")
            for action in summary.actions:
                if action.kind not in _IMPLEMENTED_ACTIONS:
                    continue
                parts.append(f"[{action.hotkey}]", style="dim bold")
                parts.append(f" {action.label}  ", style="dim")

        # Artifact chips (file/url labels)
        if summary.artifacts:
            for artifact in summary.artifacts:
                icon = _artifact_icon(artifact.kind)
                parts.append(f" {icon} {artifact.label} ", style="dim cyan")

        self._content.update(parts)

        # Stderr split row — multi-line, last 300 chars
        if summary.stderr_tail:
            self._stderr_row.update(self._render_stderr(summary.stderr_tail))
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
        Binding("enter", "toggle_collapse",  "Toggle",        show=False),
        Binding("c",     "copy_body",        "Copy output",   show=False),
        Binding("o",     "open_primary",     "Open",          show=False),
        Binding("e",     "copy_err",         "Copy stderr",   show=False),
        Binding("p",     "copy_paths",       "Copy paths",    show=False),
        Binding("+",     "expand_lines",     "Expand lines",  show=False),
        Binding("-",     "collapse_lines",   "Collapse lines",show=False),
        Binding("*",     "expand_all_lines", "Expand all",    show=False),
        Binding("r",     "retry",            "Retry",         show=False),
        Binding("j",     "scroll_body_down", "↓",             show=False),
        Binding("k",     "scroll_body_up",   "↑",             show=False),
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
        promoted_texts: frozenset[str] = frozenset()
        header = getattr(self._block, "_header", None)
        if header is not None:
            if summary.primary is not None:
                header._primary_hero = summary.primary
            header._error_kind = summary.error_kind
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
            promoted_texts = frozenset(text for text, _ in promoted)

        # Render v4 footer (skip chips already in header)
        if self._footer_pane is not None:
            self._footer_pane.update_summary_v4(summary, promoted_chip_texts=promoted_texts)

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

    def action_open_primary(self) -> None:
        """Open header path if path-clickable; else fall back to first file artifact (C1)."""
        import os
        import shlex
        header = getattr(self._block, "_header", None)
        if header is not None and getattr(header, "_path_clickable", False) and header._full_path:
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            try:
                self.app._open_path_action(header, header._full_path, opener, False)  # type: ignore[attr-defined]
                self._flash_header("opening…")
            except Exception:
                pass
            return
        # Fallback: first file artifact
        paths = self._result_paths_for_action()
        if not paths:
            return
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
        if editor:
            subprocess.Popen([*shlex.split(editor), paths[0]])
        else:
            open_cmd = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([open_cmd, paths[0]])
        self._flash_header("opening…")

    # ------------------------------------------------------------------
    # Footer actions — Phase A
    # ------------------------------------------------------------------

    def _result_paths_for_action(self) -> list[str]:
        rs = self._result_summary_v4
        paths: list[str] = []
        if rs is not None:
            for artifact in (rs.artifacts or ()):
                if artifact.kind == "file":
                    paths.append(artifact.path_or_url)
        if not paths:
            paths = list(self._result_paths)
        return paths

    def _flash_header(self, msg: str) -> None:
        header = getattr(self._block, "_header", None)
        if header is None:
            return
        header._flash_msg = msg
        header._flash_expires = time.monotonic() + 1.2
        header.refresh()
        self.set_timer(1.3, lambda: setattr(header, "_flash_msg", None) or header.refresh())

    def action_copy_body(self) -> None:
        text = self.copy_content()
        if not text:
            return
        self.app._copy_text_with_hint(text)
        self._flash_header("copied")

    def action_open_first(self) -> None:
        paths = self._result_paths_for_action()
        if not paths:
            return
        import os
        import shlex
        editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
        if editor:
            subprocess.Popen([*shlex.split(editor), paths[0]])
        else:
            open_cmd = "open" if sys.platform == "darwin" else "xdg-open"
            subprocess.Popen([open_cmd, paths[0]])
        self._flash_header("opening…")

    def action_copy_err(self) -> None:
        rs = self._result_summary_v4
        if rs is None or not rs.stderr_tail:
            return
        self.app._copy_text_with_hint(rs.stderr_tail)
        self._flash_header("copied stderr")

    def action_copy_paths(self) -> None:
        paths = self._result_paths_for_action()
        if not paths:
            return
        self.app._copy_text_with_hint("\n".join(paths))
        self._flash_header(f"copied {len(paths)} path(s)")

    def action_retry(self) -> None:
        rs = self._result_summary_v4
        if rs is None or not rs.is_error:
            return
        try:
            self.app._initiate_retry()
        except Exception:
            self._flash_header("retry failed")

    def action_scroll_body_down(self) -> None:
        """Scroll tool body down (j) (C2)."""
        if self.collapsed:
            return
        try:
            from hermes_cli.tui.widgets import CopyableRichLog
            log = self._block._body.query_one(CopyableRichLog)
            log.scroll_down(animate=False)
        except Exception:
            pass

    def action_scroll_body_up(self) -> None:
        """Scroll tool body up (k) (C2)."""
        if self.collapsed:
            return
        try:
            from hermes_cli.tui.widgets import CopyableRichLog
            log = self._block._body.query_one(CopyableRichLog)
            log.scroll_up(animate=False)
        except Exception:
            pass

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

    def _build_hint_text(self) -> "Any":
        from rich.text import Text
        t = Text()
        t.append("  Enter", style="bold"); t.append(" toggle  ", style="dim")
        bar = self._get_omission_bar()
        if bar is not None:
            t.append("+/-", style="bold"); t.append(" lines  ", style="dim")
            t.append("*", style="bold"); t.append(" all  ", style="dim")
        if not self.collapsed:
            t.append("j/k", style="bold"); t.append(" scroll  ", style="dim")
        t.append("c", style="bold"); t.append(" copy  ", style="dim")
        rs = self._result_summary_v4
        if rs is not None:
            if rs.is_error:
                t.append("r", style="bold"); t.append(" retry  ", style="dim")
            if rs.stderr_tail:
                t.append("e", style="bold"); t.append(" stderr  ", style="dim")
            if self._result_paths_for_action():
                t.append("o", style="bold"); t.append(" open  ", style="dim")
                t.append("p", style="bold"); t.append(" paths", style="dim")
        return t

    def _get_omission_bar(self) -> "Any | None":
        try:
            from hermes_cli.tui.tool_blocks import OmissionBar as _OB
            block = self._block
            bar = getattr(block, "_omission_bar_bottom", None)
            if isinstance(bar, _OB) and getattr(block, "_omission_bar_bottom_mounted", False):
                return bar
        except Exception:
            pass
        return None

    def action_expand_lines(self) -> None:
        bar = self._get_omission_bar()
        if bar is not None:
            from hermes_cli.tui.tool_blocks import _PAGE_SIZE
            block = self._block
            bar._parent_block.rerender_window(
                bar._visible_start,
                min(bar._total, bar._visible_end + _PAGE_SIZE),
            )

    def action_collapse_lines(self) -> None:
        bar = self._get_omission_bar()
        if bar is None:
            return
        from hermes_cli.tui.tool_blocks import _PAGE_SIZE, _VISIBLE_CAP
        new_start = max(0, bar._visible_start - _PAGE_SIZE)
        new_end = max(_VISIBLE_CAP, bar._visible_end - _PAGE_SIZE)
        if new_start == bar._visible_start and new_end == bar._visible_end:
            self._flash_header("at minimum")
            return
        bar._parent_block.rerender_window(new_start, new_end)

    def action_expand_all_lines(self) -> None:
        bar = self._get_omission_bar()
        if bar is not None:
            bar._parent_block.rerender_window(bar._visible_start, bar._total)
