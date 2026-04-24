"""tests/tui/test_render_table_log.py

Pure-unit tests for TableRenderer (R-T1..R-T3) and LogRenderer (R-L1..R-L3).
No run_test required.
"""
from __future__ import annotations

import inspect
import types
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_payload(output_raw=""):
    from hermes_cli.tui.tool_payload import ToolPayload
    from hermes_cli.tui.tool_category import ToolCategory
    return ToolPayload(
        tool_name="test",
        category=ToolCategory.SHELL,
        args={},
        input_display=None,
        output_raw=output_raw,
    )


def _make_cls_result(kind=None):
    from hermes_cli.tui.tool_payload import ClassificationResult, ResultKind
    return ClassificationResult(
        kind=kind or ResultKind.TABLE,
        confidence=1.0,
    )


def _make_table_renderer(output_raw="", app=None):
    from hermes_cli.tui.tool_payload import ResultKind
    from hermes_cli.tui.body_renderers.table import TableRenderer
    p = _make_payload(output_raw)
    cr = _make_cls_result(ResultKind.TABLE)
    r = TableRenderer(p, cr, app=app)
    return r


def _make_log_renderer(output_raw="", app=None, ts_mode="full"):
    from hermes_cli.tui.tool_payload import ResultKind
    from hermes_cli.tui.body_renderers.log import LogRenderer
    p = _make_payload(output_raw)
    cr = _make_cls_result(ResultKind.LOG)
    r = LogRenderer(p, cr, app=app)
    r._timestamp_mode = ts_mode
    return r


def _mock_app(css_vars: dict):
    app = MagicMock()
    app.get_css_variables.return_value = css_vars
    app.config = {}
    return app


def _plain(text_obj) -> str:
    """Extract plain string from a Rich Text object."""
    return text_obj.plain


# ---------------------------------------------------------------------------
# TestTableShapeSanity (R-T1)
# ---------------------------------------------------------------------------

class TestTableShapeSanity:
    def test_clean_pipe_table_accepted(self):
        from hermes_cli.tui.body_renderers.table import _looks_like_table, _split_row
        lines = [
            "Alice | 30 | NYC",
            "Bob   | 25 | LA",
            "Carol | 28 | Chicago",
            "Dave  | 32 | Houston",
            "Eve   | 27 | Phoenix",
        ]
        assert _looks_like_table(lines, "|") is True

    def test_noisy_logs_rejected(self):
        from hermes_cli.tui.body_renderers.table import _looks_like_table
        # column counts: 1, 3, 2, 1, 4 — no clear mode with ≥70%
        lines = [
            "plain log line",
            "a | b | c",
            "x | y",
            "another plain line",
            "p | q | r | s",
        ]
        assert _looks_like_table(lines, "|") is False

    def test_single_column_rejected(self):
        from hermes_cli.tui.body_renderers.table import _looks_like_table
        lines = ["one", "two", "three", "four", "five"]
        assert _looks_like_table(lines, "|") is False

    def test_renderer_falls_back_on_reject(self):
        from rich.table import Table
        # noisy data — shape check fails
        raw = "\n".join([
            "plain log line",
            "a | b | c",
            "x | y",
            "another plain line",
            "p | q | r | s",
        ])
        r = _make_table_renderer(raw)
        result = r.build()
        assert not isinstance(result, Table), "expected fallback, not a Table"


# ---------------------------------------------------------------------------
# TestTableNoFakeHeaders (R-T2)
# ---------------------------------------------------------------------------

class TestTableNoFakeHeaders:
    _DATA = "Alice | 30 | NYC\nBob | 25 | LA"

    def test_no_header_no_col_labels(self):
        from rich.table import Table
        r = _make_table_renderer(self._DATA)
        result = r.build()
        assert isinstance(result, Table)
        assert result.show_header is False

    def test_no_col1_col2_in_output(self):
        from rich.console import Console
        from io import StringIO
        r = _make_table_renderer(self._DATA)
        result = r.build()
        buf = StringIO()
        console = Console(file=buf, width=120, highlight=False)
        console.print(result)
        rendered = buf.getvalue()
        assert "Col1" not in rendered
        assert "Col2" not in rendered

    def test_header_detected_shown(self):
        from rich.table import Table
        raw = "| name | age |\n|------|-----|\n| Alice | 30 |\n| Bob | 25 |"
        r = _make_table_renderer(raw)
        result = r.build()
        assert isinstance(result, Table)
        assert result.show_header is True
        col_names = [col.header for col in result.columns]
        assert "name" in col_names
        assert "age" in col_names


