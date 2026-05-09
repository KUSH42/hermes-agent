"""Reactive watcher logic, file-drop helpers service extracted from _app_watchers.py."""
from __future__ import annotations

import logging
import os as _os_mod
from pathlib import Path
from typing import Any, TYPE_CHECKING

_log = logging.getLogger(__name__)

from textual.css.query import NoMatches

from hermes_cli.file_drop import classify_dropped_file, format_link_token
from hermes_cli.tui.state import ChoiceOverlayState, SecretOverlayState, UndoOverlayState
from .base import AppService
from . import feedback as _fb

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp


_INTERRUPT_ATTRS = ("approval_state", "interrupt_state", "confirm_state")


class WatchersService(AppService):
    """Reactive watcher logic and file-drop helpers extracted from _WatchersMixin."""

    def __init__(self, app: "HermesApp") -> None:
        super().__init__(app)
        self._phase_before_error: str = ""  # A1: phase saved before ERROR overlay
        self._compact_warn_flashed: bool = False  # A7-1: guard single warn flash per cycle
        self._last_compact_value: bool | None = None  # PERF-3: dedup guard (None forces first call through)
        self._approval_state_seen: bool = False  # M-1: skip initial reactive fire-through
        self._pending_drop_queue: list[Path] = []  # DD-PL-6: buffered drops during modal
        self._last_drop_undo_state: tuple[str, list] | None = None  # DD-PL-7: single-slot undo

    def _modal_active(self) -> bool:
        return any(getattr(self.app, attr, None) is not None for attr in _INTERRUPT_ATTRS)

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
                    self.app._svc_spinner.set_hint_phase("typing" if has_content else "idle")

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
                    self.app._svc_spinner.set_hint_phase("typing" if has_content else "idle")

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
            image_bar.recompute_visibility()
        except (NoMatches, AttributeError):
            pass  # NoMatches: ImageBar not yet mounted during startup; AttributeError: app.size not set
        try:
            hint_bar = self.app.query_one(HintBar)
            hint_bar.display = h >= 9
        except NoMatches:
            pass

    def on_compact(self, value: bool) -> None:
        # PERF-3: dedupe against last-seen value. The reactive descriptor on
        # HermesApp is already updated to `value` by the time this runs, so
        # we cannot compare against `self.app.compact` here — that would
        # short-circuit every call. Compare against our own cached prior value.
        if self._last_compact_value == value:
            return
        self._last_compact_value = value

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
        except NoMatches:
            pass

        # A1: ToolHeaderBar deleted — sync --compact on ToolPanel directly
        for tp in self.app.query(ToolPanel):
            tp.set_class(value, "--compact")

        try:
            self.sync_compact_visibility()
        except Exception as exc:
            _log.debug("on_compact: sync_compact_visibility failed: %s", exc, exc_info=True)

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
        _warn = float(
            getattr(self.app, "config", {}).get("display", {}).get("compact_warn_threshold", 0.85)
        )
        _crit = float(
            getattr(self.app, "config", {}).get("display", {}).get("compact_badge_threshold", 0.95)
        )
        if value >= _warn and not self._compact_warn_flashed:
            self._compact_warn_flashed = True
            try:
                self.app.feedback.flash(
                    "hint-bar",
                    f"Context {int(_warn * 100)}% full — /compact available",
                    duration=8.0,
                    priority=5,
                    key=_fb.HINT_KEY_COMPACTION_WARN,
                )
            except Exception as exc:
                _log.warning("on_status_compaction_progress: feedback.flash failed: %s", exc, exc_info=True)
        elif value < _warn:
            self._compact_warn_flashed = False
        if value >= _crit and not getattr(self.app, "_compaction_warn_99", False):
            self.app._compaction_warn_99 = True
            try:
                self.app.feedback.flash(
                    "hint-bar",
                    f"Context {int(_crit * 100)}% full — /compact or clear conversation",
                    duration=8.0,
                    priority=8,
                    key=_fb.HINT_KEY_COMPACTION_CRIT,
                )
            except Exception as exc:
                _log.warning("on_status_compaction_progress: feedback.flash failed: %s", exc, exc_info=True)

    # ------------------------------------------------------------------
    # Voice watchers
    # ------------------------------------------------------------------

    def on_voice_mode(self, value: bool) -> None:
        from hermes_cli.tui.widgets import VoiceStatusBar
        try:
            self.app.query_one(VoiceStatusBar).set_class(value, "active")
        except NoMatches:
            pass
        self.app._svc_spinner.set_hint_phase("voice" if value else self.app._svc_spinner.compute_hint_phase())

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

    def _insert_plain_text(self, text: str) -> None:
        """Insert raw text at the input cursor (no link formatting)."""
        try:
            inp = self.app.query_one("#input-area")
        except NoMatches:
            return
        if hasattr(inp, "insert_text"):
            inp.insert_text(text)
        elif hasattr(inp, "value"):
            inp.value = f"{getattr(inp, 'value', '')}{text}"

    def insert_link_tokens(self, tokens: list[str]) -> None:
        if not tokens:
            return
        try:
            inp = self.app.query_one("#input-area")
        except NoMatches:
            return

        # DD-PL-7: snapshot pre-drop state for single-slot undo
        prior_text = getattr(inp, "value", "")
        prior_attached = list(getattr(self.app, "attached_images", []))

        if hasattr(inp, "history"):
            inp.history.checkpoint()

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

        if hasattr(inp, "history"):
            inp.history.checkpoint()

        self._last_drop_undo_state = (prior_text, prior_attached)

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

    def _replay_pending_drops(self) -> None:
        """Replay buffered drops once all modals are dismissed (DD-PL-6)."""
        if self._pending_drop_queue and not self._modal_active():
            queued = list(self._pending_drop_queue)
            self._pending_drop_queue.clear()
            self.handle_file_drop_inner(queued)

    def handle_file_drop(self, paths: list[Path]) -> None:
        """Route terminal drag-and-drop pasted paths into input bar."""
        try:
            self.handle_file_drop_inner(paths)
        except Exception:
            _log.exception("handle_file_drop: inner handler raised")
            self.app._flash_hint("file drop failed — see log for details", 2.0)

    def handle_file_drop_inner(self, paths: list[Path], remainder: str = "") -> None:
        if self._modal_active():
            self._pending_drop_queue.extend(paths)
            n = len(paths)
            self.app._flash_hint(
                f"queued {n} path(s) — will attach after prompt closes",
                2.0,
            )
            return

        allow_dir = bool(
            getattr(self.app, "config", {}) and
            getattr(self.app.config, "display", {}) and
            getattr(self.app.config.display, "drop_directory_as_glob", False)
        )

        cwd = self.app.get_working_directory()
        link_tokens: list[str] = []
        image_paths: list[Path] = []
        rejected_names: list[str] = []

        for path in paths:
            dropped = classify_dropped_file(path, cwd, allow_directory=allow_dir)
            if dropped.kind == "image":
                image_paths.append(path)
            elif dropped.kind == "directory_glob":
                link_tokens.append(format_link_token(path, cwd) + "/**/*")
            elif dropped.kind in ("linkable_text",):
                link_tokens.append(format_link_token(path, cwd))
            elif dropped.kind in ("unsupported_binary", "directory_rejected", "invalid"):
                rejected_names.append(path.name)
            else:
                rejected_names.append(path.name)

        if image_paths:
            self.append_attached_images(image_paths)
        if link_tokens:
            self.insert_link_tokens(link_tokens)
        if remainder:
            self._insert_plain_text(remainder)

        hint_parts: list[str] = []
        if link_tokens:
            noun = "file" if len(link_tokens) == 1 else "files"
            hint_parts.append(f"linked {len(link_tokens)} {noun}")
        if image_paths:
            noun = "image" if len(image_paths) == 1 else "images"
            hint_parts.append(f"attached {len(image_paths)} {noun}")
        if rejected_names:
            first = rejected_names[0]
            rest = len(rejected_names) - 1
            suffix = f" (+{rest} more)" if rest else ""
            self.app._flash_hint(f"⚠ skipped {first}{suffix} (unsupported)", 2.5)
            return

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
        except NoMatches:
            pass
        except Exception as exc:
            _log.debug("_post_interrupt_focus: focus call failed: %s", exc, exc_info=True)

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
        self.app._svc_spinner.set_hint_phase(self.app._svc_spinner.compute_hint_phase())

    def on_approval_state(self, value: "ChoiceOverlayState | None") -> None:
        from hermes_cli.tui.overlays import InterruptKind
        from hermes_cli.tui.overlays._adapters import make_approval_payload
        if value is None and not self._approval_state_seen:
            _log.debug("on_approval_state: initial fire-through (no approval pending)")
            return
        self._approval_state_seen = True
        _log.debug("on_approval_state: value_set=%s", value is not None)
        try:
            from hermes_cli.tui.drawbraille_overlay import DrawbrailleOverlay
            self.app.query_one(DrawbrailleOverlay).signal("waiting" if value is not None else "thinking")
        except NoMatches:
            pass
        ov = self._get_interrupt_overlay()
        if ov is None:
            if value is not None:
                _log.warning("on_approval_state: InterruptOverlay not mounted — approval prompt cannot show")
            return
        if value is not None:
            try:
                ov.present(make_approval_payload(self.app, value), replace=True)
            except Exception:
                _log.exception("on_approval_state: make_approval_payload/present failed")
                return
            self.app._hide_completion_overlay_if_present()
            self.app._dismiss_floating_panels()
            self.app.call_after_refresh(ov.focus)
            try:
                region = getattr(ov, "region", None)
                _log.debug(
                    "on_approval_state: present returned display=%s visible_cls=%s region=%s "
                    "current_kind=%s queue_len=%s",
                    getattr(ov, "display", "?"),
                    ov.has_class("--visible"),
                    region,
                    getattr(ov, "current_kind", "?"),
                    len(getattr(ov, "_queue", []) or []),
                )
            except Exception:
                _log.exception("on_approval_state: post-present diagnostic failed")
        else:
            ov.hide_if_kind(InterruptKind.APPROVAL)
            self._post_interrupt_focus()
            self._replay_pending_drops()
        self.app._svc_spinner.set_hint_phase(self.app._svc_spinner.compute_hint_phase())

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
        self.app._svc_spinner.set_hint_phase(self.app._svc_spinner.compute_hint_phase())

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
        self.app._svc_spinner.set_hint_phase(self.app._svc_spinner.compute_hint_phase())

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
        self.app._svc_spinner.set_hint_phase(self.app._svc_spinner.compute_hint_phase())
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
        except NoMatches:
            pass
        # A3-2: route error message to HintBar for prominent left-side display
        # HB2-H1: wrap in bold-red markup so _hint_to_text() preserves styling
        try:
            if value:
                _vars = getattr(self.app, "get_css_variables", lambda: {})() or {}
                err_color = _vars.get("status-error-color", "#EF5350")
                flash_text = f"[bold {err_color}]⚠ {value}[/]"
                self.app.feedback.flash(
                    "hint-bar",
                    flash_text,
                    duration=9999,
                    priority=10,
                    key=_fb.HINT_KEY_STATUS_ERROR,
                )
            else:
                self.app.feedback.cancel("hint-bar", key=_fb.HINT_KEY_STATUS_ERROR)
        except Exception as exc:
            _log.warning("on_status_error: feedback flash/cancel failed: %s", exc, exc_info=True)

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
                except Exception as exc:
                    _log.debug("on_undo_state: _set_input_locked(True) failed: %s", exc, exc_info=True)
            elif not self.app.agent_running and not self.app.command_running:
                inp.disabled = False
                try:
                    inp._set_input_locked(False)
                except Exception as exc:
                    _log.debug("on_undo_state: _set_input_locked(False) failed: %s", exc, exc_info=True)
        except NoMatches:
            pass
        if value is None:
            self.app._pending_undo_panel = None
