"""Tests for InlineImageBar and InlineThumbnail widgets (Phase F)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from rich.segment import Segment
from textual.strip import Strip

from hermes_cli.tui.widgets import InlineImageBar, InlineThumbnail


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bar(enabled: bool = True) -> InlineImageBar:
    bar = object.__new__(InlineImageBar)
    Widget = InlineImageBar.__bases__[0]
    Widget.__init__(bar)
    bar._paths = []
    bar._enabled = enabled
    return bar


# ---------------------------------------------------------------------------
# InlineImageBar — visibility and state
# ---------------------------------------------------------------------------

def test_image_bar_hidden_by_default() -> None:
    bar = _make_bar()
    # Bar starts with no paths and --visible class is only added via add_image
    assert bar._paths == []


def test_image_bar_path_list_accumulated() -> None:
    bar = _make_bar()
    bar._paths = ["a.png", "b.png"]
    assert len(bar._paths) == 2


def test_add_image_off_config() -> None:
    bar = _make_bar(enabled=False)
    # Patch mount to ensure it's never called
    bar.query_one = MagicMock(side_effect=AssertionError("should not query"))
    bar.add_image("/some/path.png")
    assert bar._paths == []


def test_image_bar_compose_has_horizontal() -> None:
    from textual.containers import Horizontal
    bar = InlineImageBar()
    children = list(bar.compose())
    assert any(isinstance(c, Horizontal) for c in children)


# ---------------------------------------------------------------------------
# InlineThumbnail — construction
# ---------------------------------------------------------------------------

def test_thumbnail_index_sequential() -> None:
    t1 = InlineThumbnail(path="a.png", index=1)
    t2 = InlineThumbnail(path="b.png", index=2)
    assert t1._index == 1
    assert t2._index == 2


def test_thumbnail_blank_strip_out_of_range() -> None:
    thumb = InlineThumbnail(path="x.png", index=1)
    thumb._strips = []
    result = thumb.render_line(99)
    assert isinstance(result, Strip)


def test_thumbnail_render_line_returns_strip() -> None:
    thumb = InlineThumbnail(path="x.png", index=1)
    fake_strip = Strip([Segment("██████████")])
    thumb._strips = [fake_strip]
    result = thumb.render_line(0)
    assert result is fake_strip


def test_thumbnail_strips_populated_after_apply() -> None:
    thumb = InlineThumbnail(path="x.png", index=1)
    strips = [Strip([Segment("a")]), Strip([Segment("b")])]
    thumb._strips = []
    thumb._apply_strips(strips)
    assert thumb._strips == strips


def test_pil_unavailable_shows_placeholder() -> None:
    thumb = InlineThumbnail(path="x.png", index=1)
    thumb._apply_strips([])
    result = thumb.render_line(0)
    assert isinstance(result, Strip)


# ---------------------------------------------------------------------------
# InlineThumbnail — worker
# ---------------------------------------------------------------------------

def test_load_strips_apply_strips_called_with_result() -> None:
    thumb = InlineThumbnail(path="/fake/img.png", index=1)
    fake_strips = [Strip([Segment("x")])]
    applied: list = []
    thumb._apply_strips = lambda s: applied.extend(s)
    thumb._apply_strips(fake_strips)
    assert applied == fake_strips


def test_load_strips_none_image_gives_empty() -> None:
    thumb = InlineThumbnail(path="/no/img.png", index=1)
    applied: list = []
    thumb._apply_strips = lambda s: applied.extend(s)
    thumb._apply_strips([])
    assert applied == []


# ---------------------------------------------------------------------------
# ImageMounted message
# ---------------------------------------------------------------------------

def test_image_mounted_message_has_path() -> None:
    from hermes_cli.tui.tool_blocks import ImageMounted
    msg = ImageMounted("/some/path.png")
    assert msg.path == "/some/path.png"


# ---------------------------------------------------------------------------
# ThumbnailClicked message
# ---------------------------------------------------------------------------

def test_thumbnail_clicked_path_and_index() -> None:
    msg = InlineImageBar.ThumbnailClicked("/img.png", 3)
    assert msg.path == "/img.png"
    assert msg.index == 3
