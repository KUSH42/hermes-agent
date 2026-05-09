"""Tests for AC-DESC: slash & skill autocomplete description preview.

Spec: spec_ac_desc_completion_preview.md
Classes:
    TestACDescH1SlashDataPlumbing  (5 tests)  — AC-DESC-H1
    TestACDescH2SkillDataPlumbing  (5 tests)  — AC-DESC-H2
    TestACDescM1PanelRender        (5 tests)  — AC-DESC-M1
    TestACDescM2EmdashFallback     (3 tests)  — AC-DESC-M2
"""
from __future__ import annotations

import logging
import types

import pytest

from hermes_cli.tui.path_search import SlashCandidate
from hermes_cli.tui.types.skill_candidate import SkillCandidate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill(
    name: str = "my-skill",
    description: str = "Does X",
    source: str = "hermes",
    trigger_phrases: list[str] | None = None,
    enabled: bool = True,
) -> SkillCandidate:
    return SkillCandidate(
        name=name,
        description=description,
        trigger_phrases=trigger_phrases or [],
        do_not_trigger=[],
        source=source,
        enabled=enabled,
    )


class _FakeInput:
    """Minimal stub for _AutocompleteMixin state."""

    def __init__(self) -> None:
        self._slash_commands: list[str] = []
        self._skills: list[SkillCandidate] = []
        self._pushed: list = []
        self._overlay_mode: dict = {}
        self._assist_kind = None

    # autocomplete mixin call-outs
    def _set_overlay_mode(self, **kw: object) -> None:
        self._overlay_mode.update(kw)

    def _push_to_list(self, items: list) -> None:
        self._pushed = list(items)

    def _resolve_assist(self, kind: object) -> None:
        self._assist_kind = kind

    def _completion_overlay_visible(self) -> bool:
        return False

    # mix in the real method under test
    from hermes_cli.tui.input._autocomplete import _AutocompleteMixin
    _show_slash_completions = _AutocompleteMixin._show_slash_completions
    _show_skill_completions = _AutocompleteMixin._show_skill_completions


# ---------------------------------------------------------------------------
# AC-DESC-H1 — slash candidates carry description / args_hint / keybind_hint
# ---------------------------------------------------------------------------

class TestACDescH1SlashDataPlumbing:
    def _inp(self, commands: list[str] | None = None) -> _FakeInput:
        inp = _FakeInput()
        inp._slash_commands = commands or ["/help", "/queue", "/q"]
        return inp

    def test_slash_candidate_carries_description(self) -> None:
        inp = self._inp()
        inp._slash_descriptions = {"/help": "Show help"}
        inp._show_slash_completions("help")
        assert inp._pushed, "no candidates pushed"
        assert inp._pushed[0].description == "Show help"

    def test_slash_candidate_carries_args_hint(self) -> None:
        inp = self._inp()
        inp._slash_descriptions = {"/help": "Show help"}
        inp._slash_args_hints = {"/help": "<topic>"}
        inp._show_slash_completions("help")
        assert inp._pushed[0].args_hint == "<topic>"

    def test_slash_candidate_carries_keybind_hint(self) -> None:
        inp = self._inp()
        inp._slash_descriptions = {"/help": "Show help"}
        inp._slash_keybind_hints = {"/help": "Ctrl+?"}
        inp._show_slash_completions("help")
        assert inp._pushed[0].keybind_hint == "Ctrl+?"

    def test_slash_candidate_alias_inherits_description(self) -> None:
        inp = self._inp()
        inp._slash_descriptions = {"/queue": "Queue desc", "/q": "Queue desc"}
        inp._show_slash_completions("")
        names = {c.command: c.description for c in inp._pushed}
        assert names.get("/queue") == "Queue desc"
        assert names.get("/q") == "Queue desc"

    def test_slash_candidate_missing_dict_falls_back_empty_string(self) -> None:
        inp = self._inp()
        # deliberately omit _slash_descriptions / _slash_args_hints / _slash_keybind_hints
        inp._show_slash_completions("help")
        assert inp._pushed[0].description == ""
        assert inp._pushed[0].args_hint == ""
        assert inp._pushed[0].keybind_hint == ""


# ---------------------------------------------------------------------------
# AC-DESC-H2 — skill candidates carry source + first trigger phrase
# ---------------------------------------------------------------------------

