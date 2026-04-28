"""GV-1..GV-4 — glyph vocabulary cleanup tests."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent.parent
TUI = REPO / "hermes_cli" / "tui"


# ---------------------------------------------------------------------------
# TestGrammarConstants — GV-1
# ---------------------------------------------------------------------------


class TestGrammarConstants:
    def test_grammar_exports_gutter_focused(self):
        from hermes_cli.tui.body_renderers._grammar import GLYPH_GUTTER_FOCUSED
        assert GLYPH_GUTTER_FOCUSED == "┃"

    def test_grammar_exports_gutter_group(self):
        from hermes_cli.tui.body_renderers._grammar import GLYPH_GUTTER_GROUP
        assert GLYPH_GUTTER_GROUP == "┊"

    def test_grammar_exports_chip_brackets(self):
        from hermes_cli.tui.body_renderers._grammar import GLYPH_CHIP_OPEN, GLYPH_CHIP_CLOSE
        assert GLYPH_CHIP_OPEN == "["
        assert GLYPH_CHIP_CLOSE == "]"


# ---------------------------------------------------------------------------
# TestGutterMigration — GV-2
# ---------------------------------------------------------------------------


class TestGutterMigration:
    def _grep_code_lines(self, path: Path, pattern: str) -> list[str]:
        """Return non-comment, non-docstring lines matching pattern."""
        result = subprocess.run(
            ["grep", "-n", pattern, str(path)],
            capture_output=True, text=True,
        )
        hits = []
        for line in result.stdout.splitlines():
            if not line:
                continue
            # strip line number prefix to get actual content
            content = line.split(":", 2)[-1] if ":" in line else line
            stripped = content.lstrip()
            # skip docstrings and comments
            if stripped.startswith("#") or '"""' in stripped or "'''" in stripped:
                continue
            hits.append(line)
        return hits

    def test_header_focused_gutter_uses_grammar_glyph(self):
        header = TUI / "tool_blocks" / "_header.py"
        hits = self._grep_code_lines(header, "┃")
        assert hits == [], f"Literal ┃ still present in _header.py: {hits}"

    def test_header_child_diff_gutter_uses_grammar_glyph(self):
        header = TUI / "tool_blocks" / "_header.py"
        hits = self._grep_code_lines(header, "╰─")
        assert hits == [], f"Literal ╰─ still present in _header.py: {hits}"

    def test_group_header_gutter_uses_grammar_glyph(self):
        tool_group = TUI / "tool_group.py"
        hits = self._grep_code_lines(tool_group, "┊")
        assert hits == [], f"Literal ┊ still present in tool_group.py: {hits}"


# ---------------------------------------------------------------------------
# TestSeparatorMigration — GV-3
# ---------------------------------------------------------------------------


class TestSeparatorMigration:
    def _grep_literal_sep(self, path: Path) -> list[str]:
        result = subprocess.run(
            ["grep", "-n", " · ", str(path)],
            capture_output=True, text=True,
        )
        # exclude docstring / comment occurrences
        lines = [
            l for l in result.stdout.splitlines()
            if l and '"""' not in l and "#" not in l.split(":")[1][:4]
        ]
        return lines

    def test_microcopy_uses_grammar_separator(self):
        microcopy = TUI / "streaming_microcopy.py"
        hits = self._grep_literal_sep(microcopy)
        assert hits == [], f"Literal ' · ' still in streaming_microcopy.py: {hits}"

    def test_microcopy_renders_separator_via_glyph(self):
        from unittest.mock import MagicMock
        from hermes_cli.tui.streaming_microcopy import StreamingState, microcopy_line
        spec = MagicMock()
        from hermes_cli.tui.tool_category import ToolCategory
        spec.category = ToolCategory.SHELL
        spec.primary_result = "lines"
        state = StreamingState(lines_received=10, bytes_received=1024, elapsed_s=0.5)
        result = microcopy_line(spec, state)
        from rich.text import Text
        assert isinstance(result, Text)
        # The separator glyph (·) should appear between "lines" and the size
        plain = result.plain
        assert "·" in plain or "-" in plain  # ASCII fallback is "-"

    def test_no_literal_dot_separator_in_tool_widget_code(self):
        """Meta: the three migrated chip surfaces no longer contain literal ' · ' in code lines."""
        # Only check the surfaces explicitly migrated by this spec (GV-3 + GV-4).
        # Other files in tool_blocks/tool_panel may still use ' · ' legitimately.
        migrated_files = [
            TUI / "tool_panel" / "_actions.py",
            TUI / "tool_panel" / "_completion.py",
            TUI / "tool_panel" / "_footer.py",
            TUI / "streaming_microcopy.py",
        ]
        offenders: list[str] = []
        for pyfile in migrated_files:
            result = subprocess.run(
                ["grep", "-n", " · ", str(pyfile)],
                capture_output=True, text=True,
            )
            for line in result.stdout.splitlines():
                if not line:
                    continue
                content = line.split(":", 2)[-1] if ":" in line else line
                stripped = content.lstrip()
                # skip docstrings and comments
                if stripped.startswith("#") or '"""' in stripped or "'''" in stripped:
                    continue
                offenders.append(f"{pyfile.name}:{line}")
        assert offenders == [], f"Literal ' · ' found in migrated files:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# TestChipHelper — GV-4
# ---------------------------------------------------------------------------


class TestChipHelper:
    def test_chip_bracketed_format(self):
        from hermes_cli.tui.body_renderers._grammar import chip
        result = chip("y", "copy", bracketed=True)
        assert result.plain == "[y] copy"

    def test_chip_unbracketed_format(self):
        from hermes_cli.tui.body_renderers._grammar import chip
        result = chip("y", "copy", bracketed=False)
        assert result.plain == "y copy"

    def test_chip_uses_dim_bracket_style(self):
        from hermes_cli.tui.body_renderers._grammar import chip
        result = chip("y", "copy", bracketed=True)
        # First span is "[" — should have "dim" in its style
        spans = result._spans
        assert len(spans) >= 1
        bracket_span = spans[0]
        style_str = str(bracket_span.style)
        assert "dim" in style_str, f"Expected dim on bracket span, got: {style_str!r}"
