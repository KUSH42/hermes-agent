"""Tests for group_semantic_label and group_path_hint helpers (v3 Phase B, §5.7).

Covers:
- Single tool name, count 1 → just the name
- Single tool name, count > 1 → 'name × N'
- Multiple names, ≤ 3 → joined with '+'
- Multiple names, > 3 → truncated with '+…'
- Dedup: duplicate tool names deduplicated before counting
- group_path_hint: single common basename
- group_path_hint: different basenames → None
- group_path_hint: no paths → None
- Empty members → fallback label
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from hermes_cli.tui.tool_group import group_semantic_label, group_path_hint


def _make_member(tool_name: str, path: str | None = None) -> MagicMock:
    m = MagicMock()
    m._tool_name = tool_name
    m._tool_args = {"path": path} if path else {}
    return m


# ---------------------------------------------------------------------------
# group_semantic_label
# ---------------------------------------------------------------------------


def test_single_member_single_name():
    """One member, one unique tool name → just the name."""
    members = [_make_member("patch")]
    assert group_semantic_label(members) == "patch"


def test_single_name_two_members():
    """Two members with same tool name → 'patch × 2'."""
    members = [_make_member("patch"), _make_member("patch")]
    assert group_semantic_label(members) == "patch × 2"


def test_single_name_three_members():
    members = [_make_member("terminal")] * 3
    assert group_semantic_label(members) == "terminal × 3"


def test_two_distinct_names():
    """Two different tool names → 'name1+name2' (sorted)."""
    members = [_make_member("patch"), _make_member("diff")]
    result = group_semantic_label(members)
    assert "+" in result
    assert "diff" in result
    assert "patch" in result


def test_three_distinct_names():
    members = [_make_member("search"), _make_member("patch"), _make_member("write")]
    result = group_semantic_label(members)
    parts = result.split("+")
    assert len(parts) == 3


def test_four_distinct_names_truncated():
    """Four+ distinct names → truncated with '+…'."""
    members = [_make_member(f"tool{i}") for i in range(4)]
    result = group_semantic_label(members)
    assert result.endswith("+…")


def test_dedup_same_names():
    """Duplicate names deduplicated — 3 patches count as single unique name."""
    members = [_make_member("patch")] * 3
    # single unique name + count > 1 → 'patch × 3'
    result = group_semantic_label(members)
    assert result == "patch × 3"


def test_mixed_dedup():
    """Two patches + one diff → unique set is {patch, diff}."""
    members = [_make_member("patch"), _make_member("patch"), _make_member("diff")]
    result = group_semantic_label(members)
    # unique: {diff, patch} → 'diff+patch' (sorted)
    assert "diff" in result and "patch" in result


def test_empty_members_fallback():
    """No members → fallback '0 tools'."""
    assert group_semantic_label([]) == "0 tools"


def test_member_with_empty_tool_name_excluded():
    """Members with empty _tool_name are excluded from unique label set.
    Total count still includes all members per spec."""
    members = [_make_member(""), _make_member("patch")]
    # unique non-empty names: {"patch"}, count of members: 2
    result = group_semantic_label(members)
    assert "patch" in result
    assert "2" in result


# ---------------------------------------------------------------------------
# group_path_hint
# ---------------------------------------------------------------------------


def test_path_hint_single_file():
    """All members have same basename → that basename."""
    members = [
        _make_member("patch", "/a/b/widgets.py"),
        _make_member("diff",  "/x/y/widgets.py"),
    ]
    assert group_path_hint(members) == "widgets.py"


def test_path_hint_different_files():
    """Different basenames → None."""
    members = [
        _make_member("patch", "/a/widgets.py"),
        _make_member("diff",  "/a/app.py"),
    ]
    assert group_path_hint(members) is None


def test_path_hint_no_paths():
    """Members with no path args → None."""
    members = [_make_member("terminal"), _make_member("terminal")]
    assert group_path_hint(members) is None


def test_path_hint_single_member():
    members = [_make_member("read", "/foo/bar.txt")]
    assert group_path_hint(members) == "bar.txt"
