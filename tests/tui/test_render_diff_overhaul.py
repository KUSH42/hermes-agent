from __future__ import annotations

import ast
import random
import string
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from rich.style import Style
from rich.text import Text

from hermes_cli.tui.body_renderers._grammar import SkinColors, build_path_header, diff_gutter
from hermes_cli.tui.tool_category import ToolCategory
from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind, ToolPayload
from hermes_cli.tui.widgets.renderers import CopyableRichLog


def _payload(output_raw: str) -> ToolPayload:
    return ToolPayload(
        tool_name="bash",
        category=ToolCategory.FILE,
        args={},
        input_display=None,
        output_raw=output_raw,
        line_count=0,
    )


def _cls() -> ClassificationResult:
    return ClassificationResult(ResultKind.DIFF, 0.9, {})


def _renderer(output_raw: str, *, app=None):
    from hermes_cli.tui.body_renderers.diff import DiffRenderer

    return DiffRenderer(_payload(output_raw), _cls(), app=app)


def _collapse_diff(*, hunks: int = 4, body_lines: int = 2) -> str:
    parts = ["--- a/src/foo.py", "+++ b/src/foo.py"]
    for idx in range(hunks):
        parts.append(f"@@ -{idx + 1},2 +{idx + 1},2 @@")
        for line_idx in range(body_lines):
            parts.append(f"-old {idx} {line_idx}")
            parts.append(f"+new {idx} {line_idx}")
    return "\n".join(parts) + "\n"


def _find_overlapping_spans(text: Text, snippet: str):
    start = text.plain.index(snippet)
    end = start + len(snippet)
    return [span for span in text._spans if span.start < end and span.end > start]


class TestCollapseAffordance:
    def test_no_collapse_under_thresholds(self):
        from hermes_cli.tui.body_renderers.diff import _DiffContainer, _HunkHeader

        diff = _collapse_diff(hunks=2, body_lines=2)
        widget = _renderer(diff).build_widget()
        assert isinstance(widget, _DiffContainer)
        children = list(getattr(widget, "_pending_children", ()))
        assert not any(isinstance(child, _HunkHeader) for child in children)

    def test_collapse_over_hunk_threshold(self):
        from hermes_cli.tui.body_renderers.diff import _HunkHeader

        diff = _collapse_diff(hunks=4, body_lines=1)
        widget = _renderer(diff).build_widget()
        children = list(getattr(widget, "_pending_children", ()))
        assert sum(isinstance(child, _HunkHeader) for child in children) == 3

    def test_collapse_text_path_has_expand_hint(self):
        body = "\n".join(
            [
                "--- a/foo.py",
                "+++ b/foo.py",
                "@@ -1,2 +1,2 @@",
                "-old first",
                "+new first",
                "@@ -5,7 +5,7 @@",
                " alpha",
                "-beta",
                "+beta changed",
                " gamma",
                "-delta",
                "+delta changed",
                " epsilon",
                "@@ -20,1 +20,1 @@",
                "-omega",
                "+omega changed",
                "@@ -30,1 +30,1 @@",
                "-sigma",
                "+sigma changed",
            ]
        ) + "\n"
        plain = _renderer(body).build().plain
        assert "space to expand" in plain
        assert "+7 lines" in plain

    def test_hunk_header_toggle_expand_and_collapse(self):
        from hermes_cli.tui.body_renderers.diff import _HunkHeader

        body_text = Text("  ▾ @@ -1,2 +1,2 @@\n+ changed")
        widget = _HunkHeader(1, "@@ -1,2 +1,2 @@", "@@ -1,2 +1,2 @@\n+ changed", body_text, 1)
        with patch.object(widget, "post_message") as mock_post:
            assert widget._expanded is False
            assert widget._body.display is False
            widget.action_toggle_expand()
            assert widget._expanded is True
            assert widget._body.display is True
            assert "▾" in str(widget._summary.content)
            first_calls = mock_post.call_count
            assert first_calls >= 1
            widget.action_toggle_expand()
            assert widget._expanded is False
            assert widget._body.display is False
            assert "▸" in str(widget._summary.content)
            assert mock_post.call_count == first_calls

    def test_hunk_header_copy(self):
        from hermes_cli.tui.body_renderers.diff import _HunkHeader

        raw_hunk = "@@ -1,2 +1,2 @@\n-old\n+new"
        widget = _HunkHeader(1, "@@ -1,2 +1,2 @@", raw_hunk, Text("+ new"), 2)
        mock_app = MagicMock()
        mock_app._svc_theme.copy_text_with_hint = MagicMock()
        with patch.object(type(widget), "app", new_callable=PropertyMock, return_value=mock_app):
            widget.action_copy_hunk()
        mock_app._svc_theme.copy_text_with_hint.assert_called_once_with(raw_hunk)

    def test_config_disables_collapse(self):
        from hermes_cli.tui.body_renderers.diff import _HunkHeader

        diff = _collapse_diff(hunks=10, body_lines=1)
        renderer = _renderer(diff)
        renderer._cfg_auto_collapse = False
        widget = renderer.build_widget()
        children = list(getattr(widget, "_pending_children", ()))
        assert not any(isinstance(child, _HunkHeader) for child in children)

    def test_hunk_count_reported_in_header_line_count(self):
        diff = _collapse_diff(hunks=4, body_lines=4)
        plain = _renderer(diff).build().plain
        assert "+8 lines" in plain

    def test_expanded_body_uses_diff_gutter(self):
        from hermes_cli.tui.body_renderers.diff import _build_body_text

        body_text = _build_body_text(
            "@@ -1,2 +1,2 @@",
            ["-old", "+new", " context"],
            SkinColors.default(),
        )
        for line in body_text.plain.splitlines():
            assert line.startswith(("+ ", "- ", "  "))

    def test_config_import_works(self):
        from hermes_cli.config import read_raw_config

        assert callable(read_raw_config)


