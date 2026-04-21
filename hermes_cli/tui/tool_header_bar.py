"""ToolHeaderBar — horizontal header row for ToolPanel v3 Phase B (§5.2).

Layout:
  StatusGlyph | ToolLabel | ArgSummary(1fr) | ResultPill | LineCountChip | Chevron | DurationChip
  width: 2      6–14        1fr              auto         5               2         6

Narrow terminal adaptation (§3.5):
  < 80 cols: hide ArgSummary
  < 60 cols: also hide ResultPill
  < 40 cols: also hide LineCountChip
  DurationChip: never hidden
"""
from __future__ import annotations

import time
from typing import ClassVar, TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from hermes_cli.tui.animation import PulseMixin

if TYPE_CHECKING:
    from hermes_cli.tui.tool_payload import ResultKind

# ---------------------------------------------------------------------------
# Glyph map
# ---------------------------------------------------------------------------

_GLYPH_MAP: dict[str, tuple[str, str]] = {
    "pending":   ("▸", "$text-muted"),
    "streaming": ("●", "$accent"),
    "ok":        ("✓", "$success"),
    "error":     ("✗", "$error"),
    "retry":     ("⟳", "$warning"),
    "timeout":   ("◔", "$warning"),
}


# ---------------------------------------------------------------------------
# StatusGlyph
# ---------------------------------------------------------------------------


class StatusGlyph(PulseMixin, Widget):
    """1-cell glyph; pulses during streaming via PulseMixin."""

    DEFAULT_CSS = "StatusGlyph { width: 2; height: 1; }"

    _state: str = "pending"

    def set_state(self, state: str) -> None:
        self._state = state
        if state == "streaming":
            self._pulse_start()
        else:
            self._pulse_stop()
        self.refresh()

    def render(self) -> Text:
        glyph, color = _GLYPH_MAP.get(self._state, ("▸", "$text-muted"))
        if self._state == "streaming":
            from hermes_cli.tui.animation import lerp_color
            color_hex = lerp_color("#888888", "#ffbf00", self._pulse_t)
            return Text(f" {glyph}", style=f"bold {color_hex}")
        return Text(f" {glyph}", style=f"bold {color}")


# ---------------------------------------------------------------------------
# LineCountChip
# ---------------------------------------------------------------------------


class LineCountChip(Static):
    """5-char right-aligned chip — shows line count or '—L' placeholder."""

    DEFAULT_CSS = "LineCountChip { width: 5; text-align: right; color: $text-muted; }"

    def __init__(self, **kwargs: object) -> None:
        super().__init__("—L", **kwargs)

    def set_count(self, count: int) -> None:
        if count > 99999:
            self.update(">99K")
        else:
            self.update(f"{count}L")


# ---------------------------------------------------------------------------
# DurationChip
# ---------------------------------------------------------------------------


class DurationChip(Widget):
    """6-char right-aligned duration — live ticker during streaming, frozen at finish."""

    DEFAULT_CSS = "DurationChip { width: 6; text-align: right; color: $text-muted; }"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._start_time: float = time.monotonic()
        self._finished_at: float | None = None
        self._timer: object | None = None

    def on_mount(self) -> None:
        self._timer = self.set_interval(0.5, self._tick)

    def on_unmount(self) -> None:
        if self._timer is not None:
            self._timer.stop()  # type: ignore[attr-defined]
            self._timer = None

    def _tick(self) -> None:
        if self._finished_at is None:
            self.refresh()

    def render(self) -> Text:
        end = self._finished_at if self._finished_at is not None else time.monotonic()
        elapsed = end - self._start_time
        return Text(f" {elapsed:.1f}s", style="dim")

    def set_finished(self, finished_at: float) -> None:
        self._finished_at = finished_at
        if self._timer is not None:
            self._timer.stop()  # type: ignore[attr-defined]
            self._timer = None
        self.refresh()


# ---------------------------------------------------------------------------
# ArgSummary
# ---------------------------------------------------------------------------


class ArgSummary(Widget):
    """1fr arg summary — Python-truncated (not CSS text-overflow, which is invalid in Textual)."""

    DEFAULT_CSS = "ArgSummary { width: 1fr; height: 1; color: $text-muted; }"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._full_text: str = ""

    def set_text(self, text: str) -> None:
        self._full_text = text
        self.refresh()

    def render(self) -> Text:
        if not self._full_text:
            return Text("")
        width = self.size.width
        if width <= 1:
            return Text("")
        from rich.cells import cell_len
        if cell_len(self._full_text) <= width:
            return Text(self._full_text, style="dim")
        out = ""
        used = 0
        for ch in self._full_text:
            ch_w = cell_len(ch)
            if used + ch_w + 1 > width:  # +1 for ellipsis
                break
            out += ch
            used += ch_w
        return Text(out + "…", style="dim")


