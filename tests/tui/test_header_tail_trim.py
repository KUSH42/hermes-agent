"""A1: _trim_tail_segments drops lowest-priority segments to protect label width."""
from __future__ import annotations

import pytest
from rich.text import Text

from hermes_cli.tui.tool_blocks._header import _trim_tail_segments, MIN_LABEL_CELLS


def _seg(name: str, content: str) -> tuple[str, Text]:
    return (name, Text(content))


def test_no_trim_when_fits():
    segs = [_seg("hero", "  exit 0"), _seg("chevron", "  ▾")]
    result = _trim_tail_segments(segs, budget=100)
    assert len(result) == 2


def test_drops_flash_first():
    segs = [
        _seg("hero", "  " + "x" * 20),
        _seg("flash", "  ✓ done"),
    ]
    total_w = sum(s.cell_len for _, s in segs)
    # budget that forces one drop
    result = _trim_tail_segments(segs, budget=total_w - 1)
    names = [n for n, _ in result]
    assert "flash" not in names
    assert "hero" in names


def test_drops_stderrwarn_before_chevron():
    segs = [
        _seg("chevron", "  ▾"),
        _seg("stderrwarn", "  ⚠ stderr (e)"),
    ]
    total_w = sum(s.cell_len for _, s in segs)
    result = _trim_tail_segments(segs, budget=total_w - 1)
    names = [n for n, _ in result]
    assert "stderrwarn" not in names
    assert "chevron" in names


def test_drops_linecount_before_chevron():
    segs = [
        _seg("linecount", "  42L"),
        _seg("chevron", "  ▾"),
    ]
    total_w = sum(s.cell_len for _, s in segs)
    result = _trim_tail_segments(segs, budget=total_w - 1)
    names = [n for n, _ in result]
    assert "linecount" not in names
    assert "chevron" in names


@pytest.mark.parametrize("width", [40, 60, 80, 120])
def test_trim_preserves_budget(width: int):
    segs = [
        _seg("hero", "  " + "h" * 15),
        _seg("diff", "  +100 -50"),
        _seg("chevron", "  ▾"),
        _seg("flash", "  ✓ completed"),
        _seg("stderrwarn", "  ⚠ stderr (e)"),
    ]
    budget = max(0, width - MIN_LABEL_CELLS - 5)  # 5 = fake prefix
    result = _trim_tail_segments(segs, budget=budget)
    actual_w = sum(s.cell_len for _, s in result)
    assert actual_w <= budget or not result  # within budget or fully empty
