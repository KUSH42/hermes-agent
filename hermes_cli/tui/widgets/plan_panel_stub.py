"""Placeholder for R1 Plan Panel."""
from __future__ import annotations
from textual.widgets import Static


class PlanPanelStub(Static):
    DEFAULT_CSS = """
    PlanPanelStub {
        color: $text-muted;
        padding: 1 2;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("Plan will appear here — R1", **kwargs)
