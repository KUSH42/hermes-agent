"""P7 — /tools timeline overlay.

ToolsScreen: full-screen Screen showing the current turn's tool calls as a
waterfall Gantt timeline.  Activated via `/tools` slash command or `T` in
browse mode.  Snapshot is frozen at construction; no live-reactive updates.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Input, ListView, ListItem, Static
from textual.containers import Horizontal
from rich.text import Text

from hermes_cli.tui.resize_utils import THRESHOLD_NARROW, crosses_threshold

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Layout helpers
# ---------------------------------------------------------------------------

def _split_flex(flex: int) -> tuple[int, int]:
    """Return (label_w, gantt_w) for a given flex budget.

    Fixed columns consume 26 cells; flex = term_w - 26.
    Post-clamp is mandatory: gantt_w = min(gantt_w, flex - label_w).
    """
    if flex >= 80:
        label_w = 40
        gantt_w = flex - 40
    elif flex >= 50:
        label_w = max(20, flex // 2)
        gantt_w = flex - label_w
    elif flex >= 30:
        label_w = max(16, flex - 20)
        gantt_w = 20
    else:
        label_w = max(10, flex - 16)
        gantt_w = 16
    # Mandatory post-clamp
    gantt_w = min(gantt_w, flex - label_w)
    return label_w, gantt_w


def _gantt_scale_text(turn_total_s: float, gantt_w: int, label_w: int) -> "Text":
    """Build a 3-marker axis label row aligned with the Gantt column."""
    from rich.text import Text
    half_s = turn_total_s / 2
    result = Text(" " * label_w)
    result.append("0s", style="dim")
    half_label = f"{half_s:.1f}s"
    total_label = f"{turn_total_s:.1f}s"
    mid_pad = max(0, (gantt_w // 2) - 2)
    result.append(" " * mid_pad)
    result.append(half_label, style="dim")
    right_pad = max(0, gantt_w - (gantt_w // 2) - len(half_label) - len(total_label))
    result.append(" " * right_pad)
    result.append(total_label, style="dim")
    return result


def _compute_turn_total_s(snapshot: list[dict]) -> float:
    """Max end time across all completed calls; floor at 0.001 to avoid div-by-zero."""
    end_times = [
        e["start_s"] + (e["dur_ms"] or 0) / 1000.0
        for e in snapshot
        if e.get("dur_ms") is not None
    ]
    return max(max(end_times, default=0.0), 0.001)


def _primary_arg_str(entry: dict) -> str:
    """Extract primary arg string value from entry['args'] for text filtering."""
    args = entry.get("args") or {}
    primary_keys = ("path", "file", "filename", "command", "cmd", "query", "pattern", "url", "thought", "task", "description")
    for k in primary_keys:
        if k in args:
            v = args[k]
            return str(v) if v is not None else ""
    # Fall back to first value
    for v in args.values():
        return str(v) if v is not None else ""
    return ""


def render_tool_row(
    entry: dict,
    cursor: bool,
    turn_total_s: float,
    term_w: int,
) -> Text:
    """Compose one Rich Text timeline row.

    Returns a single-line Text with no trailing newline.
    """
    flex = term_w - 26
    if flex < 26:
        return Text(f"  (terminal too narrow — resize to ≥60 cols)", style="dim")

    label_w, gantt_w = _split_flex(flex)

    # --- ts_col (5 cells) ---
    start_s = entry.get("start_s", 0.0)
    ts_str = f"{start_s:.1f}s"
    ts_col = ts_str.rjust(4) + " "  # e.g. "0.3s "

    # --- icon (3 cells) ---
    category = entry.get("category", "unknown")
    is_error = entry.get("is_error", False)
    mcp_server = entry.get("mcp_server")
    _CATEGORY_ICONS = {
        "file": "󰈙",
        "shell": "$",
        "search": "?",
        "web": "🌐",
        "code": "⚙",
        "agent": "✓",
        "mcp": "󰡨",
        "unknown": "·",
    }
    icon_glyph = _CATEGORY_ICONS.get(category if not mcp_server else "mcp", "·")
    icon_col = f"{icon_glyph}  "  # glyph + 2 spaces

    # --- label ---
    display_name = entry.get("name", "?")
    if mcp_server:
        tool_short = display_name.split("__")[-1] if "__" in display_name else display_name
        display_name = f"{mcp_server}.{tool_short}"
    primary_arg = _primary_arg_str(entry)
    preview_budget = max(0, label_w - len(display_name) - 2)
    primary_arg = primary_arg[:min(preview_budget, 30)]
    if len(primary_arg) == preview_budget and preview_budget < len(_primary_arg_str(entry)):
        primary_arg = primary_arg[:-1] + "…"
    label_full = f"{display_name}  {primary_arg}" if primary_arg else display_name
    if len(label_full) > label_w:
        label_full = label_full[: label_w - 1] + "…"
    label_col = label_full.ljust(label_w)

    # --- gantt bar ---
    dur_ms = entry.get("dur_ms")
    in_progress = dur_ms is None
    all_in_progress = turn_total_s <= 0.001

    if in_progress:
        bar_cells = 1
        if all_in_progress:
            offset_cells = 0
        else:
            offset_cells = min(round(start_s / turn_total_s * gantt_w), gantt_w - 1)
        bar_str = " " * offset_cells + "━⠋" + " " * max(0, gantt_w - offset_cells - 2)
    else:
        dur_s = dur_ms / 1000.0
        bar_cells = max(1, round(dur_s / turn_total_s * gantt_w))
        bar_cells = min(bar_cells, gantt_w)
        if all_in_progress:
            offset_cells = 0
        else:
            offset_cells = round(start_s / turn_total_s * gantt_w)
            offset_cells = min(offset_cells, gantt_w - bar_cells)
        bar_str = " " * offset_cells + "━" * bar_cells + " " * (gantt_w - offset_cells - bar_cells)

    # --- dur_col (9 cells) ---
    if in_progress:
        dur_col = " ⠋ …     "  # 9 chars
    else:
        d = dur_ms or 0
        if d >= 1000:
            dur_str = f"({d}ms)"
        else:
            dur_str = f"({d}ms)"
        dur_col = dur_str[:8].ljust(8) + " "

    # --- assemble ---
    row = Text()
    row.append(" ", style="")
    row.append(ts_col, style="dim")
    row.append("┊ ", style="color(4) dim")

    icon_style = "bold red" if is_error else (f"" if mcp_server else "")
    row.append(icon_col, style=icon_style)

    label_style = "bold" if cursor else ""
    row.append(label_col, style=label_style)

    row.append("  ", style="")

    gantt_style = "dim red" if is_error else ("dim" if in_progress else "")
    row.append(bar_str, style=gantt_style)

    row.append("  ", style="")

    dur_style = "italic dim red" if is_error else ("italic dim" if in_progress else "dim")
    row.append(dur_col, style=dur_style)
    row.append(" ", style="")

    if cursor:
        row.stylize("bold on #333399", 0, len(row))

    return row


# ---------------------------------------------------------------------------
# ToolsScreen
# ---------------------------------------------------------------------------

class ToolsScreen(Screen):
    """Full-screen /tools timeline overlay.

    Lifecycle: push_screen(ToolsScreen(snapshot)) → user navigates → pop_screen().
    Snapshot is frozen at construction; no live update (use `r` to refresh).
    """

    DEFAULT_CSS = """
