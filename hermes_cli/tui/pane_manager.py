"""
PaneManager — owns layout mode, pane width computation, state persistence.
Plain class (not a mixin, not a Textual widget); held at HermesApp._pane_manager.
"""
from __future__ import annotations
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass


class PaneId(str, Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class LayoutMode(str, Enum):
    SINGLE = "single"
    THREE = "three"
    THREE_WIDE = "three_wide"


@runtime_checkable
class PaneHost(Protocol):
    pane_id: "PaneId"
    widget: Any  # the concrete Textual widget
    preferred_width_cells: int | None
    collapsible: bool
    focus_binding: str | None

    def on_pane_show(self) -> None: ...
    def on_pane_hide(self) -> None: ...
    def on_pane_width_change(self, w: int) -> None: ...


class PaneManager:
    """
    Owns layout mode, pane-width math, host registry, and state persistence.
    Does NOT fire Textual reactives; sets CSS classes on #pane-row via app.
    """

    # Default thresholds (can be overridden by config at init time)
    DEFAULT_PANES_OFF = 120   # below → SINGLE
    DEFAULT_PANES_WIDE = 160  # at/above → THREE_WIDE
    HYSTERESIS = 2

    # Pane widths (cells)
    THREE_LEFT_W = 22
    THREE_RIGHT_W = 24
    THREE_WIDE_LEFT_W = 28
    THREE_WIDE_RIGHT_W = 32

    MIN_SIDE_W = 16
    MIN_CENTER_W = 80   # = resize_utils.THRESHOLD_TOOL_NARROW
    MIN_HEIGHT = 20     # below → force SINGLE

    def __init__(self, cfg: dict | None = None) -> None:
        cfg = cfg or {}
        lv2 = cfg.get("layout_v2", {})

        # Live thresholds (clamped user values)
        raw_off = int(lv2.get("panes_off_cols", self.DEFAULT_PANES_OFF))
        raw_wide = int(lv2.get("panes_wide_cols", self.DEFAULT_PANES_WIDE))
        self._threshold_off: int = max(60, min(raw_off, 180))
        self._threshold_wide: int = max(
            self._threshold_off + 20, min(raw_wide, 240)
        )

        # Per-session overrides for side-pane widths
        self._left_w_override: int | None = _int_or_none(lv2.get("default_left_w"))
        self._right_w_override: int | None = _int_or_none(lv2.get("default_right_w"))
        self._left_wide_w_override: int | None = _int_or_none(lv2.get("default_left_wide_w"))
        self._right_wide_w_override: int | None = _int_or_none(lv2.get("default_right_wide_w"))

        self._start_collapsed_left: bool = bool(lv2.get("start_collapsed_left", False))
        self._start_collapsed_right: bool = bool(lv2.get("start_collapsed_right", False))

        self.enabled: bool = cfg.get("layout", "v1") == "v2"

        self._mode: LayoutMode = LayoutMode.SINGLE
        self._left_collapsed: bool = self._start_collapsed_left
        self._right_collapsed: bool = self._start_collapsed_right
        self._center_split: bool = bool(lv2.get("center_split_enabled", False))
        self._split_target: str | None = None
        self._focused_pane: PaneId = PaneId.CENTER

        # Host registry: pane_id → PaneHost
        self._hosts: dict[PaneId, PaneHost] = {}

    # ------------------------------------------------------------------
    # Host registry
    # ------------------------------------------------------------------

    def set_host(self, pane_id: PaneId, host: PaneHost) -> None:
        self._hosts[pane_id] = host

    def get_host(self, pane_id: PaneId) -> PaneHost | None:
        return self._hosts.get(pane_id)

    # ------------------------------------------------------------------
    # Layout computation (pure, unit-testable)
    # ------------------------------------------------------------------

    def _compute_mode(self, term_w: int, term_h: int) -> LayoutMode:
        """Compute layout mode from terminal dimensions (no side effects)."""
        if not self.enabled:
            return LayoutMode.SINGLE
        if term_h < self.MIN_HEIGHT:
            return LayoutMode.SINGLE
        if term_w < self._threshold_off:
            return LayoutMode.SINGLE
        if term_w >= self._threshold_wide:
            return LayoutMode.THREE_WIDE
        return LayoutMode.THREE

    def _compute_widths(
        self, term_w: int, mode: LayoutMode
    ) -> tuple[int, int, int]:
        """
        Returns (left_w, center_w, right_w).
        Guarantees center_w >= MIN_CENTER_W or falls through to SINGLE (left=right=0).
        """
        if mode == LayoutMode.SINGLE:
            return 0, term_w, 0

        if mode == LayoutMode.THREE:
            left_w = _clamp(
                self._left_w_override or self.THREE_LEFT_W,
                self.MIN_SIDE_W, term_w // 3,
            )
            right_w = _clamp(
                self._right_w_override or self.THREE_RIGHT_W,
                self.MIN_SIDE_W, term_w // 3,
            )
        else:  # THREE_WIDE
            left_w = _clamp(
                self._left_wide_w_override or self.THREE_WIDE_LEFT_W,
                self.MIN_SIDE_W, term_w // 3,
            )
            right_w = _clamp(
                self._right_wide_w_override or self.THREE_WIDE_RIGHT_W,
                self.MIN_SIDE_W, term_w // 3,
            )

        center_w = term_w - left_w - right_w

        if center_w < self.MIN_CENTER_W:
            # Try shrinking sides proportionally
            deficit = self.MIN_CENTER_W - center_w
            # Distribute deficit proportionally between left and right
            total_side = left_w + right_w
            if total_side <= 2 * self.MIN_SIDE_W:
                # Can't shrink further — fall through to SINGLE
                return 0, term_w, 0
            left_share = deficit * left_w // total_side
            right_share = deficit - left_share
            left_w = max(self.MIN_SIDE_W, left_w - left_share)
            right_w = max(self.MIN_SIDE_W, right_w - right_share)
            center_w = term_w - left_w - right_w
            if center_w < self.MIN_CENTER_W:
                return 0, term_w, 0

        return left_w, center_w, right_w

    def compute_layout(self, term_w: int, term_h: int) -> tuple[LayoutMode, int, int, int]:
        """
        Returns (mode, left_w, center_w, right_w).
        Pure — no side effects. Used by _apply_layout and tests.
        """
        mode = self._compute_mode(term_w, term_h)
        widths = self._compute_widths(term_w, mode)
        # If widths forced fallback to SINGLE
        if widths[0] == 0 and mode != LayoutMode.SINGLE:
            mode = LayoutMode.SINGLE
        return mode, *widths

    # ------------------------------------------------------------------
    # Hysteresis-aware resize
    # ------------------------------------------------------------------

    def on_resize(self, term_w: int, term_h: int) -> bool:
        """
        Called from _flush_resize. Returns True if mode changed.
        Applies hysteresis: only transition if delta > HYSTERESIS.
        """
        if not self.enabled:
            return False
        new_mode, *_ = self.compute_layout(term_w, term_h)
        if new_mode == self._mode:
            return False
        # Hysteresis check: prevent flapping near boundary
        if new_mode == LayoutMode.SINGLE and self._mode != LayoutMode.SINGLE:
            if term_w >= self._threshold_off - self.HYSTERESIS:
                return False
        if new_mode == LayoutMode.THREE_WIDE and self._mode == LayoutMode.THREE:
            if term_w < self._threshold_wide + self.HYSTERESIS:
                return False
        if new_mode == LayoutMode.THREE and self._mode == LayoutMode.THREE_WIDE:
            if term_w >= self._threshold_wide - self.HYSTERESIS:
                return False
        self._mode = new_mode
        return True

    # ------------------------------------------------------------------
    # Collapse state
    # ------------------------------------------------------------------

    def toggle_left_collapsed(self) -> bool:
        self._left_collapsed = not self._left_collapsed
        return self._left_collapsed

    def toggle_right_collapsed(self) -> bool:
        self._right_collapsed = not self._right_collapsed
        return self._right_collapsed

    def is_collapsed(self, pane_id: PaneId) -> bool:
        if pane_id == PaneId.LEFT:
            return self._left_collapsed
        if pane_id == PaneId.RIGHT:
            return self._right_collapsed
        return False

    # ------------------------------------------------------------------
    # Center split
    # ------------------------------------------------------------------

    def toggle_center_split(self) -> bool:
        self._center_split = not self._center_split
        return self._center_split

    def apply_center_split(self, app: Any) -> None:
        """Toggle center-pane split; updates DOM via CSS class on #pane-center."""
        if not self.enabled:
            return
        try:
            pane_center = app.query_one("#pane-center")
            stub = app.query_one("#split-target-stub")
        except Exception:
            return
        if self._center_split:
            pane_center.add_class("--split")
            stub.display = True
        else:
            pane_center.remove_class("--split")
            stub.display = False

    # ------------------------------------------------------------------
    # Focus
    # ------------------------------------------------------------------

    def focus_pane(self, pane_id: PaneId) -> None:
        self._focused_pane = pane_id

    def next_visible_pane(self, reverse: bool = False) -> PaneId:
        """Return next visible (not-collapsed) pane in cycle order."""
        order = [PaneId.LEFT, PaneId.CENTER, PaneId.RIGHT]
        if reverse:
            order = list(reversed(order))
        # Find index of current
        try:
            idx = order.index(self._focused_pane)
        except ValueError:
            idx = 0
        for i in range(1, len(order) + 1):
            candidate = order[(idx + i) % len(order)]
            if not self.is_collapsed(candidate):
                return candidate
        return PaneId.CENTER

    # ------------------------------------------------------------------
    # DOM application (called from app after resize or toggle)
    # ------------------------------------------------------------------

    def _apply_layout(self, app: Any) -> None:
        """Apply current layout mode to DOM. Idempotent.

        Sets display and width on #pane-left / #pane-center / #pane-right.
        Takes ``app`` as an argument — PaneManager is not a Widget.
        """
        if not self.enabled:
            return
        try:
            app.query_one("#pane-row")
        except Exception:
            return

        _, left_w, center_w, right_w = self.compute_layout(
            app.size.width, app.size.height
        )

        try:
            pane_left = app.query_one("#pane-left")
            pane_center = app.query_one("#pane-center")
            pane_right = app.query_one("#pane-right")
        except Exception:
            return

        if self._mode == LayoutMode.SINGLE:
            pane_left.display = False
            pane_right.display = False
            pane_center.styles.width = center_w
        else:
            pane_left.display = not self._left_collapsed
            pane_right.display = not self._right_collapsed
            if not self._left_collapsed:
                pane_left.styles.width = left_w
            if not self._right_collapsed:
                pane_right.styles.width = right_w
            visible_sides = (
                (left_w if not self._left_collapsed else 0)
                + (right_w if not self._right_collapsed else 0)
            )
            pane_center.styles.width = app.size.width - visible_sides

    def focus_pane_widget(self, pane_id: "PaneId", app: Any) -> None:
        """Focus the primary widget inside a pane and update focused-pane state."""
        self.focus_pane(pane_id)
        try:
            pane = app.query_one(f"#pane-{pane_id.value}")
            children = list(pane.query("*"))
            for child in children:
                if child.can_focus:
                    child.focus()
                    break
            else:
                pane.focus()
        except Exception:
            pass
        # Show "Esc → input" hint when a side pane gets focus
        if pane_id != PaneId.CENTER:
            try:
                from hermes_cli.tui.widgets import HintBar
                app.query_one(HintBar).hint = "Esc → input"
                app.set_timer(3.0, lambda: _clear_hint_if_side_pane(app, pane_id))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Width overrides (from /layout command)
    # ------------------------------------------------------------------

    def set_left_w(self, w: int) -> None:
        self._left_w_override = max(self.MIN_SIDE_W, w)

    def set_right_w(self, w: int) -> None:
        self._right_w_override = max(self.MIN_SIDE_W, w)

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def dump_state(self) -> dict:
        return {
            "mode": self._mode.value,
            "left_collapsed": self._left_collapsed,
            "right_collapsed": self._right_collapsed,
            "left_w": self._left_w_override,
            "right_w": self._right_w_override,
            "center_split": self._center_split,
            "split_target": self._split_target,
        }

    def load_state(self, state: dict) -> None:
        """Load persisted state (mode is advisory; actual mode computed from term size)."""
        self._left_collapsed = bool(state.get("left_collapsed", False))
        self._right_collapsed = bool(state.get("right_collapsed", False))
        if state.get("left_w") is not None:
            self._left_w_override = int(state["left_w"])
        if state.get("right_w") is not None:
            self._right_w_override = int(state["right_w"])
        self._center_split = bool(state.get("center_split", False))
        self._split_target = state.get("split_target")


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(v, hi))


def _int_or_none(v: Any) -> int | None:
    return int(v) if v is not None else None


def _clear_hint_if_side_pane(app: Any, pane_id: "PaneId") -> None:
    """Timer callback: clear 'Esc → input' hint if the side pane is still focused."""
    try:
        from hermes_cli.tui.widgets import HintBar
        pm = getattr(app, "_pane_manager", None)
        if pm is not None and pm._focused_pane == pane_id:
            app.query_one(HintBar).hint = ""
    except Exception:
        pass
