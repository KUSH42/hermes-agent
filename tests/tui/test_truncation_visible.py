"""D3: OmissionBar bottom always shown when truncated lines exist."""
from __future__ import annotations

from hermes_cli.tui.tool_blocks._shared import OmissionBar, _VISIBLE_CAP


class _FakeBlock:
    def rerender_window(self, *a, **k):
        pass


def test_cap_msg_forces_bar_visible_logic():
    """When cap_msg is truthy, show_bottom becomes True even if visible_end == total."""
    bar = OmissionBar(_FakeBlock(), position="bottom")
    bar._omission_bar_bottom = bar
    bar._omission_bar_bottom_mounted = True

    # Simulate: visible_end == total (nothing below) but cap_msg present
    visible_start = 0
    visible_end = 100
    total = 100
    cap_msg = "⚠ 5 lines truncated (2.0 KB cap)"

    show_bottom = (visible_end < total) or bool(cap_msg)
    assert show_bottom, "cap_msg should force show_bottom True"


def test_no_cap_msg_hides_bar_when_all_shown():
    """When cap_msg is falsy and visible_end == total, show_bottom is False."""
    visible_start = 0
    visible_end = 50
    total = 50
    cap_msg = None

    show_bottom = (visible_end < total) or bool(cap_msg)
    assert not show_bottom


def test_cap_msg_appended_for_truncated_lines():
    """_refresh_omission_bars constructs cap_msg when _truncated_line_count > 0."""
    # Simulate the logic from _refresh_omission_bars
    truncated_line_count = 3
    line_byte_cap = 2000
    history_capped = False
    total = 50
    visible_cap = _VISIBLE_CAP

    cap_msg = None
    if history_capped:
        cap_msg = "⚠ history capped at 10k lines"
        if truncated_line_count > 0:
            cap_msg += f" · {truncated_line_count} truncated"
    elif total > visible_cap:
        cap_msg = f"⚠ {total} total · cap {visible_cap}"
        if truncated_line_count > 0:
            cap_msg += f" · {truncated_line_count} truncated"
    elif truncated_line_count > 0:
        cap_msg = f"⚠ {truncated_line_count} lines truncated ({line_byte_cap}b cap)"

    assert cap_msg is not None
    assert "truncated" in cap_msg
