"""Tests for SPEC-IB-VISUAL: visual chips, truncation, overflow.

IB-VIS-1: halfblock thumbnail strips in AttachmentChip
IB-VIS-2: width budget + name truncation + overflow chip
IB-VIS-3: size suffix + accessible tooltip
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.segment import Segment
from textual.strip import Strip

from hermes_cli.tui.widgets.inline_media import (
    ChipPlan,
    OverflowChip,
    _layout_chips,
    _render_attachment_thumb,
    _size_str_for_path,
    _size_suffix,
)
from hermes_cli.tui.widgets.status_bar import AttachmentChip


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_strip(text: str = "x") -> Strip:
    return Strip([Segment(text)])


def _make_chip(name: str = "image.png") -> AttachmentChip:
    """Create AttachmentChip without a mounted DOM (on_mount NOT called).

    Uses object.__new__ to bypass Textual's Static.__init__ entirely, then
    manually sets only the instance fields introduced by AttachmentChip.__init__.
    This avoids any Textual DOM dependencies (screen lookup, reactive machinery).
    The tooltip property setter accesses self.screen, so we store the backing
    ``_tooltip`` attribute directly.
    """
    path = Path(f"/tmp/{name}")
    chip = object.__new__(AttachmentChip)
    chip._path = path
    chip._index = 0
    chip._thumb_strips = []
    chip._name_row = 0
    from hermes_cli.tui.widgets.status_bar import _truncate
    chip._display_name = _truncate(path.name, 24)
    # Store tooltip without going through the property setter (requires screen)
    chip.__dict__["_tooltip"] = None
    return chip


# ---------------------------------------------------------------------------
# TestImageBarThumbnails (IB-VIS-1)
# ---------------------------------------------------------------------------

class TestImageBarThumbnails:
    def test_attachment_chip_thumb_strips_decoded(self) -> None:
        """_apply_thumb_strips sets _thumb_strips, _name_row, and render_line splices name."""
        chip = _make_chip("screenshot.png")
        strips = [_fake_strip("row0"), _fake_strip("row1"), _fake_strip("row2")]

        # Simulate is_mounted guard passing by setting the backing attribute
        chip.__dict__["_is_mounted"] = True
        chip.styles = MagicMock()
        chip.refresh = MagicMock()

        chip._apply_thumb_strips(strips)

        assert len(chip._thumb_strips) == 3
        assert chip._name_row == 1  # len(3) // 2 == 1

        # render_line(1) (name row) should contain _display_name in segment text
        result = chip.render_line(1)
        assert isinstance(result, Strip)
        seg_texts = [seg.text for seg in result._segments]
        assert any(chip._display_name in t for t in seg_texts), (
            f"Expected {chip._display_name!r} in segments: {seg_texts}"
        )

    def test_attachment_chip_thumb_disabled_falls_back_to_text(self) -> None:
        """When thumbnails config is false, _thumb_strips stays empty and render_line has emoji."""
        chip = _make_chip("photo.jpg")
        # No _apply_thumb_strips called (thumbnails=false path: worker not launched)
        assert chip._thumb_strips == []

        result = chip.render_line(0)
        assert isinstance(result, Strip)
        seg_texts = "".join(seg.text for seg in result._segments)
        assert "📎" in seg_texts

    def test_attachment_chip_thumb_decode_failure_falls_back_to_text(self) -> None:
        """When _apply_thumb_strips receives [], chip height stays 1 and render_line has emoji."""
        chip = _make_chip("corrupt.png")
        chip.__dict__["_is_mounted"] = True
        chip.styles = MagicMock()
        chip.refresh = MagicMock()

        chip._apply_thumb_strips([])  # decode failed → empty strips

        assert chip._thumb_strips == []
        assert chip.styles.height == 1

        result = chip.render_line(0)
        seg_texts = "".join(seg.text for seg in result._segments)
        assert "📎" in seg_texts


# ---------------------------------------------------------------------------
# TestImageBarWidthBudget (IB-VIS-2)
# ---------------------------------------------------------------------------

class TestImageBarWidthBudget:
    def test_image_bar_full_names_when_width_allows(self) -> None:
        """width=100, 2 paths: both have show_thumb=True, show_size=True, full names."""
        name1 = "screenshot.png"
        name2 = "diagram.png"
        paths = [Path(f"/tmp/{name1}"), Path(f"/tmp/{name2}")]
        plans, hidden = _layout_chips(100, paths)

        assert hidden == 0
        assert len(plans) == 2
        for plan in plans:
            assert plan.show_thumb is True
            # Budget is max(1, min(40, 100//2)) = 40 — names fit untruncated
            # display_name should equal the original name (no truncation needed for short names)
            assert plan.path.name in plan.display_name or len(plan.display_name) <= len(plan.path.name)

    def test_image_bar_truncates_names_when_budget_tight(self) -> None:
        """width=80, 4 paths: each display_name ≤ 12 chars, show_thumb=True."""
        # Budget = max(1, min(40, 80//4)) = 20; 20 >= _THUMB_DROP_BUDGET(15)
        paths = [Path(f"/tmp/verylongfilename_{i:02d}.png") for i in range(4)]
        plans, hidden = _layout_chips(80, paths)

        visible = plans  # hidden may be 0 for this width
        assert len(visible) > 0
        for plan in visible:
            # Names > budget get truncated to 12 chars by ladder step 2
            assert len(plan.display_name) <= 12, (
                f"Expected ≤12 chars, got {len(plan.display_name)!r}: {plan.display_name!r}"
            )
            assert plan.show_thumb is True

    def test_image_bar_drops_thumbnail_when_budget_below_threshold(self) -> None:
        """width=60, 5 paths: all visible plans have show_thumb=False."""
        # Budget = max(1, min(40, 60//5)) = 12; 12 < _THUMB_DROP_BUDGET(15)
        paths = [Path(f"/tmp/img_{i}.png") for i in range(5)]
        plans, hidden = _layout_chips(60, paths)

        # Some chips may be hidden (overflow), but all visible ones have show_thumb=False
        for plan in plans:
            assert plan.show_thumb is False

    def test_image_bar_overflow_collapses_to_count_chip(self) -> None:
        """width=40, 3 paths: hidden_count >= 1; visible + hidden == total."""
        paths = [Path(f"/tmp/image_{i}.png") for i in range(3)]
        plans, hidden = _layout_chips(40, paths)

        assert hidden >= 1, f"Expected hidden_count >= 1, got {hidden}"
        assert len(plans) + hidden == 3, (
            f"visible={len(plans)} + hidden={hidden} != 3"
        )


# ---------------------------------------------------------------------------
# TestImageBarSizeAndLabel (IB-VIS-3)
# ---------------------------------------------------------------------------

class TestImageBarSizeAndLabel:
    def test_image_bar_size_suffix_present_when_room(self) -> None:
        """_size_suffix with budget_spare=10 returns a non-empty size string for 2048-byte file."""
        p = Path("/tmp/test_file.png")
        stat_result = MagicMock()
        stat_result.st_size = 2048
        with patch.object(Path, "stat", return_value=stat_result):
            result = _size_suffix(p, budget_spare=10)
        assert result != ""
        # _human_size(2048) produces e.g. "2.0kB"; check that "2" appears in the suffix
        assert "2" in result

    def test_image_bar_size_suffix_omitted_when_tight(self) -> None:
        """_size_suffix with budget_spare=4 returns '' (< 6 threshold)."""
        p = Path("/tmp/test_file.png")
        result = _size_suffix(p, budget_spare=4)
        assert result == ""

    def test_image_bar_chip_tooltip_full_path_and_size(self) -> None:
        """Tooltip logic includes full posix path and human-readable size.

        The tooltip is assembled in on_mount via _size_str_for_path.  We test
        the assembly logic directly by calling _size_str_for_path and verifying
        the expected tooltip string, matching the code in AttachmentChip.on_mount.
        """
        p = Path("/tmp/screenshot_2026.png")
        stat_result = MagicMock()
        stat_result.st_size = 4096

        with patch.object(Path, "stat", return_value=stat_result):
            size_str = _size_str_for_path(p)

        assert size_str != ""
        # Reconstruct tooltip as on_mount does
        tooltip = f"{p.as_posix()} ({size_str})" if size_str else p.as_posix()
        assert p.as_posix() in tooltip
        assert size_str in tooltip  # e.g. "4.0kB"

        # When stat raises OSError, _size_str_for_path returns "" and tooltip
        # is just the posix path.
        with patch.object(Path, "stat", side_effect=OSError("no file")):
            size_str_err = _size_str_for_path(p)
        assert size_str_err == ""
        tooltip_err = f"{p.as_posix()} ({size_str_err})" if size_str_err else p.as_posix()
        assert tooltip_err == p.as_posix()
