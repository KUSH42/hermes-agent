"""ToolPanel — Phase 3 detail levels, ArgsPane, FooterPane, keyboard.

Architecture: tui-tool-panel-v2-spec.md §3, §6, §8, §9 Phase 3.
v3 Phase A: ToolAccent gutter rail, DiffAffordance, CWD stripping.
v3 Phase B: ToolHeaderBar (status glyph + chips), ToolPanelMini auto-select.
v3 Phase D: InputSection, SectionDivider, full keyboard bindings, TurnPhase infra.

Phase 1: ToolPanel shell + ToolCategory + accent bar.
Phase 2: BodyPane._renderer wired; BodyRenderer delegates per-line formatting.
Phase 3: detail_level watcher active; ArgsPane/FooterPane live; D/0-3/Enter keys.
v3-A:    ToolAccent replaces border-left; DiffAffordance in FooterPane.
v3-B:    ToolHeaderBar above BodyPane; mini-mode for qualifying SHELL calls.
v3-D:    InputSection + full keybindings (space/y/Y/r) + CSS level classes.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from rich.table import Table
from textual.app import ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.tool_accent import ToolAccent
from hermes_cli.tui.diff_affordance import DiffAffordance
from hermes_cli.tui.tool_header_bar import ToolHeaderBar

if TYPE_CHECKING:
    from hermes_cli.tui.tool_result_parse import ResultSummary
    from hermes_cli.tui.tool_category import ToolCategory
    from hermes_cli.tui.tool_payload import ClassificationResult, ToolPayload
    from hermes_cli.tui.tool_payload import ResultKind
    from hermes_cli.tui.input_section import InputSection as _InputSectionT


def _tool_panel_v2_enabled() -> bool:
    """Return True if the tool_panel_v2 accent bar is enabled in config."""
    try:
        from hermes_cli.config import read_raw_config
        return bool(read_raw_config().get("display", {}).get("tool_panel_v2", True))
    except Exception:
        return True


# ---------------------------------------------------------------------------
# _PanelContent — inner vertical container (right side of ToolAccent)
# ---------------------------------------------------------------------------


class _PanelContent(Widget):
    """Inner vertical container for ArgsPane/BodyPane/FooterPane.

    Allows ToolPanel to use layout:horizontal with ToolAccent on the left
    while keeping the panes stacked vertically on the right.
    """

    DEFAULT_CSS = "_PanelContent { layout: vertical; height: auto; width: 1fr; }"


# ---------------------------------------------------------------------------
# ArgsPane
# ---------------------------------------------------------------------------


class ArgsPane(Widget):
    """Structured key/value argument view. Shown at L3 only.

    Renders args_final via the per-category formatter from tool_args_format.py.
    Two layout modes toggled by on_resize: .wide (≥80 cols) / .narrow (<80 cols).
    """

    DEFAULT_CSS = """
    ArgsPane {
        height: auto;
        padding: 0 2;
        display: none;
        max-height: 20;
        overflow-y: auto;
    }
    """

    COMPONENT_CLASSES = {"args-pane--key", "args-pane--value"}

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        self._content = Static("", id="args-content")
        yield self._content

    def refresh_rows(self, args: dict | None, category: "ToolCategory") -> None:
        """Render args using the per-category formatter."""
        from hermes_cli.tui.tool_category import _CATEGORY_DEFAULTS
        from hermes_cli.tui.tool_args_format import get_formatter

        defaults = _CATEGORY_DEFAULTS[category]
        formatter = get_formatter(defaults.args_formatter)
        rows = formatter(args or {})

        if not rows:
            self._content.update("(no args)")
            return

        table = Table.grid(padding=(0, 1))
        table.add_column("key", style="dim", min_width=8)
        table.add_column("value")
        for key, val in rows:
            table.add_row(key + ":", val)
        self._content.update(table)

    def on_resize(self, event: object) -> None:
        width = getattr(getattr(event, "size", None), "width", 80)
        if width >= 80:
            self.remove_class("narrow")
            self.add_class("wide")
        else:
            self.remove_class("wide")
            self.add_class("narrow")


# ---------------------------------------------------------------------------
# BodyPane
# ---------------------------------------------------------------------------


class BodyPane(Widget):
    """Container for the streaming/static block body.

    Phase 2: stores _renderer singleton.
    Phase 3: set_mode("preview"|"full") toggles between block and preview Static.
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
        # _preview_static is None until first set_mode("preview") call (lazy mount).
        # Do NOT compose it here — an extra child widget (even display:none) can
        # shift sibling widget positions and break click hit-testing.
        self._preview_static: Static | None = None

    def set_mode(self, mode: str) -> None:
        """Switch body between 'full' (streaming block visible) and 'preview'.

        Preview Static is mounted lazily on first preview request to avoid
        spurious layout refreshes that shift widget screen positions.
        Only mutates display when the value actually changes.
        """
        if mode == "full":
            if self._block is not None and not self._block.display:
                self._block.display = True
            if self._preview_static is not None and self._preview_static.display:
                self._preview_static.display = False
        else:  # preview
            if self._block is not None and self._block.display:
                self._block.display = False
            if self._preview_static is None and self.is_attached:
                self._preview_static = Static("", id="body-preview")
                self.mount(self._preview_static)
            if self._preview_static is not None:
                self._update_preview(self._preview_static)
                if not self._preview_static.display:
                    self._preview_static.display = True

    def _update_preview(self, preview: Static) -> None:
        from rich.text import Text

        lines = self._get_all_plain()
        if not lines:
            preview.update("(no output)")
            return

        # While streaming: show first 3 lines (head preview).
        # After completion: show last 3 lines (tail preview).
        is_streaming = getattr(self._block, "_streaming", False) or getattr(
            self._block, "_is_streaming", False
        )
        if is_streaming:
            shown = lines[:3]
            if len(lines) > 3:
                shown = shown + ["  ⋯"]
        else:
            shown = lines[-3:] if len(lines) > 3 else lines

        t = Text()
        for ln in shown:
            t.append(ln + "\n", style="dim")
        preview.update(t)

        # Also try renderer preview for specialised kinds
        if self._renderer is not None:
            try:
                renderable = self._renderer.preview(lines, max_lines=3)
                preview.update(renderable)
            except Exception:
                pass

    def _get_all_plain(self) -> list[str]:
        if self._block is None:
            return []
        for attr in ("_all_plain", "_content_lines", "_plain_lines"):
            lines = getattr(self._block, attr, None)
            if isinstance(lines, list):
                return list(lines)
        return []


