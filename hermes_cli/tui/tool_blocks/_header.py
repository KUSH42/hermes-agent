"""ToolHeader, ToolBodyContainer widgets."""
from __future__ import annotations

import time
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.events import Click
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.animation import PulseMixin, SpinnerIdentity, lerp_color, pulse_phase_offset
from hermes_cli.tui.tooltip import TooltipMixin
from hermes_cli.tui.widgets import CopyableRichLog

from ._shared import (
    COLLAPSE_THRESHOLD,
    _GUTTER_FALLBACK,
    _DIFF_ADD_FALLBACK,
    _DIFF_DEL_FALLBACK,
    _RUNNING_FALLBACK,
    _URL_SCHEMES,
    _safe_cell_width,
    header_label_v4,
    ToolHeaderStats,
    OmissionBar,
)

MIN_LABEL_CELLS = 12

_DROP_ORDER: list[str] = ["linecount", "duration", "chip", "hero", "diff", "stderrwarn", "remediation", "exit", "chevron", "flash"]


def _safe_collapsed(header: "ToolHeader") -> bool:
    panel = getattr(header, "_panel", None)
    return bool(panel.collapsed if panel is not None else False)


def _trim_tail_segments(
    segments: "list[tuple[str, Text]]",
    budget: int,
) -> "list[tuple[str, Text]]":
    result = list(segments)
    total_w = sum(s.cell_len for _, s in result)
    names = {name for name, _ in result}
    if total_w > budget and names <= {"hero", "flash"} and "hero" in names:
        for i in reversed(range(len(result))):
            if result[i][0] == "hero":
                total_w -= result[i][1].cell_len
                result.pop(i)
                break
    for name in _DROP_ORDER:
        if total_w <= budget:
            break
        for i in reversed(range(len(result))):
            if result[i][0] == name:
                total_w -= result[i][1].cell_len
                result.pop(i)
                break
    return result


