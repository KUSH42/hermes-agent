"""Backward-compatibility shim — import from hermes_cli.tui.input instead."""
from hermes_cli.tui.input._constants import _sanitize_input_text  # noqa: F401
from hermes_cli.tui.input.widget import HermesInput  # noqa: F401

__all__ = ["HermesInput", "_sanitize_input_text"]
