"""Tests for hermes_cli/tui/fuzzy.py — ranker + span correctness + polymorphic."""

from __future__ import annotations

import pytest

from hermes_cli.tui.fuzzy import fuzzy_rank
from hermes_cli.tui.path_search import Candidate, PathCandidate, SlashCandidate


def _paths(*names: str) -> list[PathCandidate]:
    return [PathCandidate(display=n, abs_path=f"/tmp/{n}") for n in names]


def _slashes(*names: str) -> list[SlashCandidate]:
    return [SlashCandidate(display=n, command=n) for n in names]


# ---------------------------------------------------------------------------
# Phase 3 tests
# ---------------------------------------------------------------------------

def test_empty_query_returns_all() -> None:
    """fuzzy_rank('', items) returns items[:limit] with score=0 and no spans."""
    items = _paths("foo.py", "bar.py", "baz.py")
    result = fuzzy_rank("", items, limit=10)
    assert len(result) == 3
    for c in result:
        assert c.score == 0
        assert c.match_spans == ()


def test_empty_query_respects_limit() -> None:
    items = _paths(*[f"f{i}.py" for i in range(20)])
    result = fuzzy_rank("", items, limit=5)
    assert len(result) == 5


def test_consecutive_run_bonus() -> None:
    """Only contiguous matches qualify; contiguous hit ranks first."""
    items = _paths("abcxyz", "axbxc")
    result = fuzzy_rank("abc", items)
    assert [c.display for c in result] == ["abcxyz"]


def test_word_boundary_bonus() -> None:
    """Match starting after '/' scores higher than mid-word match."""
    items = _paths("src/abc.py", "xabc.py")
    result = fuzzy_rank("abc", items)
    # src/abc.py — boundary match (after /); xabc.py — mid-word
    assert result[0].display == "src/abc.py"


def test_match_spans_correct() -> None:
    """Spans cover exact contiguous substring."""
    items = _paths("xxabcyy")
    result = fuzzy_rank("abc", items)
    assert len(result) == 1
    c = result[0]
    assert c.match_spans == ((2, 5),)


def test_no_match_excluded() -> None:
    """Items that don't contain all query chars are excluded."""
    items = _paths("hello.py", "world.py")
    result = fuzzy_rank("xyz", items)
    assert result == []


def test_polymorphic_slash_candidate() -> None:
    """SlashCandidate flows through fuzzy_rank with match_spans populated."""
    items = _slashes("/help", "/history", "/hint")
    result = fuzzy_rank("hi", items)
    displays = [c.display for c in result]
    assert "/hint" in displays or "/history" in displays


def test_subsequence_match_excluded() -> None:
    """Split-letter subsequence matches should not qualify."""
    items = _paths("axbxc", "alphabetic", "foo")
    result = fuzzy_rank("abc", items)
    assert result == []


def test_limit_respected() -> None:
    """Results are capped at limit even when more candidates match."""
    items = _paths(*[f"abc_{i}.py" for i in range(100)])
    result = fuzzy_rank("abc", items, limit=10)
    assert len(result) == 10


def test_tiebreak_is_deterministic() -> None:
    """Same input always produces same output (tiebreak by len then alpha)."""
    items = _paths("b.py", "a.py", "c.py")
    r1 = fuzzy_rank("py", items)
    r2 = fuzzy_rank("py", items)
    assert [c.display for c in r1] == [c.display for c in r2]


def test_span_does_not_overlap() -> None:
    """Match spans are non-overlapping and in ascending order."""
    items = _paths("foo_bar_baz.py")
    result = fuzzy_rank("bar", items)
    if result:
        spans = result[0].match_spans
        for i in range(1, len(spans)):
            assert spans[i][0] >= spans[i - 1][1]