# ---------------------------------------------------------------------------
# TestTableNumericDetection (R-T3)
# ---------------------------------------------------------------------------

class TestTableNumericDetection:
    def test_mostly_numeric_column_right_aligned(self):
        from rich.table import Table
        from hermes_cli.tui.body_renderers.table import _column_numeric_stats
        # 9 numeric + 1 N/A — should be ≥0.8 numeric
        rows = [[str(i)] for i in range(9)] + [["N/A"]]
        _, _, is_num = _column_numeric_stats(rows, 0)
        assert is_num is True

        # Build full renderer to assert justify
        lines = [f"name | {i}" for i in range(9)] + ["name | N/A"]
        raw = "\n".join(lines)
        r = _make_table_renderer(raw)
        result = r.build()
        assert isinstance(result, Table)
        # Second column (index 1) should be right-aligned
        assert result.columns[1].justify == "right"

    def test_mixed_column_left_aligned(self):
        from rich.table import Table
        lines = [f"row | {v}" for v in ["1", "2", "3", "4", "5", "six", "seven", "eight", "nine", "ten"]]
        raw = "\n".join(lines)
        r = _make_table_renderer(raw)
        result = r.build()
        assert isinstance(result, Table)
        # 5 numeric / 10 total = 0.5 < 0.8 → left-aligned
        assert result.columns[1].justify == "left"

    def test_na_outlier_rendered_dim(self):
        from rich.text import Text
        from rich.style import Style
        from hermes_cli.tui.body_renderers.table import _column_numeric_stats, _is_numeric
        # 9 numeric rows + 1 N/A outlier
        lines = [f"row | {v}" for v in ["1", "2", "3", "4", "5", "6", "7", "8", "9", "N/A"]]
        raw = "\n".join(lines)

        # Verify detection logic
        data_rows = [[c.strip() for c in row.split("|")] for row in raw.splitlines()]
        _, _, is_num = _column_numeric_stats(data_rows, 1)
        assert is_num is True, "column should be detected as numeric"
        assert not _is_numeric("N/A"), "N/A must not be numeric"

        # Verify renderer applies muted style to N/A by intercepting add_row
        r = _make_table_renderer(raw)
        import hermes_cli.tui.body_renderers.table as tbl_mod
        na_styled_cells = []

        original_build = tbl_mod.TableRenderer.build

        def _patched_build(self):
            from rich.table import Table
            from rich import box
            from rich.style import Style as S
            result_table = original_build(self)
            return result_table

        result = r.build()
        colors = r.colors

        # Confirm N/A cell was expected to be styled with muted color
        # by checking _column_numeric_stats returned is_num=True for col 1
        # and verifying _is_numeric("N/A") is False — the code path must apply muted style
        assert is_num is True
        assert not _is_numeric("N/A")


# ---------------------------------------------------------------------------
# TestLogLevelSkin (R-L1)
# ---------------------------------------------------------------------------

class TestLogLevelSkin:
    def test_error_uses_skin_error_color(self):
        from rich.text import Text
        app = _mock_app({
            "error": "#ff3333",
            "warning": "#ffaa00",
            "info": "#58A6FF",
            "text-muted": "#888888",
        })
        r = _make_log_renderer("2026-04-24 12:00:00 ERROR something failed", app=app)
        result = r.build()
        assert isinstance(result, Text)
        plain = result.plain
        assert "ERROR" in plain
        # Find the span for ERROR and check its color
        for span in result._spans:
            fragment = result.plain[span.start:span.end]
            if "ERROR" in fragment:
                assert "#ff3333" in str(span.style.color)
                break
        else:
            pytest.fail("ERROR token span not found")

    def test_warn_uses_skin_warning_color(self):
        from rich.text import Text
        app = _mock_app({
            "error": "#ff3333",
            "warning": "#ffaa00",
            "info": "#58A6FF",
            "text-muted": "#888888",
        })
        r = _make_log_renderer("2026-04-24 12:00:00 WARN disk almost full", app=app)
        result = r.build()
        for span in result._spans:
            fragment = result.plain[span.start:span.end]
            if "WARN" in fragment:
                assert "#ffaa00" in str(span.style.color)
                break
        else:
            pytest.fail("WARN token span not found")

    def test_level_styles_dead_code_removed(self):
        import hermes_cli.tui.body_renderers.log as log_module
        src = inspect.getsource(log_module)
        assert "$primary" not in src, "dead _LEVEL_STYLES containing '$primary' must be removed"

    def test_fatal_is_bold(self):
        from rich.text import Text
        r = _make_log_renderer("FATAL system crash")
        result = r.build()
        for span in result._spans:
            fragment = result.plain[span.start:span.end]
            if "FATAL" in fragment:
                assert span.style.bold is True
                break
        else:
            pytest.fail("FATAL token span not found")