class TestACDescH2SkillDataPlumbing:
    def _inp(self, skills: list[SkillCandidate]) -> _FakeInput:
        inp = _FakeInput()
        inp._skills = skills
        return inp

    def test_skill_candidate_carries_source(self) -> None:
        skill = _make_skill(name="myplugin", source="plugin")
        inp = self._inp([skill])
        inp._show_skill_completions("")
        assert inp._pushed[0].source == "plugin"

    def test_skill_candidate_carries_first_trigger(self) -> None:
        skill = _make_skill(trigger_phrases=["use when X", "or when Y"])
        inp = self._inp([skill])
        inp._show_skill_completions("")
        assert inp._pushed[0].trigger_hint == "use when X"

    def test_skill_candidate_no_trigger_phrases_empty_hint(self) -> None:
        skill = _make_skill(trigger_phrases=[])
        inp = self._inp([skill])
        inp._show_skill_completions("")
        assert inp._pushed[0].trigger_hint == ""

    def test_skill_candidate_disabled_filtered(self) -> None:
        skill = _make_skill(enabled=False)
        inp = self._inp([skill])
        inp._show_skill_completions("")
        assert inp._pushed == []

    def test_slash_candidate_default_source_and_trigger_empty(self) -> None:
        c = SlashCandidate(display="/help", command="/help")
        assert c.source == ""
        assert c.trigger_hint == ""


# ---------------------------------------------------------------------------
# AC-DESC-M1 — SlashDescPanel renders source badge + trigger hint when present
# ---------------------------------------------------------------------------

class _FakeRichLog:
    """Captures write() calls from SlashDescPanel._on_candidate."""

    def __init__(self) -> None:
        self._lines: list[str] = []

    def clear(self) -> None:
        self._lines.clear()

    def write(self, text: str) -> None:
        self._lines.append(text)

    @property
    def last(self) -> str:
        return self._lines[-1] if self._lines else ""


def _panel_write(candidate: object) -> str:
    """Drive SlashDescPanel._on_candidate and return what was written."""
    from hermes_cli.tui.completion_overlay import SlashDescPanel, _NO_DESCRIPTION_FALLBACK

    fake_log = _FakeRichLog()

    # Patch the instance to use our fake RichLog methods
    panel = object.__new__(SlashDescPanel)
    panel.clear = fake_log.clear
    panel.write = fake_log.write

    panel._on_candidate(candidate)
    return fake_log.last


class TestACDescM1PanelRender:
    def test_panel_renders_description_only(self) -> None:
        c = SlashCandidate(display="/help", command="/help", description="Show help")
        body = _panel_write(c)
        assert "[bold]/help[/bold]" in body
        assert "Show help" in body
        assert "[dim]" not in body.split("[bold]")[0]  # no badge prefix

    def test_panel_renders_args_hint_in_title(self) -> None:
        c = SlashCandidate(display="/help", command="/help", description="d", args_hint="<topic>")
        body = _panel_write(c)
        assert "[dim]<topic>[/dim]" in body

    def test_panel_renders_source_badge_when_set(self) -> None:
        c = SlashCandidate(display="$skill", command="$skill", description="d", source="plugin")
        body = _panel_write(c)
        assert "[dim]plugin[/dim]  " in body

    def test_panel_renders_trigger_line_when_set(self) -> None:
        c = SlashCandidate(display="$skill", command="$skill", description="d", trigger_hint="use when X")
        body = _panel_write(c)
        assert "[dim italic]use when X[/dim italic]" in body

    def test_panel_falls_back_to_emdash_when_description_empty(self) -> None:
        from hermes_cli.tui.completion_overlay import _NO_DESCRIPTION_FALLBACK
        c = SlashCandidate(display="/q", command="/q")
        body = _panel_write(c)
        assert _NO_DESCRIPTION_FALLBACK in body


# ---------------------------------------------------------------------------
# AC-DESC-M2 — em-dash fallback localised + tested
# ---------------------------------------------------------------------------

class TestACDescM2EmdashFallback:
    def test_no_description_logs_debug(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.completion_overlay"):
            c = SlashCandidate(display="/q", command="/q")
            _panel_write(c)
        assert any("/q" in r.message for r in caplog.records)

    def test_no_description_renders_friendly_text(self) -> None:
        c = SlashCandidate(display="/q", command="/q")
        body = _panel_write(c)
        assert "no description" in body

    def test_description_present_does_not_log_fallback(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="hermes_cli.tui.completion_overlay"):
            c = SlashCandidate(display="/q", command="/q", description="Queue tasks")
            _panel_write(c)
        assert not any("no description" in r.message for r in caplog.records)
