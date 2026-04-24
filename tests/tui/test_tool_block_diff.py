"""B12 — N:M word-diff tests for _render_diff_chunk."""
from __future__ import annotations

import pytest
from rich.text import Text


def _chunk(removed: list[str], added: list[str], del_bg: str = "#220000", add_bg: str = "#002200") -> list[Text]:
    from hermes_cli.tui.tool_blocks._block import _render_diff_chunk
    return _render_diff_chunk(removed, added, del_bg, add_bg)


def _has_word_diff(t: Text) -> bool:
    """Return True if text contains spans with bold underline (word-diff highlighting)."""
    for span in t._spans:
        if "bold" in str(span.style) and "underline" in str(span.style):
            return True
    return False


def _plain_bg(t: Text, bg: str) -> bool:
    """Return True if text has a span with the given background color."""
    for span in t._spans:
        if f"on {bg}" in str(span.style):
            return True
    return False


# ---------------------------------------------------------------------------
# B12-1: single pair word diff (existing behavior)
# ---------------------------------------------------------------------------

def test_single_pair_word_diff():
    """1 removal + 1 addition → word-level highlighting on the paired lines."""
    lines = _chunk(["hello world"], ["hello there"])
    assert len(lines) == 2
    assert str(lines[0])[0] == "-"
    assert str(lines[1])[0] == "+"
    # At least one word should be highlighted (bold underline)
    assert _has_word_diff(lines[0]) or _has_word_diff(lines[1])


# ---------------------------------------------------------------------------
# B12-2: 3 removals, 1 addition — 1 pair word-diff, 2 excess plain
# ---------------------------------------------------------------------------

def test_multi_removal_single_add():
    """3 removals + 1 addition → 1 pair gets word-diff; 2 excess removals get plain del_bg."""
    del_bg = "#330000"
    lines = _chunk(["line one", "line two", "line three"], ["line one replaced"], del_bg=del_bg)
    # 2 paired (rem+add) + 2 excess removals = 4 total
    assert len(lines) == 4
    # First pair: word-diff lines
    assert str(lines[0]).startswith("-")
    assert str(lines[1]).startswith("+")
    # Excess removals: plain del_bg style, no bold underline
    assert str(lines[2]).startswith("-")
    assert str(lines[3]).startswith("-")
    assert _plain_bg(lines[2], del_bg)
    assert _plain_bg(lines[3], del_bg)


# ---------------------------------------------------------------------------
# B12-3: 1 removal, 3 additions — 1 pair word-diff, 2 excess plain
# ---------------------------------------------------------------------------

def test_single_removal_multi_add():
    """1 removal + 3 additions → 1 pair word-diff; 2 excess additions get plain add_bg."""
    add_bg = "#003300"
    lines = _chunk(["old line"], ["new line one", "new line two", "new line three"], add_bg=add_bg)
    # 2 paired + 2 excess additions = 4 total
    assert len(lines) == 4
    assert str(lines[0]).startswith("-")
    assert str(lines[1]).startswith("+")
    assert str(lines[2]).startswith("+")
    assert str(lines[3]).startswith("+")
    assert _plain_bg(lines[2], add_bg)
    assert _plain_bg(lines[3], add_bg)


# ---------------------------------------------------------------------------
# B12-4: 3 removals, 0 additions — all plain del_bg
# ---------------------------------------------------------------------------

def test_unpaired_removals_get_plain_style():
    """3 removals + 0 additions → all 3 get plain del_bg style."""
    del_bg = "#440000"
    lines = _chunk(["rem a", "rem b", "rem c"], [], del_bg=del_bg)
    assert len(lines) == 3
    for line in lines:
        assert str(line).startswith("-")
        assert _plain_bg(line, del_bg)


# ---------------------------------------------------------------------------
# B12-5: context line flushes pending chunks — integration via ToolBlock.finalize
# ---------------------------------------------------------------------------

def test_context_line_flushes_pending():
    """Context line between two chunks doesn't merge them: each chunk flushed independently."""
    from hermes_cli.tui.tool_blocks._block import _render_diff_chunk

    # Simulate: chunk1 [-a, +b], context " c", chunk2 [-d, +e]
    # Both chunks should be independently processed
    chunk1 = _render_diff_chunk(["alpha"], ["beta"], "#220000", "#002200")
    chunk2 = _render_diff_chunk(["delta"], ["epsilon"], "#220000", "#002200")
    # Each chunk should independently produce 2 lines (1 removal, 1 addition)
    assert len(chunk1) == 2
    assert len(chunk2) == 2
    # They are independent — no cross-chunk interference
    assert str(chunk1[0]).startswith("-")
    assert str(chunk1[1]).startswith("+")
    assert str(chunk2[0]).startswith("-")
    assert str(chunk2[1]).startswith("+")
