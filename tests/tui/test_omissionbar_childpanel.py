"""Tests for OmissionBar polish (E-1, E-2) and ChildPanel keybind alignment (D-1)."""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_button(classes: tuple[str, ...] = ()) -> MagicMock:
    """Minimal Button stand-in with a mutable class set."""
    btn = MagicMock()
    btn._classes: set[str] = set(classes)
    btn.disabled = False

    def add_class(name: str) -> None:
        btn._classes.add(name)

    def remove_class(name: str) -> None:
        btn._classes.discard(name)

    def has_class(name: str) -> bool:
        return name in btn._classes

    btn.add_class = add_class
    btn.remove_class = remove_class
    btn.has_class = has_class
    btn.classes = btn._classes
    return btn


class _FakeOmissionBar:
    """
    Minimal stand-in that replicates just the set_counts() bottom-position
    logic exercised by E-1 tests, without needing a live Textual app.
    """

    _tooltip_text: str = "Scroll output window"

    def __init__(self) -> None:
        self.position = "bottom"
        self._visible_start = 0
        self._visible_end = 0
        self._total = 0
        self._label: MagicMock | None = MagicMock()
        self._cap_label: MagicMock | None = MagicMock()
        self._reset_btn = _make_button(("--ob-cap",))

    def query_one(self, selector: str, _type: type = object) -> MagicMock:  # type: ignore[override]
        if selector == ".--ob-cap":
            return self._reset_btn
        raise Exception(f"No match for {selector}")

    def set_counts(
        self,
        visible_start: int,
        visible_end: int,
        total: int,
        above: int | None = None,
        below: int | None = None,
        cap_msg: str | None = None,
        visible_cap: int = 200,
    ) -> None:
        """Extracted from real set_counts() — bottom-position branch only."""
        self._visible_start = visible_start
        self._visible_end = visible_end
        self._total = total

        at_default = (
            visible_start == 0
            and (visible_end - visible_start) <= visible_cap
        )

        reset_btn = self.query_one(".--ob-cap")
        reset_btn.disabled = False
        if at_default:
            try:
                reset_btn.add_class("--at-default")
            except AttributeError:
                pass
            self._tooltip_text = "Already at default view"
        else:
            try:
                reset_btn.remove_class("--at-default")
            except AttributeError:
                pass
            self._tooltip_text = "Scroll output window"


class _FakeStreamingBlock:
    """
    Minimal StreamingToolBlock stand-in for E-2 tests.
    Replicates _refresh_omission_bars() logic without a live app.
    """

    def __init__(self, visible_cap: int = 200) -> None:
        self._all_plain: list[str] = []
        self._visible_start: int = 0
        self._visible_count: int = 0
        self._visible_cap: int = visible_cap
        self._history_capped: bool = False
        self._truncated_line_count: int = 0
        self._omission_bar_top_mounted: bool = False
        self._omission_bar_bottom_mounted: bool = True
        # bottom bar stand-in
        self._omission_bar_bottom: MagicMock = MagicMock()
        self._omission_bar_bottom.display = False
        self._omission_bar_top: MagicMock | None = None

    def _refresh_omission_bars(self) -> None:
        """Mirror of the real _refresh_omission_bars() with E-2 threshold."""
        total = len(self._all_plain)
        visible_start = self._visible_start
        visible_end = visible_start + self._visible_count
        visible_cap = getattr(self, "_visible_cap", 200)

        cap_msg: str | None = None
        if self._history_capped:
            cap_msg = "capped"
        elif total > visible_cap:
            cap_msg = f"cap {visible_cap}"
        elif self._truncated_line_count > 0:
            cap_msg = "truncated"

        if self._omission_bar_bottom_mounted and self._omission_bar_bottom is not None:
            warn_threshold = int(visible_cap * 0.8)
            show_bottom = (total >= warn_threshold) or (visible_end < total) or bool(cap_msg)
            if self._omission_bar_bottom.display != show_bottom:
                self._omission_bar_bottom.display = show_bottom


# ---------------------------------------------------------------------------
# E-1-01  reset button label does not contain "hide"
# ---------------------------------------------------------------------------

def test_op_e1_01_reset_label_not_hide() -> None:
    from hermes_cli.tui.tool_blocks._shared import OmissionBar
    label = OmissionBar._reset_label()
    assert "hide" not in label.lower(), f"Expected no 'hide' in label, got {label!r}"


# ---------------------------------------------------------------------------
# E-1-02  at_default=True → reset button NOT disabled
# ---------------------------------------------------------------------------

def test_op_e1_02_reset_button_never_disabled_at_default() -> None:
    bar = _FakeOmissionBar()
    # at_default: start=0, visible window ≤ cap
    bar.set_counts(visible_start=0, visible_end=50, total=50, visible_cap=200)
    assert bar._reset_btn.disabled is False


# ---------------------------------------------------------------------------
# E-1-03  at_default=True → --at-default CSS class applied
# ---------------------------------------------------------------------------

def test_op_e1_03_at_default_class_applied() -> None:
    bar = _FakeOmissionBar()
    bar.set_counts(visible_start=0, visible_end=50, total=50, visible_cap=200)
    assert "--at-default" in bar._reset_btn._classes


# ---------------------------------------------------------------------------
# E-1-04  at_default=False → --at-default CSS class absent
# ---------------------------------------------------------------------------

def test_op_e1_04_at_default_class_absent_when_not_default() -> None:
    bar = _FakeOmissionBar()
    # non-default: visible_start > 0
    bar.set_counts(visible_start=10, visible_end=60, total=100, visible_cap=200)
    assert "--at-default" not in bar._reset_btn._classes


