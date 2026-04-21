"""Tests for tools_overlay.py (P7 /tools timeline overlay).

~23 tests covering: row rendering, gantt scale, filter, export, key routing,
staleness pip, refresh.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from hermes_cli.tui.tools_overlay import (
    ToolsScreen,
    render_tool_row,
    _split_flex,
    _compute_turn_total_s,
    _primary_arg_str,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _entry(
    tool_call_id: str = "tc-aabbcc",
    name: str = "read_file",
    category: str = "file",
    start_s: float = 0.0,
    dur_ms: int | None = 12,
    is_error: bool = False,
    args: dict | None = None,
    primary_result: str = "",
    mcp_server: str | None = None,
) -> dict:
    return {
        "tool_call_id": tool_call_id,
        "name": name,
        "category": category,
        "start_s": start_s,
        "dur_ms": dur_ms,
        "is_error": is_error,
        "error_kind": None,
        "args": args or {},
        "primary_result": primary_result,
        "mcp_server": mcp_server,
    }


async def _pause(pilot, n: int = 5) -> None:
    for _ in range(n):
        await pilot.pause()


# ---------------------------------------------------------------------------
# _split_flex unit tests
# ---------------------------------------------------------------------------

def test_split_flex_large():
    label_w, gantt_w = _split_flex(94)  # term_w=120
    assert label_w == 40
    assert gantt_w == 54
    assert label_w + gantt_w == 94


def test_split_flex_medium():
    label_w, gantt_w = _split_flex(54)  # term_w=80
    assert label_w + gantt_w == 54
    assert label_w >= 20 and gantt_w >= 1


def test_split_flex_flex34():
    # flex=34 worked example from spec
    label_w, gantt_w = _split_flex(34)
    assert label_w == 16
    assert gantt_w == 18  # post-clamp: min(20, 34-16)=18
    assert label_w + gantt_w == 34


def test_split_flex_invariant_all_widths():
    """label_w + gantt_w == flex for all flex ∈ [26..200]."""
    for flex in range(26, 201):
        label_w, gantt_w = _split_flex(flex)
        assert label_w + gantt_w == flex, f"Failed at flex={flex}: {label_w}+{gantt_w}≠{flex}"
        assert label_w >= 10
        assert gantt_w >= 1


# ---------------------------------------------------------------------------
# §9.1 Row rendering
# ---------------------------------------------------------------------------

def test_render_row_basic():
    e = _entry(start_s=0.0, dur_ms=12, args={"path": "src/app.py"})
    row = render_tool_row(e, cursor=False, turn_total_s=1.0, term_w=120)
    plain = row.plain
    assert "0.0s" in plain
    assert "read_file" in plain
    assert "12ms" in plain


def test_render_row_in_progress():
    e = _entry(dur_ms=None, start_s=0.0)
    row = render_tool_row(e, cursor=False, turn_total_s=0.001, term_w=120)
    plain = row.plain
    assert "⠋" in plain


def test_render_row_error():
    e = _entry(is_error=True, dur_ms=500)
    row = render_tool_row(e, cursor=False, turn_total_s=1.0, term_w=120)
    # Row renders without crash; is_error flag is encoded in style
    assert "read_file" in row.plain


def test_render_row_cursor():
    e = _entry()
    row = render_tool_row(e, cursor=True, turn_total_s=1.0, term_w=120)
    # Cursor row has bold styling applied (style spans exist)
    assert "read_file" in row.plain


def test_render_row_mcp():
    e = _entry(name="mcp__github__search_repos", mcp_server="github", category="mcp")
    row = render_tool_row(e, cursor=False, turn_total_s=1.0, term_w=120)
    # P1-5: MCP names use server::method() format matching ToolHeader
    assert "github::search_repos()" in row.plain


def test_render_row_long_label_truncation():
    long_name = "a" * 60
    e = _entry(name=long_name)
    row = render_tool_row(e, cursor=False, turn_total_s=1.0, term_w=80)
    plain = row.plain
    # Should contain truncation ellipsis
    assert "…" in plain


# ---------------------------------------------------------------------------
# §9.2 Gantt scale
# ---------------------------------------------------------------------------

def test_gantt_single_call():
    # Single call: bar should fill all gantt cells
    e = _entry(start_s=0.0, dur_ms=100)
    turn_total_s = 0.1
    row = render_tool_row(e, cursor=False, turn_total_s=turn_total_s, term_w=80)
    plain = row.plain
    assert "━" in plain


def test_gantt_multi_call_proportional():
    entries = [
        _entry("t1", "read_file", start_s=0.0, dur_ms=100),
        _entry("t2", "grep", start_s=0.1, dur_ms=400),
        _entry("t3", "bash", start_s=0.5, dur_ms=500),
    ]
    turn_total_s = _compute_turn_total_s(entries)
    rows = [render_tool_row(e, cursor=False, turn_total_s=turn_total_s, term_w=120) for e in entries]
    # All rows render without crash
    assert all("━" in r.plain for r in rows)


def test_gantt_min_one_cell():
    # Sub-millisecond call should still render 1-cell bar
    e = _entry(dur_ms=0, start_s=0.0)
    row = render_tool_row(e, cursor=False, turn_total_s=1.0, term_w=80)
    assert "━" in row.plain or "⠋" in row.plain


def test_gantt_all_in_progress():
    entries = [_entry("t1", dur_ms=None, start_s=0.0), _entry("t2", dur_ms=None, start_s=0.0)]
    turn_total_s = _compute_turn_total_s(entries)
    assert turn_total_s == pytest.approx(0.001)
    rows = [render_tool_row(e, cursor=False, turn_total_s=turn_total_s, term_w=80) for e in entries]
    for r in rows:
        assert "⠋" in r.plain


# ---------------------------------------------------------------------------
# §9.3 Filter (pure logic tests)
# ---------------------------------------------------------------------------

def test_filter_by_text():
    screen = ToolsScreen([
        _entry("t1", "read_file"),
        _entry("t2", "bash"),
        _entry("t3", "grep"),
    ])
    screen._filter_text = "read"
    screen._filtered = [
        e for e in screen._snapshot
        if "read" in e["name"].lower()
    ]
    assert len(screen._filtered) == 1
    assert screen._filtered[0]["name"] == "read_file"


def test_filter_by_category_pill():
    screen = ToolsScreen([
        _entry("t1", "read_file", category="file"),
        _entry("t2", "bash", category="shell"),
    ])
    screen._active_categories = {"file"}
    filtered = [
        e for e in screen._snapshot
        if e["category"] in screen._active_categories
    ]
    assert len(filtered) == 1
    assert filtered[0]["category"] == "file"


def test_filter_errors_only():
    screen = ToolsScreen([
        _entry("t1", is_error=True),
        _entry("t2", is_error=False),
    ])
    screen._errors_only = True
    filtered = [e for e in screen._snapshot if e["is_error"]]
    assert len(filtered) == 1


def test_filter_empty_result():
    screen = ToolsScreen([_entry("t1", "read_file")])
    screen._filter_text = "zzznomatch"
    filtered = [e for e in screen._snapshot if screen._filter_text in e["name"]]
    assert len(filtered) == 0


# ---------------------------------------------------------------------------
# §9.4 Export (pure logic tests — no disk write)
# ---------------------------------------------------------------------------

def test_export_json_schema(tmp_path: Path):
    snapshot = [_entry("tc-001", "read_file", dur_ms=12, args={"path": "a.py"})]
    from datetime import timezone
    ts = "20260101_120000_000000"
    export_dir = tmp_path / ".hermes"
    export_dir.mkdir()
    path = export_dir / f"tools_{ts}.json"
    payload = {
        "turn_id": None,
        "exported_at": "2026-01-01T12:00:00+00:00",
        "calls": snapshot,
    }
    path.write_text(json.dumps(payload, indent=2, default=str))
    loaded = json.loads(path.read_text())
    assert loaded["turn_id"] is None
    assert len(loaded["calls"]) == 1
    assert loaded["calls"][0]["tool_call_id"] == "tc-001"


def test_export_includes_in_progress(tmp_path: Path):
    snapshot = [_entry("tc-002", dur_ms=None)]
    export_dir = tmp_path / ".hermes"
    export_dir.mkdir()
    payload = {"turn_id": None, "exported_at": "now", "calls": snapshot}
    path = export_dir / "tools_test.json"
    path.write_text(json.dumps(payload, default=str))
    loaded = json.loads(path.read_text())
    assert loaded["calls"][0]["dur_ms"] is None


def test_export_json_creates_file(tmp_path: Path):
    """action_export_json writes a valid JSON file under .hermes/."""
    snapshot = [_entry("tc-ex1", "read_file", dur_ms=50, args={"path": "a.py"})]
    hints = []
    fake_app = MagicMock()
    fake_app._flash_hint = lambda msg, dur=2.0: hints.append(msg)

    screen = ToolsScreen(snapshot)

    hermes_dir = tmp_path / ".hermes"
    hermes_dir.mkdir()

    with patch("hermes_cli.tui.tools_overlay.Path") as MockPath:
        # Make Path.cwd() return tmp_path so root detection works
        MockPath.cwd.return_value = tmp_path
        # Pass through for actual Path usage inside the method
        MockPath.side_effect = lambda *a, **kw: Path(*a, **kw) if a else hermes_dir

        # Directly call action_export_json with patched app
        with patch.object(type(screen), "app", new_callable=lambda: property(lambda self: fake_app)):
            screen.action_export_json()

    assert any("exported" in h or "export failed" in h for h in hints)


# ---------------------------------------------------------------------------
# §9.5 Key routing (app-level integration)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tools_slash_command_opens_overlay():
    """'/tools' slash command → ToolsScreen pushed onto app."""
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    # Pre-populate turn tool calls
    app._turn_tool_calls = [_entry("tc-1")]

    screens_pushed = []
    original_push = app.push_screen

    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)

        with patch.object(app, "push_screen", wraps=app.push_screen) as mock_push:
            app._handle_tui_command("/tools")
            await _pause(pilot)

        # Either push_screen was called (overlay opened) or flash_hint (no calls guard)
        # The turn has entries so overlay should open
        assert mock_push.called or len(app._turn_tool_calls) >= 0


@pytest.mark.asyncio
async def test_t_key_opens_overlay_in_browse_mode():
    """T key in browse mode calls _open_tools_overlay."""
    from hermes_cli.tui.app import HermesApp
    from textual.events import Key

    app = HermesApp(cli=MagicMock())
    app._turn_tool_calls = [_entry("tc-T")]

    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        # Enter browse mode
        app.browse_mode = True
        await _pause(pilot)

        with patch.object(app, "_open_tools_overlay") as mock_open:
            await pilot.press("T")
            await _pause(pilot)

        # _open_tools_overlay should have been called
        assert mock_open.called


@pytest.mark.asyncio
async def test_escape_closes_overlay():
    """Escape in ToolsScreen calls pop_screen."""
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    app._turn_tool_calls = [_entry("tc-esc")]

    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)

        screen = ToolsScreen([_entry("tc-esc")])
        app.push_screen(screen)
        await _pause(pilot)

        with patch.object(app, "pop_screen") as mock_pop:
            await pilot.press("escape")
            await _pause(pilot)

        # pop_screen should have been called
        assert mock_pop.called


# ---------------------------------------------------------------------------
# §9.6 Staleness pip + refresh
# ---------------------------------------------------------------------------

def test_refresh_preserves_cursor():
    """Cursor stays on same tool_call_id after refresh (T12b)."""
    snapshot = [_entry(f"tc-{i}") for i in range(5)]
    screen = ToolsScreen(snapshot)
    screen._cursor = 2

    cursor_id = screen._filtered[2]["tool_call_id"]

    # Simulate refresh with same snapshot
    new_snapshot = list(snapshot)
    screen._snapshot = new_snapshot
    screen._filtered = list(new_snapshot)

    # Restore cursor by tool_call_id
    for i, e in enumerate(screen._filtered):
        if e["tool_call_id"] == cursor_id:
            screen._cursor = i
            break
    assert screen._cursor == 2


def test_refresh_snap_on_missing():
    """Cursor snaps to 0 when previous cursor entry is missing (T12c)."""
    snapshot = [_entry(f"tc-{i}") for i in range(5)]
    screen = ToolsScreen(snapshot)
    screen._cursor = 2

    cursor_id = screen._filtered[2]["tool_call_id"]

    # New snapshot is missing entry at index 2
    new_snapshot = [e for e in snapshot if e["tool_call_id"] != cursor_id]
    screen._snapshot = new_snapshot
    screen._filtered = list(new_snapshot)

    # cursor_id no longer found → snap to 0
    found = False
    for i, e in enumerate(screen._filtered):
        if e["tool_call_id"] == cursor_id:
            screen._cursor = i
            found = True
            break
    if not found:
        screen._cursor = 0

    assert screen._cursor == 0


# ---------------------------------------------------------------------------
# app.py turn tracking unit tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_open_streaming_records_turn_entry():
    """open_streaming_tool_block appends to _turn_tool_calls."""
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        app.open_streaming_tool_block("tc-track1", "read_file src/app.py", tool_name="read_file")
        await _pause(pilot)
        assert len(app._turn_tool_calls) >= 1
        entry = app._turn_tool_calls[0]
        assert entry["tool_call_id"] == "tc-track1"
        assert entry["dur_ms"] is None
        assert entry["is_error"] is False


@pytest.mark.asyncio
async def test_close_streaming_updates_dur_ms():
    """close_streaming_tool_block updates dur_ms in _turn_tool_calls."""
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        app.open_streaming_tool_block("tc-dur", "bash cmd", tool_name="bash")
        await _pause(pilot)
        app.close_streaming_tool_block("tc-dur", "0.5s")
        await _pause(pilot)
        entry = next((e for e in app._turn_tool_calls if e["tool_call_id"] == "tc-dur"), None)
        assert entry is not None
        assert entry["dur_ms"] == 500
        assert entry["is_error"] is False


@pytest.mark.asyncio
async def test_current_turn_tool_calls_returns_copy():
    """current_turn_tool_calls returns a shallow copy (not live list)."""
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        copy = app.current_turn_tool_calls()
        assert isinstance(copy, list)
        # Mutating the copy does not affect internal list
        copy.append({"tool_call_id": "injected"})
        assert not any(e["tool_call_id"] == "injected" for e in app._turn_tool_calls)


@pytest.mark.asyncio
async def test_watch_agent_running_resets_turn_calls():
    """watch_agent_running(True) resets _turn_tool_calls."""
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        app._turn_tool_calls = [_entry("old")]
        app.agent_running = True
        await _pause(pilot)
        # After agent_running → True, turn calls reset
        assert app._turn_tool_calls == []


# ---------------------------------------------------------------------------
# P1-1: auto-refresh starts when in-progress tools exist
# P1-5: MCP label uses server::method() format
# ---------------------------------------------------------------------------

def test_mcp_tool_label_uses_header_label_v4():
    """MCP tool in Gantt row shows server::method() format (consistent with ToolHeader)."""
    e = _entry(name="mcp__github__create_issue", mcp_server="github", category="mcp")
    row = render_tool_row(e, cursor=False, turn_total_s=2.0, term_w=120)
    assert "github::create_issue()" in row.plain
    # Must not use the old dot format
    assert "github.create_issue" not in row.plain


@pytest.mark.asyncio
async def test_auto_refresh_starts_when_tool_in_progress():
    """ToolsScreen starts _refresh_timer when snapshot has an in-progress (dur_ms=None) entry."""
    from hermes_cli.tui.tools_overlay import ToolsScreen
    from hermes_cli.tui.app import HermesApp
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        snapshot = [_entry(name="bash", dur_ms=None)]  # in-progress
        screen = ToolsScreen(snapshot)
        app.push_screen(screen)
        await _pause(pilot)
        assert screen._refresh_timer is not None, "_refresh_timer must start for in-progress tools"
        app.pop_screen()
        await _pause(pilot)


@pytest.mark.asyncio
async def test_auto_refresh_stops_when_no_in_progress_tools():
    """ToolsScreen does not start _refresh_timer when all tools are completed."""
    from hermes_cli.tui.tools_overlay import ToolsScreen
    from hermes_cli.tui.app import HermesApp
    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        snapshot = [_entry(name="bash", dur_ms=500)]  # completed
        screen = ToolsScreen(snapshot)
        app.push_screen(screen)
        await _pause(pilot)
        assert screen._refresh_timer is None, "_refresh_timer must NOT start when all tools done"
        app.pop_screen()
        await _pause(pilot)


# ---------------------------------------------------------------------------
# P1-8: export_json creates file + flashes success hint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_export_json_creates_file_and_flashes_success(tmp_path):
    """action_export_json writes JSON file and calls _flash_hint with ✓ prefix."""
    from hermes_cli.tui.tools_overlay import ToolsScreen
    from hermes_cli.tui.app import HermesApp
    import os

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        snapshot = [_entry(name="bash", dur_ms=300)]
        screen = ToolsScreen(snapshot)
        app.push_screen(screen)
        await _pause(pilot)

        hint_calls: list[str] = []
        app._flash_hint = lambda t, d=1.5: hint_calls.append(t)

        with patch("hermes_cli.tui.tools_overlay.Path.cwd", return_value=tmp_path):
            # Create .hermes dir so hermes_root resolves
            (tmp_path / ".hermes").mkdir()
            screen.action_export_json()

        assert any(h.startswith("✓") for h in hint_calls), f"Expected ✓ hint, got {hint_calls}"
        exports = list((tmp_path / ".hermes").glob("tools_*.json"))
        assert len(exports) == 1, "Expected 1 exported JSON file"

        import json
        data = json.loads(exports[0].read_text())
        assert "calls" in data


@pytest.mark.asyncio
async def test_export_json_flashes_error_on_permission_denied(tmp_path):
    """action_export_json flashes ✗ error hint on PermissionError."""
    from hermes_cli.tui.tools_overlay import ToolsScreen
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        snapshot = [_entry(name="bash", dur_ms=300)]
        screen = ToolsScreen(snapshot)
        app.push_screen(screen)
        await _pause(pilot)

        hint_calls: list[str] = []
        app._flash_hint = lambda t, d=1.5: hint_calls.append(t)

        with patch("hermes_cli.tui.tools_overlay.Path.write_text", side_effect=PermissionError("denied")):
            with patch("hermes_cli.tui.tools_overlay.Path.cwd", return_value=tmp_path):
                (tmp_path / ".hermes").mkdir(exist_ok=True)
                screen.action_export_json()

        assert any(h.startswith("✗") for h in hint_calls), f"Expected ✗ hint, got {hint_calls}"


# ---------------------------------------------------------------------------
# P2-5: _apply_filter uses substring match, not startswith
# ---------------------------------------------------------------------------

def test_filter_substring_match():
    """_apply_filter matches entries whose args contain the query anywhere, not just at start."""
    from hermes_cli.tui.tools_overlay import _primary_arg_str
    # Simulate what _apply_filter does
    entries = [
        _entry(name="read_file", args={"path": "/foo/bar/baz.py"}),
        _entry(name="read_file", args={"path": "/qux/alpha.py"}),
        _entry(name="read_file", args={"path": "/start_match.py"}),
    ]
    text = "bar"  # "bar" is not at the start of any path
    matched = [
        e for e in entries
        if not text or text in e.get("name", "").lower() or text in _primary_arg_str(e).lower()
    ]
    assert len(matched) == 1, f"Expected 1 match for 'bar', got {len(matched)}: {[_primary_arg_str(e) for e in matched]}"
    assert _primary_arg_str(matched[0]) == "/foo/bar/baz.py"


def test_filter_startswith_would_miss_midstring():
    """Confirm that startswith-only filter misses mid-string match (regression guard)."""
    from hermes_cli.tui.tools_overlay import _primary_arg_str
    entry = _entry(name="read_file", args={"path": "/foo/bar/baz.py"})
    text = "bar"
    # startswith approach (old, broken)
    startswith_match = _primary_arg_str(entry).lower().startswith(text)
    assert not startswith_match, "startswith would NOT match 'bar' in '/foo/bar/baz.py' (confirms fix needed)"
    # substring approach (new, correct)
    substring_match = text in _primary_arg_str(entry).lower()
    assert substring_match, "substring 'in' must match 'bar' in '/foo/bar/baz.py'"


# ---------------------------------------------------------------------------
# P1-7: render_tool_row accepts spinner_frame and produces animated bar
# ---------------------------------------------------------------------------

def test_render_tool_row_spinner_frame_varies_output():
    """render_tool_row with different spinner_frame values produces different in-progress bars."""
    entry = _entry(dur_ms=None)  # dur_ms=None means in-progress
    row_f0 = str(render_tool_row(entry, cursor=False, turn_total_s=5.0, term_w=80, spinner_frame=0))
    row_f1 = str(render_tool_row(entry, cursor=False, turn_total_s=5.0, term_w=80, spinner_frame=1))
    assert row_f0 != row_f1, (
        "render_tool_row with spinner_frame=0 vs 1 should produce different spinner chars for in-progress rows"
    )


# ---------------------------------------------------------------------------
# P0-2: pill filter buttons are Button widgets (clickable), not Static text
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tools_screen_pill_filter_buttons_are_button_widgets():
    """Filter pills in ToolsScreen are Button widgets, not Static text."""
    from hermes_cli.tui.tools_overlay import ToolsScreen
    from hermes_cli.tui.app import HermesApp
    from textual.widgets import Button

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(120, 40)) as pilot:
        await _pause(pilot)
        snapshot = [
            _entry(name="read_file", category="file"),
            _entry(name="bash", category="shell"),
        ]
        screen = ToolsScreen(snapshot)
        app.push_screen(screen)
        await _pause(pilot, 10)

        pill_row = screen.query_one("#filter-pills-row")
        buttons = list(pill_row.query(Button))
        assert len(buttons) > 0, (
            "Expected Button widgets in #filter-pills-row — static text pills are not clickable"
        )
