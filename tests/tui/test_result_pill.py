"""Tests for ResultPill widget (v3 Phase B, tui-tool-panel-v3-spec.md §5.3).

Covers:
- Each ResultKind produces correct CSS class and label
- TEXT kind hides the pill (display: none)
- set_kind transitions remove old class, add new class
- Not mounted for TEXT (display=False by default)
"""
from __future__ import annotations

import pytest
from hermes_cli.tui.result_pill import ResultPill, PILL_LABELS, ResultKind


# ---------------------------------------------------------------------------
# Unit tests — no app needed
# ---------------------------------------------------------------------------


def test_initial_state_display_none():
    """ResultPill starts with display: none (hidden)."""
    pill = ResultPill("")
    assert "display: none" in ResultPill.DEFAULT_CSS


def test_pill_labels_covers_all_non_text_kinds():
    """PILL_LABELS has an entry for every ResultKind except TEXT."""
    for kind in ResultKind:
        if kind == ResultKind.TEXT:
            assert kind not in PILL_LABELS
        else:
            assert kind in PILL_LABELS


def test_set_kind_text_hides_pill():
    """set_kind(TEXT) sets display=False and removes all kind classes."""
    pill = ResultPill("")
    pill.set_kind(ResultKind.CODE)  # add some class first
    pill.set_kind(ResultKind.TEXT)
    assert not pill.display
    for kind in ResultKind:
        if kind != ResultKind.TEXT:
            assert not pill.has_class(f"-{kind.value}")


def test_set_kind_code_adds_class():
    pill = ResultPill("")
    pill.set_kind(ResultKind.CODE)
    assert pill.has_class("-code")
    assert pill.display is True


def test_set_kind_diff_adds_class():
    pill = ResultPill("")
    pill.set_kind(ResultKind.DIFF)
    assert pill.has_class("-diff")


def test_set_kind_search_adds_class():
    pill = ResultPill("")
    pill.set_kind(ResultKind.SEARCH)
    assert pill.has_class("-search")


def test_set_kind_transitions_remove_old_class():
    """Transitioning from CODE to SEARCH removes -code, adds -search."""
    pill = ResultPill("")
    pill.set_kind(ResultKind.CODE)
    assert pill.has_class("-code")
    pill.set_kind(ResultKind.SEARCH)
    assert not pill.has_class("-code")
    assert pill.has_class("-search")


def test_set_kind_updates_label():
    """set_kind calls update() with the correct label string."""
    pill = ResultPill("")
    pill.set_kind(ResultKind.DIFF)
    assert str(pill.render()) == "diff"


def test_all_non_text_kinds_set_display_true():
    """All non-TEXT kinds make the pill visible."""
    pill = ResultPill("")
    for kind in ResultKind:
        if kind != ResultKind.TEXT:
            pill.set_kind(kind)
            assert pill.display is True, f"kind={kind} should be visible"
