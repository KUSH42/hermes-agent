"""Mech Sweep E — Threading & Async Hardening tests.

THR-1: asyncio.ensure_future → create_task in tools_overlay.py
THR-2: MpvPoller callback marshalling through call_from_thread
THR-3: _NotifyListener docstring threading contract
THR-4: services/io.py call_soon_threadsafe comment
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import logging
import unittest
from unittest.mock import MagicMock, Mock, call


# ─────────────────────────────────────────────────────────────────────────────
# THR-1: ToolsScreen asyncio.create_task
# ─────────────────────────────────────────────────────────────────────────────

class TestThr1ToolsScreenCreateTask(unittest.IsolatedAsyncioTestCase):

    def _make_overlay(self):
        from hermes_cli.tui.tools_overlay import ToolsScreen
        snapshot = [{"tool_call_id": "t1", "name": "bash", "dur_ms": None}]
        overlay = ToolsScreen(snapshot)
        return overlay

    async def test_rebuild_task_stored_on_self(self):
        overlay = self._make_overlay()
        # _update_staleness_pip is sync; it creates the task inside the running loop
        overlay._update_staleness_pip()
        self.assertIsNotNone(overlay._rebuild_task)
        self.assertIsInstance(overlay._rebuild_task, asyncio.Task)
        self.assertFalse(overlay._rebuild_task.done())
        # cleanup
        overlay._rebuild_task.cancel()
        await asyncio.sleep(0)

    async def test_rebuild_task_cancelled_on_unmount(self):
        overlay = self._make_overlay()
        overlay._update_staleness_pip()
        task = overlay._rebuild_task
        self.assertIsNotNone(task)
        self.assertFalse(task.done())
        overlay.on_unmount()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(task), timeout=0.5)
        self.assertTrue(task.cancelled())

    def test_no_ensure_future_in_tools_overlay(self):
        import hermes_cli.tui.tools_overlay as mod
        import pathlib
        src = pathlib.Path(mod.__file__).read_text()
        tree = ast.parse(src)
        violations = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                if (
                    isinstance(func.value, ast.Name)
                    and func.value.id == "asyncio"
                    and func.attr == "ensure_future"
                ):
                    violations.append(node.lineno)
            elif isinstance(func, ast.Name) and func.id == "ensure_future":
                violations.append(node.lineno)
        self.assertEqual(
            violations,
            [],
            f"asyncio.ensure_future still present at line(s): {violations}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# THR-2: MpvPoller marshalling
# ─────────────────────────────────────────────────────────────────────────────

class TestThr2MpvPollerMarshalled(unittest.TestCase):

    def _make_poller(self, ctrl=None, app=None, on_tick=None, on_end=None):
        from textual.app import App
        from hermes_cli.tui.media_player import MpvPoller
        if app is None:
            app = MagicMock(spec=App)
        if on_tick is None:
            on_tick = Mock()
        if on_end is None:
            on_end = Mock()
        return MpvPoller(ctrl or MagicMock(), app, on_tick=on_tick, on_end=on_end), app, on_tick, on_end

    def test_on_tick_marshalled_through_app(self):
        from textual.app import App
        app = MagicMock(spec=App)
        ctrl = MagicMock()
        ctrl.is_alive.return_value = True
        ctrl.get_position.return_value = 1.0
        ctrl.get_duration.return_value = 10.0
        tick_mock = Mock()
        poller, _, _, _ = self._make_poller(ctrl=ctrl, app=app, on_tick=tick_mock)
        result = poller._poll_once()
        self.assertTrue(result)
        app.call_from_thread.assert_called_once_with(tick_mock, 1.0, 10.0)

    def test_on_end_marshalled_through_app(self):
        from textual.app import App
        app = MagicMock(spec=App)
        ctrl = MagicMock()
        ctrl.is_alive.return_value = False
        end_mock = Mock()
        poller, _, _, _ = self._make_poller(ctrl=ctrl, app=app, on_end=end_mock)
        result = poller._poll_once()
        self.assertFalse(result)
        app.call_from_thread.assert_called_once_with(end_mock)

    def test_callbacks_not_invoked_directly(self):
        from textual.app import App
        app = MagicMock(spec=App)
        # call_from_thread records but does NOT invoke the callable
        app.call_from_thread = MagicMock()
        ctrl = MagicMock()
        ctrl.is_alive.return_value = True
        ctrl.get_position.return_value = 5.0
        ctrl.get_duration.return_value = 60.0
        tick_mock = Mock()
        poller, _, _, _ = self._make_poller(ctrl=ctrl, app=app, on_tick=tick_mock)
        poller._poll_once()
        self.assertEqual(tick_mock.call_count, 0)
        self.assertEqual(app.call_from_thread.call_count, 1)

    def test_runtime_error_during_shutdown_exits_cleanly(self):
        from textual.app import App
        app = MagicMock(spec=App)
        app.call_from_thread.side_effect = RuntimeError("App not running")
        ctrl = MagicMock()
        ctrl.is_alive.return_value = True
        ctrl.get_position.return_value = 1.0
        ctrl.get_duration.return_value = 10.0
        poller, _, _, _ = self._make_poller(ctrl=ctrl, app=app)

        with self.assertLogs(
            logger="hermes_cli.tui.media_player", level=logging.DEBUG
        ) as cm:
            result = poller._poll_once()

        self.assertFalse(result)
        self.assertTrue(
            any("call_from_thread" in rec.message for rec in cm.records),
            f"Expected 'call_from_thread' in debug log, got: {[r.message for r in cm.records]}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# THR-3: _NotifyListener docstring threading contract
# ─────────────────────────────────────────────────────────────────────────────

class TestThr3NotifyListenerContract(unittest.TestCase):

    def test_notify_listener_docstring_warns_off_thread(self):
        from hermes_cli.tui.session_manager import _NotifyListener
        doc = _NotifyListener.__doc__ or ""
        self.assertIn("worker thread", doc)
        self.assertIn("call_from_thread", doc)
        self.assertIn("newline-delimited JSON", doc)

        sig = inspect.signature(_NotifyListener.__init__)
        on_event_param = sig.parameters["on_event"]
        annotation_str = str(on_event_param.annotation)
        self.assertIn("Callable", annotation_str)
        self.assertIn("dict", annotation_str)


# ─────────────────────────────────────────────────────────────────────────────
# THR-4: services/io.py call_soon_threadsafe comment
# ─────────────────────────────────────────────────────────────────────────────

class TestThr4IoBoundaryDoc(unittest.TestCase):

    def test_io_boundary_threading_comment_present(self):
        import pathlib
        import hermes_cli.tui.services.io as io_mod
        src_path = pathlib.Path(io_mod.__file__)
        lines = src_path.read_text().splitlines()

        # Find the line with call_soon_threadsafe(
        cst_indices = [
            i for i, line in enumerate(lines)
            if "call_soon_threadsafe(" in line
        ]
        self.assertEqual(
            len(cst_indices), 1,
            f"Expected exactly 1 call_soon_threadsafe( line, found at: {[i+1 for i in cst_indices]}",
        )
        cst_lineno = cst_indices[0]

        # Collect contiguous comment lines immediately preceding cst_lineno
        comment_block = []
        idx = cst_lineno - 1
        while idx >= 0 and lines[idx].lstrip().startswith("#"):
            comment_block.insert(0, lines[idx])
            idx -= 1

        comment_text = "\n".join(comment_block)
        self.assertIn(
            "put_nowait", comment_text,
            f"Comment before call_soon_threadsafe (line {cst_lineno+1}) missing 'put_nowait'. "
            f"Comment block: {comment_text!r}",
        )
        self.assertIn(
            "run_coroutine_threadsafe", comment_text,
            f"Comment before call_soon_threadsafe (line {cst_lineno+1}) missing 'run_coroutine_threadsafe'. "
            f"Comment block: {comment_text!r}",
        )
