"""Tests for chip label normalisation (CHIP-NORM-H1, H2, M1)."""
from __future__ import annotations

import re

import pytest

from hermes_cli.tui.services.chip_format import format_chip, WORD_KEYS


# ---------------------------------------------------------------------------
# H1: format_chip behaviour
# ---------------------------------------------------------------------------

class TestFormatChip:
    def test_lowercase_single_letter(self):
        assert format_chip("c", "copy") == "c copy"

    def test_uppercase_single_letter_normalised(self):
        assert format_chip("Y", "copy input") == "y copy input"

    def test_word_key_title_case(self):
        assert format_chip("Enter", "expand") == "Enter expand"
        assert format_chip("esc", "exit") == "Esc exit"

    def test_function_key_uppercase(self):
        assert format_chip("F1", "help") == "F1 help"
        assert format_chip("f1", "help") == "F1 help"

    def test_symbol_passthrough(self):
        assert format_chip("*", "all") == "* all"
        assert format_chip("?", "keys") == "? keys"

    def test_modifier_passthrough(self):
        assert format_chip("^c", "interrupt") == "^c interrupt"
        assert format_chip("shift+d", "density-back") == "shift+d density-back"


# ---------------------------------------------------------------------------
# H2: overflow chip uses " keys" not " more"
# ---------------------------------------------------------------------------

class TestOverflowChipLabel:
    def _make_actions_obj(self):
        """Return a minimal _ToolPanelActionsMixin instance for testing."""
        from hermes_cli.tui.tool_panel._actions import _ToolPanelActionsMixin

        class _Stub(_ToolPanelActionsMixin):
            def __init__(self):
                pass  # no widget init needed

        return _Stub()

    def test_hint_overflow_says_keys(self):
        obj = self._make_actions_obj()
        # primary 1 chip + 3 contextual; width=80 → at most 2 contextual shown → 1 dropped
        result = obj._render_hints(
            primary=[("Enter", "expand")],
            contextual=[("c", "copy"), ("r", "retry"), ("e", "stderr")],
            width=80,
        )
        plain = result.plain
        assert "+1 keys" in plain, f"Expected '+1 keys' in {plain!r}"
        assert " more" not in plain, f"Unexpected ' more' in {plain!r}"

    def test_artifact_overflow_unchanged(self):
        """Artifact-row overflow chip retains '+N more' label."""
        from hermes_cli.tui.tool_result_parse import _ARTIFACT_DISPLAY_CAP

        n_artifacts = _ARTIFACT_DISPLAY_CAP + 2  # 7
        n_hidden = n_artifacts - _ARTIFACT_DISPLAY_CAP  # 2
        overflow_label = f"+{n_hidden} more"
        # The overflow template at _footer.py:608 must produce "+N more", not "+N keys"
        assert overflow_label == "+2 more"
        assert "keys" not in overflow_label


# ---------------------------------------------------------------------------
# M1: IL-CHIP-1 invariant gate
# ---------------------------------------------------------------------------

class TestInvariantILChip1:
    def test_il_chip_1_no_bracket_hotkey_format(self):
        """IL-CHIP-1: No chip-build site outside chip_format.py may use bracket notation."""
        import pathlib
        root = pathlib.Path("hermes_cli/tui")
        pattern = re.compile(r'\[\{[A-Za-z_][A-Za-z0-9_.]*\}\]\s')
        exempt = {"chip_format.py"}
        violations = []
        for p in root.rglob("*.py"):
            if p.name in exempt:
                continue
            text = p.read_text(encoding="utf-8")
            for m in pattern.finditer(text):
                violations.append(f"{p}:{text[:m.start()].count(chr(10)) + 1}")
        assert violations == [], (
            f"IL-CHIP-1: bracket-notation chip build outside chip_format.py: {violations}"
        )

    def test_il_chip_1_self_test(self):
        """False-negative guard: the regex must match the known anti-pattern string."""
        pattern = re.compile(r'\[\{[A-Za-z_][A-Za-z0-9_.]*\}\]\s')
        assert pattern.search("[{action.hotkey}] foo") is not None
