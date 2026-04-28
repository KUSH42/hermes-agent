"""Tests for session auto-title feature (spec §B4).

5 tests:
  1. Auto-title derived from first user message text
  2. Auto-title truncates at 48 chars and appends '…'
  3. Markdown heading markers stripped from auto-title
  4. Auto-title fires only once (guard flag)
  5. DB unit test: set_title_if_unset is a no-op when title already exists
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from hermes_cli.tui.app import HermesApp


def _make_app() -> HermesApp:
    cli = MagicMock()
    cli.config = {}
    return HermesApp(cli=cli)


def _setup_cli_mock(app: HermesApp, messages: list[dict], session_id: str = "sess-test-001") -> MagicMock:
    """Wire cli mock so _try_auto_title can read history and DB."""
    db_mock = MagicMock()
    db_mock.set_title_if_unset.return_value = True
    app.cli.conversation_history = messages
    app.cli.session_id = session_id
    app.cli._session_db = db_mock
    return db_mock


def _extract_title_from_try_auto_title(
    app: HermesApp,
    messages: list[dict],
    session_id: str = "sess-test-001",
) -> str | None:
    """
    Run _try_auto_title logic and capture what title it would derive,
    by patching the @work decorator call so the worker fires synchronously.
    Returns the title that would have been passed to set_title_if_unset.
    """
    db_mock = _setup_cli_mock(app, messages, session_id)
    captured_title = []

    # Patch set_title_if_unset to capture the title call
    db_mock.set_title_if_unset.side_effect = lambda sid, title: captured_title.append(title) or True

    # Patch run_worker so the background worker fires synchronously
    def sync_run_worker(fn, *args, **kwargs):
        fn()

    with patch.object(app, "run_worker", sync_run_worker):
        app._auto_title_done = False
        app._svc_commands.try_auto_title()

    return captured_title[0] if captured_title else None


# ---------------------------------------------------------------------------
# 1. Auto-title derived from first user message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_title_derived_from_first_user_message():
    """_try_auto_title derives title from first user message content."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        title = _extract_title_from_try_auto_title(
            app,
            [
                {"role": "user", "content": "Fix the login bug"},
                {"role": "assistant", "content": "Sure, let me look..."},
            ],
        )
        assert title == "Fix the login bug"


# ---------------------------------------------------------------------------
# 2. Auto-title truncates at 48 chars
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_title_truncates_at_48_chars():
    """Long first-line content is truncated to 48 chars followed by '…'."""
    long_content = "A" * 60
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        title = _extract_title_from_try_auto_title(
            app,
            [{"role": "user", "content": long_content}],
        )
        assert title is not None
        assert title.endswith("…")
        assert len(title) <= 49  # 48 chars + ellipsis


# ---------------------------------------------------------------------------
# 3. Markdown heading markers stripped
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_title_strips_markdown_heading():
    """Leading '## ' heading markers are stripped from the auto-title."""
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        title = _extract_title_from_try_auto_title(
            app,
            [{"role": "user", "content": "## Fix the login"}],
        )
        assert title is not None
        assert "##" not in title
        assert "Fix the login" in title


# ---------------------------------------------------------------------------
# 4. Auto-title fires only once
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_title_fires_once():
    """The _auto_title_done guard ensures title is only derived once per session.

    watch_agent_running checks `if not self._auto_title_done` before calling
    _try_auto_title. After the first call, _auto_title_done is True, so the
    second invocation via watch_agent_running is blocked.
    """
    app = _make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        db_mock = _setup_cli_mock(app, [{"role": "user", "content": "Hello world"}])

        def sync_run_worker(fn, *args, **kwargs):
            fn()

        with patch.object(app, "run_worker", sync_run_worker):
            app._auto_title_done = False
            # Simulate watch_agent_running guard (two calls)
            if not app._auto_title_done:
                app._svc_commands.try_auto_title()
            # _auto_title_done is now True
            if not app._auto_title_done:
                app._svc_commands.try_auto_title()  # should NOT run

        assert app._auto_title_done is True
        # set_title_if_unset called exactly once
        assert db_mock.set_title_if_unset.call_count == 1


# ---------------------------------------------------------------------------
# 5. DB unit test: set_title_if_unset no-op when title already exists
# ---------------------------------------------------------------------------

def test_set_title_if_unset_noop_when_title_exists(tmp_path):
    """set_title_if_unset returns False and leaves title unchanged when already set."""
    from hermes_state import SessionDB

    db = SessionDB(tmp_path / "test.db")
    # Create a session with an existing title
    import uuid
    session_id = str(uuid.uuid4())
    db.create_session(session_id=session_id, source="test", model="test-model")
    # Manually set a title directly via the connection
    with db._lock:
        db._conn.execute(
            "UPDATE sessions SET title = ? WHERE id = ?",
            ("existing title", session_id),
        )
        db._conn.commit()

    result = db.set_title_if_unset(session_id, "new title")
    assert result is False  # no update performed

    # Verify title is still the original
    session = db.get_session(session_id)
    assert session["title"] == "existing title"


def test_set_title_if_unset_updates_when_null(tmp_path):
    """set_title_if_unset returns True and sets title when it was NULL."""
    from hermes_state import SessionDB

    db = SessionDB(tmp_path / "test.db")
    import uuid
    session_id = str(uuid.uuid4())
    db.create_session(session_id=session_id, source="test", model="test-model")
    # Title should be NULL at creation
    session = db.get_session(session_id)
    assert session["title"] is None

    result = db.set_title_if_unset(session_id, "auto title")
    assert result is True

    session = db.get_session(session_id)
    assert session["title"] == "auto title"
