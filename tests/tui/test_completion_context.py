"""Tests for hermes_cli/tui/completion_context.py — trigger dispatcher."""

from __future__ import annotations

import pytest

from hermes_cli.tui.completion_context import (
    CompletionContext,
    detect_context,
)


# ---------------------------------------------------------------------------
# Phase 4 tests
# ---------------------------------------------------------------------------

def test_slash_only_at_start() -> None:
    """/h at position 0 → SLASH_COMMAND; foo /h → NATURAL."""
    t = detect_context("/h", 2)
    assert t.context is CompletionContext.SLASH_COMMAND
    assert t.fragment == "h"

    t2 = detect_context("foo /h", 6)
    assert t2.context is CompletionContext.NATURAL


def test_slash_full_command_is_slash_context() -> None:
    """/help with cursor at end → SLASH_COMMAND, fragment='help'."""
    t = detect_context("/help", 5)
    assert t.context is CompletionContext.SLASH_COMMAND
    assert t.fragment == "help"


def test_slash_with_hyphen_matches() -> None:
    """/review-pr matches the [\\w-]* pattern."""
    t = detect_context("/review-pr", 10)
    assert t.context is CompletionContext.SLASH_COMMAND
    assert t.fragment == "review-pr"


def test_slash_with_space_after_is_natural() -> None:
    """/help (with trailing space) is no longer a slash trigger."""
    t = detect_context("/help ", 6)
    assert t.context is CompletionContext.NATURAL


def test_path_at_token_boundary() -> None:
    """@src at start → PATH_REF; foo@bar → NATURAL."""
    t = detect_context("@src", 4)
    assert t.context is CompletionContext.PATH_REF
    assert t.fragment == "src"

    t2 = detect_context("foo@bar", 7)
    assert t2.context is CompletionContext.NATURAL


def test_path_preceded_by_space() -> None:
    """'hello @bar' at cursor after bar → PATH_REF."""
    t = detect_context("hello @bar", 10)
    assert t.context is CompletionContext.PATH_REF
    assert t.fragment == "bar"


def test_cursor_mid_value() -> None:
    """detect_context uses only head[:cursor], not the full value."""
    # 'hello @s world', cursor at index 8 (after @s)
    t = detect_context("hello @s world", 8)
    assert t.context is CompletionContext.PATH_REF
    assert t.fragment == "s"


def test_empty_value_is_natural() -> None:
    """Empty value → NATURAL."""
    t = detect_context("", 0)
    assert t.context is CompletionContext.NATURAL


def test_plain_text_is_natural() -> None:
    """Plain prose → NATURAL."""
    t = detect_context("what is the weather", 19)
    assert t.context is CompletionContext.NATURAL


def test_at_only_is_path_ref() -> None:
    """@ alone (empty fragment) → PATH_REF with fragment=''."""
    t = detect_context("@", 1)
    assert t.context is CompletionContext.PATH_REF
    assert t.fragment == ""


def test_slash_only_is_slash_command() -> None:
    """/ alone → SLASH_COMMAND with fragment=''."""
    t = detect_context("/", 1)
    assert t.context is CompletionContext.SLASH_COMMAND
    assert t.fragment == ""


# ---------------------------------------------------------------------------
# PLAIN_PATH_REF tests (./  ../  ~/)
# ---------------------------------------------------------------------------

def test_dot_slash_alone_is_plain_path_ref() -> None:
    """./ alone → PLAIN_PATH_REF with empty fragment."""
    t = detect_context("./", 2)
    assert t.context is CompletionContext.PLAIN_PATH_REF
    assert t.fragment == ""


def test_dot_slash_with_fragment() -> None:
    """./src/main → PLAIN_PATH_REF with fragment 'src/main'."""
    t = detect_context("./src/main", 10)
    assert t.context is CompletionContext.PLAIN_PATH_REF
    assert t.fragment == "src/main"


def test_dotdot_slash_is_plain_path_ref() -> None:
    """../foo → PLAIN_PATH_REF with fragment 'foo'."""
    t = detect_context("../foo", 6)
    assert t.context is CompletionContext.PLAIN_PATH_REF
    assert t.fragment == "foo"


def test_tilde_slash_is_plain_path_ref() -> None:
    """~/bar → PLAIN_PATH_REF with fragment 'bar'."""
    t = detect_context("~/bar", 5)
    assert t.context is CompletionContext.PLAIN_PATH_REF
    assert t.fragment == "bar"


def test_plain_path_after_space() -> None:
    """'check ./src' at cursor after 'src' → PLAIN_PATH_REF."""
    t = detect_context("check ./src", 11)
    assert t.context is CompletionContext.PLAIN_PATH_REF
    assert t.fragment == "src"


def test_dot_slash_not_mid_word() -> None:
    """foo./bar is NOT PLAIN_PATH_REF (no space or SOL before '.')."""
    t = detect_context("foo./bar", 8)
    assert t.context is CompletionContext.NATURAL
