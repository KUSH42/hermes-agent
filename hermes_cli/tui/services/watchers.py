"""Reactive watcher logic, file-drop helpers service extracted from _app_watchers.py."""
from __future__ import annotations

import os as _os_mod
from pathlib import Path
from typing import Any, TYPE_CHECKING

from textual.css.query import NoMatches

from hermes_cli.file_drop import classify_dropped_file, format_link_token
from hermes_cli.tui.state import ChoiceOverlayState, SecretOverlayState, UndoOverlayState
from .base import AppService

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp


class WatchersService(AppService):
    """Reactive watcher logic and file-drop helpers extracted from _WatchersMixin."""

    def __init__(self, app: "HermesApp") -> None:
        super().__init__(app)
        self._phase_before_error: str = ""  # A1: phase saved before ERROR overlay

    # ------------------------------------------------------------------
    # Input change watchers
    # ------------------------------------------------------------------

    def on_text_area_changed(self, event: Any) -> None:
        """Update hint phase when HermesInput (TextArea-based) content changes."""
        if getattr(event, "text_area", None) is not None:
            inp = event.text_area
            if getattr(inp, "id", None) == "input-area":
                if (
                    not getattr(self.app, "agent_running", False)
                    and not getattr(self.app, "command_running", False)
                    and not getattr(self.app, "browse_mode", False)
                    and not bool(getattr(self.app, "status_error", ""))
                    and not any(
                        getattr(self.app, attr) is not None
                        for attr in ("approval_state", "clarify_state", "sudo_state", "secret_state")
                    )
                ):
                    has_content = bool(getattr(inp, "value", ""))
                    self.app._set_hint_phase("typing" if has_content else "idle")

    def on_input_changed(self, event: Any) -> None:
        """Update hint phase on input content change (typing phase detection)."""
        if getattr(event, "input", None) is not None:
            inp = event.input
            if getattr(inp, "id", None) == "input-area":
                if (
                    not getattr(self.app, "agent_running", False)
                    and not getattr(self.app, "command_running", False)
                    and not getattr(self.app, "browse_mode", False)
                    and not bool(getattr(self.app, "status_error", ""))
                    and not any(
                        getattr(self.app, attr) is not None
                        for attr in ("approval_state", "clarify_state", "sudo_state", "secret_state")
                    )
                ):
                    has_content = bool(getattr(inp, "value", ""))
                    self.app._set_hint_phase("typing" if has_content else "idle")

    # ------------------------------------------------------------------
    # Size / compact watchers
    # ------------------------------------------------------------------

    def on_size(self, size: Any) -> None:
        """Hide bottom-bar widgets when terminal is too short (height < 12)."""
        from hermes_cli.tui.widgets import HintBar, ImageBar
        try:
            h = size.height
        except AttributeError:
            return
        try:
            plain_rule = self.app.query_one("#input-rule-bottom")
            plain_rule.display = h >= 8
        except NoMatches:
            pass
        try:
            image_bar = self.app.query_one(ImageBar)
            if h < 10:
                image_bar.styles.display = "none"
            elif image_bar._static_content:
                image_bar.styles.display = "block"
        except (NoMatches, AttributeError):
            pass
        try:
            hint_bar = self.app.query_one(HintBar)
            hint_bar.display = h >= 9
        except NoMatches:
            pass

    def on_compact(self, value: bool) -> None:
        from hermes_cli.tui.tool_panel import ToolPanel
        from textual.widgets import Static

        # CSS class — requires _classes attr set by DOMNode.__init__
        if hasattr(self.app, "_classes"):
            if value:
                self.app.add_class("density-compact")
            else:
                self.app.remove_class("density-compact")

        # DOM operations require a running app
        try:
            chev = self.app.query_one("#input-chevron", Static)
            chev.update("❯" if value else "❯ ")
        except Exception:
            pass

        # A1: ToolHeaderBar deleted — sync --compact on ToolPanel directly
        try:
            for tp in self.app.query(ToolPanel):
                tp.set_class(value, "--compact")
        except Exception:
            pass

        try:
            self.sync_compact_visibility()
        except Exception:
            pass

    def sync_compact_visibility(self) -> None:
        from hermes_cli.tui.session_widgets import SessionBar
        compact = self.app.compact
        try:
            sbar = self.app.query_one(SessionBar)
            single = len(getattr(self.app, "_session_records_cache", [])) <= 1
            sbar.display = not (compact and single)
        except NoMatches:
            pass

    # ------------------------------------------------------------------
    # Compaction progress watcher
    # ------------------------------------------------------------------

    def on_status_compaction_progress(self, value: float) -> None:
        from hermes_cli.tui.widgets import TitledRule
        if value == 0.0:
            self.app.hooks.fire("on_compact_complete")
        try:
            self.app.query_one("#input-rule", TitledRule).progress = value
        except NoMatches:
            pass
        if value >= 0.9 and not self.app._compaction_warned:
            self.app._compaction_warned = True
            self.app._flash_hint("⚠  Context window 90% full — compaction imminent", 3.0)
        if value >= 0.99 and not getattr(self.app, "_compaction_warn_99", False):
            self.app._compaction_warn_99 = True
            self.app._flash_hint("⚠  Context 99% — send /compact or clear conversation", 5.0)

    # ------------------------------------------------------------------
    # Voice watchers
    # ------------------------------------------------------------------

    def on_voice_mode(self, value: bool) -> None:
        from hermes_cli.tui.widgets import VoiceStatusBar
        try:
            self.app.query_one(VoiceStatusBar).set_class(value, "active")
        except NoMatches:
            pass
        self.app._set_hint_phase("voice" if value else self.app._compute_hint_phase())

    def on_voice_recording(self, value: bool) -> None:
        from hermes_cli.tui.widgets import VoiceStatusBar
        try:
            bar = self.app.query_one(VoiceStatusBar)
            if value:
                bar.update_status("● REC")
            elif self.app.voice_mode:
                bar.update_status("🎤 Voice mode")
        except NoMatches:
            pass

    # ------------------------------------------------------------------
    # Attached images
    # ------------------------------------------------------------------

    def on_attached_images(self, value: list) -> None:
        from hermes_cli.tui.widgets import ImageBar
        try:
            self.app.query_one(ImageBar).update_images(value)
        except NoMatches:
            pass

    def append_attached_images(self, images: list[Path]) -> None:
        """Keep TUI image state and CLI submit payload in sync."""
        if not images:
            return
        current = list(self.app.attached_images)
        current.extend(images)
        self.app.attached_images = current
        cli = getattr(self.app, "cli", None)
        if cli is not None and hasattr(cli, "_attached_images"):
            cli._attached_images.extend(images)

    def clear_attached_images(self) -> None:
        self.app.attached_images = []
        cli = getattr(self.app, "cli", None)
        if cli is not None and hasattr(cli, "_attached_images"):
            cli._attached_images.clear()

    # ------------------------------------------------------------------
    # Link token insertion
    # ------------------------------------------------------------------

    def insert_link_tokens(self, tokens: list[str]) -> None:
        if not tokens:
            return
        try:
            inp = self.app.query_one("#input-area")
        except NoMatches:
            return
        selection = getattr(inp, "selection", None)
        if hasattr(inp, "_location_to_flat") and selection is not None:
            start = end = inp.cursor_pos
            if not selection.is_empty:
                start = inp._location_to_flat(selection.start)
                end   = inp._location_to_flat(selection.end)
        else:
            start = end = getattr(inp, "cursor_position", 0)
            if selection is not None and not selection.is_empty:
                start, end = selection.start, selection.end

        before = inp.value[:start]
        after  = inp.value[end:]
        prefix = "" if not before or before[-1].isspace() else " "
        suffix = "" if not after  or after[0].isspace()  else " "
        payload = prefix + " ".join(tokens) + suffix
        if selection is not None and not selection.is_empty:
            if hasattr(inp, "replace_flat"):
                inp.replace_flat(payload, start, end)
            elif hasattr(inp, "replace"):
                inp.replace(payload, start, end)
        else:
            inp.insert_text(payload)

    # ------------------------------------------------------------------
    # File drop
    # ------------------------------------------------------------------

    @staticmethod
    def drop_path_display(path: Path, cwd: Path) -> str:
        """Format a dropped file path: relative if in cwd/child/parent, else absolute."""
        try:
            return path.relative_to(cwd).as_posix()
        except ValueError:
            pass
        try:
            rel = _os_mod.path.relpath(path, cwd)
        except ValueError:
            return path.as_posix()
        depth = 0
        r = rel
        while r.startswith(".."):
            depth += 1
            r = r[3:] if len(r) > 2 else ""
        if depth <= 1:
            return rel.replace(_os_mod.sep, "/")
        return path.as_posix()

    def handle_file_drop(self, paths: list[Path]) -> None:
        """Route terminal drag-and-drop pasted paths into input bar."""
        try:
            self.handle_file_drop_inner(paths)
        except Exception:
            self.app._flash_hint("file drop failed — see log for details", 2.0)

    def handle_file_drop_inner(self, paths: list[Path]) -> None:
        if any(getattr(self.app, attr) is not None for attr in ("approval_state", "clarify_state", "sudo_state", "secret_state")):
            self.app._flash_hint("file drop unavailable while prompt is open", 1.5)
            return

        cwd = self.app.get_working_directory()
        link_tokens: list[str] = []
        image_paths: list[Path] = []
        rejected: list[str] = []

        for path in paths:
            dropped = classify_dropped_file(path, cwd)
            if dropped.kind == "image":
                image_paths.append(path)
            elif dropped.kind in ("linkable_text", "directory"):
                link_tokens.append(format_link_token(path, cwd))
            elif dropped.kind == "unsupported_binary":
                rejected.append(dropped.reason or "unsupported file type")
            else:
                rejected.append(dropped.reason or dropped.kind)

        if image_paths:
            self.append_attached_images(image_paths)
        if link_tokens:
            self.insert_link_tokens(link_tokens)

        hint_parts: list[str] = []
        if link_tokens:
            noun = "file" if len(link_tokens) == 1 else "files"
            hint_parts.append(f"linked {len(link_tokens)} {noun}")
        if image_paths:
            noun = "image" if len(image_paths) == 1 else "images"
            hint_parts.append(f"attached {len(image_paths)} {noun}")
        if rejected:
            noun = "item" if len(rejected) == 1 else "items"
            hint_parts.append(f"dropped {len(rejected)} unsupported {noun}")

        if hint_parts:
            self.app._flash_hint(" · ".join(hint_parts), 1.2)

    # ------------------------------------------------------------------
    # Overlay state watchers
    # ------------------------------------------------------------------

    def _get_interrupt_overlay(self):
        """Return the canonical InterruptOverlay instance, or None if not mounted."""
        from hermes_cli.tui.overlays import InterruptOverlay
        try:
            return self.app.query_one(InterruptOverlay)
        except NoMatches:
            return None

    def _post_interrupt_focus(self) -> None:
        """Restore focus after any interrupt dismissal.

        Priority: input-area (if not agent-running) → app root.
        Called unconditionally from every on_*_state(None) branch.
        """
        try:
            if not self.app.agent_running and not getattr(self.app, "command_running", False):
                self.app.call_after_refresh(self.app.query_one("#input-area").focus)
            else:
                # Agent still running: return focus to screen (App.focus() doesn't exist
                # in Textual 8.x; screen.focus() is the correct call).
                self.app.call_after_refresh(self.app.screen.focus)
        except Exception:
            pass

    def on_clarify_state(self, value: "ChoiceOverlayState | None") -> None:
        from hermes_cli.tui.overlays import InterruptKind
        from hermes_cli.tui.overlays._adapters import make_clarify_payload
        ov = self._get_interrupt_overlay()
        if ov is not None:
            if value is not None:
                ov.present(make_clarify_payload(self.app, value), replace=True)
                self.app._hide_completion_overlay_if_present()
                self.app._dismiss_floating_panels()
                self.app.call_after_refresh(ov.focus)
            else:
                ov.hide_if_kind(InterruptKind.CLARIFY)
                self._post_interrupt_focus()
        self.app._set_hint_phase(self.app._compute_hint_phase())

    def on_approval_state(self, value: "ChoiceOverlayState | None") -> None:
        from hermes_cli.tui.overlays import InterruptKind
        from hermes_cli.tui.overlays._adapters import make_approval_payload
        try:
            from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay
            self.app.query_one(DrawbrailleOverlay).signal("waiting" if value is not None else "thinking")
        except Exception:
            pass
        ov = self._get_interrupt_overlay()
        if ov is not None:
            if value is not None:
                ov.present(make_approval_payload(self.app, value), replace=True)
                self.app._hide_completion_overlay_if_present()
                self.app._dismiss_floating_panels()
                self.app.call_after_refresh(ov.focus)
            else:
                ov.hide_if_kind(InterruptKind.APPROVAL)
                self._post_interrupt_focus()
        self.app._set_hint_phase(self.app._compute_hint_phase())

    def on_highlighted_candidate(self, c: Any) -> None:
        """Route highlighted candidate to PreviewPanel (PathCandidate only)."""
        try:
            from hermes_cli.tui.preview_panel import PreviewPanel as _PP
            from hermes_cli.tui.path_search import PathCandidate as _PC
            panel = self.app.query_one(_PP)
            panel.candidate = c if isinstance(c, _PC) else None
        except NoMatches:
            pass
        try:
            from hermes_cli.tui.completion_overlay import CompletionOverlay as _CO
            comp = self.app.query_one(_CO)
            if c is None:
                comp.add_class("--no-preview")
            else:
                comp.remove_class("--no-preview")
        except NoMatches:
            pass

    def on_sudo_state(self, value: "SecretOverlayState | None") -> None:
        from hermes_cli.tui.overlays import InterruptKind
        from hermes_cli.tui.overlays._adapters import make_sudo_payload
        ov = self._get_interrupt_overlay()
        if ov is not None:
            if value is not None:
                ov.present(make_sudo_payload(self.app, value), replace=True)
                self.app._dismiss_floating_panels()
            else:
                ov.hide_if_kind(InterruptKind.SUDO)
                self._post_interrupt_focus()
        self.app._set_hint_phase(self.app._compute_hint_phase())

    def on_secret_state(self, value: "SecretOverlayState | None") -> None:
        from hermes_cli.tui.overlays import InterruptKind
        from hermes_cli.tui.overlays._adapters import make_secret_payload
        ov = self._get_interrupt_overlay()
        if ov is not None:
            if value is not None:
                ov.present(make_secret_payload(self.app, value), replace=True)
                self.app._dismiss_floating_panels()
            else:
                ov.hide_if_kind(InterruptKind.SECRET)
                self._post_interrupt_focus()
        self.app._set_hint_phase(self.app._compute_hint_phase())

    # ------------------------------------------------------------------
    # Status error watcher
    # ------------------------------------------------------------------

    def on_status_error(self, value: str) -> None:
        """Update TitledRule error state and hint phase when error changes."""
        from hermes_cli.tui.widgets import TitledRule
        try:
            self.app.query_one("#input-rule", TitledRule).set_error(bool(value))
        except NoMatches:
            pass
        self.app._set_hint_phase(self.app._compute_hint_phase())
        # A1: ERROR phase is orthogonal — save/restore previous phase
        from hermes_cli.tui.agent_phase import Phase as _Phase
        if value:
            if getattr(self.app, "status_phase", _Phase.IDLE) != _Phase.ERROR:
                self._phase_before_error = getattr(self.app, "status_phase", _Phase.IDLE)
            self.app.status_phase = _Phase.ERROR
            self.app.hooks.fire("on_error_set", error=value)
        else:
            self.app.status_phase = self._phase_before_error or _Phase.IDLE
            self._phase_before_error = ""
            self.app.hooks.fire("on_error_clear")
        # E-1: propagate error text to HermesInput error_state
        try:
            from hermes_cli.tui.input.widget import HermesInput
            inp = self.app.query_one("#input-area", HermesInput)
            inp.error_state = value if value else None
        except Exception:
            pass

    def auto_clear_status_error(self, expected: str) -> None:
        """Clear status_error if it still matches *expected*."""
        self.app._status_error_timer = None
        if self.app.status_error == expected:
            self.app.status_error = ""

    # ------------------------------------------------------------------
    # Undo state watcher
    # ------------------------------------------------------------------

    def on_undo_state(self, value: "UndoOverlayState | None") -> None:
        from hermes_cli.tui.overlays import InterruptKind
        from hermes_cli.tui.overlays._adapters import make_undo_payload
        ov = self._get_interrupt_overlay()
        if ov is not None:
            if value is not None:
                # Undo preempts any currently-visible interrupt; prior resumes
                # when undo resolves (queue-front insert).
                ov.present(make_undo_payload(self.app, value), preempt=True)
                self.app._dismiss_floating_panels()
            else:
                ov.hide_if_kind(InterruptKind.UNDO)
                self._post_interrupt_focus()
        try:
            inp = self.app.query_one("#input-area")
            if value is not None:
                inp.disabled = True
                try:
                    inp._set_input_locked(True)
                except Exception:
                    pass
            elif not self.app.agent_running and not self.app.command_running:
                inp.disabled = False
                try:
                    inp._set_input_locked(False)
                except Exception:
                    pass
        except NoMatches:
            pass
        if value is None:
            self.app._pending_undo_panel = None
