"""Tests for SUBC-DESC-H1/H2/M1 — subcommand description preview plumbing."""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

from contextlib import contextmanager


@contextmanager
def _make_registry_with(*cmds):
    """Patch COMMAND_REGISTRY, rebuild derived dicts, then restore."""
    import hermes_cli.commands as cmd_mod
    original = list(cmd_mod.COMMAND_REGISTRY)
    cmd_mod.COMMAND_REGISTRY.clear()
    cmd_mod.COMMAND_REGISTRY.extend(cmds)
    cmd_mod.rebuild_lookups()
    try:
        yield cmd_mod
    finally:
        cmd_mod.COMMAND_REGISTRY.clear()
        cmd_mod.COMMAND_REGISTRY.extend(original)
        cmd_mod.rebuild_lookups()


# ---------------------------------------------------------------------------
# TestSUBCDescH1RegistryNormalization
# ---------------------------------------------------------------------------

class TestSUBCDescH1RegistryNormalization:

    def test_normalize_string_subcommand_yields_empty_description(self):
        from hermes_cli.commands import CommandDef
        cmd = CommandDef("testcmd", "desc", "Test", subcommands=("on",))
        with _make_registry_with(cmd) as mod:
            assert mod.SUBCOMMANDS.get("/testcmd") == ["on"]
            assert mod.SUBCOMMAND_DESCRIPTIONS.get("/testcmd", {}) == {}

    def test_normalize_tuple_subcommand_yields_description(self):
        from hermes_cli.commands import CommandDef
        cmd = CommandDef("testcmd", "desc", "Test", subcommands=(("on", "Enable"),))
        with _make_registry_with(cmd) as mod:
            assert mod.SUBCOMMANDS.get("/testcmd") == ["on"]
            assert mod.SUBCOMMAND_DESCRIPTIONS.get("/testcmd") == {"on": "Enable"}

    def test_normalize_mixed_form_supports_partial_descriptions(self):
        from hermes_cli.commands import CommandDef
        cmd = CommandDef(
            "testcmd", "desc", "Test",
            subcommands=(("on", "Enable"), "off"),
        )
        with _make_registry_with(cmd) as mod:
            assert mod.SUBCOMMANDS.get("/testcmd") == ["on", "off"]
            assert mod.SUBCOMMAND_DESCRIPTIONS.get("/testcmd") == {"on": "Enable"}

    def test_args_hint_derived_subcommands_have_no_descriptions(self):
        from hermes_cli.commands import CommandDef
        cmd = CommandDef("testcmd", "desc", "Test", args_hint="[a|b|c]")
        with _make_registry_with(cmd) as mod:
            assert mod.SUBCOMMANDS.get("/testcmd") == ["a", "b", "c"]
            assert "/testcmd" not in mod.SUBCOMMAND_DESCRIPTIONS

    def test_existing_string_only_registry_entries_unchanged(self):
        """Real registry string-only entries produce empty inner dicts (no AttributeError)."""
        from hermes_cli.commands import SUBCOMMANDS, SUBCOMMAND_DESCRIPTIONS

        # Commands using only string subcommands (footer, voice, busy, etc.) must not
        # appear in SUBCOMMAND_DESCRIPTIONS at all — their SUBCOMMANDS entries are still valid.
        for key in ("/footer", "/voice", "/busy", "/reasoning", "/fast", "/indicator", "/browser"):
            if key in SUBCOMMANDS:
                assert SUBCOMMAND_DESCRIPTIONS.get(key, {}) == {}, (
                    f"{key} should have no subcommand descriptions but has some"
                )


# ---------------------------------------------------------------------------
# TestSUBCDescH2CompletionPlumbing
# ---------------------------------------------------------------------------

class _FakeInput:
    """Minimal shim standing in for HermesInput (no Textual dependency)."""

    def __init__(self, subcommands=None, sub_descs=None):
        if subcommands is not None:
            self._slash_subcommands = subcommands
        if sub_descs is not None:
            self._slash_subcommand_descriptions = sub_descs
        self._pushed: list = []
        self._overlay_mode: dict = {}
        self._assist_kind = None

    def _set_overlay_mode(self, **kwargs):
        self._overlay_mode = kwargs

    def _push_to_list(self, candidates):
        self._pushed = candidates

    @property
    def app(self):
        return types.SimpleNamespace(feedback=MagicMock())


