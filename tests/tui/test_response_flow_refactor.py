"""Tests for response_flow.py refactor: _LineClassifier, _init_fields, dispatch methods.

Tests: R01-R15 (_LineClassifier), D01-D04 (_init_fields / deduplication),
       P01-P06 (process_line dispatch smoke tests).
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeLog:
    def __init__(self):
        self.written: list[str] = []
        self._plain_lines: list[str] = []

    def write_with_source(self, rich_text, plain):
        self.written.append(plain)

    def write(self, renderable, **kw):
        pass

    def __getattr__(self, name):
        return None


def _make_engine():
    """Build a ResponseFlowEngine with no Textual deps via _init_fields()."""
    from hermes_cli.tui.response_flow import ResponseFlowEngine

    eng = object.__new__(ResponseFlowEngine)
    eng._init_fields()
    log = _FakeLog()
    eng._prose_log = log
    eng._panel = None
    eng._skin_vars = {}
    eng._pygments_theme = "monokai"
    return eng, log


# ---------------------------------------------------------------------------
# R01-R15: _LineClassifier
# ---------------------------------------------------------------------------


def test_R01_is_footnote_def_match():
    from hermes_cli.tui.response_flow import _LineClassifier
    clf = _LineClassifier()
    result = clf.is_footnote_def("[^1]: some text")
    assert result == ("1", "some text")


def test_R02_is_footnote_def_no_match():
    from hermes_cli.tui.response_flow import _LineClassifier
    clf = _LineClassifier()
    assert clf.is_footnote_def("just prose") is None


def test_R03_is_footnote_continuation_true():
    from hermes_cli.tui.response_flow import _LineClassifier
    clf = _LineClassifier()
    assert clf.is_footnote_continuation("    continued text", footnote_open=True) is True


def test_R04_is_footnote_continuation_false_when_closed():
    from hermes_cli.tui.response_flow import _LineClassifier
    clf = _LineClassifier()
    assert clf.is_footnote_continuation("    indented", footnote_open=False) is False


def test_R05_is_citation_match():
    from hermes_cli.tui.response_flow import _LineClassifier
    clf = _LineClassifier()
    result = clf.is_citation("[CITE:1 My Title — https://example.com]")
    assert result == (1, "My Title", "https://example.com")


def test_R06_is_citation_no_match():
    from hermes_cli.tui.response_flow import _LineClassifier
    clf = _LineClassifier()
    assert clf.is_citation("just a line") is None


def test_R07_is_fence_open_backtick_with_lang():
    from hermes_cli.tui.response_flow import _LineClassifier
    clf = _LineClassifier()
    result = clf.is_fence_open("```python")
    assert result == ("python", "`", 3)


def test_R08_is_fence_open_tilde_no_lang():
    from hermes_cli.tui.response_flow import _LineClassifier
    clf = _LineClassifier()
    result = clf.is_fence_open("~~~")
    assert result == ("", "~", 3)


def test_R09_is_fence_open_prose_line():
    from hermes_cli.tui.response_flow import _LineClassifier
    clf = _LineClassifier()
    assert clf.is_fence_open("this is prose") is None


def test_R10_is_fence_close_matching():
    from hermes_cli.tui.response_flow import _LineClassifier
    clf = _LineClassifier()
    assert clf.is_fence_close("```", fence_char="`", fence_depth=3) is True


def test_R11_is_fence_close_wrong_char():
    from hermes_cli.tui.response_flow import _LineClassifier
    clf = _LineClassifier()
    assert clf.is_fence_close("~~~", fence_char="`", fence_depth=3) is False


def test_R12_is_block_math_oneline_double_dollar():
    from hermes_cli.tui.response_flow import _LineClassifier
    clf = _LineClassifier()
    result = clf.is_block_math_oneline("$$E=mc^2$$")
    assert result == "E=mc^2"


def test_R13_is_block_math_oneline_bracket():
    from hermes_cli.tui.response_flow import _LineClassifier
    clf = _LineClassifier()
    result = clf.is_block_math_oneline(r"\[E=mc^2\]")
    assert result == "E=mc^2"


def test_R14_is_block_math_oneline_prose():
    from hermes_cli.tui.response_flow import _LineClassifier
    clf = _LineClassifier()
    assert clf.is_block_math_oneline("just prose") is None


def test_R15_is_indented_code():
    from hermes_cli.tui.response_flow import _LineClassifier
    clf = _LineClassifier()
    result = clf.is_indented_code("    x = 1")
    assert result == "x = 1"


# ---------------------------------------------------------------------------
# D01-D04: _init_fields / ReasoningFlowEngine deduplication
# ---------------------------------------------------------------------------


def test_D01_init_fields_sets_required_attrs():
    from hermes_cli.tui.response_flow import ResponseFlowEngine, _LineClassifier

    eng = object.__new__(ResponseFlowEngine)
    eng._init_fields()
    assert hasattr(eng, "_block_buf")
    assert eng._state == "NORMAL"
    assert isinstance(eng._clf, _LineClassifier)
    assert isinstance(eng._code_fence_buffer, list)
    assert eng._footnote_defs == {}
    assert eng._cite_entries == {}


def test_D02_reasoning_engine_does_not_re_init_common_fields():
    from hermes_cli.tui.response_flow import ReasoningFlowEngine

    # Fields set by _init_fields that ReasoningFlowEngine must NOT reassign
    preserved_fields = {"_block_buf", "_clf", "_code_fence_buffer", "_state",
                        "_footnote_defs", "_footnote_order", "_cite_entries",
                        "_cite_order", "_emitted_media_urls", "_partial"}
    src = inspect.getsource(ReasoningFlowEngine.__init__)
    for field in preserved_fields:
        # The field name should not appear as an assignment target (lhs of `=`)
        # A simple heuristic: `self.{field} =` should not appear
        assert f"self.{field} =" not in src, (
            f"ReasoningFlowEngine.__init__ re-assigns {field} which _init_fields() already sets"
        )


def test_D03_new_field_in_init_fields_visible_on_reasoning_engine():
    """Confirm that _init_fields-set fields propagate to ReasoningFlowEngine."""
    from hermes_cli.tui.response_flow import ResponseFlowEngine

    eng = object.__new__(ResponseFlowEngine)
    eng._init_fields()
    # _clf must be available without any extra assignment
    assert hasattr(eng, "_clf")
    assert hasattr(eng, "_code_fence_buffer")


def test_D04_reasoning_engine_init_source_no_duplicate_assignments():
    """ReasoningFlowEngine.__init__ must not re-assign fields that _init_fields provides
    and that have no reasoning-specific override.  Fields with intentional overrides
    (math disabled, citations gated, emoji gated) are excluded from the check.
    """
    from hermes_cli.tui.response_flow import ReasoningFlowEngine

    # Fields that must stay at _init_fields defaults — no reasoning-specific logic needed
    must_not_override = {
        "_block_buf", "_clf", "_code_fence_buffer", "_state",
        "_fence_char", "_fence_depth", "_active_block",
        "_footnote_defs", "_footnote_order", "_footnote_def_open",
        "_cite_entries", "_cite_order",
        "_emitted_media_urls", "_emitted_emoji_anchors",
        "_partial", "_prose_callback", "_pending_source_line",
        "_pending_code_intro", "_list_cont_indent",
        "_math_lines", "_math_env", "_prose_section_counter",
    }
    reasoning_src = inspect.getsource(ReasoningFlowEngine.__init__)
    for field in must_not_override:
        assert f"self.{field} =" not in reasoning_src, (
            f"ReasoningFlowEngine.__init__ unnecessarily overrides {field}"
        )


# ---------------------------------------------------------------------------
# P01-P06: process_line dispatch smoke tests
# ---------------------------------------------------------------------------


def test_P01_footnote_def_suppressed_collected():
    eng, log = _make_engine()
    eng._citations_enabled = False
    # patch methods that touch panel
    eng._open_code_block = MagicMock(return_value=MagicMock())
    eng._flush_block_buf = lambda: None
    eng._emit_complete_code_block = MagicMock()

    eng.process_line("[^1]: my footnote text")

    assert "1" in eng._footnote_defs
    assert eng._footnote_defs["1"] == "my footnote text"
    assert log.written == []  # suppressed from prose log


def test_P02_citation_suppressed_collected():
    eng, log = _make_engine()
    eng._citations_enabled = True
    eng._flush_block_buf = lambda: None
    eng._emit_complete_code_block = MagicMock()

    eng.process_line("[CITE:2 Example Title — https://example.org]")

    assert 2 in eng._cite_entries
    assert eng._cite_entries[2] == ("Example Title", "https://example.org")
    assert log.written == []


def test_P03_fence_open_transitions_to_in_code():
    eng, log = _make_engine()
    eng._citations_enabled = False

    fake_block = MagicMock()
    eng._open_code_block = MagicMock(return_value=fake_block)
    eng._flush_block_buf = lambda: None
    eng._emit_complete_code_block = MagicMock()

    eng.process_line("```python")

    assert eng._state == "IN_CODE"
    assert eng._fence_char == "`"
    assert eng._fence_depth == 3
    eng._open_code_block.assert_called_once_with("python")


def test_P04_fence_open_lines_close_returns_to_normal():
    eng, log = _make_engine()
    eng._citations_enabled = False

    fake_block = MagicMock()
    eng._open_code_block = MagicMock(return_value=fake_block)
    eng._flush_block_buf = lambda: None
    eng._emit_complete_code_block = MagicMock()

    eng.process_line("```python")
    eng.process_line("x = 1")
    eng.process_line("```")

    assert eng._state == "NORMAL"
    fake_block.append_line.assert_called_once_with("x = 1")
    fake_block.complete.assert_called_once()


def test_P05_block_math_oneline_calls_flush_math():
    eng, log = _make_engine()
    eng._math_enabled = True
    eng._citations_enabled = False

    called_with = []

    def fake_flush_math(latex):
        called_with.append(latex)

    eng._flush_math_block = fake_flush_math
    eng._flush_block_buf = lambda: None

    eng.process_line("$$E=mc^2$$")

    assert called_with == ["E=mc^2"]


def test_P06_normal_prose_reaches_log():
    eng, log = _make_engine()
    eng._math_enabled = False
    eng._citations_enabled = False
    eng._sync_prose_log = lambda: None  # panel=None, skip re-resolve

    class PassthroughBuf:
        def process_line(self, raw):
            return raw
        def flush(self):
            return None

    eng._block_buf = PassthroughBuf()

    eng.process_line("hello world")

    assert any("hello world" in w for w in log.written)