# ---------------------------------------------------------------------------
# ToolHeaderBar
# ---------------------------------------------------------------------------


class ToolHeaderBar(Widget):
    """Horizontal header row: StatusGlyph + ToolLabel + ArgSummary + ResultPill + chips.

    Spec: tui-tool-panel-v3-spec.md §5.2.
    Emits ToolHeaderBar.Clicked on click so ToolPanel can cycle detail level.
    """

    COMPONENT_CLASSES: ClassVar[set[str]] = {
        "tool-header-bar--glyph",
        "tool-header-bar--label",
        "tool-header-bar--arg-summary",
        "tool-header-bar--pill",
        "tool-header-bar--line-count",
        "tool-header-bar--chevron",
        "tool-header-bar--duration",
    }

    DEFAULT_CSS = "ToolHeaderBar { height: 1; layout: horizontal; padding: 0 1 0 0; }"

    class Clicked(Message):
        """Fired on click — ToolPanel handles by cycling detail level."""

    def __init__(self, label: str = "", **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._label = label
        self._status_glyph: StatusGlyph | None = None
        self._label_widget: Static | None = None
        self._arg_summary: ArgSummary | None = None
        self._result_pill: object | None = None   # ResultPill; TYPE_CHECKING import only
        self._line_count: LineCountChip | None = None
        self._last_state: str = "pending"
        self._rerun_flash_timer: object | None = None
        self._chevron: Static | None = None
        self._duration: DurationChip | None = None

    def compose(self) -> ComposeResult:
        from hermes_cli.tui.result_pill import ResultPill
        self._status_glyph = StatusGlyph(classes="tool-header-bar--glyph")
        self._label_widget = Static(self._label, classes="tool-header-bar--label")
        self._arg_summary = ArgSummary(classes="tool-header-bar--arg-summary")
        self._result_pill = ResultPill("", classes="tool-header-bar--pill")
        self._line_count = LineCountChip(classes="tool-header-bar--line-count")
        self._chevron = Static("▸", classes="tool-header-bar--chevron")
        self._duration = DurationChip(classes="tool-header-bar--duration")
        yield self._status_glyph
        yield self._label_widget
        yield self._arg_summary
        yield self._result_pill  # type: ignore[misc]
        yield self._line_count
        yield self._chevron
        yield self._duration

    def on_mount(self) -> None:
        try:
            if self.app.compact:  # type: ignore[attr-defined]
                self.add_class("--compact")
        except Exception:
            pass

    def on_click(self) -> None:
        self.post_message(self.Clicked())

    def on_resize(self, event: object) -> None:
        """Narrow terminal: collapse chips in priority order."""
        width = getattr(getattr(event, "size", None), "width", 80)
        if self._arg_summary is not None:
            self._arg_summary.display = width >= 80
        if self._result_pill is not None:
            from textual.widget import Widget as _W
            if isinstance(self._result_pill, _W):
                self._result_pill.display = width >= 60
        if self._line_count is not None:
            self._line_count.display = width >= 40

    # ------------------------------------------------------------------
    # Public API called by ToolPanel
    # ------------------------------------------------------------------

    def set_state(self, state: str) -> None:
        self._last_state = state
        if self._status_glyph is not None:
            self._status_glyph.set_state(state)

    def flash_rerun(self) -> None:
        """Flash ⟳ (streaming state) on StatusGlyph for 600ms to confirm rerun queued."""
        if self._status_glyph is None:
            return
        if self._rerun_flash_timer is not None:
            self._rerun_flash_timer.stop()
        self._status_glyph.set_state("streaming")
        self._rerun_flash_timer = self.set_timer(0.6, self._restore_after_rerun)

    def _restore_after_rerun(self) -> None:
        self._rerun_flash_timer = None
        if self._status_glyph is None:
            return
        self._status_glyph.set_state(self._last_state)

    def set_chevron(self, level: int) -> None:
        if self._chevron is not None:
            self._chevron.update("▾" if level >= 2 else "▸")

    def set_line_count(self, count: int) -> None:
        if self._line_count is not None:
            self._line_count.set_count(count)

    def set_kind(self, kind: "ResultKind") -> None:
        from hermes_cli.tui.result_pill import ResultPill
        if isinstance(self._result_pill, ResultPill):
            self._result_pill.set_kind(kind)

    def set_arg_summary(self, text: str) -> None:
        if self._arg_summary is not None:
            self._arg_summary.set_text(text)

    def set_finished(self, finished_at: float) -> None:
        if self._duration is not None:
            self._duration.set_finished(finished_at)
