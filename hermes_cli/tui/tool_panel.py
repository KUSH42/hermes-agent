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

_TONE_STYLES: dict[str, str] = {
    "success": "bold green",
    "warning": "bold yellow",
    "error": "bold red",
    "accent": "bold cyan",
    "neutral": "dim",
}

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Static

from hermes_cli.tui.resize_utils import THRESHOLD_NARROW, crosses_threshold

if TYPE_CHECKING:
    from hermes_cli.tui.tool_result_parse import ResultSummary, ResultSummaryV4
    from hermes_cli.tui.tool_category import ToolCategory


# Footer action kinds that have real BINDINGS wired — deferred kinds are
# silently skipped from footer display until implemented.
_IMPLEMENTED_ACTIONS: frozenset[str] = frozenset({
    "copy_body", "open_first", "copy_err", "copy_paths", "retry",
    "copy_invocation", "copy_urls",  # G1, G2
    "edit_cmd", "open_url",          # A1, A2
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
        self._renderer_degraded: bool = False
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
                self._renderer_degraded = True
        else:
            self._renderer = None

    def on_mount(self) -> None:
        if self._renderer_degraded:
            self.add_class("--body-degraded")

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
    FooterPane > .footer-remediation {
        height: auto;
        display: none;
        color: $text-muted;
        padding: 0;
    }
    FooterPane.has-remediation > .footer-remediation { display: block; }
    FooterPane > .artifact-row {
        height: auto;
        layout: horizontal;
        display: none;
    }
    FooterPane.has-artifacts > .artifact-row { display: block; }
    FooterPane > .artifact-row > .--artifact-chip {
        height: 1;
        border: none;
        background: transparent;
        min-width: 0;
        color: $accent-muted;
    }
    """

    COMPONENT_CLASSES = {"footer--exit-chip", "footer--badge", "footer--retry-hint"}

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._show_all_artifacts: bool = False  # B3: show all after overflow button click
        self._last_summary: "ResultSummaryV4 | None" = None
        self._last_promoted: "frozenset[str]" = frozenset()
        self._last_resize_w: int = 0

    def compose(self) -> ComposeResult:
        self._content = Static("", classes="footer-main")
        self._stderr_row = Static("", classes="footer-stderr")
        self._remediation_row = Static("", classes="footer-remediation")
        self._artifact_row = Horizontal(classes="artifact-row")
        yield self._content
        yield self._stderr_row
        yield self._remediation_row
        yield self._artifact_row

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
        self._last_summary = summary
        self._last_promoted = promoted_chip_texts
        self._render_footer(summary, promoted_chip_texts)

    def _render_footer(
        self,
        summary: "ResultSummaryV4",
        promoted_chip_texts: "frozenset[str]",
    ) -> None:
        """Internal render — called from update_summary_v4 and _rebuild_chips."""
        from rich.text import Text

        parts = Text()

        # Chips row (skip chips already promoted to header)
        chips = [c for c in summary.chips if c.text not in promoted_chip_texts]
        for chip in chips:
            tone_style = _TONE_STYLES.get(chip.tone, "dim")
            parts.append(f" {chip.text} ", style=tone_style)

        # Payload-truncated warning chip
        if any(getattr(a, "payload_truncated", False) for a in summary.actions):
            parts.append(" truncated ", style=_TONE_STYLES["warning"])

        # Action row — only implemented actions
        if summary.actions:
            parts.append("  ")
            for action in summary.actions:
                if action.kind not in _IMPLEMENTED_ACTIONS:
                    continue
                parts.append(f"[{action.hotkey}]", style="dim bold")
                parts.append(f" {action.label}  ", style="dim")

        self._content.update(parts)

        # D2: rebuild artifact row with clickable buttons
        self._rebuild_artifact_buttons(summary)

        # Stderr split row — multi-line, last 300 chars
        if summary.stderr_tail:
            self._stderr_row.update(self._render_stderr(summary.stderr_tail))
            self.add_class("has-stderr")
        else:
            self._stderr_row.update("")
            self.remove_class("has-stderr")

        # A2: remediation hint — any chip with non-None remediation
        remediation_hints = [
            c.remediation for c in summary.chips if getattr(c, "remediation", None)
        ]
        if remediation_hints:
            from rich.text import Text as _T
            rem_text = _T()
            rem_text.append("  hint: ", style="dim")
            rem_text.append("  ·  ".join(remediation_hints), style="dim italic")
            self._remediation_row.update(rem_text)
            self.add_class("has-remediation")
        else:
            self._remediation_row.update("")
            self.remove_class("has-remediation")

    def _rebuild_chips(self) -> None:
        """B3: re-render after _show_all_artifacts changes."""
        if self._last_summary is not None:
            self._render_footer(self._last_summary, self._last_promoted)

    def _rebuild_artifact_buttons(self, summary: "ResultSummaryV4") -> None:
        """D2/D4: rebuild artifact row with clickable Button per artifact."""
        from hermes_cli.tui.tool_result_parse import _ARTIFACT_DISPLAY_CAP
        # Remove old artifact chip buttons
        try:
            for btn in list(self._artifact_row.query(".--artifact-chip")):
                btn.remove()
        except Exception:
            pass
        # Also remove old overflow buttons inside artifact_row
        try:
            for btn in list(self._artifact_row.query(".--artifact-overflow")):
                btn.remove()
        except Exception:
            pass
        # D4: also remove old collapse buttons
        try:
            for btn in list(self._artifact_row.query(".--artifact-collapse")):
                btn.remove()
        except Exception:
            pass

        if not summary.artifacts:
            self.remove_class("has-artifacts")
            return

        artifacts_to_show = (
            summary.artifacts
            if self._show_all_artifacts
            else summary.artifacts[:_ARTIFACT_DISPLAY_CAP]
        )
        buttons = []
        for artifact in artifacts_to_show:
            icon = _artifact_icon(artifact.kind)
            label = f"{icon} {artifact.label}"
            btn = Button(label, classes="--artifact-chip")
            btn._artifact_path = artifact.path_or_url  # type: ignore[attr-defined]
            btn._artifact_kind = artifact.kind          # type: ignore[attr-defined]
            buttons.append(btn)

        if (
            not self._show_all_artifacts
            and getattr(summary, "artifacts_truncated", False)
        ):
            n_hidden = len(summary.artifacts) - _ARTIFACT_DISPLAY_CAP
            overflow_artifacts = summary.artifacts[_ARTIFACT_DISPLAY_CAP:]
            if any(a.kind == "url" for a in overflow_artifacts):
                overflow_tooltip = "press u to copy all URLs"
            else:
                overflow_tooltip = "press p to copy paths"
            overflow_btn = Button(f"+{n_hidden} more", classes="--artifact-overflow")
            overflow_btn._overflow_remediation = overflow_tooltip  # type: ignore[attr-defined]
            buttons.append(overflow_btn)

        # D4: collapse button when showing all
        if self._show_all_artifacts:
            collapse_btn = Button("↑ fewer", classes="--artifact-collapse")
            buttons.append(collapse_btn)

        if buttons:
            self._artifact_row.mount(*buttons)
        self.add_class("has-artifacts")

    def on_button_pressed(self, event: "Button.Pressed") -> None:
        """B3: artifact overflow; D2: artifact chip click; D4: collapse."""
        if "--artifact-overflow" in event.button.classes:
            self._show_all_artifacts = True
            self._rebuild_chips()
            event.stop()
            return
        # D4: collapse back to truncated view
        if "--artifact-collapse" in event.button.classes:
            self._show_all_artifacts = False
            self._rebuild_chips()
            event.stop()
            return
        if "--artifact-chip" in event.button.classes:
            path = getattr(event.button, "_artifact_path", None)
            if path:
                import sys as _sys
                open_cmd = "open" if _sys.platform == "darwin" else "xdg-open"
                try:
                    subprocess.Popen([open_cmd, path])
                except Exception:
                    pass
            event.stop()

    def on_resize(self, event: object) -> None:
        width = getattr(getattr(event, "size", None), "width", 80)
        if crosses_threshold(self._last_resize_w, width, THRESHOLD_NARROW):
            self.set_class(width < THRESHOLD_NARROW, "compact")
        self._last_resize_w = width


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

    class PathFocused(Message):
        """Posted on first focus when block has a clickable path (OSC 8 hint)."""
        def __init__(self, panel: "ToolPanel") -> None:
            super().__init__()
            self.panel = panel

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
        Binding("enter", "toggle_collapse",  "Toggle",           show=False),
        Binding("c",     "copy_body",        "Copy output",      show=False),
        Binding("C",     "copy_ansi",        "Copy +color",      show=False),
        Binding("H",     "copy_html",        "Copy HTML",        show=False),
        Binding("I",     "copy_invocation",  "Copy invocation",  show=False),
        Binding("u",     "copy_urls",        "Copy URLs",        show=False),
        Binding("o",     "open_primary",     "Open",             show=False),
        Binding("e",     "copy_err",         "Copy stderr",      show=False),
        Binding("p",     "copy_paths",       "Copy paths",       show=False),
        Binding("+",     "expand_lines",     "Expand lines",     show=False),
        Binding("-",     "collapse_lines",   "Collapse lines",   show=False),
        Binding("*",     "expand_all_lines", "Expand all",       show=False),
        Binding("r",     "retry",            "Retry",            show=False),
        Binding("E",     "edit_cmd",         "Edit cmd",         show=False),
        Binding("O",     "open_url",         "Open URL",         show=False),
        Binding("f",     "toggle_tail_follow", "tail", show=False),
        Binding("j",     "scroll_body_down",      "↓",    show=False),
        Binding("k",     "scroll_body_up",        "↑",    show=False),
        Binding("J",     "scroll_body_page_down", "↓↓",   show=False),
        Binding("K",     "scroll_body_page_up",   "↑↑",   show=False),
        Binding("<",     "scroll_body_top",        "Top",  show=False),
        Binding(">",     "scroll_body_bottom",     "End",  show=False),
        Binding("question_mark", "show_help",      "Keys", show=False),
        Binding("P",     "copy_full_path",   "Copy full path",   show=False),  # A7
        Binding("x",     "dismiss_error_banner", "Dismiss",      show=False),  # A5
        Binding("question_mark", "show_context_menu", "Menu",    show=False),  # D1
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
        self._last_resize_w: int = 0
        self._saved_visible_start: int | None = None  # B6: preserve scroll position

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
        # B6: save/restore visible window position across collapse/expand
        if new:
            # Collapsing — save visible_start
            if hasattr(self._block, "_visible_start"):
                self._saved_visible_start = self._block._visible_start
        else:
            # Expanding — restore visible window if we have a saved position
            if (self._saved_visible_start is not None and
                    hasattr(self._block, "_visible_start") and
                    hasattr(self._block, "_all_plain")):
                saved = self._saved_visible_start
                total = len(self._block._all_plain)
                visible_cap = getattr(self._block, "_visible_cap", 200)
                end = min(total, saved + visible_cap)
                if saved > 0:
                    try:
                        self._block.rerender_window(saved, end)
                    except Exception:
                        pass

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
        if self._user_collapse_override:
            return
        rs = self._result_summary_v4
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

        # F1: schedule "completed Xs ago" age microcopy at 10s post-completion
        _completed_at_snap = self._completed_at
        def _show_age() -> None:
            elapsed = int(time.monotonic() - _completed_at_snap)
            if hasattr(self._block, "set_age_microcopy"):
                self._block.set_age_microcopy(f"completed {elapsed}s ago")
        self.set_timer(10.0, _show_age)

        # Push primary + promoted chips to ToolHeader
        promoted_texts: frozenset[str] = frozenset()
        header = getattr(self._block, "_header", None)
        if header is not None:
            if summary.primary is not None:
                header._primary_hero = summary.primary
            header._error_kind = summary.error_kind
            primary_text = summary.primary or ""
            promoted: list[tuple[str, str]] = []
            for chip in (summary.chips or [])[:3]:
                if chip.text in primary_text:
                    continue
                style = _TONE_STYLES.get(chip.tone, "dim")
                promoted.append((chip.text, style))
                if len(promoted) >= 2:
                    break
            header._header_chips = promoted
            header.refresh()
            promoted_texts = frozenset(text for text, _ in promoted)

        # Render v4 footer (skip chips already in header)
        if self._footer_pane is not None:
            self._footer_pane.update_summary_v4(summary, promoted_chip_texts=promoted_texts)

        # A1: sub-500ms closure flash — if microcopy never shown, flash "done" on header
        if not summary.is_error:
            block_microcopy_shown = getattr(self._block, "_microcopy_shown", True)
            if not block_microcopy_shown and header is not None:
                header._flash_msg = "done"
                header._flash_expires = time.monotonic() + 0.5

        # A5: error banner — mount between header and body
        if header is not None:
            # Remove any existing error banner first
            try:
                for existing in list(self._block.query(".error-banner")):
                    existing.remove()
            except Exception:
                pass
            if summary.is_error and summary.error_kind is not None:
                try:
                    _ICON_MAP = {
                        "timeout": "⏱",
                        "signal": "💀",
                        "auth": "🔒",
                        "exit": "✗",
                        "network": "🌐",
                    }
                    from hermes_cli.tui.tool_result_parse import _SHELL_REMEDIATIONS
                    icon = _ICON_MAP.get(summary.error_kind, "✗")
                    kind_label = summary.error_kind.replace("_", " ").title()
                    # Find remediation from chips
                    remediation = next(
                        (c.remediation for c in (summary.chips or ()) if c.remediation),
                        None
                    )
                    if remediation:
                        banner_text = f"  {icon}  {kind_label}  ·  {remediation}"
                    else:
                        banner_text = f"  {icon}  {kind_label}"
                    from textual.widgets import Static as _Static
                    banner = _Static(banner_text, classes="error-banner")
                    self._block.mount(banner, after=header)
                except Exception:
                    pass

        # Auto-collapse / error promotion
        # D1: errors always expand regardless of user collapse override
        if summary.is_error:
            self.collapsed = False
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
                if artifact.kind in ("file", "url"):
                    paths.append(artifact.path_or_url)
        if not paths:
            paths = list(self._result_paths)
        return paths

    def _flash_header(self, msg: str, tone: str = "success") -> None:
        """C5: flash msg on header with tone-aware color."""
        header = getattr(self._block, "_header", None)
        if header is None:
            return
        header._flash_msg = msg
        header._flash_tone = tone  # C5: tone for color selection
        header._flash_expires = time.monotonic() + 1.2
        header.refresh()
        self.set_timer(1.2, lambda: setattr(header, "_flash_msg", None) or header.refresh())

    def action_copy_body(self) -> None:
        text = self.copy_content()
        if not text:
            return
        self.app._copy_text_with_hint(text)
        self._flash_header("copied text")

    def action_open_url(self) -> None:
        """A2: open first URL artifact or open_url action payload."""
        rs = self._result_summary_v4
        url: str | None = None
        if rs is not None:
            # Prefer explicit open_url payload
            for action in (rs.actions or ()):
                if action.kind == "open_url" and action.payload:
                    url = action.payload
                    break
            if not url:
                for artifact in (rs.artifacts or ()):
                    if artifact.kind == "url":
                        url = artifact.path_or_url
                        break
        if not url:
            return
        open_cmd = "open" if sys.platform == "darwin" else "xdg-open"
        try:
            subprocess.Popen([open_cmd, url])
            self._flash_header("opening…")
        except Exception:
            self._flash_header("open failed")

    def action_edit_cmd(self) -> None:
        """A1: pre-populate input with the failed command for editing."""
        rs = self._result_summary_v4
        payload: str | None = None
        if rs is not None:
            for action in (rs.actions or ()):
                if action.kind == "edit_cmd" and action.payload:
                    payload = action.payload
                    break
        if not payload:
            return
        try:
            from hermes_cli.tui.input_widget import HermesInput
            inp = self.app.query_one(HermesInput)
            # Save existing input to history before overwriting
            existing = inp.text.strip() if hasattr(inp, "text") else ""
            if existing:
                try:
                    inp._save_to_history(existing)
                except Exception:
                    pass
            inp.value = payload
            inp.focus()
            self._flash_header("edit cmd")
        except Exception:
            self._flash_header("edit unavailable")

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
        self._flash_header(f"copied paths ({len(paths)})")

    def action_retry(self) -> None:
        rs = self._result_summary_v4
        if rs is None or not rs.is_error:
            self._flash_header("no error")
            return
        try:
            self.app._initiate_retry()
        except Exception:
            self._flash_header("retry failed")

    def action_copy_invocation(self) -> None:
        """G1: copy tool name + args + body as plain text."""
        terminal_width = getattr(self.app, "size", None)
        terminal_width = terminal_width.width if terminal_width else 80
        try:
            from hermes_cli.tui.tool_category import spec_for, ToolCategory
            spec = spec_for(self._tool_name or "")
            is_shell = spec.category == ToolCategory.SHELL
            cat_name = spec.category.value
        except Exception:
            is_shell = False
            cat_name = "tool"
        label = self._tool_name or "tool"
        if is_shell:
            block = self._block
            cmd = ""
            if block is not None:
                args = getattr(block, "_header", None)
                args = getattr(args, "_header_args", {}) if args else {}
                cmd = str(args.get("command") or args.get("cmd") or "")
            header_line = f"{label} (shell)  $  {cmd}"
        else:
            primary_label = self._tool_name or "tool"
            block = self._block
            if block is not None:
                _hdr = getattr(block, "_header", None)
                if _hdr is not None:
                    primary_label = _hdr._label or primary_label
            header_line = f"{label} ({cat_name})    {primary_label}"
        sep_len = min(40, terminal_width - 4)
        separator = "─" * sep_len
        body = self.copy_content()
        text = "\n".join([header_line, separator, body])
        self.app._copy_text_with_hint(text)
        self._flash_header("copied invocation")  # C5: format label

    def action_copy_ansi(self) -> None:
        """C5: copy with ANSI color codes."""
        import io
        from rich.console import Console
        terminal_width = getattr(self.app, "size", None)
        terminal_width = terminal_width.width if terminal_width else 80
        block = self._block
        if block is None:
            return
        # Try _all_rich from StreamingToolBlock / CopyableRichLog
        all_rich = getattr(block, "_all_rich", None)
        if all_rich is None:
            try:
                from hermes_cli.tui.widgets import CopyableRichLog
                rl = block._body.query_one(CopyableRichLog)
                all_rich = getattr(rl, "_all_rich", None)
            except Exception:
                pass
        if not all_rich:
            # Fallback: plain copy
            self.action_copy_body()
            return
        buf = io.StringIO()
        console = Console(force_terminal=True, width=terminal_width, file=buf, highlight=False)
        for t in all_rich:
            console.print(t, highlight=False)
        ansi_text = buf.getvalue()
        self.app._copy_text_with_hint(ansi_text)
        self._flash_header("copied ANSI")

    def action_copy_html(self) -> None:
        """C5: copy as HTML with inline styles."""
        import time as _time
        from rich.console import Console
        terminal_width = getattr(self.app, "size", None)
        terminal_width = terminal_width.width if terminal_width else 80
        block = self._block
        if block is None:
            return
        all_rich = getattr(block, "_all_rich", None)
        if all_rich is None:
            try:
                from hermes_cli.tui.widgets import CopyableRichLog
                rl = block._body.query_one(CopyableRichLog)
                all_rich = getattr(rl, "_all_rich", None)
            except Exception:
                pass
        if not all_rich:
            return
        console = Console(record=True, width=terminal_width)
        for t in all_rich:
            console.print(t, highlight=False)
        html = console.export_html(inline_styles=True)
        # Inject skin background color
        try:
            bg_hex = self.app.get_css_variables().get("base", "#1e1e2e")
        except Exception:
            bg_hex = "#1e1e2e"
        html = html.replace('<pre style="', f'<pre style="background:{bg_hex}; ', 1)
        tmp_path = f"/tmp/hermes_copy_{int(_time.time())}.html"
        self.app._copy_text_with_hint(html)
        try:
            with open(tmp_path, "w") as f:
                f.write(html)
            self._flash_header(f"copied HTML  (saved {tmp_path})")
        except Exception:
            self._flash_header("copied HTML")

    def action_copy_urls(self) -> None:
        """G2: copy newline-joined URL artifacts."""
        rs = self._result_summary_v4
        if rs is None:
            return
        urls = [a.path_or_url for a in rs.artifacts if a.kind == "url"]
        if not urls:
            return
        self.app._copy_text_with_hint("\n".join(urls))
        self._flash_header(f"copied URLs ({len(urls)})")

    def action_copy_full_path(self) -> None:
        """A7: copy full untruncated path from header."""
        header = getattr(self._block, "_header", None)
        if header is None:
            return
        path = getattr(header, "_full_path", None)
        if not path:
            return
        self.app._copy_text_with_hint(path)
        self._flash_header("copied path")

    def action_dismiss_error_banner(self) -> None:
        """A5: dismiss the error banner (x key)."""
        try:
            for banner in list(self._block.query(".error-banner")):
                banner.remove()
        except Exception:
            pass

    def action_show_context_menu(self) -> None:
        """D1: show context menu at header center (keyboard-accessible path)."""
        header = getattr(self._block, "_header", None)
        if header is None:
            return
        try:
            header._show_context_menu_at_center()
        except Exception:
            pass

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

    def action_scroll_body_page_down(self) -> None:
        """Scroll tool body down by a page (J)."""
        if self.collapsed:
            return
        try:
            from hermes_cli.tui.widgets import CopyableRichLog
            log = self._block._body.query_one(CopyableRichLog)
            page = max(5, (self.size.height or 20) // 2)
            log.scroll_relative(y=page, animate=False)
        except Exception:
            pass

    def action_scroll_body_page_up(self) -> None:
        """Scroll tool body up by a page (K)."""
        if self.collapsed:
            return
        try:
            from hermes_cli.tui.widgets import CopyableRichLog
            log = self._block._body.query_one(CopyableRichLog)
            page = max(5, (self.size.height or 20) // 2)
            log.scroll_relative(y=-page, animate=False)
        except Exception:
            pass

    def action_scroll_body_top(self) -> None:
        """Scroll tool body to top (<)."""
        if self.collapsed:
            return
        try:
            from hermes_cli.tui.widgets import CopyableRichLog
            log = self._block._body.query_one(CopyableRichLog)
            log.scroll_home(animate=False)
        except Exception:
            pass

    def action_scroll_body_bottom(self) -> None:
        """Scroll tool body to bottom (>)."""
        if self.collapsed:
            return
        try:
            from hermes_cli.tui.widgets import CopyableRichLog
            log = self._block._body.query_one(CopyableRichLog)
            log.scroll_end(animate=False)
        except Exception:
            pass

    def action_show_help(self) -> None:
        """E1: show/hide ToolPanel key reference overlay."""
        from hermes_cli.tui.overlays import ToolPanelHelpOverlay
        try:
            existing = self.app.query_one(ToolPanelHelpOverlay)
            existing.hide_overlay()
        except Exception:
            overlay = ToolPanelHelpOverlay()
            self.app.mount(overlay)
            overlay.show_overlay()

    # Focus styling done via CSS :focus pseudo-class in hermes.tcss.
    # on_focus/on_blur avoided: they trigger layout refreshes that interfere
    # with click hit-testing. watch_has_focus is content-only update.

    def watch_has_focus(self, value: bool) -> None:
        if self._hint_row is None:
            return
        if value:
            self._hint_row.update(self._build_hint_text())
            # P1-7: emit once so app can show "o to open" hint in non-OSC-8 terminals
            try:
                block = self._block
                if block is not None and getattr(block._header, "_path_clickable", False):
                    self.post_message(ToolPanel.PathFocused(self))
            except Exception:
                pass
        else:
            self._hint_row.update("")

    def on_resize(self, event: object) -> None:
        width = getattr(getattr(event, "size", None), "width", 80)
        self._last_resize_w = width
        if self.has_focus and self._hint_row is not None:
            self._hint_row.update(self._build_hint_text())

    def _build_hint_text(self) -> "Any":
        from rich.text import Text
        _mounted = getattr(self, "is_mounted", True)
        _size = getattr(self, "size", None)
        width = ((_size.width if _size is not None else 0) or 80) if _mounted else 80
        narrow = width < 50

        rs = self._result_summary_v4
        hints: list[tuple[str, str, str]] = []  # (key, sep, label)

        # D3: state-aware hints
        if rs is not None and rs.is_error:
            hints.append(("r", " ", "retry  "))
            has_edit = any(a.kind == "edit_cmd" and a.payload for a in (rs.actions or ()))
            if has_edit:
                hints.append(("E", " ", "edit cmd  "))

        hints.append(("?", " ", "menu  "))  # D1: always show menu hint
        hints.append(("c", " ", "copy  "))

        if not narrow:
            hints.append(("  Enter", " ", "toggle  "))
            bar = self._get_omission_bar()
            if bar is not None:
                hints.append(("+/-", " ", "lines  "))
                hints.append(("*", " ", "all  "))
            # D3: j/k scroll only when expanded
            if not self.collapsed:
                hints.append(("j/k", " ", "scroll  "))
            hints.append(("C/H", " ", "color/html  "))
            hints.append(("I", " ", "invocation  "))
            if rs is not None:
                # D3: stderr hint only when there is stderr
                if rs.stderr_tail:
                    hints.append(("e", " ", "stderr  "))
                # D3: error banner dismiss
                try:
                    if list(self.query(".error-banner")):
                        hints.append(("x", " ", "dismiss  "))
                except Exception:
                    pass
                if self._result_paths_for_action():
                    hints.append(("o", " ", "open  "))
                    hints.append(("p", " ", "paths"))
                has_urls = any(a.kind == "url" for a in (rs.artifacts or ()))
                if has_urls:
                    hints.append(("  O", " ", "url  "))
                    hints.append(("u", " ", "copy urls"))
                # D3: O open only when path-clickable
                try:
                    if getattr(self._block._header, "_path_clickable", False):
                        if not any(h[0] == "o" for h in hints):
                            hints.append(("O", " ", "open  "))
                except Exception:
                    pass

        t = Text()
        max_hints = 3 if narrow else len(hints)
        for key, sep, label in hints[:max_hints]:
            t.append(key, style="bold")
            t.append(sep + label, style="dim")
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

    def action_toggle_tail_follow(self) -> None:
        """C2: toggle tail-follow mode on the streaming block."""
        from hermes_cli.tui.tool_blocks import StreamingToolBlock
        block = self._block
        if not isinstance(block, StreamingToolBlock):
            return
        block._follow_tail = not block._follow_tail
        state = "on" if block._follow_tail else "off"
        self._flash_header(f"tail: {state}")
