"""_KeyHandlerMixin — on_key, on_hermes_input_submitted, on_hermes_input_files_dropped."""
from __future__ import annotations

import time as _time
from typing import Any

from textual.css.query import NoMatches
from rich.text import Text

from hermes_cli.tui.state import ChoiceOverlayState
from hermes_cli.tui._browse_types import BrowseAnchorType

from hermes_cli.tui._app_constants import KNOWN_SLASH_COMMANDS as _KNOWN_SLASH_COMMANDS


class _KeyHandlerMixin:
    """Global key handler and input submission logic.

    Extracted from HermesApp to reduce file size.  Self is always a HermesApp
    instance at runtime — all attribute access on self is valid.
    """

    def on_key(self, event: Any) -> None:
        """Global key handler for overlay navigation, copy, and interrupt.

        Keybinding split:
        - ctrl+c: copy selected text → cancel overlay → clear input → exit
        - ctrl+shift+c: dedicated agent interrupt (double-press = force exit)
        - escape: cancel overlay → interrupt agent
        """
        from hermes_cli.tui.widgets import (
            ApprovalWidget, ClarifyWidget, CopyableRichLog, OutputPanel,
            HistorySearchOverlay, HintBar, ThinkingWidget,
        )
        from hermes_cli.tui.overlays import (
            HelpOverlay, UsageOverlay, CommandsOverlay,
            WorkspaceOverlay, SessionOverlay,
        )

        # F4: track last keypress time so _maybe_notify can skip notifying
        # when the user is actively watching the TUI.
        self._last_keypress_time = _time.monotonic()  # type: ignore[attr-defined]
        key = event.key

        # --- ctrl+p → path/file picker (@-completion) ---
        if key == "ctrl+p":
            try:
                from hermes_cli.tui.input_widget import HermesInput as _HI
                inp = self.query_one(_HI)  # type: ignore[attr-defined]
                inp.focus()
                inp.insert_text("@")
            except (NoMatches, Exception):
                pass
            event.prevent_default()
            return

        # --- Alt+1–9 → switch parallel session by index ---
        if key.startswith("alt+") and key[4:].isdigit() and len(key) == 5:
            n = int(key[4:]) - 1
            if n >= 0 and self._sessions_enabled:  # type: ignore[attr-defined]
                self._switch_to_session_by_index(n)  # type: ignore[attr-defined]
                event.prevent_default()
                return

        # --- undo overlay key dispatch ---
        if self.undo_state is not None:  # type: ignore[attr-defined]
            if event.key in ("y", "enter"):
                pending_panel = self._pending_undo_panel  # type: ignore[attr-defined]
                pending_n = self._pending_rollback_n  # type: ignore[attr-defined]
                self.undo_state = None  # type: ignore[attr-defined]
                self._pending_undo_panel = None  # type: ignore[attr-defined]
                if pending_panel is not None:
                    self._run_undo_sequence(pending_panel)  # type: ignore[attr-defined]
                else:
                    self._run_rollback_sequence(pending_n)  # type: ignore[attr-defined]
                event.prevent_default()
                return
            if event.key in ("n", "escape"):
                self.undo_state = None  # type: ignore[attr-defined]
                self._pending_undo_panel = None  # type: ignore[attr-defined]
                event.prevent_default()
                return

        # --- E5: Shift+X: dismiss all error banners (only when input not focused) ---
        if key == "X":
            try:
                from hermes_cli.tui.input_widget import HermesInput as _HI
                inp = self.query_one(_HI)  # type: ignore[attr-defined]
                if not inp.has_focus:
                    self.action_dismiss_all_error_banners()  # type: ignore[attr-defined]
                    event.prevent_default()
                    return
            except Exception:
                pass

        # --- w: toggle workspace overlay (only when input not focused) ---
        if key == "w":
            try:
                from hermes_cli.tui.input_widget import HermesInput as _HI
                inp = self.query_one(_HI)  # type: ignore[attr-defined]
                if inp.has_focus:
                    return  # let w type normally into input
            except NoMatches:
                pass
            self.action_toggle_workspace()  # type: ignore[attr-defined]
            event.prevent_default()
            return

        # --- ctrl+c: copy / cancel overlay / clear / exit ---
        if key == "ctrl+c":
            selected = self._get_selected_text()  # type: ignore[attr-defined]
            if selected:
                self._copy_text_with_hint(selected)  # type: ignore[attr-defined]
                event.prevent_default()
                return

            for state_attr in ("approval_state", "clarify_state"):
                state: ChoiceOverlayState | None = getattr(self, state_attr)
                if state is not None:
                    state.response_queue.put("deny")
                    setattr(self, state_attr, None)
                    event.prevent_default()
                    return
            for state_attr in ("sudo_state", "secret_state"):
                state = getattr(self, state_attr)
                if state is not None:
                    state.response_queue.put("")
                    setattr(self, state_attr, None)
                    event.prevent_default()
                    return

            if not self.agent_running:  # type: ignore[attr-defined]
                try:
                    inp = self.query_one("#input-area")  # type: ignore[attr-defined]
                    if hasattr(inp, "content") and inp.content:
                        inp.clear()
                    else:
                        self.exit()  # type: ignore[attr-defined]
                except NoMatches:
                    self.exit()  # type: ignore[attr-defined]
            event.prevent_default()
            return

        # --- ctrl+shift+c: dedicated agent interrupt ---
        if key == "ctrl+shift+c":
            if self.agent_running and hasattr(self.cli, "agent") and self.cli.agent:  # type: ignore[attr-defined]
                now = _time.monotonic()
                last = getattr(self, "_last_interrupt_time", 0.0)
                if now - last < 2.0:
                    self.exit()  # type: ignore[attr-defined]
                    event.prevent_default()
                    return
                self._last_interrupt_time = now  # type: ignore[attr-defined]
                self.cli.agent.interrupt()  # type: ignore[attr-defined]
                try:
                    _out = self.query_one(OutputPanel)  # type: ignore[attr-defined]
                    _out.flush_live()
                except NoMatches:
                    pass
                try:
                    panel = self.query_one(OutputPanel)  # type: ignore[attr-defined]
                    msg = panel.current_message
                    if msg is not None:
                        rl = msg.response_log
                        rl.write(
                            Text.from_markup("[bold red]⚡ Interrupting...[/bold red]")
                        )
                        if rl._deferred_renders:
                            self.call_after_refresh(msg.refresh, layout=True)  # type: ignore[attr-defined]
                except NoMatches:
                    self.log.warning("interrupt feedback: OutputPanel not available")  # type: ignore[attr-defined]
                except Exception as exc:
                    self.log.warning(f"interrupt feedback failed: {exc}")  # type: ignore[attr-defined]
                event.prevent_default()
                return

        # --- escape: cancel overlay, interrupt agent, browse mode, or enter browse ---
        if key == "escape":
            from hermes_cli.tui.overlays import ToolPanelHelpOverlay as _TPHO
            for _cls in (HelpOverlay, UsageOverlay, CommandsOverlay, WorkspaceOverlay, SessionOverlay, _TPHO):
                try:
                    _ov = self.query_one(_cls)  # type: ignore[attr-defined]
                    if _ov.has_class("--visible"):
                        _ov.action_dismiss() if hasattr(_ov, "action_dismiss") else _ov.remove_class("--visible")
                        event.prevent_default()
                        return
                except NoMatches:
                    pass

            try:
                hs = self.query_one(HistorySearchOverlay)  # type: ignore[attr-defined]
                if hs.has_class("--visible"):
                    hs.action_dismiss()
                    event.prevent_default()
                    return
            except NoMatches:
                pass

            try:
                from hermes_cli.tui.completion_overlay import CompletionOverlay as _CO
                _co = self.query_one(_CO)  # type: ignore[attr-defined]
                if _co.has_class("--visible"):
                    _co.remove_class("--visible")
                    _co.remove_class("--slash-only")
                    event.prevent_default()
                    return
            except NoMatches:
                pass

            # R2 pane layout: Esc returns focus to input when a side pane is active.
            # Runs AFTER overlay dismissal so overlay Esc is not intercepted here.
            _pm = getattr(self, "_pane_manager", None)
            if _pm is not None and _pm.enabled:
                from hermes_cli.tui.pane_manager import PaneId
                if _pm._focused_pane != PaneId.CENTER:
                    try:
                        self.query_one("#input-area").focus()  # type: ignore[attr-defined]
                        _pm.focus_pane(PaneId.CENTER)
                        event.prevent_default()
                        return
                    except Exception:
                        pass

            if self.browse_mode:  # type: ignore[attr-defined]
                self.browse_mode = False  # type: ignore[attr-defined]
                event.prevent_default()
                return

            for state_attr in ("approval_state", "clarify_state"):
                state = getattr(self, state_attr)
                if state is not None:
                    state.response_queue.put(None)
                    setattr(self, state_attr, None)
                    event.prevent_default()
                    return
            for state_attr in ("sudo_state", "secret_state"):
                state = getattr(self, state_attr)
                if state is not None:
                    state.response_queue.put("")
                    setattr(self, state_attr, None)
                    event.prevent_default()
                    return

            if self.agent_running and hasattr(self.cli, "agent") and self.cli.agent:  # type: ignore[attr-defined]
                self.cli.agent.interrupt()  # type: ignore[attr-defined]
                try:
                    _out = self.query_one(OutputPanel)  # type: ignore[attr-defined]
                    _out.flush_live()
                except NoMatches:
                    pass
                try:
                    panel = self.query_one(OutputPanel)  # type: ignore[attr-defined]
                    msg = panel.current_message
                    if msg is not None:
                        rl = msg.response_log
                        rl.write(
                            Text.from_markup("[bold red]⚡ Interrupting...[/bold red]")
                        )
                        if rl._deferred_renders:
                            self.call_after_refresh(msg.refresh, layout=True)  # type: ignore[attr-defined]
                except NoMatches:
                    self.log.warning("interrupt feedback: OutputPanel not available")  # type: ignore[attr-defined]
                except Exception as exc:
                    self.log.warning(f"interrupt feedback failed: {exc}")  # type: ignore[attr-defined]
                event.prevent_default()
                return

            no_overlay = all(
                getattr(self, a) is None
                for a in ("approval_state", "clarify_state", "sudo_state", "secret_state")
            )
            if no_overlay and not self.agent_running:  # type: ignore[attr-defined]
                _inp_value = ""
                try:
                    _inp = self.query_one("#input-area")  # type: ignore[attr-defined]
                    _inp_value = getattr(_inp, "value", "") or ""
                except NoMatches:
                    pass
                if not _inp_value:
                    self.browse_mode = True  # type: ignore[attr-defined]
                    event.prevent_default()
                    return

        # --- c: copy usage stats when UsageOverlay is visible ---
        if key == "c":
            try:
                _uov = self.query_one(UsageOverlay)  # type: ignore[attr-defined]
                if _uov.has_class("--visible"):
                    _uov._do_copy()
                    event.prevent_default()
                    return
            except NoMatches:
                pass

        # --- J/K: focus next/prev ToolPanel (Phase 3 panel nav) ---
        if key == "J":
            self._focus_tool_panel(+1)  # type: ignore[attr-defined]
            event.prevent_default()
            return
        elif key == "K":
            self._focus_tool_panel(-1)  # type: ignore[attr-defined]
            event.prevent_default()
            return

        # --- D1: Ctrl+Shift+Arrow — cycle overlay through 9 named grid positions ---
        if key in ("ctrl+shift+up", "ctrl+shift+down", "ctrl+shift+left", "ctrl+shift+right"):
            try:
                from hermes_cli.tui.drawille_overlay import DrawilleOverlay as _DO, _POS_TO_RC, _POS_GRID, AnimConfigPanel as _ACP
                ov = self.query_one(_DO)  # type: ignore[attr-defined]
                if not ov.has_class("-visible") or isinstance(self.screen, _ACP):
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
                    self._persist_anim_config({"position": new_pos})  # type: ignore[attr-defined]
                    self._flash_hint(f"Overlay → {new_pos}", 1.5)  # type: ignore[attr-defined]
            except Exception:
                pass
            event.stop()
            return

        # --- Browse mode key handling ---
        if self.browse_mode:  # type: ignore[attr-defined]
            from hermes_cli.tui.tool_blocks import ToolHeader as _TH
            headers = list(self.query(_TH))  # type: ignore[attr-defined]
            total = max(1, len(headers))

            if key == "tab":
                self.browse_index = (self.browse_index + 1) % total  # type: ignore[attr-defined]
                event.prevent_default()
                return
            elif key == "shift+tab":
                self.browse_index = (self.browse_index - 1) % total  # type: ignore[attr-defined]
                event.prevent_default()
                return
            elif key == "enter":
                focused = self.focused  # type: ignore[attr-defined]
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
                    idx = self.browse_index % len(headers)  # type: ignore[attr-defined]
                    parent = headers[idx].parent
                    if hasattr(parent, "toggle"):
                        parent.toggle()
                event.prevent_default()
                return
            elif key == "c":
                if headers:
                    idx = self.browse_index % len(headers)  # type: ignore[attr-defined]
                    h = headers[idx]
                    parent = h.parent
                    if hasattr(parent, "copy_content"):
                        self._copy_text_with_hint(parent.copy_content())  # type: ignore[attr-defined]
                    h.flash_copy()
                event.prevent_default()
                return
            elif key == "a":
                from hermes_cli.tui.tool_panel import ToolPanel as _TP
                for panel in self.query(_TP):  # type: ignore[attr-defined]
                    if panel.collapsed:
                        panel.action_toggle_collapse()
                event.prevent_default()
                return
            elif key == "A":
                from hermes_cli.tui.tool_panel import ToolPanel as _TP
                for panel in self.query(_TP):  # type: ignore[attr-defined]
                    if not panel.collapsed:
                        panel.action_toggle_collapse()
                event.prevent_default()
                return
            elif key == "escape":
                focused = self.focused  # type: ignore[attr-defined]
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
                self.browse_mode = False  # type: ignore[attr-defined]
                event.prevent_default()
                return
            elif key == "]":
                self._jump_anchor(+1)  # type: ignore[attr-defined]
                event.prevent_default()
                return
            elif key == "[":
                self._jump_anchor(-1)  # type: ignore[attr-defined]
                event.prevent_default()
                return
            elif key == "}":
                self._jump_anchor(+1, BrowseAnchorType.CODE_BLOCK)  # type: ignore[attr-defined]
                event.prevent_default()
                return
            elif key == "{":
                self._jump_anchor(-1, BrowseAnchorType.CODE_BLOCK)  # type: ignore[attr-defined]
                event.prevent_default()
                return
            elif key == "alt+down":
                self._jump_anchor(+1, BrowseAnchorType.TURN_START)  # type: ignore[attr-defined]
                event.prevent_default()
                return
            elif key == "alt+up":
                self._jump_anchor(-1, BrowseAnchorType.TURN_START)  # type: ignore[attr-defined]
                event.prevent_default()
                return
            elif key == "m":
                self._jump_anchor(+1, BrowseAnchorType.MEDIA)  # type: ignore[attr-defined]
                event.prevent_default()
                return
            elif key == "M":
                self._jump_anchor(-1, BrowseAnchorType.MEDIA)  # type: ignore[attr-defined]
                event.prevent_default()
                return
            elif key == "backslash":
                self.call_later(self.action_toggle_minimap)  # type: ignore[attr-defined]
                event.prevent_default()
                return
            elif key == "T":
                self._open_tools_overlay()  # type: ignore[attr-defined]
                event.prevent_default()
                return
            elif event.character is not None:
                self.browse_mode = False  # type: ignore[attr-defined]
                try:
                    inp = self.query_one("#input-area")  # type: ignore[attr-defined]
                    if hasattr(inp, "insert_text"):
                        inp.insert_text(event.character)
                except NoMatches:
                    pass
                event.prevent_default()
                return

        # --- F9: toggle PlanPanel collapsed state ---
        if key == "f9":
            self.plan_panel_collapsed = not self.plan_panel_collapsed  # type: ignore[attr-defined]
            event.prevent_default()
            return

        # Overlay key handling — check each overlay in priority order
        for state_attr, widget_type in [
            ("approval_state", ApprovalWidget),
            ("clarify_state", ClarifyWidget),
        ]:
            state = getattr(self, state_attr)
            if state is not None:
                # For approval overlays: diff log scroll takes priority over
                # choice navigation when the diff log has focus.
                if state_attr == "approval_state":
                    try:
                        approval_widget = self.query_one(ApprovalWidget)  # type: ignore[attr-defined]
                        diff_log = approval_widget.query_one(
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
                    except NoMatches:
                        pass

                    # Tab: cycle focus between diff log and approval widget
                    if key == "tab":
                        try:
                            approval_widget = self.query_one(ApprovalWidget)  # type: ignore[attr-defined]
                            diff_log = approval_widget.query_one(
                                "CopyableRichLog#approval-diff", CopyableRichLog
                            )
                            if diff_log.display:
                                if diff_log.has_focus:
                                    approval_widget.focus()
                                else:
                                    diff_log.focus()
                                event.stop()
                                return
                        except NoMatches:
                            pass

                if key == "up" and state.selected > 0:
                    state.selected -= 1
                    try:
                        self.query_one(widget_type).update(state)  # type: ignore[attr-defined]
                    except NoMatches:
                        pass
                    event.prevent_default()
                    return
                elif key == "down" and state.selected < len(state.choices) - 1:
                    state.selected += 1
                    try:
                        self.query_one(widget_type).update(state)  # type: ignore[attr-defined]
                    except NoMatches:
                        pass
                    event.prevent_default()
                    return
                elif key == "enter":
                    if state.choices:
                        chosen = state.choices[state.selected]
                        state.response_queue.put(chosen)
                        setattr(self, state_attr, None)
                    event.prevent_default()
                    return

    def on_hermes_input_submitted(self, event: Any) -> None:
        """Handle input submission from HermesInput.

        When agent is running: interrupt first, then send new message
        (except /queue and /btw which queue without interrupting).
        """
        from hermes_cli.tui.widgets import ThinkingWidget
        text = event.value

        if isinstance(text, str) and self._handle_tui_command(text):  # type: ignore[attr-defined]
            return

        if isinstance(text, str) and text.startswith("/"):
            cmd = text.split()[0].lower()
            if cmd not in _KNOWN_SLASH_COMMANDS:
                self._flash_hint(f"Unknown command: {cmd}  (F1 for help)", 3.0)  # type: ignore[attr-defined]
                return

        images = list(self.attached_images)  # type: ignore[attr-defined]
        if images:
            self._clear_attached_images()  # type: ignore[attr-defined]
            payload = (text, images)
        else:
            payload = text

        if self.agent_running and text:  # type: ignore[attr-defined]
            _cmd = text.lstrip("/").split()[0].lower() if text.startswith("/") else ""
            if _cmd in ("queue", "btw"):
                if hasattr(self.cli, "_pending_input"):  # type: ignore[attr-defined]
                    self.cli._pending_input.put(payload)  # type: ignore[attr-defined]
                return
            try:
                self.query_one(ThinkingWidget).activate()  # type: ignore[attr-defined]
            except NoMatches:
                pass
            if hasattr(self.cli, "agent") and self.cli.agent:  # type: ignore[attr-defined]
                self.cli.agent.interrupt()  # type: ignore[attr-defined]
            if hasattr(self.cli, "_pending_input"):  # type: ignore[attr-defined]
                self.cli._pending_input.put(payload)  # type: ignore[attr-defined]
            return

        try:
            self.query_one(ThinkingWidget).activate()  # type: ignore[attr-defined]
        except NoMatches:
            pass
        # Reset per-turn plan/budget state before starting a new agent turn.
        if hasattr(self, "cli") and self.cli is not None:  # type: ignore[attr-defined]
            try:
                self.cli._reset_turn_state()  # type: ignore[attr-defined]
            except Exception:
                pass
        if hasattr(self, "cli") and self.cli is not None:  # type: ignore[attr-defined]
            if hasattr(self.cli, "_pending_input"):  # type: ignore[attr-defined]
                self.cli._pending_input.put(payload)  # type: ignore[attr-defined]

    def on_hermes_input_files_dropped(self, event: Any) -> None:
        """Handle terminal drag-and-drop pasted paths from HermesInput."""
        self.handle_file_drop(event.paths)  # type: ignore[attr-defined]
