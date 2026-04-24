"""Tests for _format_vision_result — MEDIA: tag injection in vision tool results."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.vision_tools import _format_vision_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(text: str = "analysis here") -> str:
    return json.dumps({"success": True, "analysis": text}, indent=2)


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------

def test_local_path_appends_media_line(tmp_path: Path) -> None:
    img = tmp_path / "test.png"
    img.write_bytes(b"fake")
    result = _format_vision_result(_make_result(), str(img))
    assert f"MEDIA: {img}" in result


def test_nonexistent_path_no_media_line() -> None:
    result = _format_vision_result(_make_result(), "/no/such/file.png")
    assert "MEDIA:" not in result


def test_remote_url_no_media_line() -> None:
    result = _format_vision_result(_make_result(), None)
    assert "MEDIA:" not in result


def test_format_vision_result_none_path() -> None:
    body = _make_result("some analysis")
    result = _format_vision_result(body, None)
    assert result == body


def test_media_line_at_end(tmp_path: Path) -> None:
    img = tmp_path / "img.jpg"
    img.write_bytes(b"fake")
    result = _format_vision_result(_make_result(), str(img))
    lines = result.rstrip("\n").splitlines()
    assert lines[-1].startswith("MEDIA:")


def test_format_result_passes_through_text(tmp_path: Path) -> None:
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    body = _make_result("original text")
    result = _format_vision_result(body, str(img))
    assert "original text" in result


def test_result_no_double_newline(tmp_path: Path) -> None:
    img = tmp_path / "pic.png"
    img.write_bytes(b"x")
    result = _format_vision_result(_make_result(), str(img))
    assert result.endswith(f"\nMEDIA: {img}\n")


def test_format_vision_result_json_structure_preserved(tmp_path: Path) -> None:
    img = tmp_path / "out.png"
    img.write_bytes(b"x")
    body = json.dumps({"success": True, "analysis": "ok"}, indent=2)
    result = _format_vision_result(body, str(img))
    # JSON part (before MEDIA:) should still be valid JSON
    json_part = result.split("\nMEDIA:")[0]
    parsed = json.loads(json_part)
    assert parsed["success"] is True
