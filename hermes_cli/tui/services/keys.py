"""Key event dispatcher, input submission service extracted from _app_key_handler.py."""
from __future__ import annotations

import time as _time
from typing import Any, TYPE_CHECKING

from textual.css.query import NoMatches
from rich.text import Text

from hermes_cli.tui.state import ChoiceOverlayState
from hermes_cli.tui._browse_types import BrowseAnchorType
from hermes_cli.tui._app_constants import KNOWN_SLASH_COMMANDS as _KNOWN_SLASH_COMMANDS
from .base import AppService

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp


class KeyDispatchService(AppService):
    """Key event dispatcher and input submission logic extracted from _KeyHandlerMixin."""

    def __init__(self, app: "HermesApp") -> None:
        super().__init__(app)

    def dispatch_key(self, event: Any) -> None:
        """Global key handler for overlay navigation, copy, and interrupt."""
        from hermes_cli.tui.widgets import (
            ApprovalWidget, ClarifyWidget, CopyableRichLog, OutputPanel,
            HistorySearchOverlay, HintBar, ThinkingWidget,
        )
        from hermes_cli.tui.overlays import (
            ConfigOverlay, HelpOverlay, UsageOverlay, CommandsOverlay,
            WorkspaceOverlay, SessionOverlay,
        )

        # F4: track last keypress time so _maybe_notify can skip notifying
        # when the user is actively watching the TUI.
        self.app._last_keypress_time = _time.monotonic()
        key = event.key

        # --- ctrl+p → path/file picker (@-completion) ---
        if key == "ctrl+p":
            try:
                from hermes_cli.tui.input_widget import HermesInput as _HI
                inp = self.app.query_one(_HI)
                inp.focus()
                inp.insert_text("@")
            except (NoMatches, Exception):
                pass
            event.prevent_default()
            return

        # --- Alt+1–9 → switch parallel session by index ---
        if key.startswith("alt+") and key[4:].isdigit() and len(key) == 5:
            n = int(key[4:]) - 1
            if n >= 0 and self.app._sessions_enabled:
                self.app._switch_to_session_by_index(n)
                event.prevent_default()
                return

        # --- undo overlay key dispatch ---
        if self.app.undo_state is not None:
            if event.key in ("y", "enter"):
                pending_panel = self.app._pending_undo_panel
                pending_n = self.app._pending_rollback_n
                self.app.undo_state = None
                self.app._pending_undo_panel = None
                if pending_panel is not None:
                    self.app._run_undo_sequence(pending_panel)
                else:
                    self.app._run_rollback_sequence(pending_n)
                event.prevent_default()
                return
            if event.key in ("n", "escape"):
                self.app.undo_state = None
                self.app._pending_undo_panel = None
                event.prevent_default()
                return

        # --- E5: Shift+X: dismiss all error banners (only when input not focused) ---
        if key == "X":
            try:
                from hermes_cli.tui.input_widget import HermesInput as _HI
                inp = self.app.query_one(_HI)
                if not inp.has_focus:
                    self.app.action_dismiss_all_error_banners()
                    event.prevent_default()
                    return
            except Exception:
                pass

        # --- w: toggle workspace overlay (only when input not focused) ---
        if key == "w":
            try:
                from hermes_cli.tui.input_widget import HermesInput as _HI
                inp = self.app.query_one(_HI)
                if inp.has_focus:
                    return  # let w type normally into input
            except NoMatches:
                pass
            self.app.action_toggle_workspace()
            event.prevent_default()
            return

        # --- ctrl+c: copy / cancel overlay / clear / exit ---
        if key == "ctrl+c":
            selected = self.app._get_selected_text()
            if selected:
                self.app._svc_theme.copy_text_with_hint(selected)
                event.prevent_default()
                return

            # Bash mode: SIGINT running command, or clear input
            try:
                inp = self.app.query_one("#input-area")
            except NoMatches:
                inp = None
            if inp is not None and inp.has_class("--bash-mode"):
                if self.app._svc_bash.is_running:
                    self.app._svc_bash.kill()
                    self.app._flash_hint("Command interrupted", 1.5)
                    event.prevent_default()
                    return
                else:
                    inp.clear()
                    event.prevent_default()
                    return

            # Kill bash command before trying overlay-cancel or agent-interrupt
            if self.app._svc_bash.is_running:
                self.app._svc_bash.kill()
                self.app._flash_hint("Command interrupted", 1.5)
                event.prevent_default()
                return

            for state_attr in ("approval_state", "clarify_state"):
                state: ChoiceOverlayState | None = getattr(self.app, state_attr)
                if state is not None:
                    state.response_queue.put("deny")
                    setattr(self.app, state_attr, None)
                    event.prevent_default()
                    return
            for state_attr in ("sudo_state", "secret_state"):
                state = getattr(self.app, state_attr)
                if state is not None:
                    state.response_queue.put("")
                    setattr(self.app, state_attr, None)
                    event.prevent_default()
                    return

            if not self.app.agent_running:
                try:
                    inp = self.app.query_one("#input-area")
                    if hasattr(inp, "content") and inp.content:
                        inp.clear()
                    else:
                        self.app.exit()
                except NoMatches:
                    self.app.exit()
            event.prevent_default()
            return

        # --- ctrl+shift+c: dedicated agent interrupt ---
        if key == "ctrl+shift+c":
            if self.app.agent_running and hasattr(self.app.cli, "agent") and self.app.cli.agent:
                now = _time.monotonic()
                last = getattr(self.app, "_last_interrupt_time", 0.0)
                if now - last < 2.0:
                    self.app.exit()
                    event.prevent_default()
                    return
                self.app._last_interrupt_time = now
                self.app._interrupt_source = "ctrl+shift+c"
                self.app.cli.agent.interrupt()
                try:
                    _out = self.app.query_one(OutputPanel)
                    _out.flush_live()
                except NoMatches:
                    pass
                try:
                    panel = self.app.query_one(OutputPanel)
                    msg = panel.current_message
                    if msg is not None:
                        rl = msg.response_log
                        rl.write(
                            Text.from_markup("[bold red]⚡ Interrupting...[/bold red]")
                        )
                        if rl._deferred_renders:
                            self.app.call_after_refresh(msg.refresh, layout=True)
                except NoMatches:
                    self.app.log.warning("interrupt feedback: OutputPanel not available")
                except Exception as exc:
                    self.app.log.warning(f"interrupt feedback failed: {exc}")
                event.prevent_default()
                return

        # --- escape: cancel overlay, interrupt agent, browse mode, or enter browse ---
        if key == "escape":
            from hermes_cli.tui.overlays import ToolPanelHelpOverlay as _TPHO
            for _cls in (HelpOverlay, UsageOverlay, CommandsOverlay, WorkspaceOverlay, SessionOverlay, ConfigOverlay, _TPHO):
                try:
                    _ov = self.app.query_one(_cls)
                    if _ov.has_class("--visible"):
                        _ov.action_dismiss() if hasattr(_ov, "action_dismiss") else _ov.remove_class("--visible")
                        event.prevent_default()
                        return
                except NoMatches:
                    pass

            try:
                hs = self.app.query_one(HistorySearchOverlay)
                if hs.has_class("--visible"):
                    hs.action_dismiss()
                    event.prevent_default()
                    return
            except NoMatches:
                pass

            try:
                from hermes_cli.tui.completion_overlay import CompletionOverlay as _CO
                _co = self.app.query_one(_CO)
                if _co.has_class("--visible"):
                    _co.remove_class("--visible")
                    _co.remove_class("--slash-only")
                    event.prevent_default()
                    return
            except NoMatches:
                pass

            # R2 pane layout: Esc returns focus to input when a side pane is active.
            # Runs AFTER overlay dismissal so overlay Esc is not intercepted here.
            _pm = getattr(self.app, "_pane_manager", None)
            if _pm is not None and _pm.enabled:
                from hermes_cli.tui.pane_manager import PaneId
                if _pm._focused_pane != PaneId.CENTER:
                    try:
                        self.app.query_one("#input-area").focus()
                        _pm.focus_pane(PaneId.CENTER)
                        event.prevent_default()
                        return
                    except Exception:
                        pass

            if self.app.browse_mode:
                self.app.browse_mode = False
                event.prevent_default()
                return

            for state_attr in ("approval_state", "clarify_state"):
                state = getattr(self.app, state_attr)
                if state is not None:
                    state.response_queue.put(None)
                    setattr(self.app, state_attr, None)
                    event.prevent_default()
                    return
            for state_attr in ("sudo_state", "secret_state"):
                state = getattr(self.app, state_attr)
                if state is not None:
                    state.response_queue.put("")
                    setattr(self.app, state_attr, None)
                    event.prevent_default()
                    return

            if self.app.agent_running and hasattr(self.app.cli, "agent") and self.app.cli.agent:
                self.app._interrupt_source = "esc"
                self.app.cli.agent.interrupt()
                try:
                    _out = self.app.query_one(OutputPanel)
                    _out.flush_live()
                except NoMatches:
                    pass
                try:
                    panel = self.app.query_one(OutputPanel)
                    msg = panel.current_message
                    if msg is not None:
                        rl = msg.response_log
                        rl.write(
                            Text.from_markup("[bold red]⚡ Interrupting...[/bold red]")
                        )
                        if rl._deferred_renders:
                            self.app.call_after_refresh(msg.refresh, layout=True)
                except NoMatches:
                    self.app.log.warning("interrupt feedback: OutputPanel not available")
                except Exception as exc:
                    self.app.log.warning(f"interrupt feedback failed: {exc}")
                event.prevent_default()
                return

            no_overlay = all(
                getattr(self.app, a) is None
                for a in ("approval_state", "clarify_state", "sudo_state", "secret_state")
            )
            if no_overlay and not self.app.agent_running:
                _inp_value = ""
                try:
                    _inp = self.app.query_one("#input-area")
                    _inp_value = getattr(_inp, "value", "") or ""
                except NoMatches:
                    pass
                if not _inp_value:
                    self.app.browse_mode = True
                    event.prevent_default()
                    return

        # --- c: copy usage stats when UsageOverlay is visible ---
        if key == "c":
            try:
                _uov = self.app.query_one(UsageOverlay)
                if _uov.has_class("--visible"):
                    _uov._do_copy()
                    event.prevent_default()
                    return
            except NoMatches:
                pass

        # --- J/K: focus next/prev ToolPanel (Phase 3 panel nav) ---
        if key == "J":
            self.app._focus_tool_panel(+1)
            event.prevent_default()
            return
        elif key == "K":
            self.app._focus_tool_panel(-1)
            event.prevent_default()
            return

        # --- D1: Ctrl+Shift+Arrow — cycle overlay through 9 named grid positions ---
        if key in ("ctrl+shift+up", "ctrl+shift+down", "ctrl+shift+left", "ctrl+shift+right"):
            try:
                from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay as _DO, _POS_TO_RC, _POS_GRID, AnimConfigPanel as _ACP
                ov = self.app.query_one(_DO)
                if not ov.has_class("-visible") or isinstance(self.app.screen, _ACP):
                    pass
                else:
                    col, row = _POS_TO_RC.get(ov.position, (1, 1))
                    if key == "ctrl+shift+right":
                        col = (col + 1) % 3
                    elif key == "ctrl+shift+left":
                        col = (col - 1) % 3
                    elif key == "ctrl+shift+down":
                        row = (row + 1) % 3
                    elif key == "ctrl+shift+up":
                        row = (row - 1) % 3
                    new_pos = _POS_GRID[row][col]
                    ov.position = new_pos
                    self.app._persist_anim_config({"position": new_pos})
                    self.app._flash_hint(f"Overlay → {new_pos}", 1.5)
            except Exception:
                pass
            event.stop()
            return

        # --- Browse mode key handling ---
        if self.app.browse_mode:
            from hermes_cli.tui.tool_blocks import ToolHeader as _TH
            headers = list(self.app.query(_TH))
            total = max(1, len(headers))

            if key == "tab":
                self.app.browse_index = (self.app.browse_index + 1) % total
                event.prevent_default()
                return
            elif key == "shift+tab":
                self.app.browse_index = (self.app.browse_index - 1) % total
                event.prevent_default()
                return
            elif key == "enter":
                focused = self.app.focused
                if focused is not None:
                    try:
                        from hermes_cli.tui.tool_group import ToolGroup as _TG
                        if isinstance(focused, _TG):
                            focused.collapsed = not focused.collapsed
                            if not focused.collapsed:
                                focused.focus_first_child()
                            event.prevent_default()
                            return
                    except Exception:
                        pass
                if headers:
                    idx = self.app.browse_index % len(headers)
                    parent = headers[idx].parent
                    if hasattr(parent, "toggle"):
                        parent.toggle()
                event.prevent_default()
                return
            elif key == "c":
                if headers:
                    idx = self.app.browse_index % len(headers)
                    h = headers[idx]
                    parent = h.parent
                    if hasattr(parent, "copy_content"):
                        self.app._svc_theme.copy_text_with_hint(parent.copy_content())
                    h.flash_copy()
                event.prevent_default()
                return
            elif key == "a":
                from hermes_cli.tui.tool_panel import ToolPanel as _TP
                for panel in self.app.query(_TP):
                    if panel.collapsed:
                        panel.action_toggle_collapse()
                event.prevent_default()
                return
            elif key == "A":
                from hermes_cli.tui.tool_panel import ToolPanel as _TP
                for panel in self.app.query(_TP):
                    if not panel.collapsed:
                        panel.action_toggle_collapse()
                event.prevent_default()
                return
            elif key == "escape":
                focused = self.app.focused
                if focused is not None:
                    try:
                        from hermes_cli.tui.tool_group import ToolGroup as _TG, GroupBody as _GB
                        parent = getattr(focused, "parent", None)
                        if isinstance(parent, _GB):
                            grandparent = getattr(parent, "parent", None)
                            if isinstance(grandparent, _TG):
                                grandparent.focus()
                                event.prevent_default()
                                return
                    except Exception:
                        pass
                self.app.browse_mode = False
                event.prevent_default()
                return
            elif key == "]":
                self.app._jump_anchor(+1)
                event.prevent_default()
                return
            elif key == "[":
                self.app._jump_anchor(-1)
                event.prevent_default()
                return
            elif key == "}":
                self.app._jump_anchor(+1, BrowseAnchorType.CODE_BLOCK)
                event.prevent_default()
                return
            elif key == "{":
                self.app._jump_anchor(-1, BrowseAnchorType.CODE_BLOCK)
                event.prevent_default()
                return
            elif key == "alt+down":
                self.app._jump_anchor(+1, BrowseAnchorType.TURN_START)
                event.prevent_default()
                return
            elif key == "alt+up":
                self.app._jump_anchor(-1, BrowseAnchorType.TURN_START)
                event.prevent_default()
                return
            elif key == "m":
                self.app._jump_anchor(+1, BrowseAnchorType.MEDIA)
                event.prevent_default()
                return
            elif key == "M":
                self.app._jump_anchor(-1, BrowseAnchorType.MEDIA)
                event.prevent_default()
                return
            elif key == "backslash":
                self.app.call_later(self.app.action_toggle_minimap)
                event.prevent_default()
                return
            elif key == "T":
                self.app._open_tools_overlay()
                event.prevent_default()
                return
            elif event.character is not None:
                self.app.browse_mode = False
                try:
                    inp = self.app.query_one("#input-area")
                    if hasattr(inp, "insert_text"):
                        inp.insert_text(event.character)
                except NoMatches:
                    pass
                event.prevent_default()
                return

        # --- F9: toggle PlanPanel collapsed state ---
        if key == "f9":
            self.app.plan_panel_collapsed = not self.app.plan_panel_collapsed
            event.prevent_default()
            return

        # Overlay key handling — route through InterruptOverlay for clarify /
        # approval (the 2 kinds that present choice rows).
        from hermes_cli.tui.overlays import InterruptKind, InterruptOverlay
        try:
            io = self.app.query_one(InterruptOverlay)
        except NoMatches:
            io = None
        if io is not None and io._current_payload is not None \
                and io._current_payload.kind in (InterruptKind.CLARIFY, InterruptKind.APPROVAL):
            payload = io._current_payload
            # Approval diff-panel scroll + Tab focus cycling.
            if payload.kind == InterruptKind.APPROVAL:
                try:
                    diff_log = io.query_one(
                        "CopyableRichLog#approval-diff", CopyableRichLog
                    )
                    if diff_log.display and diff_log.has_focus:
                        if key == "up":
                            diff_log.scroll_up()
                            event.stop()
                            return
                        if key == "down":
                            diff_log.scroll_down()
                            event.stop()
                            return
                    if key == "tab" and diff_log.display:
                        if diff_log.has_focus:
                            io.focus()
                        else:
                            diff_log.focus()
                        event.stop()
                        return
                except NoMatches:
                    pass

            if key == "up":
                io.select_choice(-1)
                event.prevent_default()
                return
            if key == "down":
                io.select_choice(1)
                event.prevent_default()
                return
            if key == "enter":
                io.confirm_choice()
                event.prevent_default()
                return

    def dispatch_input_submitted(self, event: Any) -> None:
        """Handle input submission from HermesInput.

        When agent is running: interrupt first, then send new message
        (except /queue and /btw which queue without interrupting).
        """
        from hermes_cli.tui.widgets import ThinkingWidget
        text = event.value

        # --- bash passthrough: "!cmd" prefix ---
        if isinstance(text, str) and text.lstrip().startswith("!"):
            if self.app.agent_running:
                self.app._flash_hint("Agent running — finish or interrupt first", 2.5)
                return
            if self.app._svc_bash.is_running:
                self.app._flash_hint("Command running — Ctrl+C to kill", 2.5)
                return
            cmd = text.lstrip()[1:].strip()
            if not cmd:
                self.app._flash_hint("Empty bash command", 2.0)
                return
            self.app._svc_bash.run(cmd)
            return

        if isinstance(text, str) and self.app._handle_tui_command(text):
            return

        if isinstance(text, str) and text.startswith("/"):
            cmd = text.split()[0].lower()
            if cmd not in _KNOWN_SLASH_COMMANDS:
                self.app._flash_hint(f"Unknown command: {cmd}  (F1 for help)", 3.0)
                return

        images = list(self.app.attached_images)
        if images:
            self.app._clear_attached_images()
            payload = (text, images)
        else:
            payload = text

        if self.app.agent_running and text:
            _cmd = text.lstrip("/").split()[0].lower() if text.startswith("/") else ""
            if _cmd in ("queue", "btw"):
                if hasattr(self.app.cli, "_pending_input"):
                    self.app.cli._pending_input.put(payload)
                return
            try:
                self.app.query_one(ThinkingWidget).activate()
            except NoMatches:
                pass
            if hasattr(self.app.cli, "agent") and self.app.cli.agent:
                self.app._interrupt_source = "resubmit"
                self.app.cli.agent.interrupt()
            if hasattr(self.app.cli, "_pending_input"):
                self.app.cli._pending_input.put(payload)
            return

        try:
            self.app.query_one(ThinkingWidget).activate()
        except NoMatches:
            pass
        # Reset per-turn plan/budget state before starting a new agent turn.
        if hasattr(self.app, "cli") and self.app.cli is not None:
            try:
                self.app.cli._reset_turn_state()
            except Exception:
                pass
        if hasattr(self.app, "cli") and self.app.cli is not None:
            if hasattr(self.app.cli, "_pending_input"):
                self.app.cli._pending_input.put(payload)
