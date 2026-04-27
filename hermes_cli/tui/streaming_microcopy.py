"""Streaming microcopy — per-category progress line for v4 §3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.text import Text

from hermes_cli.tui.body_renderers._grammar import (
    GLYPH_META_SEP,
    GLYPH_WARNING,
    glyph as _glyph,
)

if TYPE_CHECKING:
    from hermes_cli.tui.tool_category import ToolSpec
    from hermes_cli.tui.body_renderers._grammar import SkinColors


@dataclass
class StreamingState:
    lines_received: int
    bytes_received: int
    elapsed_s: float
    total_lines: int | None = None
    total_bytes: int | None = None
    last_status: str | None = None
    matches_so_far: int | None = None
    rate_bps: float | None = None  # B2: streaming rate in bytes/s


def _kb(b: int) -> str:
    """Legacy alias — prefer _human_size for new call sites."""
    return _human_size(b)


def _human_size(b: int) -> str:
    """D1: human-readable byte count with B/kB/MB suffixes."""
    if b < 1024:
        return f"{b}B"
    if b < 1_048_576:
        return f"{b / 1024:.1f}kB"
    return f"{b / 1_048_576:.1f}MB"


def _thinking_shimmer(shimmer_phase: float, elapsed_s: float = 0.0) -> Text:
    """Animated shimmer for AGENT category microcopy."""
    from hermes_cli.tui.animation import lerp_color
    label = "Thinking…"
    phase = shimmer_phase % 2.0
    t = phase if phase <= 1.0 else 2.0 - phase
    ACCENT = "#00ff99"
    DIM = "#446644"
    result = Text("▸ ", style="dim")
    for i, ch in enumerate(label):
        char_t = (t + i / len(label)) % 1.0
        color = lerp_color(DIM, ACCENT, char_t)
        result.append(ch, style=f"bold {color}")
    elapsed_str = f"  {int(elapsed_s)}s" if elapsed_s >= 1.0 else ""
    result.append(elapsed_str, style="dim")
    return result


_GUTTER = "▸ "
_GUTTER_STYLE = "dim"
_VALUE_STYLE = ""
_SEP_STYLE = "dim"
_ELAPSED_STYLE = "dim"
_STALL_STYLE = "bold yellow"


def _stall_text(stalled: bool, colors: "SkinColors | None" = None) -> "Text | None":
    if not stalled:
        return None
    warn_style = f"bold {colors.warning}" if colors is not None else _STALL_STYLE
    warn_glyph = _glyph(GLYPH_WARNING)
    t = Text()
    t.append(f" {warn_glyph} stalled?", style=warn_style)
    return t


def _microcopy_text(
    segments: list[tuple[str, str]],
    elapsed_s: float,
    stall: "Text | None",
) -> Text:
    _SEP = _glyph(GLYPH_META_SEP)
    t = Text()
    t.append(_GUTTER, style=_GUTTER_STYLE)
    for i, (frag, style) in enumerate(segments):
        if i > 0:
            t.append(f" {_SEP} ", style=_SEP_STYLE)
        t.append(frag, style=style)
    if elapsed_s > 2.0:
        t.append(f" {_SEP} ", style=_SEP_STYLE)
        t.append(f"{elapsed_s:.1f}s", style=_ELAPSED_STYLE)
    if stall is not None:
        t.append_text(stall)
    return t


def microcopy_line(
    spec: "ToolSpec",
    state: StreamingState,
    reduced_motion: bool = False,
    shimmer_phase: float = 0.0,
    stalled: bool = False,
    colors: "SkinColors | None" = None,
) -> Text:
    """Return microcopy for current streaming state, or empty Text for no line.

    D2: reduced_motion=True → static text for AGENT category.
    D3: all categories append elapsed when state.elapsed_s > 2.0.
    SCT-1: colors provides skin-aware warning style for stall indicator.
    MCC-1: all branches always return Text.
    """
    from hermes_cli.tui.tool_category import ToolCategory

    cat = spec.category
    elapsed_s = state.elapsed_s
    stall = _stall_text(stalled, colors)

    if cat == ToolCategory.SHELL:
        segments = [
            (f"{state.lines_received} lines", _VALUE_STYLE),
            (_human_size(state.bytes_received), _VALUE_STYLE),
        ]
        if state.rate_bps is not None and state.rate_bps > 0:
            segments.append((f"{state.rate_bps / 1024:.0f} kB/s", _VALUE_STYLE))
        return _microcopy_text(segments, elapsed_s, stall)

    if cat == ToolCategory.FILE:
        if spec.primary_result in ("lines", "bytes"):
            segments = [
                (f"{state.lines_received} lines", _VALUE_STYLE),
                (_human_size(state.bytes_received), _VALUE_STYLE),
            ]
            if state.rate_bps is not None and state.rate_bps > 0:
                segments.append((f"{state.rate_bps / 1024:.0f} kB/s", _VALUE_STYLE))
            return _microcopy_text(segments, elapsed_s, stall)
        segments = [(f"{state.lines_received} lines written", _VALUE_STYLE)]
        return _microcopy_text(segments, elapsed_s, stall)

    if cat == ToolCategory.SEARCH:
        count = (
            state.matches_so_far
            if state.matches_so_far is not None
            else state.lines_received
        )
        segments = [(f"{count} matches so far…", _VALUE_STYLE)]
        return _microcopy_text(segments, elapsed_s, stall)

    if cat == ToolCategory.WEB:
        status = state.last_status or "connecting"
        segments = [
            (status, _VALUE_STYLE),
            (_human_size(state.bytes_received), _VALUE_STYLE),
        ]
        return _microcopy_text(segments, elapsed_s, stall)

    if cat == ToolCategory.MCP:
        prov = spec.provenance or ""
        server = prov[4:] if prov.startswith("mcp:") else ""
        if not server and "__" in spec.name:
            parts = spec.name.split("__")
            server = parts[1] if len(parts) >= 3 else parts[-1]
        if not server:
            server = spec.name or "?"
        segments = [
            ("mcp", _VALUE_STYLE),
            (f"{server} server", _VALUE_STYLE),
        ]
        return _microcopy_text(segments, elapsed_s, stall)

    if cat == ToolCategory.CODE:
        # B1: match SHELL/FILE rate display for consistency
        segments = [
            (f"{state.lines_received} lines", _VALUE_STYLE),
            (_human_size(state.bytes_received), _VALUE_STYLE),
        ]
        if state.rate_bps is not None and state.rate_bps > 0:
            segments.append((f"{state.rate_bps / 1024:.0f} kB/s", _VALUE_STYLE))
        return _microcopy_text(segments, elapsed_s, stall)

    if cat == ToolCategory.AGENT:
        # D2: static text when reduced_motion
        if reduced_motion:
            result = Text("▸ thinking…")
            if (st := _stall_text(stalled, colors)) is not None:
                result.append_text(st)
            return result
        result = _thinking_shimmer(shimmer_phase, state.elapsed_s)
        if (st := _stall_text(stalled, colors)) is not None:
            result.append_text(st)
        return result

    if cat == ToolCategory.UNKNOWN:
        segments = [(f"{state.lines_received} lines", _VALUE_STYLE)]
        return _microcopy_text(segments, elapsed_s, stall)

    return Text()
