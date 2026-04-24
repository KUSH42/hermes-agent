"""B6 — OmissionBar [reset] button label and duplicate-button removal.

Run with:
    pytest -o "addopts=" tests/tui/test_omission_bar_reset.py -v
"""
from __future__ import annotations

from unittest.mock import MagicMock

from hermes_cli.tui.tool_blocks import OmissionBar, _VISIBLE_CAP


def _composed_buttons(bar: OmissionBar):
    from textual.widgets import Button
    return [w for w in bar.compose() if isinstance(w, Button)]


# ---------------------------------------------------------------------------
# B6-1: visible reset button label is "[reset]"
# ---------------------------------------------------------------------------

def test_visible_reset_button_label():
    """Bottom OmissionBar's --ob-cap button must have label '[reset]'."""
    bar = OmissionBar(parent_block=MagicMock(), position="bottom")
    buttons = _composed_buttons(bar)
    cap_btns = [b for b in buttons if "--ob-cap" in getattr(b, "_classes", set())]
    assert len(cap_btns) == 1, f"Expected exactly 1 --ob-cap button; got {len(cap_btns)}"
    assert str(cap_btns[0].label) == "[reset]", (
        f"Expected '[reset]', got '{cap_btns[0].label}'"
    )


# ---------------------------------------------------------------------------
# B6-2: no --ob-cap-adv button exists
# ---------------------------------------------------------------------------

def test_no_ob_cap_adv_button():
    """The duplicate --ob-cap-adv button must not exist in compose()."""
    bar = OmissionBar(parent_block=MagicMock(), position="bottom")
    buttons = _composed_buttons(bar)
    adv_cap_btns = [b for b in buttons if "--ob-cap-adv" in getattr(b, "_classes", set())]
    assert len(adv_cap_btns) == 0, (
        f"Found {len(adv_cap_btns)} --ob-cap-adv button(s) — should have been removed"
    )


# ---------------------------------------------------------------------------
# B6-3: pressing --ob-cap calls rerender_window(0, _VISIBLE_CAP)
# ---------------------------------------------------------------------------

def test_reset_rewinds_to_cap():
    """Pressing the --ob-cap button calls parent_block.rerender_window(0, _VISIBLE_CAP)."""
    parent = MagicMock()
    bar = OmissionBar.__new__(OmissionBar)
    bar._parent_block = parent
    bar._visible_start = 100
    bar._visible_end = 300
    bar._total = 500
    bar._advanced_visible = False

    # Build a fake button with --ob-cap class
    from textual.widgets import Button
    fake_btn = MagicMock(spec=Button)
    fake_btn.classes = {"--ob-cap"}

    # Build fake event
    event = MagicMock()
    event.button = fake_btn

    # query_one(".--ob-cap", Button) must not raise and not return --at-default
    not_at_default = MagicMock(spec=Button)
    not_at_default.classes = set()
    bar.query_one = MagicMock(return_value=not_at_default)

    bar.on_button_pressed(event)

    parent.rerender_window.assert_called_once_with(0, _VISIBLE_CAP)
