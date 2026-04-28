"""Autocomplete dispatch and accept/dismiss mixin for HermesInput."""
from __future__ import annotations

import logging
import time
from typing import Any

from textual.css.query import NoMatches

from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger, detect_context, _SKILL_RE
from hermes_cli.tui.completion_list import VirtualCompletionList
from hermes_cli.tui.fuzzy import fuzzy_rank
from hermes_cli.tui.path_search import PathCandidate, SlashCandidate

from ._assist import AssistKind, SKILL_PICKER_TRIGGER_PREFIX
from ._constants import _SLASH_FULL_RE

_log = logging.getLogger(__name__)


class _AutocompleteMixin:
    """Mixin: autocomplete dispatch, slash/path completion, accept/dismiss."""

    # State initialised by HermesInput.__init__
    _current_trigger: Any
    _raw_candidates: list
    _slash_commands: list[str]
    _suppress_autocomplete_once: bool

    # --- Dispatch ---

    def _update_autocomplete(self) -> None:
        """Dispatch to the correct completion provider based on context."""
        from hermes_cli.tui.perf import measure

        with measure("input._update_autocomplete", budget_ms=4.0):
            if self._suppress_autocomplete_once:
                self._suppress_autocomplete_once = False
                return
            if getattr(self.app, "choice_overlay_active", False):  # type: ignore[attr-defined]
                self._resolve_assist(AssistKind.NONE)  # type: ignore[attr-defined]
                return

            # In bash mode: @file completion is intentional (useful for !cat @path)
            # Slash-command completion is suppressed (/ is a path separator in shell)
            from hermes_cli.tui.input._mode import InputMode
            if (
                getattr(self, "_mode", None) is not InputMode.BASH  # type: ignore[attr-defined]
                and
                "\n" not in self.value  # type: ignore[attr-defined]
                and self.value.startswith("/")  # type: ignore[attr-defined]
                and _SLASH_FULL_RE.match(self.value)  # type: ignore[attr-defined]
            ):
                fragment = self.value[1:]  # type: ignore[attr-defined]
                new_trigger = CompletionTrigger(
                    CompletionContext.SLASH_COMMAND, fragment, 1,
                )
                # Guard: prevents watch_items → refresh → watch_value re-entry loop.
                if new_trigger == self._current_trigger:
                    return
                self._current_trigger = new_trigger
                self._raw_candidates = []
                self._show_slash_completions(fragment)
                return

            _bash_mode = getattr(self, "_mode", None) is InputMode.BASH  # type: ignore[attr-defined]
            trigger = detect_context(self.value, self.cursor_position, bash_mode=_bash_mode)  # type: ignore[attr-defined]
            # Guard: prevents re-entry loop on unchanged trigger.
            if trigger == self._current_trigger:
                return
            self._current_trigger = trigger
            self._raw_candidates = []

            if trigger.context is CompletionContext.SKILL_INVOKE:
                # $-typed path: open (or update) the skill picker.
                # Do NOT mount the inline completion overlay — the picker IS
                # the completion surface for $-prefixed input.
                try:
                    self._resolve_assist(AssistKind.PICKER)  # type: ignore[attr-defined]
                except Exception:
                    _log.exception("skill picker open failed for fragment=%r", trigger.fragment)
                    try:
                        self.app._flash_hint("skill picker unavailable", 2.0)  # type: ignore[attr-defined]
                    except Exception as exc:  # app._flash_hint unavailable — fallback hint not shown
                        _log.debug("skill picker fallback flash failed: %s", exc, exc_info=True)
                return

            # Auto-dismiss a prefix-triggered picker when the regex no longer matches.
            if not _bash_mode and not _SKILL_RE.match(self.value):  # type: ignore[attr-defined]
                try:
                    from hermes_cli.tui.overlays.skill_picker import SkillPickerOverlay
                    picker = self.app.query_one(SkillPickerOverlay)  # type: ignore[attr-defined]
                    if getattr(picker, "_trigger", None) == SKILL_PICKER_TRIGGER_PREFIX:
                        picker.dismiss()
                except Exception:
                    # NoMatches or SkillPickerOverlay not yet imported — fine
                    pass

            if trigger.context is CompletionContext.SLASH_COMMAND:
                self._show_slash_completions(trigger.fragment)
            elif trigger.context in (
                CompletionContext.PATH_REF,
                CompletionContext.PLAIN_PATH_REF,
                CompletionContext.ABSOLUTE_PATH_REF,
            ):
                self._show_path_completions(trigger.fragment)  # type: ignore[attr-defined]
            else:
                if self._completion_overlay_visible():  # type: ignore[attr-defined]
                    self._resolve_assist(AssistKind.NONE)  # type: ignore[attr-defined]

    def _show_slash_completions(self, fragment: str) -> None:
        items = [
            SlashCandidate(display=c, command=c)
            for c in self._slash_commands
            if c.startswith("/" + fragment)
        ]
        from hermes_cli.tui.perf import measure

        with measure("slash_completions.fuzzy_rank", budget_ms=2.0, silent=True):
            ranked = fuzzy_rank(fragment, items, limit=len(items))
        if not ranked:
            hint = ""
            duration = 1.5
            if fragment and len(fragment) >= 2:
                all_slash = [SlashCandidate(display=c, command=c) for c in self._slash_commands]
                suggestions = fuzzy_rank(fragment, all_slash, limit=1)
                if suggestions:
                    hint = f"Did you mean: {suggestions[0].command}?"
                    duration = 2.0
                else:
                    hint = f"Unknown command: /{fragment}"
                    duration = 1.5
            elif fragment:
                hint = f"Unknown command: /{fragment}"
                duration = 1.5
            now = time.monotonic()
            last_fragment = getattr(self, "_last_slash_hint_fragment", None)
            last_time = getattr(self, "_last_slash_hint_time", 0.0)
            if hint and not (last_fragment == fragment and now - last_time < 2.0):
                self._last_slash_hint_fragment = fragment  # type: ignore[attr-defined]
                self._last_slash_hint_time = now  # type: ignore[attr-defined]
                try:
                    self.app._flash_hint(hint, duration)  # type: ignore[attr-defined]
                except AttributeError as exc:
                    # AttributeError: test harness or early-mount context without _flash_hint.
                    _log.debug("flash_hint unavailable: %s", exc, exc_info=True)
            self._resolve_assist(AssistKind.NONE)  # type: ignore[attr-defined]
            return
        self._set_overlay_mode(slash_only=True)  # type: ignore[attr-defined]
        self._push_to_list(ranked)  # type: ignore[attr-defined]
        self._resolve_assist(AssistKind.OVERLAY)  # type: ignore[attr-defined]

    # --- Paging ---

    def action_completion_page_up(self) -> None:
        """PageUp: jump one page up in the completion list."""
        if not self._completion_overlay_visible():  # type: ignore[attr-defined]
            return
        try:
            clist = self.screen.query_one(VirtualCompletionList)  # type: ignore[attr-defined]
            if not clist.items:
                return
            page = max(1, clist.size.height - 1)
            clist.highlighted = max(0, clist.highlighted - page)
        except NoMatches:
            pass

    def action_completion_page_down(self) -> None:
        """PageDown: jump one page down in the completion list."""
        if not self._completion_overlay_visible():  # type: ignore[attr-defined]
            return
        try:
            clist = self.screen.query_one(VirtualCompletionList)  # type: ignore[attr-defined]
            if not clist.items:
                return
            page = max(1, clist.size.height - 1)
            clist.highlighted = min(len(clist.items) - 1, clist.highlighted + page)
        except NoMatches:
            pass

    # --- Accept / dismiss ---

    def action_accept_autocomplete(self) -> None:
        """Tab: accept highlighted completion or ghost-text suggestion.

        When the completion overlay is not visible, Tab delegates to
        action_cursor_right() which accepts the ghost-text suggestion (if any).
        """
        if not self._completion_overlay_visible():  # type: ignore[attr-defined]
            self.action_cursor_right()  # type: ignore[attr-defined]
            return
        try:
            clist = self.screen.query_one(VirtualCompletionList)  # type: ignore[attr-defined]
        except NoMatches:
            return
        if not clist.items or clist.highlighted < 0:
            return

        c = clist.items[clist.highlighted]
        trig = self._current_trigger

        if isinstance(c, SlashCandidate):
            new_value = c.command + " "
            new_cursor = len(new_value)
        elif isinstance(c, PathCandidate):
            insert_text = c.insert_text or c.display
            if trig.context in (
                CompletionContext.PLAIN_PATH_REF,
                CompletionContext.ABSOLUTE_PATH_REF,
            ):
                if trig.context is CompletionContext.PLAIN_PATH_REF and not c.insert_text:
                    prefix_end = self.value.index("/", trig.start) + 1  # type: ignore[attr-defined]
                    path_prefix = self.value[trig.start:prefix_end]  # type: ignore[attr-defined]
                    insert_text = f"{path_prefix}{c.display}"
                before = self.value[:trig.start]  # type: ignore[attr-defined]
                after = self.value[self.cursor_position:]  # type: ignore[attr-defined]
                tail = " " if not after else ""
                new_value = f"{before}{insert_text}{tail}{after}"
                new_cursor = len(before) + len(insert_text) + len(tail)
            else:
                before = self.value[: trig.start - 1]  # type: ignore[attr-defined]
                after = self.value[self.cursor_position:]  # type: ignore[attr-defined]
                tail = " " if not after else ""
                new_value = f"{before}@{insert_text}{tail}{after}"
                new_cursor = len(before) + 1 + len(insert_text) + len(tail)
        else:
            return

        self.value = new_value  # type: ignore[attr-defined]
        self.cursor_position = new_cursor  # type: ignore[attr-defined]
        self._resolve_assist(AssistKind.NONE)  # type: ignore[attr-defined]

    def action_dismiss_autocomplete(self) -> None:
        """Dismiss completion overlay without affecting agent-interrupt semantics."""
        if self._completion_overlay_visible():  # type: ignore[attr-defined]
            self._hide_completion_overlay()  # type: ignore[attr-defined]
