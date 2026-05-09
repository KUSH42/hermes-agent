"""Rendered-position helpers for vertical-rhythm tests (LP-RHYTHM-4).

These helpers compute OutputPanel-relative row positions from widget regions
after layout. Call after ``await pilot.pause()`` to ensure layout has run.
"""
from __future__ import annotations


def widget_first_row(widget) -> int:
    """Return the OutputPanel-relative top row of a mounted widget.

    Requires the widget to be mounted and laid out (call after await pilot.pause()).
    """
    return widget.region.y - widget.parent.region.y


def gap_between(w1, w2) -> int:
    """Rows between the bottom edge of w1 and the top edge of w2."""
    return widget_first_row(w2) - (widget_first_row(w1) + w1.region.height)
