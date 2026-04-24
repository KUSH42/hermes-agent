"""Backward-compatibility shim — import from hermes_cli.tui.input instead."""
import subprocess  # noqa: F401 — re-exported so tests can patch hermes_cli.tui.input_widget.subprocess
from hermes_cli.tui.input._constants import _sanitize_input_text, _HISTORY_FILE  # noqa: F401
from hermes_cli.tui.input.widget import HermesInput  # noqa: F401

__all__ = ["HermesInput", "_sanitize_input_text", "_HISTORY_FILE", "subprocess"]
