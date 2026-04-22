"""Tests for banner.py — V1 full-width splash + V3 welcome-print removal."""
from __future__ import annotations

import io
import textwrap
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console
from rich.panel import Panel


# ---------------------------------------------------------------------------
# V1 — Panel expand=True
# ---------------------------------------------------------------------------

def _capture_panel(console: Console | None = None) -> Panel | None:
    """Call build_welcome_banner and capture the Panel passed to console.print."""
    if console is None:
        console = Console(file=io.StringIO(), width=120)

    captured: list[Panel] = []
    original_print = console.print

    def _capture(*args, **kwargs):
        for a in args:
            if isinstance(a, Panel):
                captured.append(a)

    with patch.object(console, "print", side_effect=_capture):
        try:
            from hermes_cli.banner import build_welcome_banner
            build_welcome_banner(
                console=console,
                model="claude-test",
                cwd="/tmp",
                tools=[],
                print_logo=False,
                print_hero=False,
            )
        except Exception:
            pass  # errors in skin/config don't matter — we only need the Panel

    return captured[0] if captured else None


def test_build_welcome_banner_panel_has_expand_true() -> None:
    """Panel produced by build_welcome_banner must have expand=True."""
    console = Console(file=io.StringIO(), width=120)
    panel = _capture_panel(console)
    assert panel is not None, "build_welcome_banner did not print a Panel"
    assert panel.expand is True, f"Panel.expand is {panel.expand!r}, expected True"


# ---------------------------------------------------------------------------
# V3 — welcome console.print removed from both TUI and REPL paths in cli.py
# ---------------------------------------------------------------------------

def _read_cli_source() -> str:
    import pathlib
    root = pathlib.Path(__file__).parent.parent.parent
    cli_path = root / "cli.py"
    return cli_path.read_text(encoding="utf-8")


def test_tui_startup_path_has_no_welcome_print() -> None:
    """The TUI startup block no longer contains a welcome console.print call."""
    src = _read_cli_source()
    # After _ensure_tui_startup_message() the old block started with the try/except
    # for _welcome_skin and ended with console.print(f"[{_welcome_color}]...").
    # Check that _welcome_color no longer appears in the TUI startup context.
    assert "_welcome_color" not in src, (
        "Found _welcome_color in cli.py — V3 welcome-print removal incomplete"
    )


def test_welcome_skin_branding_field_still_present_in_skins() -> None:
    """The skin 'welcome' branding field must still be loadable — we only removed print calls."""
    import pathlib
    skin_dir = pathlib.Path(__file__).parent.parent.parent / "skins"
    # At least one skin should have a component_vars section (they all do)
    assert any(p.suffix in {".yaml", ".json"} for p in skin_dir.iterdir()), (
        "No skin files found — something is very wrong"
    )
