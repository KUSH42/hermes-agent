"""Pure formatters for GroupHeader right-corner chip (GHF-H1)."""
from __future__ import annotations

import datetime


def _clock_hhmm(ts: float) -> str:
    """Format a monotonic timestamp as HH:MM wall-clock time."""
    import time
    offset = datetime.datetime.now().timestamp() - time.monotonic()
    wall = datetime.datetime.fromtimestamp(ts + offset)
    return wall.strftime("%H:%M")


def terminal_stats(tool_count: int, total_span_s: float, clock_hhmm: str) -> str:
    """Right-corner chip for a terminal group: '<N> tool[s] · <elapsed> · <HH:MM>'"""
    from hermes_cli.tui.widgets.utils import format_elapsed_short
    plural = "tool" if tool_count == 1 else "tools"
    return f"{tool_count} {plural} · {format_elapsed_short(total_span_s)} · {clock_hhmm}"