class TestSkinBackgrounds:
    def test_add_line_uses_skin_add_bg(self):
        app = MagicMock()
        app.get_css_variables.return_value = {"diff-add-bg": "#abcdef"}
        app.config = {}
        result = _renderer(_collapse_diff(hunks=1, body_lines=1), app=app).build()
        spans = _find_overlapping_spans(result, "new 0 0")
        assert any(getattr(span.style, "bgcolor", None) and "#abcdef" in str(span.style.bgcolor).lower() for span in spans)

    def test_del_line_uses_skin_del_bg(self):
        app = MagicMock()
        app.get_css_variables.return_value = {"diff-del-bg": "#fedcba"}
        app.config = {}
        result = _renderer(_collapse_diff(hunks=1, body_lines=1), app=app).build()
        spans = _find_overlapping_spans(result, "old 0 0")
        assert any(getattr(span.style, "bgcolor", None) and "#fedcba" in str(span.style.bgcolor).lower() for span in spans)

    def test_no_hex_literals_in_diff_py(self):
        source = Path("/tmp/hermes-render-diff-overhaul/hermes_cli/tui/body_renderers/diff.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        banned = {0x1A3A1A, 0x3A1A1A}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant):
                if isinstance(node.value, str):
                    assert not __import__("re").fullmatch(r"#[0-9a-fA-F]{6}", node.value)
                if isinstance(node.value, int):
                    assert node.value not in banned


class TestWordDiffFidelity:
    def test_word_diff_preserves_whitespace_runs(self):
        from hermes_cli.tui.body_renderers.diff import _word_diff

        rem_t, _ = _word_diff("foo  bar", "foo bar")
        assert rem_t.plain == "foo  bar"

    def test_word_diff_preserves_tabs(self):
        from hermes_cli.tui.body_renderers.diff import _word_diff

        rem_t, _ = _word_diff("a\tb", "a b")
        assert rem_t.plain == "a\tb"

    def test_word_diff_preserves_punctuation(self):
        from hermes_cli.tui.body_renderers.diff import _word_diff

        rem_t, add_t = _word_diff("x.y", "x_y")
        assert rem_t.plain == "x.y"
        assert add_t.plain == "x_y"

    def test_word_diff_equal_chunks_plain_style(self):
        from hermes_cli.tui.body_renderers.diff import _word_diff

        rem_t, _ = _word_diff("foo bar", "foo baz")
        assert rem_t.plain == "foo bar"
        assert any(
            span.start == 4
            and span.end == 7
            and span.style == Style(bold=True, underline=True)
            for span in rem_t._spans
        )
        assert rem_t.plain[0:4] == "foo "

    def test_word_diff_roundtrip_copy(self):
        from hermes_cli.tui.body_renderers.diff import _word_diff

        random.seed(42)
        alphabet = [c for c in string.printable if c not in "\x0b\x0c\r"]
        for _ in range(50):
            removed = "".join(random.choices(alphabet, k=random.randint(5, 40)))
            added = "".join(random.choices(alphabet, k=random.randint(5, 40)))
            rem_t, add_t = _word_diff(removed, added)
            assert rem_t.plain == removed
            assert add_t.plain == added


class TestFileHeader:
    def test_file_header_has_plus_minus_counts(self):
        diff = "\n".join(
            [
                "--- a/src/foo.py",
                "+++ b/src/foo.py",
                "@@ -1,3 +1,4 @@",
                "-one",
                "-two",
                "+alpha",
                "+beta",
                "+gamma",
                " context",
            ]
        ) + "\n"
        plain = _renderer(diff).build().plain
        assert "+3" in plain
        assert "-2" in plain

    def test_file_header_uses_success_error_colors(self):
        colors = SkinColors.default()
        header = build_path_header(
            "src/foo.py",
            right_meta=Text.assemble(
                ("+3", Style(color=colors.success)),
                (" ", Style()),
                ("-2", Style(color=colors.error)),
            ),
            colors=colors,
        )
        plus_spans = _find_overlapping_spans(header, "+3")
        minus_spans = _find_overlapping_spans(header, "-2")
        assert any(colors.success.lower() in str(span.style.color).lower() for span in plus_spans)
        assert any(colors.error.lower() in str(span.style.color).lower() for span in minus_spans)

    def test_file_header_accent_glyph(self):
        colors = SkinColors.default()
        header = build_path_header("src/foo.py", right_meta="+1 -1", colors=colors)
        spans = _find_overlapping_spans(header, glyph := header.plain[0])
        assert glyph == "▸"
        assert any(colors.accent.lower() in str(span.style.color).lower() for span in spans)

    def test_multiple_files_each_get_header(self):
        diff = "\n".join(
            [
                "--- a/a.py",
                "+++ b/a.py",
                "@@ -1 +1 @@",
                "-old a",
                "+new a",
                "--- a/b.py",
                "+++ b/b.py",
                "@@ -1 +1 @@",
                "-old b",
                "+new b",
                "+extra b",
                "--- a/c.py",
                "+++ b/c.py",
                "@@ -1 +1 @@",
                "-old c",
            ]
        ) + "\n"
        plain = _renderer(diff).build().plain
        assert "a.py" in plain and "+1 -1" in plain
        assert "b.py" in plain and "+2 -1" in plain
        assert "c.py" in plain and "+0 -1" in plain


class TestGutter:
    def test_gutter_width_always_two(self):
        diff = "\n".join(
            [
                "--- a/foo.py",
                "+++ b/foo.py",
                "@@ -1,3 +1,3 @@",
                " context",
                "-old",
                "+new",
            ]
        ) + "\n"
        lines = _renderer(diff).build().plain.splitlines()
        diff_lines = [line for line in lines if line.startswith(("+ ", "- ", "  "))]
        assert diff_lines
        assert all(line[:2] in {"+ ", "- ", "  "} for line in diff_lines)

    def test_context_line_has_gutter(self):
        diff = "\n".join(
            [
                "--- a/foo.py",
                "+++ b/foo.py",
                "@@ -1 +1 @@",
                " context",
            ]
        ) + "\n"
        lines = _renderer(diff).build().plain.splitlines()
        assert any(line.startswith("  context") for line in lines)

    def test_gutter_is_not_copyable(self):
        colors = SkinColors.default()
        line_text = diff_gutter("+", colors=colors)
        line_text.append("hello")
        filtered = CopyableRichLog._filter_non_copyable(line_text)
        assert not filtered.startswith("+ ")
        assert filtered == "hello"

    def test_gutter_add_uses_success_color(self):
        colors = SkinColors.default()
        gutter = diff_gutter("+", colors=colors)
        assert colors.success.lower() in str(gutter._spans[0].style.color).lower()

    def test_gutter_del_uses_error_color(self):
        colors = SkinColors.default()
        gutter = diff_gutter("-", colors=colors)
        assert colors.error.lower() in str(gutter._spans[0].style.color).lower()
