"""Streaming microcopy — per-category progress line for v4 §3."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Union

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


def microcopy_line(
    spec: "ToolSpec",
    state: StreamingState,
    reduced_motion: bool = False,
    shimmer_phase: float = 0.0,
    stalled: bool = False,
    colors: "SkinColors | None" = None,
) -> "Union[str, Text]":
    """Return microcopy for current streaming state, or '' for no line.

    D2: reduced_motion=True → static text for AGENT category.
    D3: all categories append elapsed when state.elapsed_s > 2.0.
    SCT-1: when stalled or colors is provided, returns Text with skin warning style.
    Non-stall + colors=None branches return str fast-path (preserves existing == assertions).
    """
    from hermes_cli.tui.tool_category import ToolCategory

    cat = spec.category
    elapsed_s = state.elapsed_s
    _SEP = _glyph(GLYPH_META_SEP)

    warn_style = f"bold {colors.warning}" if colors is not None else "bold yellow"
    warn_glyph = _glyph(GLYPH_WARNING)
    stall_text = f" {warn_glyph} stalled?"

    def _elapsed_suffix() -> str:
        """D3: append separator + N.Ns when elapsed > 2s."""
        if elapsed_s > 2.0:
            return f" {_SEP} {elapsed_s:.1f}s"
        return ""

    def _apply_stall(base: str) -> "Union[str, Text]":
        """SCT-1: str fast-path when not stalled and no colors; Text otherwise."""
        if not stalled and colors is None:
            return base
        if stalled and colors is None:
            # legacy str behaviour: warning baked unstyled into return string
            return base + stall_text
        # colors provided → Text with styled warning span (only when stalled)
        t = Text(base)
        if stalled:
            t.append(stall_text, style=warn_style)
        return t

    if cat == ToolCategory.SHELL:
        base = f"▸ {state.lines_received} lines {_SEP} {_human_size(state.bytes_received)}"
        if state.rate_bps is not None and state.rate_bps > 0:
            base += f" {_SEP} {state.rate_bps / 1024:.0f} kB/s"
        return _apply_stall(base + _elapsed_suffix())

    if cat == ToolCategory.FILE:
        if spec.primary_result in ("lines", "bytes"):
            base = f"▸ {state.lines_received} lines {_SEP} {_human_size(state.bytes_received)}"
            if state.rate_bps is not None and state.rate_bps > 0:
                base += f" {_SEP} {state.rate_bps / 1024:.0f} kB/s"
            return _apply_stall(base + _elapsed_suffix())
        return _apply_stall(f"▸ {state.lines_received} lines written" + _elapsed_suffix())

    if cat == ToolCategory.SEARCH:
        count = (
            state.matches_so_far
            if state.matches_so_far is not None
            else state.lines_received
        )
        return _apply_stall(f"▸ {count} matches so far…" + _elapsed_suffix())

    if cat == ToolCategory.WEB:
        status = state.last_status or "connecting"
        return _apply_stall(f"▸ {status} {_SEP} {_human_size(state.bytes_received)}" + _elapsed_suffix())

    if cat == ToolCategory.MCP:
        prov = spec.provenance or ""
        server = prov[4:] if prov.startswith("mcp:") else ""
        if not server and "__" in spec.name:
            parts = spec.name.split("__")
            server = parts[1] if len(parts) >= 3 else parts[-1]
        if not server:
            server = spec.name or "?"
        return _apply_stall(f"▸ mcp {_SEP} {server} server" + _elapsed_suffix())

    if cat == ToolCategory.CODE:
        # B1: match SHELL/FILE rate display for consistency
        base = f"▸ {state.lines_received} lines {_SEP} {_human_size(state.bytes_received)}"
        if state.rate_bps is not None and state.rate_bps > 0:
            base += f" {_SEP} {state.rate_bps / 1024:.0f} kB/s"
        return _apply_stall(base + _elapsed_suffix())

    if cat == ToolCategory.AGENT:
        # AGENT branch always returns Text (shimmer or static label).
        if reduced_motion:
            result = Text("▸ thinking…")
        else:
            result = _thinking_shimmer(shimmer_phase, state.elapsed_s)
        if stalled:
            result.append(stall_text, style=warn_style)
        return result

    if cat == ToolCategory.UNKNOWN:
        return _apply_stall(f"▸ {state.lines_received} lines" + _elapsed_suffix())

    return ""
