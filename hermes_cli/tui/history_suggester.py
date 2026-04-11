"""Fish-style history-based ghost text via Textual's native Suggester API.

``HistorySuggester`` holds a reference to ``HermesInput`` and reads its
``_history`` list at suggestion time, returning the most recent entry that
starts with the current value.

Cache is disabled (``use_cache=False``) because history is append-only and
each session starts fresh.  Textual's per-value cache inside ``Suggester``
would serve stale suggestions if the same value was typed across restarts
within one process.

Wire-up in ``HermesInput.__init__``:
    super().__init__(..., suggester=HistorySuggester(self))

Textual's ``Input`` then handles:
- Rendering the dim suggestion at the correct offset.
- ``cursor_right`` action accepting the suggestion when at end-of-line.

No custom bindings, no extra widgets, no layered Statics.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.suggester import Suggester

if TYPE_CHECKING:
    from hermes_cli.tui.input_widget import HermesInput


class HistorySuggester(Suggester):
    """Prefix match against the most recent matching history entry.

    Returns the **full value** (not just the tail) per the Suggester contract:
    Textual diffs the suggestion against the current value itself to figure
    out what to render as the ghost suffix.
    """

    def __init__(self, input_widget: "HermesInput") -> None:
        super().__init__(use_cache=False, case_sensitive=True)
        self._input = input_widget

    async def get_suggestion(self, value: str) -> str | None:
        if not value:
            return None
        for entry in reversed(self._input._history):
            if entry != value and entry.startswith(value):
                return entry
        return None