# ---------------------------------------------------------------------------
# FooterPane
# ---------------------------------------------------------------------------


class FooterPane(Widget):
    """Exit-code chip, stat badges, stderr tail, retry hint.

    Shown conditionally based on _should_show_footer() in ToolPanel.
    """

    DEFAULT_CSS = """
    FooterPane {
        height: 1;
        padding: 0 1;
        display: none;
        color: $text-muted;
        layout: horizontal;
    }
    FooterPane.compact > .footer-stderr { display: none; }
    """

    COMPONENT_CLASSES = {"footer--exit-chip", "footer--badge", "footer--retry-hint"}

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._diff_affordance: DiffAffordance | None = None

    def compose(self) -> ComposeResult:
        self._content = Static("", id="footer-content")
        self._diff_affordance = DiffAffordance()
        yield self._content
        yield self._diff_affordance

    def update_summary(self, summary: "ResultSummary") -> None:
        """Re-render footer from a ResultSummary."""
        from rich.text import Text

        parts = Text()
        if summary.exit_code is not None and summary.exit_code != 0:
            parts.append(f" exit {summary.exit_code} ", style="bold red")
            parts.append("  ")
        for badge in summary.stat_badges:
            if badge.startswith("+"):
                parts.append(badge, style="green")
            elif badge.startswith("-"):
                parts.append(badge, style="red")
            else:
                parts.append(badge, style="dim")
            parts.append("  ")
        if summary.stderr_tail:
            parts.append(summary.stderr_tail[:80], style="dim")
        if summary.retry_hint:
            parts.append("  ")
            parts.append(summary.retry_hint, style="underline cyan")
        self._content.update(parts)

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
    """Unified tool-call display container — Phase 3 / v3-A.

    Compose tree (v3-A):
        ToolPanel  [layout: horizontal]
        ├── ToolAccent           1-cell vertical gutter rail
        └── _PanelContent        [layout: vertical]
            ├── ArgsPane         (display:none unless L3)
            ├── BodyPane         (hosts the streaming/static block; hidden at L0)
            └── FooterPane       (shown conditionally; contains DiffAffordance)

    detail_level reactive (0..3):
        L0 — header only (collapsed)
        L1 — header + 3-line preview + conditional footer
        L2 — header + full body + conditional footer
        L3 — header + ArgsPane (args) + full body + footer (always)
    """

    DEFAULT_CSS = "ToolPanel { height: auto; layout: horizontal; }"
    _content_type: str = "tool"
    can_focus = True

    COMPONENT_CLASSES = {
        "tool-panel--accent",
        "tool-panel--error",
        "tool-panel--grouped",
        "tool-panel--focused",
    }

    BINDINGS = [
        Binding("d", "cycle_detail_forward", "Detail+", show=False),
        Binding("D", "cycle_detail_reverse", "Detail-", show=False),
        Binding("0", "set_level_0", "L0", show=False),
        Binding("1", "set_level_1", "L1", show=False),
        Binding("2", "set_level_2", "L2", show=False),
        Binding("3", "set_level_3", "L3", show=False),
        Binding("enter", "toggle_l1_l2", "Toggle", show=False),
        Binding("space", "toggle_l0_restore", "Collapse", show=False),
        Binding("y", "copy_output", "Copy output", show=False),
        Binding("Y", "copy_input", "Copy input", show=False),
        Binding("r", "rerun", "Rerun", show=False),
    ]

    # Compile-time default 1; overridden in on_mount based on category defaults.
    detail_level: reactive[int] = reactive(1, layout=True)

    def __init__(self, block: Widget, tool_name: str | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._block = block
        self._tool_name = tool_name or ""
        from hermes_cli.tui.tool_category import classify_tool
        self._category = classify_tool(self._tool_name)

        # Phase 3 state
        self._user_detail_override: bool = False
        self._tool_args: dict | None = None
        self._result_summary: "ResultSummary | None" = None
        self._start_time: float = time.monotonic()
        self._completed_at: float | None = None
        self._result_paths: list[str] = []

        # Phase D state
        self._pre_collapse_level: int = 2
        self._forced_renderer_kind: "ResultKind | None" = None

        # Pane refs (set in compose)
        self._accent: ToolAccent | None = None
        self._header_bar: ToolHeaderBar | None = None
        self._input_section: "InputSection | None" = None
        self._args_pane: ArgsPane | None = None
        self._body_pane: BodyPane | None = None
        self._footer_pane: FooterPane | None = None

        # CWD stripping — enable on SHELL category blocks
        from hermes_cli.tui.tool_category import ToolCategory
        if self._category == ToolCategory.SHELL and hasattr(block, "_should_strip_cwd"):
            block._should_strip_cwd = True

    def compose(self) -> ComposeResult:
        self._accent = ToolAccent()
        self._header_bar = ToolHeaderBar(label=self._tool_name)
        # InputSection is mounted lazily in on_mount after layout has settled.
        # Composing it here invalidates layout-hit-testing caches on sibling widgets,
        # breaking pilot.click() on ToolHeaderBar in async tests.
        self._args_pane = ArgsPane()
        self._body_pane = BodyPane(self._block, category=self._category)
        self._footer_pane = FooterPane()
        yield self._accent
        with _PanelContent():
            yield self._header_bar
            yield self._args_pane
            yield self._body_pane
            yield self._footer_pane

    def on_mount(self) -> None:
        from hermes_cli.tui.tool_category import _CATEGORY_DEFAULTS

        self.add_class(f"category-{self._category.value}")

        # Set initial detail_level.
        # Static blocks (total_lines > 0 at mount = pre-populated ToolBlock) always
        # start at L2 (full body). Hiding a pre-populated static block causes
        # Textual's layout engine to rebuild the RichLog with 0-width, clearing
        # the _lines cache. Auto-collapse for static blocks happens only via
        # _apply_complete_auto_level called from set_result_summary().
        # Streaming blocks (total_lines = 0 at mount) use max(default_detail, 2).
        defaults = _CATEGORY_DEFAULTS[self._category]
        total_lines = self._body_line_count()
        if total_lines > 0:
            initial = 2  # static block: always start expanded
            state = "ok"
        else:
            initial = max(defaults.default_detail, 2)  # streaming: at least L2
            state = "streaming"
        if self._accent is not None:
            self._accent.state = state
        if self._header_bar is not None:
            self._header_bar.set_state(state)
            # Populate initial arg summary
            self._header_bar.set_arg_summary(self._format_arg_summary())
        self.detail_level = max(0, min(3, initial))

        # Mount InputSection after the first refresh to avoid invalidating
        # ToolHeaderBar click hit-testing caches during initial layout.
        self.call_after_refresh(self._mount_input_section_lazy)

    def _mount_input_section_lazy(self) -> None:
        """Mount InputSection into _PanelContent after layout has settled.

        Called via call_after_refresh from on_mount so that the initial
        ToolHeaderBar layout cache is populated before we add a new sibling,
        preventing click hit-testing failures in async tests.
        """
        from hermes_cli.tui.input_section import InputSection

        if self._input_section is not None:
            return  # already mounted
        try:
            panel_content = next(
                c for c in self.children if isinstance(c, _PanelContent)
            )
        except StopIteration:
            return

        self._input_section = InputSection(
            category=self._category, args=self._tool_args
        )
        # Mount before _args_pane so it appears between header_bar and args_pane
        try:
            panel_content.mount(self._input_section, before=self._args_pane)
        except Exception:
            try:
                panel_content.mount(self._input_section)
            except Exception:
                self._input_section = None
                return

        # Apply correct initial display state
        level = self.detail_level
        want_is = level >= 2 and InputSection.should_show(self._category)
        if not want_is:
            self._input_section.styles.display = "none"

    # ------------------------------------------------------------------
    # detail_level watcher
    # ------------------------------------------------------------------

    def watch_detail_level(self, old: int, new: int) -> None:
        from hermes_cli.tui.input_section import InputSection

        ap = self._args_pane
        bp = self._body_pane
        fp = self._footer_pane
        ip = self._input_section
        if ap is None or bp is None or fp is None:
            return

        # Only mutate display when the value actually changes.
        # Redundant writes trigger layout refreshes that can shift widget
        # screen positions (breaking click hit-testing on child widgets).

        want_ap = new == 3          # ArgsPane: show at L3 only
        want_bp = new != 0          # BodyPane: hide at L0 only
        want_fp = self._should_show_footer(new)
        # InputSection: show at L2+ only when category supports it
        want_is = new >= 2 and InputSection.should_show(self._category)

        if ap.display != want_ap:
            ap.styles.display = "block" if want_ap else "none"
        if bp.display != want_bp:
            bp.styles.display = "none" if not want_bp else "block"
        bp.set_mode("preview" if new == 1 else "full")
        if fp.display != want_fp:
            fp.styles.display = "block" if want_fp else "none"
        if ip is not None and ip.display != want_is:
            ip.styles.display = "block" if want_is else "none"

        # CSS level class — remove old, add new (avoid removing all 4 each time)
        if old != new:
            self.remove_class(f"-l{old}")
            self.add_class(f"-l{new}")

        # Sync ToolHeaderBar chevron
        if self._header_bar is not None:
            self._header_bar.set_chevron(new)

        # Refresh ArgsPane when entering L3
        if new == 3 and self._tool_args is not None:
            ap.refresh_rows(self._tool_args, self._category)

    def _should_show_footer(self, level: int) -> bool:
        if level == 0:
            return False
        if level == 3:
            return True
        # At L1/L2: show if there's something footer-worthy
        rs = self._result_summary
        if rs is None:
            return False
        if rs.exit_code is not None and rs.exit_code != 0:
            return True
        if rs.stat_badges:
            return True
        if rs.retry_hint:
            return True
        return False

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

    def _apply_complete_auto_level(self) -> None:
        from hermes_cli.tui.tool_category import _CATEGORY_DEFAULTS
        rs = self._result_summary
        if self._user_detail_override:
            # Exception: user collapsed to L0 but tool errored — promote to L1
            if rs is not None and rs.is_error and self.detail_level == 0:
                self.detail_level = 1
            return
        total = self._body_line_count()
        threshold = _CATEGORY_DEFAULTS[self._category].default_collapsed_lines
        if total > threshold:
            self.detail_level = 1  # preview
        else:
            self.detail_level = 2  # full

    def set_tool_args(self, args: dict | None) -> None:
        """Call from app after tool_start to supply parsed args."""
        self._tool_args = args
        if self._header_bar is not None:
            self._header_bar.set_arg_summary(self._format_arg_summary())
        if self.detail_level == 3 and self._args_pane is not None:
            self._args_pane.refresh_rows(args, self._category)
        if self._input_section is not None:
            self._input_section.refresh_content(args)

    # ------------------------------------------------------------------
    # ToolHeaderBar helpers (Phase B)
    # ------------------------------------------------------------------

    def _format_arg_summary(self) -> str:
        """Build a short arg summary string for the header bar."""
        args = self._tool_args or {}
        if not args:
            return ""
        # Prefer common high-signal keys
        for key in ("command", "cmd", "shell_command", "path", "pattern", "query", "url"):
            val = args.get(key)
            if val is not None:
                return str(val)
        # Fallback: first value
        first = next(iter(args.values()), None)
        return str(first) if first is not None else ""

    def _update_kind_from_classifier(self, line_count: int) -> None:
        """Run content classifier and update ResultPill kind.

        Phase C: also triggers _swap_renderer for non-TEXT/SHELL classified output.
        """
        if self._header_bar is None:
            return
        try:
            from hermes_cli.tui.content_classifier import classify_content
            from hermes_cli.tui.tool_payload import ToolPayload
            output_raw = ""
            block = self._block
            if block is not None:
                for attr in ("_all_plain", "_content_lines", "_plain_lines"):
                    lines = getattr(block, attr, None)
                    if isinstance(lines, list):
                        output_raw = "\n".join(lines)
                        break
            payload = ToolPayload(
                tool_name=self._tool_name,
                category=self._category,
                args=self._tool_args or {},
                input_display=None,
                output_raw=output_raw,
                line_count=line_count,
            )
            result = classify_content(payload)
            self._header_bar.set_kind(result.kind)
            # Phase C: swap renderer for specialized kinds
            self._maybe_swap_renderer(result, payload)
        except Exception:
            pass

    def _swap_renderer(
        self,
        new_renderer_cls: type,
        payload: "ToolPayload",
        cls_result: "ClassificationResult",
    ) -> None:
        """Replace BodyPane content with a new renderer widget."""
        if self._body_pane is None:
            return
        try:
            from hermes_cli.tui.body_renderers.base import BodyRenderer as _BR
            renderer = new_renderer_cls(payload, cls_result)
            new_widget = renderer.build_widget()
            # Remove old block, mount new widget
            old_block = self._block
            self._body_pane.mount(new_widget)
            if old_block is not None and old_block.is_attached:
                old_block.remove()
            self._block = new_widget
            self._body_pane._block = new_widget
        except Exception:
            pass  # keep old renderer on failure

    def _maybe_swap_renderer(
        self,
        result: "ClassificationResult",
        payload: "ToolPayload",
    ) -> None:
        """Conditionally swap body renderer based on classification result."""
        try:
            from hermes_cli.tui.tool_payload import ResultKind
            from hermes_cli.tui.tool_category import ToolCategory
            from hermes_cli.tui.body_renderers import pick_renderer, FallbackRenderer

            if result.kind in (ResultKind.TEXT, ResultKind.EMPTY):
                return
            if self._category == ToolCategory.SHELL:
                return  # SHELL always keeps its renderer
            renderer_cls = pick_renderer(result, payload)
            if renderer_cls is FallbackRenderer:
                return  # don't swap to fallback unnecessarily
            self._swap_renderer(renderer_cls, payload, result)
        except Exception:
            pass

    def _maybe_activate_mini(self, summary: "ResultSummary") -> None:
        """Activate mini-mode if SHELL+exit0+≤3L+no-stderr criteria met."""
        from hermes_cli.tui.tool_panel_mini import meets_mini_criteria
        exit_code = getattr(summary, "exit_code", None)
        stderr_raw = getattr(summary, "stderr_tail", None) or ""
        line_count = self._body_line_count()
        if not meets_mini_criteria(self._category, exit_code, line_count, stderr_raw):
            return
        if not self.is_attached or self.parent is None:
            return
        try:
            from hermes_cli.tui.tool_panel_mini import ToolPanelMini
            cmd = self._format_arg_summary() or self._tool_name
            dur = 0.0
            if self._completed_at is not None:
                dur = self._completed_at - self._start_time
            mini = ToolPanelMini(source_panel=self, command=cmd, duration_s=dur)
            self.parent.mount(mini, after=self)
            self.display = False
        except Exception:
            pass

    def set_result_summary(self, summary: "ResultSummary") -> None:
        """Call from app at tool completion to populate footer."""
        self._result_summary = summary
        self._completed_at = time.monotonic()
        if self._footer_pane is not None:
            self._footer_pane.update_summary(summary)
        # Update accent + header bar state
        final_state = "error" if summary.is_error else "ok"
        if self._accent is not None:
            self._accent.state = final_state
        if self._header_bar is not None:
            self._header_bar.set_state(final_state)
            self._header_bar.set_finished(self._completed_at)
            line_count = self._body_line_count()
            self._header_bar.set_line_count(line_count)
            # Classify content and update pill
            self._update_kind_from_classifier(line_count)
        self._apply_complete_auto_level()
        # Refresh footer visibility
        if self._footer_pane is not None:
            show = self._should_show_footer(self.detail_level)
            self._footer_pane.styles.display = "block" if show else "none"
        # Activate mini-mode for qualifying SHELL calls
        self._maybe_activate_mini(summary)
        # Notify enclosing GroupHeader so it can refresh dot color + stats
        self._notify_group_header()

    def _notify_group_header(self) -> None:
        """Find the GroupHeader for our group (if any) and refresh its stats."""
        parent = self.parent
        if parent is None:
            return
        group_id: str | None = None
        for cls in self.classes:
            if cls.startswith("group-id-"):
                group_id = cls[9:]
                break
        if group_id is None:
            return
        try:
            from hermes_cli.tui.tool_group import GroupHeader as _GH
            for child in parent.children:
                if isinstance(child, _GH) and child._group_id == group_id:
                    child.refresh_stats()
                    return
        except Exception:
            pass

    def copy_content(self) -> str:
        """Return full plain-text output regardless of detail level."""
        if self._block is None:
            return ""
        for method in ("copy_content",):
            fn = getattr(self._block, method, None)
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

    def _mark_user_override(self) -> None:
        self._user_detail_override = True

    def action_cycle_detail_forward(self) -> None:
        """D: cycle L1→L2→L3→L1 (at L0, jump to L1 first)."""
        self._mark_user_override()
        if self.detail_level == 0:
            self.detail_level = 1
        else:
            self.detail_level = (self.detail_level % 3) + 1  # 1→2→3→1

    def action_cycle_detail_reverse(self) -> None:
        """Shift+D: reverse cycle L3→L2→L1→L0."""
        self._mark_user_override()
        if self.detail_level == 0:
            return  # stay at L0
        self.detail_level = self.detail_level - 1  # 3→2→1→0

    def action_set_level_0(self) -> None:
        self._mark_user_override()
        self.detail_level = 0

    def action_set_level_1(self) -> None:
        self._mark_user_override()
        self.detail_level = 1

    def action_set_level_2(self) -> None:
        self._mark_user_override()
        self.detail_level = 2

    def action_set_level_3(self) -> None:
        self._mark_user_override()
        self.detail_level = 3

    def action_toggle_l1_l2(self) -> None:
        """Enter: cycle L1↔L2; from L0→L1; from L3→L2."""
        self._mark_user_override()
        if self.detail_level == 0:
            self.detail_level = 1
        elif self.detail_level == 1:
            self.detail_level = 2
        elif self.detail_level == 2:
            self.detail_level = 1
        else:  # L3
            self.detail_level = 2

    def action_toggle_l0_restore(self) -> None:
        """space: toggle between L0 (collapsed) and previous level."""
        self._mark_user_override()
        if self.detail_level == 0:
            self.detail_level = self._pre_collapse_level
        else:
            self._pre_collapse_level = self.detail_level
            self.detail_level = 0

    def action_copy_output(self) -> None:
        """y: copy tool output to clipboard."""
        text = self.copy_content()
        if text:
            try:
                import pyperclip
                pyperclip.copy(text)
                self.app.notify("Copied output", timeout=1.5)
            except Exception:
                self.app.notify("Copy failed — use mouse select", timeout=3)

    def action_copy_input(self) -> None:
        """Y: copy tool input summary to clipboard."""
        if self._input_section is not None:
            text = self._input_section._build_text()
            if text:
                try:
                    import pyperclip
                    pyperclip.copy(text)
                    self.app.notify("Copied input", timeout=1.5)
                except Exception:
                    self.app.notify("Copy failed", timeout=3)

    def action_rerun(self) -> None:
        """r: emit ToolRerunRequested message."""
        try:
            from hermes_cli.tui.messages import ToolRerunRequested
            self.post_message(ToolRerunRequested(panel=self))
        except Exception:
            self.app.notify("Rerun not available", timeout=2)

    def force_renderer(self, kind: "ResultKind") -> None:
        """Override classifier and swap to given kind's renderer."""
        self._forced_renderer_kind = kind
        try:
            from hermes_cli.tui.body_renderers import pick_renderer
            from hermes_cli.tui.tool_payload import ToolPayload, ClassificationResult

            output_raw = self.copy_content()
            payload = ToolPayload(
                tool_name=self._tool_name,
                category=self._category,
                args=self._tool_args or {},
                input_display=None,
                output_raw=output_raw,
                line_count=self._body_line_count(),
            )
            cls_result = ClassificationResult(kind=kind, confidence=1.0)
            renderer_cls = pick_renderer(cls_result, payload)
            self._swap_renderer(renderer_cls, payload, cls_result)
            if self._header_bar is not None:
                self._header_bar.set_kind(kind)
        except Exception:
            pass

    def on_tool_header_bar_clicked(self, event: ToolHeaderBar.Clicked) -> None:
        """ToolHeaderBar click → cycle detail level."""
        event.stop()
        self.action_toggle_l1_l2()

    # Focus styling is done via CSS :focus pseudo-class in hermes.tcss.
    # No on_focus/on_blur handlers — they trigger layout refreshes that
    # can interfere with click event hit-testing on child widgets.
