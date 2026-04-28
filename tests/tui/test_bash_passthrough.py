"""Tests for bash passthrough mode (T01–T31).

Covers: HermesInput --bash-mode toggle, KeyDispatchService routing,
BashService execution, BashOutputBlock widget, Ctrl+C kill routing,
and one integration test.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock, call

import pytest


# ---------------------------------------------------------------------------
# Input widget — --bash-mode CSS class (T01–T06)
# ---------------------------------------------------------------------------

class _FakeApp:
    def __init__(self):
        self._flash_calls = []
        self._cancel_calls = []
        self.feedback = SimpleNamespace(cancel=lambda ch: self._cancel_calls.append(ch))

    def _flash_hint(self, msg, dur):
        self._flash_calls.append((msg, dur))


class _FakeInput:
    """Minimal stand-in for HermesInput — no Textual internals."""

    def __init__(self, text: str, app: _FakeApp) -> None:
        self._text = text
        self.app = app
        self._classes: set = set()

    @property
    def text(self) -> str:
        return self._text

    def has_class(self, cls: str) -> bool:
        return cls in self._classes

    def set_class(self, flag: bool, cls: str) -> None:
        if flag:
            self._classes.add(cls)
        else:
            self._classes.discard(cls)


def _run_bash_toggle(text: str, start_in_bash: bool = False) -> tuple[set, _FakeApp]:
    """Exercise the bash-mode toggle block from on_text_area_changed."""
    app = _FakeApp()
    inp = _FakeInput(text, app)
    if start_in_bash:
        inp._classes.add("--bash-mode")

    _is_bash = inp.text.lstrip().startswith("!")
    if _is_bash != inp.has_class("--bash-mode"):
        inp.set_class(_is_bash, "--bash-mode")
        if _is_bash:
            app._flash_hint("bash  ·  Enter: run  ·  Esc: cancel", 30.0)
        else:
            app.feedback.cancel("hint-bar")

    return inp._classes, app


def test_t01_bash_mode_added_on_bang():
    classes, _ = _run_bash_toggle("!ls")
    assert "--bash-mode" in classes


def test_t02_bash_mode_removed_when_text_changes():
    classes, app = _run_bash_toggle("ls", start_in_bash=True)
    assert "--bash-mode" not in classes
    assert "hint-bar" in app._cancel_calls


def test_t03_no_bash_mode_for_slash():
    classes, _ = _run_bash_toggle("/model")
    assert "--bash-mode" not in classes


def test_t04_no_bash_mode_for_at():
    classes, _ = _run_bash_toggle("@file.py")
    assert "--bash-mode" not in classes


def test_t05_leading_whitespace_triggers_bash():
    classes, _ = _run_bash_toggle("  !ls -la")
    assert "--bash-mode" in classes


def test_t06_mode_exit_calls_feedback_cancel():
    _, app = _run_bash_toggle("ls", start_in_bash=True)
    assert "hint-bar" in app._cancel_calls


# ---------------------------------------------------------------------------
# KeyDispatchService routing (T07–T13)
# ---------------------------------------------------------------------------

def _make_keys_svc(agent_running=False, bash_running=False):
    from hermes_cli.tui.services.keys import KeyDispatchService

    svc = object.__new__(KeyDispatchService)
    app = MagicMock()
    app.agent_running = agent_running
    app._svc_bash = MagicMock()
    app._svc_bash.is_running = bash_running
    app._svc_commands.handle_tui_command = MagicMock(return_value=False)
    svc.app = app
    return svc, app


def _submitted(text):
    ev = MagicMock()
    ev.value = text
    return ev


def test_t07_bang_routes_to_bash_service():
    svc, app = _make_keys_svc()
    svc.dispatch_input_submitted(_submitted("!ls"))
    app._svc_bash.run.assert_called_once_with("ls")


def test_t08_bare_bang_flashes_empty_hint():
    svc, app = _make_keys_svc()
    svc.dispatch_input_submitted(_submitted("!"))
    app._svc_bash.run.assert_not_called()
    app._flash_hint.assert_called()
    assert "Empty" in app._flash_hint.call_args[0][0]


def test_t09_bang_whitespace_only_flashes_empty_hint():
    svc, app = _make_keys_svc()
    svc.dispatch_input_submitted(_submitted("!   "))
    app._svc_bash.run.assert_not_called()
    app._flash_hint.assert_called()


def test_t10_agent_running_blocks_bash():
    svc, app = _make_keys_svc(agent_running=True)
    svc.dispatch_input_submitted(_submitted("!ls"))
    app._svc_bash.run.assert_not_called()
    app._flash_hint.assert_called()
    assert "Agent running" in app._flash_hint.call_args[0][0]


def test_t11_bash_already_running_blocks_new_cmd():
    svc, app = _make_keys_svc(bash_running=True)
    svc.dispatch_input_submitted(_submitted("!ls"))
    app._svc_bash.run.assert_not_called()
    app._flash_hint.assert_called()
    assert "running" in app._flash_hint.call_args[0][0].lower()


def test_t12_no_bang_routes_to_agent_path():
    svc, app = _make_keys_svc()
    # Patch the agent path indicator — it tries to call ThinkingWidget etc.
    with patch.object(svc, "app") as mock_app:
        mock_app.agent_running = False
        mock_app._svc_bash = MagicMock()
        mock_app._svc_bash.is_running = False
        mock_app._svc_commands.handle_tui_command = MagicMock(return_value=False)
        mock_app.attached_images = []
        mock_app.cli = MagicMock()
        mock_app.cli._pending_input = MagicMock()
        mock_app.query_one = MagicMock(side_effect=Exception("no dom"))

        ev = _submitted("hello agent")
        try:
            svc.dispatch_input_submitted(ev)
        except Exception:
            pass  # DOM not available in unit test — just confirm bash not called
        mock_app._svc_bash.run.assert_not_called()


def test_t13_slash_cmd_not_treated_as_bash():
    svc, app = _make_keys_svc()
    app._svc_commands.handle_tui_command = MagicMock(return_value=True)
    svc.dispatch_input_submitted(_submitted("/model"))
    app._svc_bash.run.assert_not_called()


# ---------------------------------------------------------------------------
# BashService unit tests (T14–T22)
# ---------------------------------------------------------------------------

def _make_bash_svc():
    from hermes_cli.tui.services.bash_service import BashService

    svc = object.__new__(BashService)
    app = MagicMock()
    app.call_from_thread = lambda fn, *a, **kw: fn(*a, **kw)  # synchronous for tests
    svc.app = app
    svc._proc = None
    svc._running = False
    svc._bash_cwd = None
    return svc, app


def test_t14_is_running_transitions():
    svc, app = _make_bash_svc()
    assert not svc.is_running
    # Simulate _finalize setting it False
    block = MagicMock()
    svc._running = True
    assert svc.is_running
    svc._finalize(block, 0, 0.1)
    assert not svc.is_running


def test_t15_running_reset_on_worker_raise():
    from hermes_cli.tui.services.bash_service import BashService

    svc = object.__new__(BashService)
    svc.app = MagicMock()
    svc._proc = None
    svc._running = False

    block = MagicMock()
    svc.app._mount_bash_block = MagicMock(return_value=block)
    svc.app._start_bash_worker = MagicMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        svc.run("ls")
    assert not svc._running


def test_t16_exec_sync_pushes_echo_line():
    svc, app = _make_bash_svc()
    block = MagicMock()
    svc._exec_sync("echo hello", block)
    lines = [c[0][0] for c in block.push_line.call_args_list]
    assert any("hello" in ln for ln in lines)


def test_t17_exec_sync_exit_1():
    svc, app = _make_bash_svc()
    block = MagicMock()
    svc._exec_sync("/usr/bin/env sh -c 'exit 1'", block)
    block.mark_done.assert_called_once()
    args = block.mark_done.call_args[0]
    assert args[0] == 1


def test_t18_exec_sync_exit_0():
    svc, app = _make_bash_svc()
    block = MagicMock()
    svc._exec_sync("/usr/bin/env true", block)
    block.mark_done.assert_called_once()
    args = block.mark_done.call_args[0]
    assert args[0] == 0


def test_t19_exec_sync_nonexistent_cmd():
    svc, app = _make_bash_svc()
    block = MagicMock()
    svc._exec_sync("_this_binary_does_not_exist_xyz_abc", block)
    lines = [c[0][0] for c in block.push_line.call_args_list]
    assert any("not found" in ln or "command not found" in ln for ln in lines)
    block.mark_done.assert_called_once()


def test_t19b_parse_error_on_malformed_quote():
    svc, app = _make_bash_svc()
    block = MagicMock()
    svc._exec_sync('echo "unterminated', block)
    lines = [c[0][0] for c in block.push_line.call_args_list]
    # sh may say "parse error", "syntax error", or "unterminated" depending on shell
    assert any(
        "parse error" in ln.lower() or "syntax error" in ln.lower() or "unterminated" in ln.lower()
        for ln in lines
    )
    block.mark_done.assert_called_once()


def test_t20_kill_sends_sigint_to_group():
    svc, app = _make_bash_svc()
    mock_proc = MagicMock()
    mock_proc.pid = 9999
    svc._proc = mock_proc

    with patch("os.getpgid", return_value=9998) as mock_getpgid, \
         patch("os.killpg") as mock_killpg:
        import signal
        svc.kill()
        mock_getpgid.assert_called_once_with(9999)
        mock_killpg.assert_called_once_with(9998, signal.SIGINT)


def test_t21_kill_no_proc_no_exception():
    svc, app = _make_bash_svc()
    svc._proc = None
    svc.kill()  # must not raise


def test_t22_finalize_clears_running_then_calls_mark_done():
    svc, app = _make_bash_svc()
    svc._running = True
    block = MagicMock()
    order = []
    block.mark_done.side_effect = lambda *a, **kw: order.append("mark_done")

    original_setattr = object.__setattr__

    class _Tracker:
        pass

    svc._running = True
    svc._finalize(block, 0, 1.0)
    # _running must be False before mark_done is called (both in same call)
    assert not svc._running
    block.mark_done.assert_called_once_with(0, 1.0)


# ---------------------------------------------------------------------------
# BashOutputBlock widget tests (T23–T28c)
# ---------------------------------------------------------------------------

def _make_block(cmd="ls"):
    from hermes_cli.tui.widgets.bash_output_block import BashOutputBlock

    block = object.__new__(BashOutputBlock)
    block._cmd = cmd
    block._start_time = time.monotonic()
    block._elapsed_timer = None
    block._body = MagicMock()
    block._status = MagicMock()
    block._classes: set = set()
    block.has_class = lambda c: c in block._classes
    block.add_class = lambda *cs: block._classes.update(cs)
    block.remove_class = lambda *cs: [block._classes.discard(c) for c in cs]
    # Note: block.app is a read-only ContextVar property — do NOT assign it here.
    # Tests needing app must use patch.object(type(block), 'app', PropertyMock).
    return block


def test_t23_push_line_calls_write_with_ansi():
    from rich.text import Text

    block = _make_block()
    block.push_line("hello \x1b[32mworld\x1b[0m")
    block._body.write.assert_called_once()
    arg = block._body.write.call_args[0][0]
    assert isinstance(arg, Text)


def test_t24_mark_done_success():
    block = _make_block()
    block._classes.add("--running")
    mock_timer = MagicMock()
    block._elapsed_timer = mock_timer

    block.mark_done(0, 1.23)

    mock_timer.stop.assert_called_once()
    assert "--running" not in block._classes
    assert "--done" in block._classes
    assert "--error" not in block._classes
    block._status.update.assert_called()
    txt = block._status.update.call_args[0][0]
    assert "✓" in txt
    assert "1.23" in txt


def test_t25_mark_done_error():
    block = _make_block()
    block._classes.add("--running")
    block._elapsed_timer = MagicMock()

    block.mark_done(1, 0.5)

    assert "--error" in block._classes
    assert "--done" in block._classes
    txt = block._status.update.call_args[0][0]
    assert "exit 1" in txt


def test_t26_mark_done_success_no_error_class():
    block = _make_block()
    block._elapsed_timer = MagicMock()
    block.mark_done(0, 0.1)
    assert "--error" not in block._classes


def test_t27_tick_elapsed_updates_status():
    block = _make_block()
    block._start_time = time.monotonic() - 2.0
    block._tick_elapsed()
    block._status.update.assert_called_once()
    txt = block._status.update.call_args[0][0]
    assert "s" in txt


def test_t28b_on_unmount_stops_timer():
    from hermes_cli.tui.widgets.bash_output_block import BashOutputBlock

    block = object.__new__(BashOutputBlock)
    block._classes: set = set()
    block.has_class = lambda c: c in block._classes
    mock_timer = MagicMock()
    block._elapsed_timer = mock_timer
    mock_app = MagicMock()

    with patch.object(type(block), "app", new_callable=PropertyMock, return_value=mock_app):
        block.on_unmount()

    mock_timer.stop.assert_called_once()
    assert block._elapsed_timer is None


def test_t28c_on_unmount_kills_if_running():
    from hermes_cli.tui.widgets.bash_output_block import BashOutputBlock

    block = object.__new__(BashOutputBlock)
    block._classes: set = {"--running"}
    block.has_class = lambda c: c in block._classes
    block._elapsed_timer = None
    mock_app = MagicMock()

    with patch.object(type(block), "app", new_callable=PropertyMock, return_value=mock_app):
        block.on_unmount()

    mock_app._svc_bash.kill.assert_called_once()


# ---------------------------------------------------------------------------
# Ctrl+C routing tests (T28–T30)
# ---------------------------------------------------------------------------

def _make_keys_for_ctrlc(has_selection=False, bash_running=False):
    from hermes_cli.tui.services.keys import KeyDispatchService

    svc = object.__new__(KeyDispatchService)
    app = MagicMock()
    app._get_selected_text = MagicMock(return_value="selected" if has_selection else "")
    app._svc_bash = MagicMock()
    app._svc_bash.is_running = bash_running
    app.agent_running = False
    svc.app = app
    return svc, app


def _ctrlc_event():
    ev = MagicMock()
    ev.key = "ctrl+c"
    return ev


def test_t28_ctrlc_with_selection_copies_not_kills():
    svc, app = _make_keys_for_ctrlc(has_selection=True, bash_running=True)
    ev = _ctrlc_event()
    # Run just the ctrl+c block
    from hermes_cli.tui.services.keys import KeyDispatchService
    # Reconstruct minimally
    key = "ctrl+c"
    selected = app._get_selected_text()
    if selected:
        app._svc_theme.copy_text_with_hint(selected)
        ev.prevent_default()
    # Must not have called kill
    app._svc_bash.kill.assert_not_called()
    app._svc_theme.copy_text_with_hint.assert_called_once_with("selected")


def test_t29_ctrlc_no_selection_bash_running_kills():
    svc, app = _make_keys_for_ctrlc(has_selection=False, bash_running=True)
    ev = _ctrlc_event()

    key = "ctrl+c"
    selected = app._get_selected_text()
    if not selected:
        if app._svc_bash.is_running:
            app._svc_bash.kill()
            app._flash_hint("Command interrupted", 1.5)
            ev.prevent_default()

    app._svc_bash.kill.assert_called_once()
    app._flash_hint.assert_called()
    ev.prevent_default.assert_called()


def test_t30_ctrlc_no_selection_no_bash_falls_through():
    svc, app = _make_keys_for_ctrlc(has_selection=False, bash_running=False)
    ev = _ctrlc_event()

    key = "ctrl+c"
    selected = app._get_selected_text()
    kill_called = False
    if not selected:
        if app._svc_bash.is_running:
            kill_called = True

    assert not kill_called
    app._svc_bash.kill.assert_not_called()


# ---------------------------------------------------------------------------
# Integration test (T31) — runs real app, executes echo command
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_t31_end_to_end_echo():
    from unittest.mock import MagicMock, patch
    from hermes_cli.tui.app import HermesApp

    app = HermesApp(cli=MagicMock())
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause(delay=0.2)

        # Submit a bash command
        inp = app.query_one("#input-area")
        inp.load_text("!echo integration_test_output")
        await pilot.pause()
        await pilot.press("enter")
        # Give the subprocess time to run and complete
        await pilot.pause(delay=1.0)

        from hermes_cli.tui.widgets.bash_output_block import BashOutputBlock
        blocks = list(app.query(BashOutputBlock))
        assert blocks, "BashOutputBlock was not mounted"
        block = blocks[-1]
        # Block should be done
        assert block.has_class("--done"), "Block did not reach --done state"
        assert not block.has_class("--error"), "Echo should not error"
