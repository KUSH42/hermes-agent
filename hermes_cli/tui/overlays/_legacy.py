"""Info overlay widgets for slash command TUI integration.

HelpOverlay, UsageOverlay, CommandsOverlay, WorkspaceOverlay have been migrated
to hermes_cli.tui.overlays.reference (R3 Phase C).  This file retains
SessionOverlay and ToolPanelHelpOverlay.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.style import Style
from rich.text import Text
from textual import work
from textual.app import ComposeResult

_log = logging.getLogger(__name__)
from textual.binding import Binding
from hermes_cli.tui.overlays._modal_mixin import ModalOverlayMixin
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Button, Checkbox, ContentSwitcher, Input, OptionList, Static
from textual.widgets.option_list import Option


try:
    from hermes_cli.config import (
        _set_nested as _cfg_set_nested,
        get_hermes_home as _cfg_get_hermes_home,
        read_raw_config as _cfg_read_raw_config,
        save_config as _cfg_save_config,
    )
except ImportError:  # il-ex-1-exempt: swallow
    def _cfg_read_raw_config():  # type: ignore[misc]
        return {}

    def _cfg_save_config(cfg):  # type: ignore[misc]
        pass

    def _cfg_set_nested(cfg, key, value):  # type: ignore[misc]
        pass

    def _cfg_get_hermes_home():  # type: ignore[misc]
        from pathlib import Path
        return Path.home() / ".hermes"


_SESS_FOOTER_LEGEND = "[dim]↑↓ navigate · Enter resume · N new · D delete · Esc close[/dim]"


def _format_tokens_compact(total: int) -> str:
    """Return a right-aligned 9-char token count string, e.g. ' 1.2k tok'."""
    if total == 0:
        return "    — tok"
    if total < 1_000:
        return f"{total:>5} tok"
    if total < 10_000:
        # 1k–9.9k: one decimal, strip trailing .0
        val = int(total / 100) / 10
        s = f"{val:.1f}".rstrip("0").rstrip(".") + "k"
        return f"{s:>5} tok"
    if total < 1_000_000:
        # 10k–999k: zero decimals (floor)
        s = f"{int(total / 1000)}k"
        return f"{s:>5} tok"
    if total >= 99_000_000:
        return " >99M tok"
    # 1M–98.9M: one decimal, strip trailing .0
    val = int(total / 100_000) / 10
    s = f"{val:.1f}".rstrip("0").rstrip(".") + "M"
    return f"{s:>5} tok"


class _SessionResumedBanner(Widget):
    """Single-line banner displayed after /resume clears OutputPanel."""

    DEFAULT_CSS = """
    _SessionResumedBanner {
        height: 1;
        width: 1fr;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self, session_title: str, turn_count: int) -> None:
        super().__init__()
        self._session_title = session_title
        self._turn_count = turn_count

    def render(self) -> str:
        label = self._session_title or ""
        turns = self._turn_count
        turn_word = "turn" if turns == 1 else "turns"
        return f"╌╌  resumed: {label}  ·  {turns} previous {turn_word}  ╌╌"


