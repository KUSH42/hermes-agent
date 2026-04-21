"""Tests for MEDIA: detection helpers in hermes_cli.tui.tool_blocks."""

from __future__ import annotations

import re

import pytest

from hermes_cli.tui.tool_blocks import (
    _extract_image_path,
    _IMAGE_EXTS,
    _MEDIA_LINE_RE,
)


# ---------------------------------------------------------------------------
# _extract_image_path
# ---------------------------------------------------------------------------

def test_media_png():
    assert _extract_image_path("MEDIA: /tmp/foo.png") == "/tmp/foo.png"


def test_media_jpg():
    assert _extract_image_path("MEDIA: /tmp/x.jpg") == "/tmp/x.jpg"


def test_media_jpeg():
    assert _extract_image_path("MEDIA: /tmp/x.jpeg") == "/tmp/x.jpeg"


def test_media_case_insensitive():
    assert _extract_image_path("media: /tmp/foo.PNG") == "/tmp/foo.PNG"


def test_media_txt_returns_none():
    assert _extract_image_path("MEDIA: /tmp/foo.txt") is None


def test_media_no_extension_returns_none():
    assert _extract_image_path("MEDIA: /tmp/noext") is None


def test_bare_png_path():
    assert _extract_image_path("/tmp/chart.png") == "/tmp/chart.png"


def test_bare_gif_path():
    assert _extract_image_path("/tmp/anim.gif") == "/tmp/anim.gif"


def test_bare_webp_path():
    assert _extract_image_path("/some/path/img.webp") == "/some/path/img.webp"


def test_plain_text_returns_none():
    assert _extract_image_path("hello world") is None


def test_empty_string_returns_none():
    assert _extract_image_path("") is None


def test_media_with_leading_whitespace():
    assert _extract_image_path("  MEDIA: /tmp/foo.png") == "/tmp/foo.png"


# ---------------------------------------------------------------------------
# _MEDIA_LINE_RE — multi-line matching
# ---------------------------------------------------------------------------

def test_regex_finds_single_media_line():
    text = "some output\nMEDIA: /tmp/chart.png\nmore output"
    matches = _MEDIA_LINE_RE.findall(text)
    assert len(matches) == 1
    assert "/tmp/chart.png" in matches[0]


def test_regex_finds_last_of_multiple():
    text = "MEDIA: /tmp/first.png\nother\nMEDIA: /tmp/second.png"
    matches = _MEDIA_LINE_RE.findall(text)
    assert len(matches) == 2
    assert "/tmp/second.png" in matches[-1]


def test_regex_no_match_on_plain_text():
    text = "no images here\njust text"
    assert _MEDIA_LINE_RE.findall(text) == []


def test_regex_requires_non_whitespace_after_media():
    # "MEDIA: " with nothing after → no match (spec: \S required)
    text = "MEDIA:   "
    assert _MEDIA_LINE_RE.findall(text) == []


# ---------------------------------------------------------------------------
# _IMAGE_EXTS completeness
# ---------------------------------------------------------------------------

def test_image_exts_contains_common_formats():
    for ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff"):
        assert ext in _IMAGE_EXTS
