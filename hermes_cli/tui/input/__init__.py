"""Input subsystem for Hermes TUI.

Public surface: HermesInput, _sanitize_input_text.
"""
from ._constants import _sanitize_input_text
from .widget import HermesInput

__all__ = ["HermesInput", "_sanitize_input_text"]
