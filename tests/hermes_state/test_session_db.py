"""Unit tests for SessionDB message count semantics (spec §C10).

3 tests:
  1. message_count excludes tool-role messages
  2. tool_call_count increments for 'tool' role messages
  3. message_count unchanged when only tool messages added
"""

from __future__ import annotations

import pytest
from pathlib import Path

from hermes_state import SessionDB


# ---------------------------------------------------------------------------
# 1. message_count excludes tool messages
# ---------------------------------------------------------------------------

def test_message_count_excludes_tool_messages(tmp_path: Path):
    """add_message for user + assistant increments message_count; 'tool' does not."""
    import uuid
    db = SessionDB(tmp_path / "test.db")
    sid = str(uuid.uuid4())
    db.create_session(session_id=sid, source="test", model="test-model")

    db.append_message(session_id=sid, role="user", content="Hello")
    db.append_message(session_id=sid, role="assistant", content="Hi there")
    db.append_message(session_id=sid, role="tool", content="tool result")

    session = db.get_session(sid)
    assert session["message_count"] == 2  # user + assistant only


# ---------------------------------------------------------------------------
# 2. tool_call_count increments for tool role
# ---------------------------------------------------------------------------

def test_tool_call_count_increments_for_tool_role(tmp_path: Path):
    """add_message with role='tool' increments tool_call_count."""
    import uuid
    db = SessionDB(tmp_path / "test.db")
    sid = str(uuid.uuid4())
    db.create_session(session_id=sid, source="test", model="test-model")

    db.append_message(session_id=sid, role="tool", content="tool result 1")
    db.append_message(session_id=sid, role="tool", content="tool result 2")

    session = db.get_session(sid)
    assert session["tool_call_count"] == 2


# ---------------------------------------------------------------------------
# 3. message_count unchanged for tool-only session
# ---------------------------------------------------------------------------

def test_message_count_unchanged_for_tool_only_session(tmp_path: Path):
    """Session with only tool messages has message_count == 0."""
    import uuid
    db = SessionDB(tmp_path / "test.db")
    sid = str(uuid.uuid4())
    db.create_session(session_id=sid, source="test", model="test-model")

    db.append_message(session_id=sid, role="tool", content="result a")
    db.append_message(session_id=sid, role="tool", content="result b")
    db.append_message(session_id=sid, role="tool", content="result c")

    session = db.get_session(sid)
    assert session["message_count"] == 0
    assert session["tool_call_count"] == 3