class TestSUBCDescH2CompletionPlumbing:

    def _call_show(self, inp, command, fragment=""):
        """Invoke _show_subcommand_completions on the mixin directly."""
        from hermes_cli.tui.input._history import _HistoryMixin

        apply_calls = []

        def fake_apply(self_arg, kind, suggestion=""):
            apply_calls.append(kind)

        with patch("hermes_cli.tui.input._history._apply_assist", fake_apply):
            _HistoryMixin._show_subcommand_completions(inp, command, fragment)

        return apply_calls

    def test_subcandidate_carries_description_when_present(self):
        inp = _FakeInput(
            subcommands={"/anim": ["preset", "list"]},
            sub_descs={"/anim": {"preset": "Apply preset"}},
        )
        self._call_show(inp, "anim", "")
        assert len(inp._pushed) == 2
        preset_cand = next(c for c in inp._pushed if c.display == "preset")
        assert preset_cand.description == "Apply preset"

    def test_subcandidate_empty_description_when_dict_missing_entry(self):
        inp = _FakeInput(
            subcommands={"/anim": ["list"]},
            sub_descs={"/anim": {}},
        )
        self._call_show(inp, "anim", "")
        assert len(inp._pushed) == 1
        assert inp._pushed[0].description == ""

    def test_subcandidate_filters_by_fragment_preserves_description(self):
        inp = _FakeInput(
            subcommands={"/anim": ["preset", "ambient"]},
            sub_descs={"/anim": {"preset": "Apply preset", "ambient": "Toggle ambient"}},
        )
        self._call_show(inp, "anim", "pr")
        assert len(inp._pushed) == 1
        assert inp._pushed[0].display == "preset"
        assert inp._pushed[0].description == "Apply preset"

    def test_set_slash_subcommand_descriptions_attribute_initialised(self):
        inp = _FakeInput()
        from hermes_cli.tui.input._history import _HistoryMixin
        data = {"/anim": {"preset": "Apply preset"}}
        _HistoryMixin.set_slash_subcommand_descriptions(inp, data)
        assert inp._slash_subcommand_descriptions is data

    def test_show_subcommand_completions_no_attr_uses_empty_dict(self):
        """Missing _slash_subcommand_descriptions must not raise AttributeError."""
        inp = _FakeInput(subcommands={"/anim": ["preset"]})
        # intentionally do NOT set _slash_subcommand_descriptions
        assert not hasattr(inp, "_slash_subcommand_descriptions")
        self._call_show(inp, "anim", "")
        assert len(inp._pushed) == 1
        assert inp._pushed[0].description == ""


# ---------------------------------------------------------------------------
# TestSUBCDescM1AuthoredDescriptions
# ---------------------------------------------------------------------------

class TestSUBCDescM1AuthoredDescriptions:

    def test_anim_preset_has_description(self):
        from hermes_cli.commands import SUBCOMMAND_DESCRIPTIONS
        desc = SUBCOMMAND_DESCRIPTIONS.get("/anim", {}).get("preset", "")
        assert desc, "/anim preset must have a non-empty description"

    def test_skills_inspect_has_description(self):
        from hermes_cli.commands import SUBCOMMAND_DESCRIPTIONS
        desc = SUBCOMMAND_DESCRIPTIONS.get("/skills", {}).get("inspect", "")
        assert desc, "/skills inspect must have a non-empty description"

    def test_kanban_dispatch_has_description(self):
        from hermes_cli.commands import SUBCOMMAND_DESCRIPTIONS
        desc = SUBCOMMAND_DESCRIPTIONS.get("/kanban", {}).get("dispatch", "")
        assert desc, "/kanban dispatch must have a non-empty description"

    def test_self_evident_groups_remain_undocumented(self):
        """Regression guard: on/off/status groups must not gain description noise."""
        from hermes_cli.commands import SUBCOMMAND_DESCRIPTIONS
        for cmd in ("/footer", "/voice", "/busy", "/reasoning", "/fast", "/indicator", "/browser"):
            assert SUBCOMMAND_DESCRIPTIONS.get(cmd, {}) == {}, (
                f"{cmd} should have no per-subcommand descriptions"
            )