class SessionOverlay(ModalOverlayMixin, Widget):
    """Session browser overlay. Open with /sessions or Ctrl+J."""

    _push_modal_on_mount: bool = False  # permanent widget; push/pop managed in open_sessions/dismiss_overlay

    DEFAULT_CSS = """
    SessionOverlay {
        display: none;
        layer: overlay;
        dock: top;
        height: auto;
        max-height: 60%;
        min-height: 10;
        width: 1fr;
        max-width: 80;
        margin: 1 2;
        padding: 0 1;
        background: $surface;
        border: tall $primary 15%;
        border-title-align: left;
        border-title-color: $accent;
        border-subtitle-align: right;
        border-subtitle-color: $text-muted;
    }
    SessionOverlay.--visible { display: block; }
    SessionOverlay #sess-scroll { height: auto; max-height: 50%; overflow-y: auto; }
    SessionOverlay #sess-columns { height: 1; padding: 0 1; color: $text-muted; text-style: bold; }
    SessionOverlay #sess-confirm { height: 1; padding: 0 1; color: $warning; display: none; }
    SessionOverlay #sess-confirm.--visible { display: block; }
    SessionOverlay ._SessionRow { height: 1; padding: 0 1; }
    SessionOverlay ._SessionRow.--selected { background: $accent 20%; }
    SessionOverlay ._SessionRow:hover { background: $accent 10%; }
    SessionOverlay ._SessionRow.--current { color: $accent; }
    """

    BINDINGS = [
        Binding("escape", "dismiss", priority=True),
        Binding("up",     "move_up",   priority=True),
        Binding("down",   "move_down", priority=True),
        Binding("ctrl+p", "move_up",   priority=True),
        Binding("ctrl+n", "move_down", priority=True),
        Binding("enter",  "select",    priority=True),
        Binding("n",      "new_session", priority=True),
        Binding("d",      "delete_selected", priority=True),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._sessions: list[dict] = []
        self._selected_idx: int = 0
        self._pending_delete_idx: int | None = None
        self._last_resize_w: int = 0
        cfg = _cfg_read_raw_config()
        self._heavy_threshold: int = (
            cfg.get("tui", {}).get("session_overlay", {}).get("tokens_heavy", 200_000)
        )

    def compose(self) -> "ComposeResult":
        yield Static("", id="sess-header")
        yield Static("", id="sess-columns")
        yield ScrollableContainer(id="sess-scroll")
        yield Static("", id="sess-confirm")
        yield Static(_SESS_FOOTER_LEGEND, id="sess-footer")

    def on_mount(self) -> None:
        # Permanent widget: do NOT call ModalOverlayMixin.on_mount().
        # push_modal / --modal are managed per open_sessions() / dismiss_overlay() cycle.
        pass

    def on_unmount(self) -> None:
        # Permanent widget: never removed from DOM. ModalOverlayMixin.on_unmount must NOT
        # be called here — stack/focus cleanup is owned by dismiss_overlay(), not lifecycle hooks.
        pass

    def on_resize(self, event) -> None:
        if not self.has_class("--visible") or not self._sessions:
            return
        new_w = getattr(getattr(event, "size", None), "width", 0)
        if new_w == self._last_resize_w:
            return
        self._last_resize_w = new_w
        self._render_rows(self._sessions, preserve_idx=self._selected_idx)

    def open_sessions(self) -> None:
        """Show overlay and load sessions in background worker."""
        if self.has_class("--visible"):
            return  # already open — don't double-push the modal stack
        self._cancel_pending_delete()
        self.border_title = "Sessions"
        self._capture_focus_caller()
        try:
            self.app.push_modal(self)  # il-m1: register in arbiter stack
        except AttributeError:  # il-ex-1-exempt: push_modal absent in tests or pre-patch HermesApp — graceful degrade
            _log.debug("SessionOverlay.open_sessions: app has no push_modal")
        self.add_class("--modal", "--visible")  # il-m1: owned by open_sessions (permanent widget override)
        self._selected_idx = 0
        try:
            self.query_one("#sess-scroll", ScrollableContainer).remove_children()
            self.query_one("#sess-scroll", ScrollableContainer).mount(Static("[dim]Loading…[/dim]", id="sess-loading"))
        except NoMatches:  # il-ex-1-exempt: swallow
            pass
        self._load_sessions()
        # C3: take keyboard focus so ↑↓ navigation works immediately after opening.
        self.focus()

    def dismiss_overlay(self) -> None:
        """Permanent-widget dismiss: hide without removing from DOM."""
        target = self._restore_focus_to()
        self.remove_class("--visible", "--modal")  # il-m1: owned by dismiss_overlay (permanent override)
        try:
            self.app.pop_modal(self)  # il-m1: deregister from arbiter stack
        except AttributeError:  # il-ex-1-exempt: pop_modal absent in tests or pre-patch HermesApp — graceful degrade
            _log.debug("SessionOverlay.dismiss_overlay: app has no pop_modal")
        if target is not None:
            try:
                if target.is_mounted:
                    target.focus()
            except Exception:
                _log.debug("SessionOverlay.dismiss_overlay: focus restore failed", exc_info=True)

    def _cancel_pending_delete(self) -> None:
        self._pending_delete_idx = None
        try:
            self.query_one("#sess-confirm").remove_class("--visible")
        except NoMatches:  # il-ex-1-exempt: swallow
            _log.debug("_cancel_pending_delete: #sess-confirm not found")
        try:
            self.query_one("#sess-footer").styles.display = "block"
        except NoMatches:  # il-ex-1-exempt: swallow
            _log.debug("_cancel_pending_delete: #sess-footer not found")

    @work(thread=True)
    def _load_sessions(self) -> None:
        """Fetch session list from DB in worker thread."""
        try:
            db = getattr(self.app.cli, "_session_db", None) if hasattr(self, "app") else None
            if db is None:
                sessions: list[dict] = []
            else:
                sessions = db.list_sessions_rich(limit=20)
        except Exception:
            _log.warning("_load_sessions: session DB read failed", exc_info=True)
            sessions = []
        self.app.call_from_thread(self._render_rows, sessions)

    def _build_column_header(self, title_width: int) -> str:
        return (
            f"{'':2}{'':2}"
            f"{'TITLE':<{title_width}} "
            f"{'LAST':<11} "
            f"{'TURNS':>9} "
            f"{'TOKENS':>9}"
        )

    def _render_rows(self, sessions: list[dict], *, preserve_idx: int | None = None) -> None:
        """Render session rows after worker completes (event-loop only)."""
        self._sessions = sessions
        try:
            scroll = self.query_one("#sess-scroll", ScrollableContainer)
        except NoMatches:  # il-ex-1-exempt: swallow
            return
        scroll.remove_children()
        current_id = getattr(getattr(self.app, "cli", None), "session_id", None)
        title_width = max(18, self.content_size.width - 2 - 2 - 11 - 9 - 9 - 3 - 2)

        # SO-2: resolve token colors from skin; fall back to defaults if not valid hex
        def _is_hex(s: str) -> bool:
            return bool(s and s.startswith("#") and len(s) in (4, 7, 9) and
                        all(c in "0123456789abcdefABCDEF" for c in s[1:]))

        color_tokens_warning = "#FEA62B"
        color_tokens_muted = "#767C8C"
        color_tokens_disabled = "#3E4252"
        try:
            from hermes_cli.tui.body_renderers._grammar import SkinColors
            sc = SkinColors.from_app(self.app)
            if _is_hex(sc.warning):
                color_tokens_warning = sc.warning
            if _is_hex(sc.muted):
                color_tokens_muted = sc.muted
        except Exception:  # il-ex-1-exempt: swallow
            pass
        try:
            _cv = self.app.get_css_variables()
            raw_disabled = (_cv.get("text-disabled") or "").strip()
            if _is_hex(raw_disabled):
                color_tokens_disabled = raw_disabled
        except Exception:  # il-ex-1-exempt: swallow
            pass

        rows: list["_SessionRow"] = []
        for i, s in enumerate(sessions):
            is_current = (s.get("id") == current_id)
            row = _SessionRow(
                s, is_current=is_current, idx=i,
                title_width=title_width, heavy_threshold=self._heavy_threshold,
                color_tokens_warning=color_tokens_warning,
                color_tokens_muted=color_tokens_muted,
                color_tokens_disabled=color_tokens_disabled,
            )
            rows.append(row)
        if rows:
            scroll.mount(*rows)
        else:
            scroll.mount(Static("[dim]No sessions found[/dim]"))
        # Update header
        current_label = ""
        for s in sessions:
            if s.get("id") == current_id:
                current_label = s.get("title") or (s.get("id", "")[-8:] if s.get("id") else "")
                break
        try:
            self.query_one("#sess-header", Static).update(
                f"[bold]Sessions[/bold]  [dim]Current: {current_label}[/dim]"
            )
        except NoMatches:  # il-ex-1-exempt: swallow
            pass
        try:
            self.query_one("#sess-columns", Static).update(self._build_column_header(title_width))
        except NoMatches:  # il-ex-1-exempt: swallow
            pass
        if preserve_idx is not None:
            self._selected_idx = min(preserve_idx, max(0, len(sessions) - 1))
        else:
            self._selected_idx = 0
        self._update_selection()

    def _update_selection(self) -> None:
        try:
            rows = list(self.query(_SessionRow))
        except Exception:
            _log.debug("SessionOverlay._update_selection: query failed", exc_info=True)
            return
        for i, row in enumerate(rows):
            is_sel = (i == self._selected_idx)
            row.set_class(is_sel, "--selected")
            row.update(row._build_label(selected=is_sel))  # SO-1: update selector glyph
        # C2: scroll to keep selected row visible (unchanged)
        if 0 <= self._selected_idx < len(rows):
            try:
                self.query_one("#sess-scroll", ScrollableContainer).scroll_to_widget(
                    rows[self._selected_idx], animate=False
                )
            except NoMatches:  # il-ex-1-exempt: swallow
                pass

    def action_move_up(self) -> None:
        self._cancel_pending_delete()
        self._selected_idx = max(0, self._selected_idx - 1)
        self._update_selection()

    def action_move_down(self) -> None:
        self._cancel_pending_delete()
        count = len(self._sessions)
        self._selected_idx = min(max(count - 1, 0), self._selected_idx + 1)
        self._update_selection()

    def action_select(self) -> None:
        if not self._sessions:
            self.dismiss_overlay()
            return
        idx = max(0, min(self._selected_idx, len(self._sessions) - 1))
        session = self._sessions[idx]
        current_id = getattr(getattr(self.app, "cli", None), "session_id", None)
        sid = session.get("id", "")
        self.dismiss_overlay()
        if sid == current_id:
            return
        try:
            self.app.action_resume_session(sid)
        except Exception:
            _log.warning("SessionOverlay.action_select: action_resume_session failed", exc_info=True)

    def action_new_session(self) -> None:
        self.dismiss_overlay()
        try:
            self.app._svc_commands.handle_tui_command("/new")
        except Exception:
            _log.warning("SessionOverlay.action_new_session: handle_tui_command failed", exc_info=True)

    def action_delete_selected(self) -> None:
        if self._pending_delete_idx is not None:
            # Second-D path: confirm the delete
            idx = self._pending_delete_idx
            if not (0 <= idx < len(self._sessions)):
                _log.debug("delete_session: pending idx %d out of range (sessions len %d)", idx, len(self._sessions))
                self._cancel_pending_delete()
                return
            session = self._sessions[idx]
            session_id = session.get("id", "")
            db = getattr(getattr(self.app, "cli", None), "_session_db", None)
            if db is None:
                _log.warning("delete_session: no _session_db on app.cli — skipping")
                self._cancel_pending_delete()
                return
            sessions_dir = _cfg_get_hermes_home() / "sessions"
            # Eagerly pop row before worker starts
            self._sessions.pop(idx)
            self._cancel_pending_delete()
            self._render_rows(self._sessions, preserve_idx=min(idx, max(0, len(self._sessions) - 1)))
            self._run_delete_worker(session_id, db, sessions_dir, original_idx=idx, session=session)
            return

        # First-D path
        if not self._sessions:
            return
        idx = self._selected_idx
        session = self._sessions[idx]
        current_session_id = getattr(getattr(self.app, "cli", None), "session_id", None)
        if session.get("id") == current_session_id:
            try:
                self.query_one("#sess-footer", Static).update(
                    "Cannot delete the active session — switch first"
                )
            except NoMatches:  # il-ex-1-exempt: swallow
                pass

            def _restore_footer() -> None:
                try:
                    self.query_one("#sess-footer", Static).update(_SESS_FOOTER_LEGEND)
                except NoMatches:  # il-ex-1-exempt: swallow
                    pass  # overlay may have been dismissed before timer fired

            self.set_timer(2, _restore_footer)
            return

        title = session.get("title") or ""
        self._pending_delete_idx = idx
        try:
            self.query_one("#sess-confirm", Static).update(
                f"Delete '{title or 'untitled'}'? Press D again to confirm, Esc to cancel"
            )
            self.query_one("#sess-confirm").add_class("--visible")
        except NoMatches:  # il-ex-1-exempt: swallow
            pass
        try:
            self.query_one("#sess-footer").styles.display = "none"
        except NoMatches:  # il-ex-1-exempt: swallow
            pass

    @work(thread=True)
    def _run_delete_worker(self, session_id, db, sessions_dir, original_idx, session):
        try:
            deleted = db.delete_session(session_id, sessions_dir=sessions_dir)
            if not deleted:
                _log.debug("delete_session: session %s already gone", session_id)
            # deleted=False treated as success — row already removed from UI
        except Exception:
            _log.exception("delete_session failed for %s", session_id)
            self.app.call_from_thread(self._after_delete_failure, session, original_idx)

    def _after_delete_failure(self, session: dict, idx: int) -> None:
        insert_at = min(idx, len(self._sessions))
        self._sessions.insert(insert_at, session)
        self._render_rows(self._sessions, preserve_idx=insert_at)
        try:
            self.query_one("#sess-footer").styles.display = "none"
        except NoMatches:  # il-ex-1-exempt: swallow
            _log.debug("_after_delete_failure: #sess-footer not found")
        try:
            confirm = self.query_one("#sess-confirm")
            confirm.update("Delete failed — see log")
            confirm.add_class("--visible")
            self._pending_delete_idx = insert_at
        except NoMatches:  # il-ex-1-exempt: swallow
            _log.debug("_after_delete_failure: #sess-confirm not found")

    def dismiss(self) -> None:
        """Public close helper — delegates to action_dismiss."""
        self.action_dismiss()

    def action_dismiss(self) -> None:
        if self._pending_delete_idx is not None:
            self._cancel_pending_delete()
            return
        self.dismiss_overlay()


class _SessionRow(Static):
    """Single row in SessionOverlay."""

    def __init__(
        self,
        session_meta: dict,
        is_current: bool,
        idx: int,
        title_width: int = 18,
        heavy_threshold: int = 200_000,
        color_tokens_warning: str = "#FEA62B",
        color_tokens_muted: str = "#767C8C",
        color_tokens_disabled: str = "#3E4252",
        **kwargs: object,
    ) -> None:
        self._meta = session_meta
        self._is_current = is_current
        self._idx = idx
        self._title_width = title_width
        self._heavy_threshold = heavy_threshold
        self._color_tokens_warning = color_tokens_warning
        self._color_tokens_muted = color_tokens_muted
        self._color_tokens_disabled = color_tokens_disabled
        super().__init__(self._build_label(), **kwargs)
        if is_current:
            self.add_class("--current")

    def _build_label(self, selected: bool = False) -> Text:
        import time as _time
        from datetime import datetime as _datetime
        meta = self._meta
        title = meta.get("title") or ""
        last_active = meta.get("last_active") or meta.get("started_at") or 0
        turn_count = int(meta.get("message_count") or 0)

        # Selector slot
        t = Text()
        t.append("› " if selected else "  ")
        # Current marker slot
        t.append("● " if self._is_current else "  ")

        # Title slot — operate on plain text, no markup pollution
        tw = self._title_width
        if title:
            display_title = title[:tw] if len(title) <= tw else title[:tw - 1] + "…"
            t.append(f"{display_title:<{tw}}")
        else:
            # Render 'untitled' in dim italic style; pad to title_width
            padded = f"{'untitled':<{tw}}"
            t.append(padded, style=Style(color="#767C8C", italic=True))
        t.append(" ")  # sep after title

        # Last-active slot (11 chars, right-padded)
        now = _time.time()
        diff = now - float(last_active) if last_active else 0
        if diff < 3600:
            rel = f"{int(diff/60)}m ago" if diff >= 60 else "just now"
        elif diff < 86400:
            rel = f"{int(diff/3600)}h ago"
        elif diff < 604800:
            rel = f"{int(diff/86400)}d ago"
        elif diff < 4838400:
            rel = f"{int(diff/604800)}w ago"
        else:
            rel = _datetime.fromtimestamp(float(last_active)).strftime("%Y-%m-%d") if last_active else "?"
        t.append(f"{rel:<11}")
        t.append(" ")  # sep after last

        # Turns slot (9 chars, right-aligned)
        if turn_count < 1_000:
            turn_word = "turn " if turn_count == 1 else "turns"
            turns_str = f"{turn_count:>3} {turn_word}"
        elif turn_count < 10_000:
            turns_str = f"{turn_count // 1000}k turn"
            turns_str = f"{turns_str:>9}"
        elif turn_count < 100_000:
            turns_str = f"{turn_count // 1000}k turn"
            turns_str = f"{turns_str:>9}"
        else:
            turns_str = ">99k turn"
        t.append(f"{turns_str:>9}")
        t.append(" ")  # sep after turns

        # Tokens slot (9 chars)
        total = (
            int(meta.get("input_tokens") or 0)
            + int(meta.get("output_tokens") or 0)
            + int(meta.get("cache_read_tokens") or 0)
            + int(meta.get("cache_write_tokens") or 0)
            + int(meta.get("reasoning_tokens") or 0)
        )
        tok_str = _format_tokens_compact(total)
        if total == 0:
            tok_color = self._color_tokens_disabled
        elif total >= self._heavy_threshold:
            tok_color = self._color_tokens_warning
        else:
            tok_color = self._color_tokens_muted
        t.append(tok_str, style=Style(color=tok_color))

        return t


class ToolPanelHelpOverlay(ModalOverlayMixin, Widget):
    """Binding reference for focused ToolPanel. Shown by F1, dismissed by Esc."""

    _push_modal_on_mount: bool = False  # permanent widget; push/pop managed in show_overlay/dismiss_overlay

    DEFAULT_CSS = """
    ToolPanelHelpOverlay {
        layer: overlay;
        display: none;
        height: auto;
        max-height: 24;
        width: 50;
        margin: 2 4;
        padding: 1 2;
        background: $surface;
        border: tall $primary 20%;
        border-title-align: left;
        border-title-color: $accent;
        dock: right;
        overflow-y: auto;
        scrollbar-gutter: stable;
    }
    ToolPanelHelpOverlay.--visible { display: block; }
    ToolPanelHelpOverlay > Static { height: auto; }
    """

    # Section order and action membership — drives dynamic table generation.
    # Add new actions to a section here; the key/description are read from
    # ToolPanel.BINDINGS automatically.
    _SECTIONS: list[tuple[str, list[str]]] = [
        ("Navigate", [
            "toggle_collapse",
            "scroll_body_down", "scroll_body_up",
            "scroll_body_page_down", "scroll_body_page_up",
            "scroll_body_top", "scroll_body_bottom",
            "toggle_tail_follow",
        ]),
        ("Copy", [
            "copy_body", "copy_input",
            "copy_ansi", "copy_html",
            "copy_invocation", "copy_urls",
            "copy_err", "copy_paths", "copy_full_path",
        ]),
        ("Open / Edit", [
            "open_primary", "open_url",
            "edit_cmd", "edit_args",
            "retry",
        ]),
        ("View", [
            "density_cycle", "density_cycle_reverse",
            "cycle_kind", "kind_revert",
            "expand_lines", "collapse_lines", "expand_all_lines",
        ]),
        ("Other", [
            "dismiss_error_banner",
            "show_context_menu",
            "show_help",
        ]),
    ]

    _HEADER_CHIPS = """\
[bold]Header chips[/bold]

…STARTING    tool is initialising
STREAMING    output arriving
…FINALIZING  wrapping up
DONE         completed successfully
CANCELLED    cancelled by user
ERR          exited with error
2m 3s        elapsed time after finish
✓            action confirmed (copy/retry)
HERO         full detail view
TRACE        condensed view
COMPACT      minimal view
"""

    BINDINGS = [
        Binding("escape",        "dismiss", "Close", priority=True, show=False),
        Binding("question_mark", "dismiss", "Close", priority=True, show=False),
    ]

    def on_mount(self) -> None:
        # Permanent widget: do NOT call ModalOverlayMixin.on_mount().
        # push_modal / --modal are managed per show_overlay() / dismiss_overlay() cycle.
        pass

    def on_unmount(self) -> None:
        # Permanent widget: never removed from DOM. ModalOverlayMixin.on_unmount must NOT
        # be called here — stack/focus cleanup is owned by dismiss_overlay(), not lifecycle hooks.
        pass

    @classmethod
    def _fmt_key(cls, key: str) -> str:
        _SPECIAL = {
            "enter": "Enter", "escape": "Esc",
            "question_mark": "?", "f1": "F1",
        }
        if key in _SPECIAL:
            return _SPECIAL[key]
        if key.startswith("shift+"):
            return f"Shift+{key[6:].upper()}"
        return key

    @classmethod
    def _build_table(cls) -> str:
        from hermes_cli.tui.tool_panel._core import ToolPanel  # lazy — avoids circular import

        action_map: dict[str, tuple[str, str]] = {}
        for b in ToolPanel.BINDINGS:
            action = b.action if isinstance(b.action, str) else str(b.action)
            key_disp = b.key_display or cls._fmt_key(b.key)
            if action not in action_map:
                action_map[action] = (key_disp, b.description)

        lines: list[str] = ["[bold]ToolPanel key reference[/bold]", ""]
        for section_name, actions in cls._SECTIONS:
            rows = [
                (key_disp, desc)
                for action in actions
                if (entry := action_map.get(action)) is not None
                for key_disp, desc in (entry,)
            ]
            if rows:
                lines.append(f"[bold]{section_name}[/bold]")
                col = max(len(k) for k, _ in rows) + 2
                for key_disp, desc in rows:
                    lines.append(f"[bold]{key_disp}[/bold]{' ' * (col - len(key_disp))}{desc}")
                lines.append("")
        lines.append(cls._HEADER_CHIPS)
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        try:
            markup = self._build_table()
        except Exception:
            _log.warning("ToolPanelHelpOverlay: failed to build dynamic table", exc_info=True)
            markup = "[dim]Key reference unavailable[/dim]"
        yield Static(markup, markup=True)

    def show_overlay(self) -> None:
        if self.has_class("--visible"):
            return  # already open — don't double-push the modal stack
        self.border_title = "Tool keys"
        self._capture_focus_caller()  # capture ToolPanel (or whatever has focus) before we steal it
        try:
            self.app.push_modal(self)  # il-m1: register in arbiter stack
        except AttributeError:  # il-ex-1-exempt: swallow
            _log.debug("ToolPanelHelpOverlay.show_overlay: app has no push_modal")
        self.add_class("--modal", "--visible")  # il-m1: owned by show_overlay (permanent widget override)
        self.focus()

    def hide_overlay(self) -> None:
        """Alias kept for call-sites that use hide_overlay(); delegates to dismiss_overlay."""
        self.dismiss_overlay()

    def dismiss_overlay(self) -> None:
        """Permanent-widget dismiss: hide without removing from DOM."""
        target = self._restore_focus_to()
        self.remove_class("--visible", "--modal")  # il-m1: owned by dismiss_overlay (permanent override)
        try:
            self.app.pop_modal(self)  # il-m1: deregister from arbiter stack
        except AttributeError:  # il-ex-1-exempt: swallow
            _log.debug("ToolPanelHelpOverlay.dismiss_overlay: app has no pop_modal")
        if target is not None:
            try:
                if target.is_mounted:
                    target.focus()
            except Exception:
                _log.debug("ToolPanelHelpOverlay.dismiss_overlay: focus restore failed", exc_info=True)

    def dismiss(self) -> None:
        """Public close helper — delegates to action_dismiss."""
        self.action_dismiss()

    def action_dismiss(self) -> None:
        """Action bound to Esc/? via BINDINGS — delegates to dismiss_overlay."""
        self.dismiss_overlay()



FIXTURE_CODE = """\
def fibonacci(n):
    if n <= 1:  # base case
        return n
    return fibonacci(n-1) + fibonacci(n-2)

result = [fibonacci(i) for i in range(10)]
print(f"sequence: {result}")  # [0,1,1,2,3...]
"""

_FIXTURE_BY_LANG: dict[str, str] = {
    "python": FIXTURE_CODE,
    "javascript": """\
function fibonacci(n) {
  if (n <= 1) return n;  // base case
  return fibonacci(n - 1) + fibonacci(n - 2);
}
console.log([...Array(10).keys()].map(fibonacci));
""",
    "typescript": """\
function fibonacci(n: number): number {
  if (n <= 1) return n;  // base case
  return fibonacci(n - 1) + fibonacci(n - 2);
}
console.log(Array.from({length: 10}, (_, i) => fibonacci(i)));
""",
    "go": """\
func fibonacci(n int) int {
    if n <= 1 { return n }  // base case
    return fibonacci(n-1) + fibonacci(n-2)
}
""",
    "rust": """\
fn fibonacci(n: u64) -> u64 {
    if n <= 1 { return n; }  // base case
    fibonacci(n - 1) + fibonacci(n - 2)
}
""",
    "ruby": """\
def fibonacci(n)
  return n if n <= 1  # base case
  fibonacci(n - 1) + fibonacci(n - 2)
end
puts (0..9).map { |i| fibonacci(i) }.inspect
""",
    "bash": """\
fibonacci() {
  local n=$1
  [ "$n" -le 1 ] && echo $n && return  # base case
  echo $(( $(fibonacci $((n-1))) + $(fibonacci $((n-2))) ))
}
""",
    "java": """\
static int fibonacci(int n) {
    if (n <= 1) return n;  // base case
    return fibonacci(n - 1) + fibonacci(n - 2);
}
""",
    "cpp": """\
int fibonacci(int n) {
    if (n <= 1) return n;  // base case
    return fibonacci(n-1) + fibonacci(n-2);
}
""",
    "c": """\
int fibonacci(int n) {
    if (n <= 1) return n;  /* base case */
    return fibonacci(n-1) + fibonacci(n-2);
}
""",
    "markdown": """\
# Fibonacci

A sequence where each number is the sum of the two preceding ones.

- Starts with: `0, 1, 1, 2, 3, 5, 8, 13...`
- Formula: `F(n) = F(n-1) + F(n-2)`
""",
}