ToolsScreen {
    layout: vertical;
    background: $surface;
}
ToolsScreen > #tools-header {
    height: 1;
    background: $primary 20%;
    padding: 0 1;
}
ToolsScreen > #tools-list {
    height: 1fr;
    scrollbar-size: 1 1;
}
ToolsScreen > #filter-row {
    height: 1;
    padding: 0 1;
    background: $surface-darken-1;
}
ToolsScreen > #filter-row > #filter-input {
    width: 1fr;
    border: none;
    background: transparent;
}
ToolsScreen > #tools-footer {
    height: 1;
    padding: 0 1;
    background: $primary 10%;
    color: $text-muted;
}
"""

    BINDINGS = [
        Binding("escape", "dismiss_overlay", "Close", priority=True),
        Binding("slash", "open_filter", "Filter", show=False),
        Binding("x", "export_json", "Export", show=False),
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("enter", "jump_to_panel", "Jump", show=False),
        Binding("r", "refresh", "Refresh snapshot", show=False),
    ]

    def __init__(self, snapshot: list[dict]) -> None:
        super().__init__()
        self._snapshot: list[dict] = snapshot
        self._filtered: list[dict] = list(snapshot)
        self._cursor: int = 0
        self._filter_text: str = ""
        self._active_categories: set[str] = set()
        self._errors_only: bool = False
        self._turn_total_s: float = _compute_turn_total_s(snapshot)
        self._term_w: int = 80
        self._last_resize_w: int = 0
        self._snapshot_ts: float = time.monotonic()
        self._stale_timer: object | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="tools-header")
        yield Static("", id="gantt-scale")
        yield ListView(id="tools-list")
        yield Horizontal(
            Static("", id="filter-pills"),
            Input(id="filter-input", placeholder="filter…"),
            id="filter-row",
        )
        yield Static("[Enter] jump  [Esc] close  [/] filter  [x] export  [r] refresh", id="tools-footer")

    async def on_mount(self) -> None:
        self._term_w = self.app.size.width
        if self._term_w < 60:
            self.app._flash_hint("⚠  terminal too narrow for /tools overlay", 2.0)
            self.app.pop_screen()
            return
        self.query_one("#filter-input", Input).display = False
        self._stale_timer = self.set_interval(1.0, self._update_staleness_pip)
        await self._rebuild()

    def on_unmount(self) -> None:
        if self._stale_timer is not None:
            self._stale_timer.stop()

    def on_resize(self) -> None:
        w = self.app.size.width
        self._term_w = w
        if crosses_threshold(self._last_resize_w, w, THRESHOLD_NARROW) and w < THRESHOLD_NARROW:
            self.app._flash_hint("⚠  terminal too narrow for /tools overlay", 2.0)
            self.app.pop_screen()
        self._last_resize_w = w

    def _update_staleness_pip(self) -> None:
        elapsed = time.monotonic() - self._snapshot_ts
        n = len(self._filtered)
        total_s = self._turn_total_s
        if elapsed < 5:
            pip = "● live"
            pip_style = "green"
        elif elapsed < 30:
            pip = "○ stale  press r to refresh"
            pip_style = "dim"
        else:
            pip = "○ stale — press r"
            pip_style = "yellow dim"
        header_text = Text()
        header_text.append(f" Tools in this turn ", style="bold")
        header_text.append(f"  {n} calls · {total_s:.1f}s  ", style="dim")
        header_text.append(pip, style=pip_style)
        try:
            self.query_one("#tools-header", Static).update(header_text)
        except Exception:
            pass

    async def _rebuild(self) -> None:
        listview = self.query_one("#tools-list", ListView)
        await listview.clear()
        # Update Gantt scale header
        try:
            flex = self._term_w - 26
            label_w, gantt_w = _split_flex(flex)
            scale = _gantt_scale_text(max(self._turn_total_s, 0.001), gantt_w, label_w)
            self.query_one("#gantt-scale", Static).update(scale)
        except Exception:
            pass
        if not self._filtered:
            await listview.append(ListItem(Static(Text("  no matching tool calls", style="dim"))))
            return
        for i, entry in enumerate(self._filtered):
            row_text = render_tool_row(
                entry,
                cursor=(i == self._cursor),
                turn_total_s=self._turn_total_s,
                term_w=self._term_w,
            )
            await listview.append(ListItem(Static(row_text)))
        self._update_staleness_pip()
        self._update_pills()

    def _update_pills(self) -> None:
        cats = sorted({e.get("category", "unknown") for e in self._snapshot})
        parts = []
        # errors-only pill
        err_style = "bold" if self._errors_only else "dim"
        parts.append(Text("[errors]", style=err_style))
        parts.append(Text(" ", style=""))
        # category pills
        for cat in ["file", "shell", "search", "web", "code", "agent", "mcp"] + [c for c in cats if c not in ("file", "shell", "search", "web", "code", "agent", "mcp")]:
            if cat not in cats:
                continue
            active = cat in self._active_categories
            style = "bold" if active else "dim"
            parts.append(Text(f"[{cat}]", style=style))
            parts.append(Text(" ", style=""))
        combined = Text()
        for p in parts:
            combined.append_text(p)
        try:
            self.query_one("#filter-pills", Static).update(combined)
        except Exception:
            pass

    async def on_key(self, event) -> None:
        if event.key == "escape":
            fi = self.query_one("#filter-input", Input)
            if fi.display:
                self._filter_text = ""
                fi.display = False
                fi.value = ""
                await self._apply_filter()
                event.prevent_default()
                return
        # arrow key cursor sync with ListView.index
        if event.key in ("up", "down"):
            if self._filtered:
                if event.key == "up":
                    self._cursor = max(0, self._cursor - 1)
                else:
                    self._cursor = min(len(self._filtered) - 1, self._cursor + 1)
                lv = self.query_one("#tools-list", ListView)
                lv.index = self._cursor
                await self._rebuild()
                event.prevent_default()

    async def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-input":
            self._filter_text = event.value
            await self._apply_filter()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "filter-input":
            fi = self.query_one("#filter-input", Input)
            fi.display = False
            await self.action_jump_to_panel()

    async def action_dismiss_overlay(self) -> None:
        self.app.pop_screen()

    async def action_open_filter(self) -> None:
        fi = self.query_one("#filter-input", Input)
        fi.display = True
        fi.focus()

    async def action_cursor_up(self) -> None:
        if self._filtered:
            self._cursor = max(0, self._cursor - 1)
            await self._rebuild()

    async def action_cursor_down(self) -> None:
        if self._filtered:
            self._cursor = min(len(self._filtered) - 1, self._cursor + 1)
            await self._rebuild()

    async def action_jump_to_panel(self) -> None:
        if not self._filtered:
            return
        entry = self._filtered[self._cursor]
        panel_id = f"tool-{entry['tool_call_id']}"
        self.app.pop_screen()

        def _after_pop() -> None:
            try:
                from textual.css.query import NoMatches
                try:
                    panel = self.app.query_one(f"#{panel_id}")
                except NoMatches:
                    self.app._flash_hint("⚠  panel not found", 2.0)
                    return
                # Expand enclosing ToolGroup if collapsed
                try:
                    from hermes_cli.tui.tool_group import ToolGroup as _TG
                    for ancestor in panel.ancestors:
                        if isinstance(ancestor, _TG) and ancestor.collapsed:
                            ancestor.collapsed = False
                            break
                except Exception:
                    pass
                # Expand own body if collapsed
                try:
                    if hasattr(panel, "_body") and not panel._body.has_class("expanded"):
                        panel.toggle()
                except Exception:
                    pass
                panel.scroll_visible(animate=False)
                if self.app.browse_mode:
                    try:
                        from hermes_cli.tui.tool_blocks import ToolHeader as _TH
                        headers = list(self.app.query(_TH))
                        for i, h in enumerate(headers):
                            if h.parent is panel or (hasattr(h, "parent") and getattr(h.parent, "parent", None) is panel):
                                self.app.browse_index = i
                                break
                    except Exception:
                        pass
            except Exception:
                pass

        self.app.call_later(_after_pop)

    def action_export_json(self) -> None:
        try:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
            # Find hermes root (dir containing .hermes/)
            hermes_root: Path | None = None
            cwd = Path.cwd()
            for candidate in [cwd, cwd.parent, cwd.parent.parent]:
                if (candidate / ".hermes").is_dir():
                    hermes_root = candidate
                    break
            if hermes_root is None:
                hermes_root = cwd
            export_dir = hermes_root / ".hermes"
            export_dir.mkdir(parents=True, exist_ok=True)
            path = export_dir / f"tools_{ts}.json"
            payload = {
                "turn_id": None,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "calls": self._snapshot,
            }
            path.write_text(json.dumps(payload, indent=2, default=str))
            self.app._flash_hint(f"✓ exported → {path}", 3.0)
        except PermissionError as e:
            self.app._flash_hint(f"✗ export failed: permission denied — {e}", 3.0)
        except OSError as e:
            self.app._flash_hint(f"✗ export failed: {e}", 3.0)

    async def action_refresh(self) -> None:
        """Re-fetch snapshot from app and rebuild."""
        new_snapshot = self.app.current_turn_tool_calls()
        # Preserve cursor by tool_call_id
        cursor_id: str | None = None
        if self._filtered and 0 <= self._cursor < len(self._filtered):
            cursor_id = self._filtered[self._cursor].get("tool_call_id")
        self._snapshot = new_snapshot
        self._filtered = list(new_snapshot)
        self._turn_total_s = _compute_turn_total_s(new_snapshot)
        self._snapshot_ts = time.monotonic()
        await self._apply_filter()
        # Restore cursor
        if cursor_id is not None:
            for i, e in enumerate(self._filtered):
                if e.get("tool_call_id") == cursor_id:
                    self._cursor = i
                    break
            else:
                self._cursor = 0
        await self._rebuild()

    async def _apply_filter(self) -> None:
        text = self._filter_text.lower()
        cat_filter = self._active_categories
        self._filtered = [
            e for e in self._snapshot
            if (not text or text in e.get("name", "").lower() or _primary_arg_str(e).lower().startswith(text))
            and (not cat_filter or e.get("category", "unknown") in cat_filter)
            and (not self._errors_only or e.get("is_error", False))
        ]
        self._cursor = max(0, min(self._cursor, len(self._filtered) - 1))
        await self._rebuild()