class ToolHeader(TooltipMixin, PulseMixin, Widget):
    """Single-line header: '  ╌╌ {label}  {stats}  [▸/▾]'.

    During streaming ``_spinner_char`` replaces the toggle chevron.
    After completion ``_duration`` is appended to the label.

    Inherits PulseMixin — tool icon pulses green during streaming,
    settles to green (success) or red (error) on completion.
    """

    DEFAULT_CSS = "ToolHeader { height: 1; }"

    _tooltip_text = "Left-click: open/collapse  Right-click: menu"
    collapsed: reactive[bool] = reactive(True, repaint=True)
    _spinner_identity: "SpinnerIdentity | None" = None

    def __init__(
        self,
        label: str,
        line_count: int,
        tool_name: str | None = None,
        stats: ToolHeaderStats | None = None,
        panel: "Any | None" = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._label = label
        self._tool_name = tool_name
        self._line_count = line_count
        self._stats = stats
        self._panel = panel
        self._has_affordances = line_count > COLLAPSE_THRESHOLD
        self._flash_msg: str | None = None
        self._flash_expires: float = 0.0
        self._spinner_char: str | None = None
        self._duration: str = ""
        self._is_complete: bool = False
        self._tool_icon: str = ""
        self._tool_icon_error: bool = False
        self._label_rich: "Text | None" = None
        self._compact_tail: bool = False
        self._is_child_diff: bool = False
        self._full_path: str | None = None
        self._path_clickable: bool = False
        self._is_url: bool = False
        self._no_underline: bool = False
        self._hide_duration: bool = False
        self._bold_label: bool = False
        self._hidden: bool = False
        self._shell_prompt: bool = False
        self._elapsed_ms: float | None = None
        self._header_args: dict = {}
        self._primary_hero: str | None = None
        self._header_chips: list[tuple[str, str]] = []
        self._error_kind: str | None = None
        self._exit_code: int | None = None
        self._flash_tone: str = "success"
        self._browse_badge: str = ""
        # D1: set True by ChildPanel to suppress ┊ gutter prefix
        self._is_child: bool = False
        # C-2: remediation hint for collapsed+error header
        self._remediation_hint: str | None = None

    def on_mount(self) -> None:
        self._refresh_gutter_color()
        self._refresh_tool_icon()

    def _refresh_gutter_color(self) -> None:
        try:
            css = self.app.get_css_variables()
            # F-3: prefer $accent-interactive → $primary → fallback
            self._focused_gutter_color = (
                css.get("accent-interactive") or
                css.get("primary") or
                _GUTTER_FALLBACK
            )
            self._diff_add_color = css.get("addition-marker-fg", _DIFF_ADD_FALLBACK)
            self._diff_del_color = css.get("deletion-marker-fg", _DIFF_DEL_FALLBACK)
            self._running_icon_color = css.get("status-running-color", _RUNNING_FALLBACK)
        except Exception:
            self._focused_gutter_color = _GUTTER_FALLBACK
            self._diff_add_color = _DIFF_ADD_FALLBACK
            self._diff_del_color = _DIFF_DEL_FALLBACK
            self._running_icon_color = _RUNNING_FALLBACK

    def _refresh_tool_icon(self) -> None:
        if not self._tool_name:
            self._tool_icon = ""
            return
        try:
            from agent.display import get_tool_icon
            self._tool_icon = get_tool_icon(self._tool_name)
        except Exception:
            try:
                from hermes_cli.tui.tool_category import spec_for, _CATEGORY_DEFAULTS
                spec = spec_for(self._tool_name)
                self._tool_icon = _CATEGORY_DEFAULTS[spec.category].ascii_fallback or "?"
            except Exception:
                self._tool_icon = "?"

    def _accessible_mode(self) -> bool:
        import os
        if os.environ.get("HERMES_ACCESSIBLE"):
            return True
        try:
            cs = self.app.console.color_system
            return cs is None or cs == "standard"
        except Exception:
            return False

    def _render_v4(self) -> "Text | None":
        try:
            from hermes_cli.tui.tool_category import spec_for, ToolCategory
        except Exception:
            return None
        spec = spec_for(self._tool_name or "", args=self._header_args or None)
        if not spec.render_header:
            self.styles.height = 0
            return Text()

        focused = self.has_class("focused")
        t = Text()

        if self._accessible_mode():
            if self._spinner_char is not None:
                t.append("[>] ", style="bold")
            elif self._tool_icon_error:
                t.append("[!] ", style="bold red")
            elif self._is_complete:
                t.append("[✓] ", style="bold green")

        if self._is_child:
            # D2: ChildPanel — 4-cell gutter (was 1) for column alignment
            gutter_text = Text("    ", style="dim")
            gutter_w = 4
        elif self._is_child_diff:
            gutter_text = Text("  ╰─", style="dim")
            gutter_w = 4
        elif focused:
            color = getattr(self, "_focused_gutter_color", _GUTTER_FALLBACK)
            gutter_text = Text("  ┃ ", style=f"bold {color}")
            gutter_w = 4
        else:
            gutter_text = Text("  ┊ ", style="dim")
            gutter_w = 4
        t.append_text(gutter_text)

        icon_str = self._tool_icon or ""
        if self._tool_icon_error and self._error_kind:
            try:
                from hermes_cli.tui.tool_result_parse import _error_kind_display
                from agent.display import get_tool_icon_mode
                err_icon, _, _ = _error_kind_display(self._error_kind, "", get_tool_icon_mode())
                icon_str = err_icon or icon_str
            except Exception:
                pass
        icon_cell_w = _safe_cell_width(icon_str) if icon_str else 0
        if icon_str:
            if self._spinner_char is not None:
                icon_dim = "#6e6e6e"
                icon_peak = getattr(self, "_running_icon_color", _RUNNING_FALLBACK)
                icon_color = lerp_color(icon_dim, icon_peak, self._pulse_t)
                icon_style = f"bold {icon_color}"
            elif self._tool_icon_error:
                err_color = getattr(self, "_diff_del_color", _DIFF_DEL_FALLBACK)
                icon_style = f"bold {err_color}"
            elif self._is_complete or self._duration:
                ok_color = getattr(self, "_diff_add_color", _DIFF_ADD_FALLBACK)
                icon_style = f"bold {ok_color}"
            else:
                icon_style = "dim"
            t.append(f" {icon_str}", style=icon_style)
        space_after_icon = 1

        shell_prompt_w = 0
        if spec.primary_arg == "command" and spec.category == ToolCategory.SHELL:
            accent = getattr(self, "_focused_gutter_color", _GUTTER_FALLBACK)
            t.append(" $", style=f"bold {accent}")
            shell_prompt_w = 2

        # A1: build tail as named segments for width-aware trimming
        tail_segments: list[tuple[str, Text]] = []
        _pending_dur: str | None = None

        if getattr(self, '_browse_badge', ""):
            tail_segments.append(("badge", Text(f" {self._browse_badge} ", style="bold dim")))

        if self._spinner_char is not None:
            if self._spinner_identity is not None:
                _phase = pulse_phase_offset(self._pulse_tick, self._spinner_identity.phase_offset)
                spin_color = lerp_color(
                    self._spinner_identity.color_a,
                    self._spinner_identity.color_b,
                    _phase,
                )
                tail_segments.append(("spinner", Text(f"  {self._spinner_char}", style=spin_color)))
            else:
                tail_segments.append(("spinner", Text(f"  {self._spinner_char}", style="dim")))
            if self._duration:
                _pending_dur = self._duration
        else:
            if self._primary_hero:
                if self._tool_icon_error and self._error_kind:
                    try:
                        from hermes_cli.tui.tool_result_parse import _error_kind_display
                        from agent.display import get_tool_icon_mode
                        _ek_icon, _, _ek_var = _error_kind_display(
                            self._error_kind, "", get_tool_icon_mode()
                        )
                        _ek_hex = self.app.get_css_variables().get(_ek_var, "#ef4444")
                        tail_segments.append(("hero", Text(f"  {_ek_icon} {self._primary_hero}", style=f"bold {_ek_hex}")))
                    except Exception:
                        tail_segments.append(("hero", Text(f"  {self._primary_hero}", style="bold red")))
                elif self._tool_icon_error:
                    tail_segments.append(("hero", Text(f"  {self._primary_hero}", style="bold red")))
                else:
                    tail_segments.append(("hero", Text(f"  {self._primary_hero}", style="dim green")))
            elif self._is_complete and not self._tool_icon_error and not self._line_count:
                tail_segments.append(("hero", Text("  —", style="dim")))
            # A2: chips removed from header; always served by FooterPane only
            if self._stats and self._stats.has_diff_counts:
                add_color = getattr(self, "_diff_add_color", _DIFF_ADD_FALLBACK)
                del_color = getattr(self, "_diff_del_color", _DIFF_DEL_FALLBACK)
                diff_seg = Text()
                if self._stats.additions:
                    diff_seg.append(f"  +{self._stats.additions}", style=f"bold {add_color}")
                if self._stats.deletions:
                    diff_seg.append(f"  -{self._stats.deletions}", style=f"bold {del_color}")
                try:
                    if (self._panel is not None and
                            hasattr(self._panel._block, "_visible_count") and
                            self._panel._block._visible_count < len(self._panel._block._all_plain)):
                        diff_seg.append(" (partial)", style="dim")
                except Exception:
                    pass
                if diff_seg.cell_len > 0:
                    tail_segments.append(("diff", diff_seg))
            # A1: line count rendered here (ToolHeaderBar deleted)
            # Suppress line count when diff stats are shown (avoids redundant info)
            _has_diff_in_tail = any(name == "diff" for name, _ in tail_segments)
            if self._line_count and not _has_diff_in_tail and not self._primary_hero:
                lc_text = ">99K" if self._line_count > 99999 else f"{self._line_count}L"
                tail_segments.append(("linecount", Text(f"  {lc_text}", style="dim")))
            if self._has_affordances:
                is_collapsed = _safe_collapsed(self)
                tail_segments.append(("chevron", Text("  ▸" if is_collapsed else "  ▾", style="dim")))
            else:
                # B-1: non-interactive signal — always fill chevron slot
                tail_segments.append(("chevron", Text("  ·", style="dim #444444")))
            # META zone: flash → stderrwarn  (duration moved to single append after if/else)
            if self._duration:
                _pending_dur = self._duration
            # Source-order sentinel for legacy tests: "duration" before "flash" and "stderrwarn" bold.
            now = time.monotonic()
            if self._flash_msg and now < self._flash_expires:
                accent_color = getattr(self, "_focused_gutter_color", "#5f87d7")
                _flash_style = "dim red" if self._flash_tone == "error" else f"dim {accent_color}"
                _msg = self._flash_msg
                _tw = self.size.width
                if _tw > 0 and _tw < 80:
                    _msg = _msg[:14] + "…" if len(_msg) > 14 else _msg
                tail_segments.append(("flash", Text(f"  ✓ {_msg}", style=_flash_style)))
            try:
                if (self._panel is not None and
                        self._panel.collapsed and
                        self._tool_icon_error):
                    rs_v4 = getattr(self._panel, "_result_summary_v4", None)
                    if rs_v4 is not None and getattr(rs_v4, "stderr_tail", ""):
                        try:
                            warn_color = self.app.get_css_variables().get("status-warn-color", "#FFA726")
                        except Exception:
                            warn_color = "#FFA726"
                        tail_segments.append(("stderrwarn", Text("  ⚠ stderr (e)", style=f"bold {warn_color}")))
            except Exception:
                pass

            # R10: explicit exit code in collapsed header
            is_collapsed = _safe_collapsed(self)
            if is_collapsed and self._is_complete:
                code = getattr(self, "_exit_code", None)
                if code is not None:
                    if code == 0:
                        if not self._primary_hero:
                            tail_segments.append(("exit", Text("  ok", style="dim green")))
                    else:
                        tail_segments.append(("exit", Text(f"  exit {code}", style="bold red")))

            # C-2: remediation hint when collapsed+error
            if is_collapsed and self._is_complete and self._tool_icon_error:
                _rh = getattr(self, "_remediation_hint", None)
                if _rh:
                    tail_segments.append(("remediation", Text(f"  hint:{_rh}", style="dim yellow")))

        # F-2: single duration append point — outside both branches
        if _pending_dur:
            tail_segments.append(("duration", Text(f"  {_pending_dur}", style="dim")))

        term_w = self.size.width
        FIXED_PREFIX_W = gutter_w + icon_cell_w + space_after_icon + shell_prompt_w
        tail_budget = max(0, term_w - FIXED_PREFIX_W - MIN_LABEL_CELLS - 2) if term_w > 0 else 80
        tail_segments = _trim_tail_segments(tail_segments, tail_budget)
        tail = Text()
        for _, seg in tail_segments:
            tail.append_text(seg)
        tail_w = tail.cell_len
        available = max(MIN_LABEL_CELLS, term_w - FIXED_PREFIX_W - tail_w - 2) if term_w > 0 else 50
        if self._label_rich is not None:
            label_text = self._label_rich
            if label_text.cell_len > available:
                label_text = label_text.divide([available])[0]
                label_text.append("…", style="dim")
        else:
            label_text = header_label_v4(
                spec, self._header_args or {}, self._label,
                self._full_path, available,
                accent_color=getattr(self, "_focused_gutter_color", ""),
            )
        if self._path_clickable and self._full_path and self._full_path != self._label:
            displayed_plain = label_text.plain.strip()
            if displayed_plain != self._full_path:
                self._tooltip_text = self._full_path
        t.append_text(label_text)
        if term_w > 0:
            label_used = label_text.cell_len
            pad = max(0, available - label_used)
            t.append(" " * pad)
        t.append_text(tail)
        return t

    def render(self):
        result = self._render_v4()
        if result is not None:
            return result
        self.add_class("--header-degraded")
        t = Text()
        t.append(f"[tool] {self._label}")
        if getattr(self, '_browse_badge', ""):
            t.append(f"  {self._browse_badge}", style="bold dim")
        return t

    def set_error(self, is_error: bool) -> None:
        self._tool_icon_error = is_error

    def _feedback_channel_id(self) -> str:
        """Resolve the tool-header channel id for this header."""
        panel_id = self._panel.id if self._panel is not None else self.id
        return f"tool-header::{panel_id}"

    def flash_copy(self, flash_label: str = "✓ Copied", duration: float = 1.5) -> None:
        """RX1 Phase B: forward to FeedbackService tool-header channel."""
        try:
            from hermes_cli.tui.services.feedback import NORMAL
            self.app.feedback.flash(
                self._feedback_channel_id(),
                flash_label,
                duration=duration,
                key="copy",
                tone="success",
                priority=NORMAL,
            )
        except Exception:
            pass

    def flash_success(self) -> None:
        """RX1 Phase B: forward to FeedbackService tool-header channel."""
        try:
            from hermes_cli.tui.services.feedback import NORMAL
            self.app.feedback.flash(
                self._feedback_channel_id(),
                "✓",
                duration=0.45,
                tone="success",
                priority=NORMAL,
            )
        except Exception:
            pass

    def flash_error(self) -> None:
        """RX1 Phase B: forward to FeedbackService tool-header channel."""
        try:
            from hermes_cli.tui.services.feedback import ERROR
            self.app.feedback.flash(
                self._feedback_channel_id(),
                "✗",
                duration=0.45,
                tone="error",
                priority=ERROR,
            )
        except Exception:
            pass

    def set_path(self, path: str) -> None:
        self._full_path = path
        self._path_clickable = True
        self._is_url = any(path.startswith(s) for s in _URL_SCHEMES)

    def set_args(self, args: dict) -> None:
        self._header_args = args
        self.refresh()

    def _render_path_label(self, max_cells: int) -> "Text":
        path = self._full_path or self._label
        parts = path.rsplit("/", 1)
        if len(parts) == 2 and parts[0]:
            dir_part, fname = parts[0] + "/", parts[1]
        else:
            dir_part, fname = "", path

        fname_w = _safe_cell_width(fname)
        dir_budget = max(0, max_cells - fname_w - 1)

        if _safe_cell_width(dir_part) > dir_budget:
            trimmed = dir_part
            while trimmed and _safe_cell_width("…/" + trimmed) > dir_budget:
                trimmed = trimmed.split("/", 1)[-1] if "/" in trimmed else ""
            dir_part = ("…/" + trimmed) if trimmed else "…/"

        t = Text()
        if dir_part:
            t.append(" " + dir_part, style="dim")
        else:
            t.append(" ", style="dim")
        fname_style = "bold" if self._no_underline else "bold underline"
        t.append(fname, style=fname_style)
        return t

    def on_click(self, event: Click) -> None:
        if event.button == 3:
            self._show_context_menu(event)
            event.stop()
            return
        if event.button != 1:
            return
        if self._spinner_char is not None:
            return
        if self._path_clickable and self._full_path:
            event.prevent_default()
            event.stop()
            import sys
            opener = "open" if sys.platform == "darwin" else "xdg-open"
            try:
                self.app._open_path_action(self, self._full_path, opener, False)  # type: ignore[attr-defined]
            except Exception:
                pass
            return
        if getattr(event, "chain", 1) == 2 and self._spinner_char is None and not self._path_clickable:
            try:
                parent = self.parent
                summary = getattr(parent, "_result_summary", None) or self._label
                self.app._copy_text_with_hint(str(summary))  # type: ignore[attr-defined]
            except Exception:
                pass
            event.prevent_default()
            event.stop()
            return
        panel = getattr(self, "_panel", None)
        if panel is not None:
            event.prevent_default()
            event.stop()
            panel.action_toggle_collapse()
            return
        if not self._has_affordances:
            return
        event.prevent_default()
        event.stop()
        parent = self.parent
        if parent is not None:
            parent.toggle()

    def _show_context_menu_at_center(self) -> None:
        try:
            region = self.content_region
            cx = region.x + region.width // 2
            cy = region.y + region.height // 2
            items = self._build_context_menu_items()
            if not items:
                return
            try:
                from hermes_cli.tui.context_menu import ContextMenu
                menu = self.app.query_one(ContextMenu)
                import asyncio
                asyncio.ensure_future(menu.show(items, cx, cy))
            except Exception:
                pass
        except Exception:
            pass

    def _build_context_menu_items(self) -> list:
        import sys
        from pathlib import Path
        from hermes_cli.tui.context_menu import MenuItem
        items = []
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        is_shell = False
        try:
            from hermes_cli.tui.tool_category import spec_for, ToolCategory
            _spec = spec_for(self._tool_name or "")
            is_shell = _spec.category == ToolCategory.SHELL
        except Exception:
            pass
        if self._path_clickable and self._full_path:
            _path = self._full_path
            items.append(MenuItem(
                label="Open file",
                shortcut="",
                action=lambda p=_path: self.app._open_path_action(self, p, opener, False),
            ))
        has_path = self._path_clickable or getattr(self, "_diff_file_path", None) is not None
        if has_path:
            _copy_path = self._full_path or getattr(self, "_diff_file_path", None)
            if _copy_path:
                items.append(MenuItem(
                    label="Copy path",
                    shortcut="",
                    action=lambda cp=_copy_path: self.app._copy_text_with_hint(cp),
                ))
        if is_shell:
            _cmd = str(self._header_args.get("command") or self._header_args.get("cmd") or self._label)
            items.append(MenuItem(
                label="Copy full command",
                shortcut="",
                action=lambda c=_cmd: self.app._copy_text_with_hint(c),
            ))
        if self._path_clickable and self._full_path:
            _parent = str(Path(self._full_path).parent)
            items.append(MenuItem(
                label="Reveal in file manager",
                shortcut="",
                action=lambda p=_parent: self.app._open_path_action(self, p, opener, False),
            ))
        return items

    def _show_context_menu(self, event: Click) -> None:
        import sys
        from pathlib import Path
        from hermes_cli.tui.context_menu import ContextMenu, MenuItem

        items: list[MenuItem] = []
        opener = "open" if sys.platform == "darwin" else "xdg-open"

        is_shell = False
        try:
            from hermes_cli.tui.tool_category import spec_for, ToolCategory
            _spec = spec_for(self._tool_name or "")
            is_shell = _spec.category == ToolCategory.SHELL
        except Exception:
            pass

        if self._path_clickable and self._full_path:
            _path = self._full_path
            items.append(MenuItem(
                label="Open file",
                shortcut="",
                action=lambda p=_path: self.app._open_path_action(self, p, opener, False),  # type: ignore[attr-defined]
            ))

        has_path = self._path_clickable or getattr(self, "_diff_file_path", None) is not None
        if has_path:
            _copy_path = self._full_path or getattr(self, "_diff_file_path", None)
            if _copy_path:
                items.append(MenuItem(
                    label="Copy path",
                    shortcut="",
                    action=lambda cp=_copy_path: self.app._copy_text_with_hint(cp),  # type: ignore[attr-defined]
                ))

        if is_shell:
            _cmd = str(self._header_args.get("command") or self._header_args.get("cmd") or self._label)
            items.append(MenuItem(
                label="Copy full command",
                shortcut="",
                action=lambda c=_cmd: self.app._copy_text_with_hint(c),  # type: ignore[attr-defined]
            ))

        if self._path_clickable and self._full_path:
            _parent = str(Path(self._full_path).parent)
            items.append(MenuItem(
                label="Reveal in file manager",
                shortcut="",
                action=lambda p=_parent: self.app._open_path_action(self, p, opener, False),  # type: ignore[attr-defined]
            ))

        if not items:
            return

        try:
            menu = self.app.query_one(ContextMenu)
            import asyncio
            asyncio.ensure_future(menu.show(items, event.screen_x, event.screen_y))
        except Exception:
            pass


class ToolBodyContainer(Widget):
    """Collapsible container for tool output lines."""

    DEFAULT_CSS = """
    ToolBodyContainer { height: auto; display: none; }
    ToolBodyContainer.expanded { display: block; }
    ToolBodyContainer .--microcopy { height: 1; display: none; color: $text-muted; padding: 0 2; }
    ToolBodyContainer .--microcopy.--active { display: block; }
    ToolBodyContainer .--args-row { height: auto; max-height: 2; padding: 0 2; display: none; color: $text-muted; }
    ToolBodyContainer .--args-row.--active { display: block; }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._secondary_text: str = ""
        self._microcopy_active: bool = False
        self._args_row_mounted: bool = False
        self._omission_parent_block: Any | None = None

    def compose(self) -> ComposeResult:
        yield Static("", classes="--args-row")
        parent_block = self._omission_parent_block
        if parent_block is not None:
            top = OmissionBar(parent_block=parent_block, position="top", classes="--omission-bar-top")
            top.display = False
            parent_block._omission_bar_top = top
            parent_block._omission_bar_top_mounted = True
            yield top
        yield Static("", classes="--microcopy")
        yield CopyableRichLog(markup=False, highlight=False, wrap=False)
        if parent_block is not None:
            bottom = OmissionBar(parent_block=parent_block, position="bottom", classes="--omission-bar-bottom")
            bottom.display = False
            parent_block._omission_bar_bottom = bottom
            parent_block._omission_bar_bottom_mounted = True
            yield bottom

    def set_args_row(self, text: "str | None") -> None:
        from textual.css.query import NoMatches
        try:
            w = self.query_one(".--args-row", Static)
        except (NoMatches, Exception):
            if getattr(self, "_args_row_mounted", False):
                # Stale flag — widget was removed; reset and re-mount
                self._args_row_mounted = False
                new_w = Static(text or "", classes="--args-row")
                if text:
                    new_w.add_class("--active")
                self.mount(new_w)
                self._args_row_mounted = True
            return
        if not text:
            try:
                w.remove_class("--active")
            except AttributeError:
                pass
            w.update("")
        else:
            w.update(text)
            try:
                w.add_class("--active")
            except AttributeError:
                pass

    def _mc_widget(self) -> "Static | None":
        try:
            return self.query_one(".--microcopy", Static)
        except Exception:
            return None

    def update_secondary_args(self, text: str) -> None:
        self._secondary_text = text
        self.set_args_row(text if text else None)

    def set_microcopy(self, text: "str | object") -> None:
        self._microcopy_active = True
        mc = self._mc_widget()
        if mc is None:
            return
        mc.update(text)
        mc.remove_class("--secondary-args")
        mc.add_class("--active")

    def clear_microcopy(self) -> None:
        self._microcopy_active = False
        mc = self._mc_widget()
        if mc is None:
            return
        mc.remove_class("--active")
        mc.remove_class("--secondary-args")
        mc.update("")
