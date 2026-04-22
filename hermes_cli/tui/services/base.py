"""Base class for all HermesApp behavior services."""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hermes_cli.tui.app import HermesApp


class AppService:
    """
    Base class for HermesApp-backed behavior services.
    Services are plain Python objects; no Textual reactives here.
    Init order on HermesApp is documented and load-bearing (see services/__init__.py).
    """

    def __init__(self, app: "HermesApp") -> None:
        self.app = app
