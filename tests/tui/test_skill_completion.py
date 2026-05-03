"""Tests for AC — Skill Inline Completion via $ trigger."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call, patch


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_skill(name: str, description: str = "", enabled: bool = True):
    from hermes_cli.tui.types.skill_candidate import SkillCandidate
    return SkillCandidate(
        name=name,
        description=description,
        trigger_phrases=[],
        do_not_trigger=[],
        enabled=enabled,
    )


class _FakeAutocomplete:
    """Minimal stub that mixes in _AutocompleteMixin without a real Textual app."""

    def __init__(self, skills: list, slash_commands: list | None = None):
        from hermes_cli.tui.input._autocomplete import _AutocompleteMixin
        # Inject mixin methods onto this instance's class
        for attr in dir(_AutocompleteMixin):
            if not attr.startswith("__"):
                method = getattr(_AutocompleteMixin, attr)
                if callable(method):
                    setattr(self.__class__, attr, method)

        self._skills = skills
        self._slash_commands = slash_commands or []
        self._current_trigger = None
        self._raw_candidates = []
        self._suppress_autocomplete_once = False
        self.value = ""
        self.cursor_position = 0

        # Track calls for assertion
        self._resolve_assist_calls: list = []
        self._push_to_list_calls: list = []
        self._set_overlay_mode_calls: list = []
        self._flash_hint_calls: list = []

        self.app = MagicMock()
        self.app._flash_hint.side_effect = self._record_flash

        self._overlay_visible = False

    def _record_flash(self, msg, duration=1.5):
        self._flash_hint_calls.append((msg, duration))

    def _resolve_assist(self, kind):
        self._resolve_assist_calls.append(kind)

    def _push_to_list(self, items):
        self._push_to_list_calls.append(list(items))

    def _set_overlay_mode(self, *, slash_only: bool = False):
        self._set_overlay_mode_calls.append({"slash_only": slash_only})

    def _completion_overlay_visible(self):
        return self._overlay_visible


def _make_stub(skills, **kw):
    stub = _FakeAutocomplete.__new__(_FakeAutocomplete)
    _FakeAutocomplete.__init__(stub, skills, **kw)
    return stub


# ---------------------------------------------------------------------------
# AC-1 tests
# ---------------------------------------------------------------------------

class TestDollarShowsOverlay:
    def test_dollar_shows_overlay(self):
        """_show_skill_completions('') with 2 enabled skills → OVERLAY + 2 SlashCandidates."""
        from hermes_cli.tui.input._autocomplete import _AutocompleteMixin
        from hermes_cli.tui.input._assist import AssistKind
        from hermes_cli.tui.path_search import SlashCandidate

        stub = _make_stub([
            _make_skill("review-pr"),
            _make_skill("commit-msg"),
        ])
        _AutocompleteMixin._show_skill_completions(stub, "")

        assert stub._resolve_assist_calls == [AssistKind.OVERLAY]
        assert len(stub._push_to_list_calls) == 1
        pushed = stub._push_to_list_calls[0]
        assert len(pushed) == 2
        assert all(isinstance(c, SlashCandidate) for c in pushed)

    def test_dollar_fragment_filters(self):
        """_show_skill_completions('re') → only $review-pr; display has no $ prefix."""
        from hermes_cli.tui.input._autocomplete import _AutocompleteMixin
        from hermes_cli.tui.input._assist import AssistKind
        from hermes_cli.tui.path_search import SlashCandidate

        stub = _make_stub([
            _make_skill("review-pr"),
            _make_skill("commit-msg"),
        ])
        _AutocompleteMixin._show_skill_completions(stub, "re")

        assert stub._resolve_assist_calls == [AssistKind.OVERLAY]
        pushed = stub._push_to_list_calls[0]
        assert len(pushed) == 1
        c = pushed[0]
        assert isinstance(c, SlashCandidate)
        assert c.command == "$review-pr"
        assert c.display == "review-pr"  # no $ prefix in display

    def test_dollar_no_match_resolves_none(self):
        """_show_skill_completions('xyz') → NONE + flash."""
        from hermes_cli.tui.input._autocomplete import _AutocompleteMixin
        from hermes_cli.tui.input._assist import AssistKind

        stub = _make_stub([
            _make_skill("review-pr"),
            _make_skill("commit-msg"),
        ])
        _AutocompleteMixin._show_skill_completions(stub, "xyz")

        assert stub._resolve_assist_calls == [AssistKind.NONE]
        assert stub._push_to_list_calls == []
        assert len(stub._flash_hint_calls) == 1
        msg, _ = stub._flash_hint_calls[0]
        assert msg == "Unknown skill: $xyz"

    def test_dollar_empty_no_flash(self):
        """_show_skill_completions('') with no skills → NONE without flash."""
        from hermes_cli.tui.input._autocomplete import _AutocompleteMixin
        from hermes_cli.tui.input._assist import AssistKind

        stub = _make_stub([])
        _AutocompleteMixin._show_skill_completions(stub, "")

        assert stub._resolve_assist_calls == [AssistKind.NONE]
        assert stub._flash_hint_calls == []
        assert stub._push_to_list_calls == []

    def test_dollar_disabled_skill_excluded(self):
        """Disabled skills are not shown in completions."""
        from hermes_cli.tui.input._autocomplete import _AutocompleteMixin
        from hermes_cli.tui.input._assist import AssistKind

        stub = _make_stub([
            _make_skill("review-pr", enabled=False),
            _make_skill("readme-gen", enabled=True),
        ])
        _AutocompleteMixin._show_skill_completions(stub, "re")

        assert stub._resolve_assist_calls == [AssistKind.OVERLAY]
        pushed = stub._push_to_list_calls[0]
        assert len(pushed) == 1
        assert pushed[0].command == "$readme-gen"

    def test_dollar_accept_inserts_dollar_prefix(self):
        """action_accept_autocomplete on SlashCandidate(command='$review-pr') → value '$review-pr '."""
        from hermes_cli.tui.input._autocomplete import _AutocompleteMixin
        from hermes_cli.tui.input._assist import AssistKind
        from hermes_cli.tui.completion_context import CompletionContext, CompletionTrigger
        from hermes_cli.tui.path_search import SlashCandidate
        from hermes_cli.tui.completion_list import VirtualCompletionList

        stub = _make_stub([])
        stub._overlay_visible = True
        stub._current_trigger = CompletionTrigger(CompletionContext.SKILL_INVOKE, "review-pr", 1)

        candidate = SlashCandidate(display="review-pr", command="$review-pr")
        fake_clist = MagicMock(spec=VirtualCompletionList)
        fake_clist.items = [candidate]
        fake_clist.highlighted = 0
        stub.screen = MagicMock()
        stub.screen.query_one.return_value = fake_clist

        _AutocompleteMixin.action_accept_autocomplete(stub)

        assert stub.value == "$review-pr "
        assert stub.cursor_position == len("$review-pr ")
        assert stub._resolve_assist_calls == [AssistKind.NONE]

    def test_dollar_sets_slash_only_mode(self):
        """_set_overlay_mode(slash_only=True) is called before _push_to_list."""
        from hermes_cli.tui.input._autocomplete import _AutocompleteMixin

        call_order: list[str] = []

        stub = _make_stub([_make_skill("review-pr")])

        original_set = stub._set_overlay_mode
        original_push = stub._push_to_list

        def tracked_set(**kw):
            call_order.append("set_overlay_mode")
            original_set(**kw)

        def tracked_push(items):
            call_order.append("push_to_list")
            original_push(items)

        stub._set_overlay_mode = tracked_set
        stub._push_to_list = tracked_push

        _AutocompleteMixin._show_skill_completions(stub, "")

        assert call_order.index("set_overlay_mode") < call_order.index("push_to_list")
        assert stub._set_overlay_mode_calls[0] == {"slash_only": True}

    def test_dollar_no_match_hint_dedup(self):
        """Flash hint fires only once when called twice within 2 seconds."""
        from hermes_cli.tui.input._autocomplete import _AutocompleteMixin

        stub = _make_stub([])

        # First call — hint fires
        _AutocompleteMixin._show_skill_completions(stub, "xyz")
        assert len(stub._flash_hint_calls) == 1

        # Second call within 2s with same fragment — hint suppressed
        _AutocompleteMixin._show_skill_completions(stub, "xyz")
        assert len(stub._flash_hint_calls) == 1  # still 1; dedup fired


# ---------------------------------------------------------------------------
# AC-2 tests
# ---------------------------------------------------------------------------

class TestDollarNoPicker:
    def test_dollar_no_picker_query(self):
        """_update_autocomplete with $xyz value never queries SkillPickerOverlay."""
        from hermes_cli.tui.input._autocomplete import _AutocompleteMixin
        from hermes_cli.tui.input._assist import AssistKind

        stub = _make_stub([])
        stub.value = "$xyz"
        stub.cursor_position = 4
        stub.app.query_one = MagicMock()

        from hermes_cli.tui.input._mode import InputMode
        stub._mode = InputMode.NORMAL

        _AutocompleteMixin._update_autocomplete(stub)

        # query_one must never have been called with SkillPickerOverlay
        from hermes_cli.tui.overlays.skill_picker import SkillPickerOverlay
        for c in stub.app.query_one.call_args_list:
            assert c.args[0] is not SkillPickerOverlay, \
                f"query_one called with SkillPickerOverlay: {c}"

        # routing: NONE (no matching skills), not PICKER
        assert AssistKind.PICKER not in stub._resolve_assist_calls
        assert AssistKind.NONE in stub._resolve_assist_calls
