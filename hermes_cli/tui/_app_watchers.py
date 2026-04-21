"""_WatchersMixin — reactive watchers for input, size, compaction, voice, images, and file drop."""
from __future__ import annotations

import os as _os_mod
from pathlib import Path
from typing import Any

from textual.css.query import NoMatches

from hermes_cli.file_drop import classify_dropped_file, format_link_token


class _WatchersMixin:
    """Reactive watchers and input/file-drop helpers.

    Extracted from HermesApp to reduce file size.  Self is always a HermesApp
    instance at runtime — all attribute access on self is valid.
    """

    def on_text_area_changed(self, event: Any) -> None:
        """Update hint phase when HermesInput (TextArea-based) content changes."""
        if getattr(event, "text_area", None) is not None:
            inp = event.text_area
            if getattr(inp, "id", None) == "input-area":
                if (
                    not getattr(self, "agent_running", False)
                    and not getattr(self, "command_running", False)
                    and not getattr(self, "browse_mode", False)
                    and not bool(getattr(self, "status_error", ""))
                    and not any(
                        getattr(self, attr) is not None
                        for attr in ("approval_state", "clarify_state", "sudo_state", "secret_state")
                    )
                ):
                    has_content = bool(getattr(inp, "value", ""))
                    self._set_hint_phase("typing" if has_content else "idle")  # type: ignore[attr-defined]

    def on_input_changed(self, event: Any) -> None:
        """Update hint phase on input content change (typing phase detection)."""
        if getattr(event, "input", None) is not None:
            inp = event.input
            if getattr(inp, "id", None) == "input-area":
                if (
                    not getattr(self, "agent_running", False)
                    and not getattr(self, "command_running", False)
                    and not getattr(self, "browse_mode", False)
                    and not bool(getattr(self, "status_error", ""))
                    and not any(
                        getattr(self, attr) is not None
                        for attr in ("approval_state", "clarify_state", "sudo_state", "secret_state")
                    )
                ):
                    has_content = bool(getattr(inp, "value", ""))
                    self._set_hint_phase("typing" if has_content else "idle")  # type: ignore[attr-defined]

    def watch_size(self, size: Any) -> None:
        """Hide bottom-bar widgets when terminal is too short (height < 12)."""
        from hermes_cli.tui.widgets import HintBar, ImageBar
        try:
            h = size.height
        except AttributeError:
            return
        try:
            plain_rule = self.query_one("#input-rule-bottom")  # type: ignore[attr-defined]
            plain_rule.display = h >= 8
        except NoMatches:
            pass
        try:
            image_bar = self.query_one(ImageBar)  # type: ignore[attr-defined]
            if h < 10:
                image_bar.styles.display = "none"
            elif image_bar._static_content:
                image_bar.styles.display = "block"
        except (NoMatches, AttributeError):
            pass
        try:
            hint_bar = self.query_one(HintBar)  # type: ignore[attr-defined]
            hint_bar.display = h >= 9
        except NoMatches:
            pass

    def watch_status_compaction_progress(self, value: float) -> None:
        from hermes_cli.tui.widgets import TitledRule
        if value == 0.0:
            self.context_pct = 0.0  # type: ignore[attr-defined]
            self._compaction_warned = False  # type: ignore[attr-defined]
            self._compaction_warn_99: bool = getattr(self, "_compaction_warn_99", False)
            self._compaction_warn_99 = False
        try:
            self.query_one("#input-rule", TitledRule).progress = value  # type: ignore[attr-defined]
        except NoMatches:
            pass
        if value >= 0.9 and not self._compaction_warned:  # type: ignore[attr-defined]
            self._compaction_warned = True  # type: ignore[attr-defined]
            self._flash_hint("⚠  Context window 90% full — compaction imminent", 3.0)  # type: ignore[attr-defined]
        if value >= 0.99 and not getattr(self, "_compaction_warn_99", False):
            self._compaction_warn_99 = True  # type: ignore[attr-defined]
            self._flash_hint("⚠  Context 99% — send /compact or clear conversation", 5.0)  # type: ignore[attr-defined]

    def watch_voice_mode(self, value: bool) -> None:
        from hermes_cli.tui.widgets import VoiceStatusBar
        try:
            self.query_one(VoiceStatusBar).set_class(value, "active")  # type: ignore[attr-defined]
        except NoMatches:
            pass
        self._set_hint_phase("voice" if value else self._compute_hint_phase())  # type: ignore[attr-defined]

    def watch_voice_recording(self, value: bool) -> None:
        from hermes_cli.tui.widgets import VoiceStatusBar
        try:
            bar = self.query_one(VoiceStatusBar)  # type: ignore[attr-defined]
            if value:
                bar.update_status("● REC")
            elif self.voice_mode:  # type: ignore[attr-defined]
                bar.update_status("🎤 Voice mode")
        except NoMatches:
            pass

    def watch_attached_images(self, value: list) -> None:
        from hermes_cli.tui.widgets import ImageBar
        try:
            self.query_one(ImageBar).update_images(value)  # type: ignore[attr-defined]
        except NoMatches:
            pass

    def _append_attached_images(self, images: list[Path]) -> None:
        """Keep TUI image state and CLI submit payload in sync."""
        if not images:
            return
        current = list(self.attached_images)  # type: ignore[attr-defined]
        current.extend(images)
        self.attached_images = current  # type: ignore[attr-defined]
        cli = getattr(self, "cli", None)
        if cli is not None and hasattr(cli, "_attached_images"):
            cli._attached_images.extend(images)

    def _clear_attached_images(self) -> None:
        self.attached_images = []  # type: ignore[attr-defined]
        cli = getattr(self, "cli", None)
        if cli is not None and hasattr(cli, "_attached_images"):
            cli._attached_images.clear()

    def _insert_link_tokens(self, tokens: list[str]) -> None:
        if not tokens:
            return
        try:
            inp = self.query_one("#input-area")  # type: ignore[attr-defined]
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

    @staticmethod
    def _drop_path_display(path: Path, cwd: Path) -> str:
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
            self._handle_file_drop_inner(paths)
        except Exception:
            self._flash_hint("file drop failed — see log for details", 2.0)  # type: ignore[attr-defined]

    def _handle_file_drop_inner(self, paths: list[Path]) -> None:
        if any(getattr(self, attr) is not None for attr in ("approval_state", "clarify_state", "sudo_state", "secret_state")):
            self._flash_hint("file drop unavailable while prompt is open", 1.5)  # type: ignore[attr-defined]
            return

        cwd = self.get_working_directory()  # type: ignore[attr-defined]
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
            self._append_attached_images(image_paths)
        if link_tokens:
            self._insert_link_tokens(link_tokens)

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
            self._flash_hint(" · ".join(hint_parts), 1.2)  # type: ignore[attr-defined]