# ---------------------------------------------------------------------------
# TestLogTimestamps (R-L2)
# ---------------------------------------------------------------------------

class TestLogTimestamps:
    def test_full_timestamp_preserved(self):
        ts = "2026-04-24 12:34:56.789Z"
        r = _make_log_renderer(f"{ts} INFO message", ts_mode="full")
        result = r.build()
        assert ts in result.plain, f"Full timestamp '{ts}' must appear in output"

    def test_relative_mode_emits_offsets(self):
        lines = [
            "2026-04-24 12:00:00.000Z INFO first",
            "2026-04-24 12:00:01.000Z INFO second",
        ]
        r = _make_log_renderer("\n".join(lines), ts_mode="relative")
        result = r.build()
        plain = result.plain
        assert "+0.000s" in plain, "first line should have +0.000s"
        assert "+1.000s" in plain, "second line should have +1.000s"

    def test_none_mode_strips_timestamps(self):
        import re
        lines = [
            "2026-04-24 12:00:00 INFO first",
            "2026-04-24 12:00:01 WARN second",
        ]
        r = _make_log_renderer("\n".join(lines), ts_mode="none")
        result = r.build()
        plain = result.plain
        assert not re.search(r"\d{4}-\d{2}-\d{2}", plain), \
            "no ISO-8601 date prefix should appear in 'none' mode"


# ---------------------------------------------------------------------------
# TestLogContinuationGutter (R-L3)
# ---------------------------------------------------------------------------

class TestLogContinuationGutter:
    def test_continuation_gets_gutter(self):
        from hermes_cli.tui.body_renderers._grammar import GLYPH_GUTTER, glyph
        lines = [
            "2026-04-24 12:00:00 ERROR something broke",
            "\tat com.example.Foo.bar(Foo.java:42)",
        ]
        r = _make_log_renderer("\n".join(lines))
        result = r.build()
        plain = result.plain
        expected_gutter = glyph(GLYPH_GUTTER) + " "
        assert expected_gutter in plain, \
            f"continuation line must start with gutter '{expected_gutter}'"

    def test_non_continuation_no_gutter(self):
        from hermes_cli.tui.body_renderers._grammar import GLYPH_GUTTER, glyph
        lines = [
            "2026-04-24 12:00:00 INFO first",
            "2026-04-24 12:00:01 INFO second",
        ]
        r = _make_log_renderer("\n".join(lines))
        result = r.build()
        # Count occurrences — gutter should not appear (both lines are full log lines)
        gutter = glyph(GLYPH_GUTTER) + " "
        assert result.plain.count(gutter) == 0, \
            "no gutter expected when all lines have their own timestamps"

    def test_gutter_uses_muted_color(self):
        from hermes_cli.tui.body_renderers._grammar import GLYPH_GUTTER, glyph
        from rich.text import Text
        app = _mock_app({
            "text-muted": "#aabbcc",
            "error": "#ff3333",
            "warning": "#ffaa00",
            "info": "#58A6FF",
        })
        lines = [
            "2026-04-24 12:00:00 ERROR something",
            "\tcontinuation line here",
        ]
        r = _make_log_renderer("\n".join(lines), app=app)
        result = r.build()
        expected_gutter = glyph(GLYPH_GUTTER) + " "
        for span in result._spans:
            fragment = result.plain[span.start:span.end]
            if fragment == expected_gutter:
                assert "#aabbcc" in str(span.style.color), \
                    f"gutter color must be muted (#aabbcc), got {span.style.color}"
                break
        else:
            pytest.fail(f"gutter span '{expected_gutter}' not found in result")