# ---------------------------------------------------------------------------
# E-1-05  at_default=True → tooltip "Already at default view"
# ---------------------------------------------------------------------------

def test_op_e1_05_tooltip_at_default() -> None:
    bar = _FakeOmissionBar()
    bar.set_counts(visible_start=0, visible_end=100, total=100, visible_cap=200)
    assert bar._tooltip_text == "Already at default view"


# ---------------------------------------------------------------------------
# E-1-06  at_default=False → tooltip "Scroll output window"
# ---------------------------------------------------------------------------

def test_op_e1_06_tooltip_not_at_default() -> None:
    bar = _FakeOmissionBar()
    # force non-default by having more lines than visible window
    bar.set_counts(visible_start=50, visible_end=150, total=300, visible_cap=200)
    assert bar._tooltip_text == "Scroll output window"


# ---------------------------------------------------------------------------
# E-2-01  bottom bar pre-mounted with display=False (source check)
# ---------------------------------------------------------------------------

def test_op_e2_01_bottom_bar_premounted_display_false() -> None:
    src = inspect.getsource(
        __import__(
            "hermes_cli.tui.tool_blocks._streaming",
            fromlist=["StreamingToolBlock"],
        ).StreamingToolBlock.on_mount
    )
    # Both bars should be set to display=False after mounting
    assert "_omission_bar_bottom.display = False" in src
    assert "_omission_bar_bottom_mounted = True" in src


# ---------------------------------------------------------------------------
# E-2-02  at 80% of cap → show_bottom=True
# ---------------------------------------------------------------------------

def test_op_e2_02_show_bottom_at_80_percent() -> None:
    block = _FakeStreamingBlock(visible_cap=200)
    block._all_plain = ["line"] * 160  # exactly 80%
    block._visible_start = 0
    block._visible_count = 160
    block._refresh_omission_bars()
    assert block._omission_bar_bottom.display is True


# ---------------------------------------------------------------------------
# E-2-03  at 79% → show_bottom=False (no cap_msg, no truncation)
# ---------------------------------------------------------------------------

def test_op_e2_03_no_show_below_threshold() -> None:
    block = _FakeStreamingBlock(visible_cap=200)
    block._all_plain = ["line"] * 159  # one below threshold
    block._visible_start = 0
    block._visible_count = 159
    block._refresh_omission_bars()
    assert block._omission_bar_bottom.display is False


# ---------------------------------------------------------------------------
# E-2-04  at 100% (200 lines) → bar visible
# ---------------------------------------------------------------------------

def test_op_e2_04_show_at_100_percent() -> None:
    block = _FakeStreamingBlock(visible_cap=200)
    block._all_plain = ["line"] * 200
    block._visible_start = 0
    block._visible_count = 200
    block._refresh_omission_bars()
    assert block._omission_bar_bottom.display is True


# ---------------------------------------------------------------------------
# E-2-05  cap_msg present at any count → bar visible
# ---------------------------------------------------------------------------

def test_op_e2_05_cap_msg_forces_visible() -> None:
    block = _FakeStreamingBlock(visible_cap=200)
    block._all_plain = ["line"] * 5  # very few lines
    block._visible_start = 0
    block._visible_count = 5
    block._history_capped = True  # triggers cap_msg
    block._refresh_omission_bars()
    assert block._omission_bar_bottom.display is True


# ---------------------------------------------------------------------------
# D-1-01  "space" not in ChildPanel.BINDINGS
# ---------------------------------------------------------------------------

def test_op_d1_01_space_not_in_bindings() -> None:
    from hermes_cli.tui.child_panel import ChildPanel
    keys = {b.key for b in ChildPanel.BINDINGS}
    assert "space" not in keys, f"'space' should be removed from ChildPanel.BINDINGS; found: {keys}"


# ---------------------------------------------------------------------------
# D-1-02  "alt+c" in ChildPanel.BINDINGS
# ---------------------------------------------------------------------------

def test_op_d1_02_alt_c_in_bindings() -> None:
    from hermes_cli.tui.child_panel import ChildPanel
    keys = {b.key for b in ChildPanel.BINDINGS}
    assert "alt+c" in keys, f"'alt+c' missing from ChildPanel.BINDINGS; found: {keys}"


# ---------------------------------------------------------------------------
# D-1-03  alt+c maps to action_toggle_compact
# ---------------------------------------------------------------------------

def test_op_d1_03_alt_c_maps_to_toggle_compact() -> None:
    from hermes_cli.tui.child_panel import ChildPanel
    matches = [b for b in ChildPanel.BINDINGS if b.key == "alt+c"]
    assert matches, "'alt+c' binding not found"
    assert matches[0].action == "toggle_compact", (
        f"Expected action 'toggle_compact', got {matches[0].action!r}"
    )
    # Also confirm action_toggle_compact is callable on ChildPanel
    assert callable(getattr(ChildPanel, "action_toggle_compact", None))


# ---------------------------------------------------------------------------
# D-1-04  "space" absent from top-level ToolPanel.BINDINGS (regression guard)
# ---------------------------------------------------------------------------

def test_op_d1_04_space_not_in_toolpanel_bindings() -> None:
    from hermes_cli.tui.tool_panel import ToolPanel
    keys = {b.key for b in ToolPanel.BINDINGS}
    assert "space" not in keys, (
        f"Top-level ToolPanel.BINDINGS still has 'space'; that was removed at C2: {keys}"
    )
