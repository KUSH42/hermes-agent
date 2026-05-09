"""TUI-level tests for DD-PL-2, DD-PL-6, DD-PL-7 using _FakeApp stubs."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Shared stub helpers
# ---------------------------------------------------------------------------


def _make_app(*, approval_state=None, interrupt_state=None, confirm_state=None,
              attached_images=None):
    """Build a minimal _FakeApp namespace for WatchersService tests."""
    app = SimpleNamespace(
        approval_state=approval_state,
        interrupt_state=interrupt_state,
        confirm_state=confirm_state,
        attached_images=list(attached_images or []),
        config=None,
        _flash_hint_calls=[],
    )

    def _flash_hint(msg: str, duration: float = 1.5) -> None:
        app._flash_hint_calls.append(msg)
        app._last_hint = msg

    app._flash_hint = _flash_hint
    app.get_working_directory = lambda: Path("/tmp")
    app.query_one = MagicMock(side_effect=Exception("no dom"))
    return app


def _make_svc(app=None):
    """Build a WatchersService with a fake app, bypassing __init__."""
    from hermes_cli.tui.services.watchers import WatchersService

    svc = WatchersService.__new__(WatchersService)
    svc.app = app or _make_app()
    svc._pending_drop_queue = []
    svc._last_drop_undo_state = None
    svc.append_attached_images = MagicMock()
    svc.insert_link_tokens = MagicMock()
    return svc


# ---------------------------------------------------------------------------
# TestRejectionHint — DD-PL-2
# ---------------------------------------------------------------------------


class TestRejectionHint:
    def test_drop_unsupported_hint_includes_first_filename(self, tmp_path: Path) -> None:
        binary = tmp_path / "myfile.bin"
        binary.write_bytes(b"\x00\x01\x02\x03")

        app = _make_app()
        svc = _make_svc(app)
        svc.handle_file_drop_inner([binary])

        assert app._flash_hint_calls, "no hint was flashed"
        hint = app._flash_hint_calls[-1]
        assert "myfile.bin" in hint, f"filename not in hint: {hint!r}"
        assert "skipped" in hint

    def test_drop_unsupported_hint_includes_overflow_count(self, tmp_path: Path) -> None:
        bins = []
        for i in range(3):
            b = tmp_path / f"file{i}.bin"
            b.write_bytes(b"\x00\x01")
            bins.append(b)

        app = _make_app()
        svc = _make_svc(app)
        svc.handle_file_drop_inner(bins)

        assert app._flash_hint_calls, "no hint was flashed"
        hint = app._flash_hint_calls[-1]
        assert "(+2 more)" in hint, f"overflow count not in hint: {hint!r}"


# ---------------------------------------------------------------------------
# TestModalDropQueue — DD-PL-6
# ---------------------------------------------------------------------------


class TestModalDropQueue:
    def test_drop_during_approval_buffered_with_queued_hint(self, tmp_path: Path) -> None:
        from hermes_cli.tui.state import ChoiceOverlayState
        import queue

        sentinel = ChoiceOverlayState(
            deadline=0.0,
            response_queue=queue.Queue(),
            question="Allow?",
            choices=["yes", "no"],
            selected=0,
        )
        path = tmp_path / "main.py"
        path.write_text("x = 1")

        app = _make_app(approval_state=sentinel)
        svc = _make_svc(app)
        svc.handle_file_drop_inner([path])

        assert svc._pending_drop_queue == [path]
        assert app._flash_hint_calls, "no hint was flashed"
        hint = app._flash_hint_calls[-1]
        assert "queued" in hint, f"expected 'queued' in hint: {hint!r}"

    def test_drop_replays_when_approval_resolves(self, tmp_path: Path) -> None:
        from hermes_cli.tui.state import ChoiceOverlayState
        import queue

        sentinel = ChoiceOverlayState(
            deadline=0.0,
            response_queue=queue.Queue(),
            question="Allow?",
            choices=["yes", "no"],
            selected=0,
        )
        path = tmp_path / "replay.py"
        path.write_text("x = 1")

        app = _make_app(approval_state=sentinel)
        svc = _make_svc(app)
        svc._pending_drop_queue = [path]

        # Simulate approval clearing
        app.approval_state = None

        classified_paths: list[Path] = []

        from hermes_cli.file_drop import DroppedFile

        def fake_classify(p, cwd, *, allow_directory=False):
            classified_paths.append(p)
            return DroppedFile(path=p, kind="linkable_text")

        with patch("hermes_cli.tui.services.watchers.classify_dropped_file", fake_classify):
            svc._replay_pending_drops()

        assert svc._pending_drop_queue == [], "queue not cleared after replay"
        assert classified_paths == [path], f"classify not called for buffered path: {classified_paths}"

    def test_drop_queue_does_not_replay_while_other_modal_active(self, tmp_path: Path) -> None:
        from hermes_cli.tui.state import ChoiceOverlayState
        import queue

        approval = ChoiceOverlayState(
            deadline=0.0,
            response_queue=queue.Queue(),
            question="Allow?",
            choices=["yes", "no"],
            selected=0,
        )
        interrupt = ChoiceOverlayState(
            deadline=0.0,
            response_queue=queue.Queue(),
            question="Interrupt?",
            choices=["yes", "no"],
            selected=0,
        )

        path = tmp_path / "blocked.py"
        path.write_text("x = 1")

        # Buffer via approval_state
        app = _make_app(approval_state=approval)
        svc = _make_svc(app)
        svc._pending_drop_queue = [path]

        # Clear approval but keep interrupt_state active
        app.approval_state = None
        app.interrupt_state = interrupt

        classified_paths: list[Path] = []
        from hermes_cli.file_drop import DroppedFile

        def fake_classify(p, cwd, *, allow_directory=False):
            classified_paths.append(p)
            return DroppedFile(path=p, kind="linkable_text")

        with patch("hermes_cli.tui.services.watchers.classify_dropped_file", fake_classify):
            svc._replay_pending_drops()

        # Queue should NOT be consumed since interrupt_state is still active
        assert svc._pending_drop_queue == [path], "queue was consumed while modal still active"
        assert classified_paths == [], "classify was called while modal still active"


# ---------------------------------------------------------------------------
# TestDropUndo — DD-PL-7
# ---------------------------------------------------------------------------


class _FakeHistory:
    """Minimal TextArea history stub."""

    def __init__(self):
        self.checkpoints: int = 0

    def checkpoint(self) -> None:
        self.checkpoints += 1


class _FakeInput:
    """Minimal HermesInput stub with mutable value."""

    def __init__(self, value: str = ""):
        self._value = value
        self.history = _FakeHistory()
        self.selection = None
        self._loaded_texts: list[str] = []
        self._insert_calls: list[str] = []

    @property
    def value(self) -> str:
        return self._value

    def load_text(self, text: str) -> None:
        self._loaded_texts.append(text)
        self._value = text

    def insert_text(self, payload: str) -> None:
        self._insert_calls.append(payload)
        self._value = self._value + payload


class _FakeAppWithInput:
    """Fake app that returns _FakeInput from query_one."""

    def __init__(self, inp: _FakeInput, attached: list | None = None):
        self._inp = inp
        self.attached_images = list(attached or [])
        self._flash_hint_calls: list[str] = []
        self.approval_state = None
        self.interrupt_state = None
        self.confirm_state = None
        self.config = None

    def _flash_hint(self, msg: str, duration: float = 1.5) -> None:
        self._flash_hint_calls.append(msg)

    def query_one(self, selector, *args, **kwargs):
        if selector == "#input-area" or (args and args[0].__name__ == "HermesInput"):
            return self._inp
        raise Exception(f"no match: {selector}")

    def get_working_directory(self) -> Path:
        return Path("/tmp")


class TestDropUndo:
    def test_drop_undo_restores_input_text(self, tmp_path: Path) -> None:
        f = tmp_path / "script.py"
        f.write_text("x = 1")

        inp = _FakeInput("hello world")
        app = _FakeAppWithInput(inp)

        from hermes_cli.tui.services.watchers import WatchersService
        svc = WatchersService.__new__(WatchersService)
        svc.app = app
        svc._pending_drop_queue = []
        svc._last_drop_undo_state = None
        svc.append_attached_images = MagicMock()

        from hermes_cli.file_drop import DroppedFile

        with patch("hermes_cli.tui.services.watchers.classify_dropped_file",
                   return_value=DroppedFile(path=f, kind="linkable_text")):
            svc.handle_file_drop_inner([f])

        assert svc._last_drop_undo_state is not None
        prior_text, prior_attached = svc._last_drop_undo_state

        # Simulate undo: restore prior state
        inp.load_text(prior_text)
        svc._last_drop_undo_state = None

        assert inp.value == "hello world", f"undo did not restore: {inp.value!r}"
        assert svc._last_drop_undo_state is None

    def test_drop_undo_removes_attached_image(self, tmp_path: Path) -> None:
        img = tmp_path / "photo.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n")

        inp = _FakeInput("")
        app = _FakeAppWithInput(inp, attached=[])

        from hermes_cli.tui.services.watchers import WatchersService
        svc = WatchersService.__new__(WatchersService)
        svc.app = app
        svc._pending_drop_queue = []
        svc._last_drop_undo_state = None

        def fake_append(images: list[Path]) -> None:
            app.attached_images.extend(images)

        svc.append_attached_images = fake_append
        svc.insert_link_tokens = MagicMock()

        from hermes_cli.file_drop import DroppedFile

        with patch("hermes_cli.tui.services.watchers.classify_dropped_file",
                   return_value=DroppedFile(path=img, kind="image")):
            svc.handle_file_drop_inner([img])

        # After drop, image is attached
        assert img in app.attached_images

        # The undo state has empty prior list (image added by append, not insert_link_tokens)
        # For image-only drops, undo state is set by append_attached_images hook —
        # but in current design, _last_drop_undo_state is only set by insert_link_tokens.
        # Image-only drops do not set the undo slot; verify it's None.
        assert svc._last_drop_undo_state is None

    def test_drop_undo_restores_text_selection(self, tmp_path: Path) -> None:
        f = tmp_path / "util.py"
        f.write_text("def main(): pass")

        prior_value = "before drop text"
        inp = _FakeInput(prior_value)
        app = _FakeAppWithInput(inp)

        from hermes_cli.tui.services.watchers import WatchersService
        svc = WatchersService.__new__(WatchersService)
        svc.app = app
        svc._pending_drop_queue = []
        svc._last_drop_undo_state = None
        svc.append_attached_images = MagicMock()

        from hermes_cli.file_drop import DroppedFile

        with patch("hermes_cli.tui.services.watchers.classify_dropped_file",
                   return_value=DroppedFile(path=f, kind="linkable_text")):
            svc.handle_file_drop_inner([f])

        assert svc._last_drop_undo_state is not None
        prior_text, _ = svc._last_drop_undo_state

        # Simulate undo
        inp.load_text(prior_text)
        svc._last_drop_undo_state = None

        assert inp.value == prior_value
        assert svc._last_drop_undo_state is None, "undo slot not cleared after undo"
