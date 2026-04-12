"""EventBus — in-process pub/sub with persistent SQLite event log.

Every event is persisted to SQLite before being dispatched to subscribers.
This ensures events survive crashes and are queryable for dashboard/replay.
"""

from __future__ import annotations

import fnmatch
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

_BUSY_MAX_RETRIES = 5
_BUSY_BASE_DELAY = 0.05  # seconds

# ---------------------------------------------------------------------------
# Event dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Event:
    """Immutable event record."""

    id: str
    type: str
    source: str
    payload: dict[str, Any]
    timestamp: str
    workflow_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _make_event(
    event_type: str,
    payload: dict[str, Any],
    source: str = "",
    workflow_id: str | None = None,
) -> Event:
    return Event(
        id=uuid.uuid4().hex[:16],
        type=event_type,
        source=source,
        payload=payload,
        timestamp=datetime.now(UTC).isoformat(),
        workflow_id=workflow_id,
    )


# ---------------------------------------------------------------------------
# SQLite persistence
# ---------------------------------------------------------------------------

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    timestamp TEXT NOT NULL,
    workflow_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_workflow ON events(workflow_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
"""


class _EventStore:
    """Thread-safe SQLite append-only event log."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.commit()

    def _retry_on_busy(self, fn):
        """Execute fn with exponential backoff on SQLITE_BUSY."""
        for attempt in range(_BUSY_MAX_RETRIES + 1):
            try:
                return fn()
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < _BUSY_MAX_RETRIES:
                    delay = _BUSY_BASE_DELAY * (2 ** attempt)
                    logger.warning("event_bus: SQLITE_BUSY, retry %d after %.2fs", attempt + 1, delay)
                    time.sleep(delay)
                else:
                    logger.error("event_bus: SQLite error after %d retries: %s", attempt, e)
                    raise

    def insert(self, event: Event) -> None:
        import json

        def _do_insert():
            with self._lock:
                if self._conn is None:
                    logger.warning("event_bus: dropped event %s (type=%s) — bus already closed", event.id, event.type)
                    return
                self._conn.execute(
                    "INSERT INTO events (id, type, source, payload, timestamp, workflow_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        event.id,
                        event.type,
                        event.source,
                        json.dumps(event.payload),
                        event.timestamp,
                        event.workflow_id,
                    ),
                )
                self._conn.commit()

        try:
            self._retry_on_busy(_do_insert)
        except sqlite3.OperationalError:
            logger.error("event_bus: dropping event %s (type=%s) after retries exhausted", event.id, event.type)

    def query(
        self,
        event_type: str | None = None,
        workflow_id: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        import json

        clauses: list[str] = []
        params: list[Any] = []
        if event_type is not None:
            clauses.append("type = ?")
            params.append(event_type)
        if workflow_id is not None:
            clauses.append("workflow_id = ?")
            params.append(workflow_id)
        if since is not None:
            clauses.append("timestamp >= ?")
            params.append(since)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM events {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        def _do_query():
            with self._lock:
                if self._conn is None:
                    return []
                return self._conn.execute(sql, params).fetchall()

        rows = self._retry_on_busy(_do_query)

        events = []
        for row in rows:
            events.append(
                Event(
                    id=row["id"],
                    type=row["type"],
                    source=row["source"],
                    payload=json.loads(row["payload"]),
                    timestamp=row["timestamp"],
                    workflow_id=row["workflow_id"],
                )
            )
        return events

    def prune(self, before: str) -> int:
        """Delete events older than *before* ISO timestamp. Returns count deleted."""
        def _do_prune():
            with self._lock:
                if self._conn is None:
                    return 0
                cur = self._conn.execute(
                    "DELETE FROM events WHERE timestamp < ?", (before,)
                )
                self._conn.commit()
                return cur.rowcount

        return self._retry_on_busy(_do_prune)

    def count(self) -> int:
        with self._lock:
            if self._conn is None:
                return 0
            row = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()
            return row[0]

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------


@dataclass
class _Subscription:
    id: str
    pattern: str  # Exact type or glob pattern (e.g. "tool.*")
    callback: Callable[[Event], None]
    is_pattern: bool = field(default=False)


# ---------------------------------------------------------------------------
# EventBus
# ---------------------------------------------------------------------------


class EventBus:
    """In-process pub/sub with persistent SQLite event log.

    Thread-safe. Callbacks are invoked synchronously on the emitting thread.
    Exceptions in callbacks are logged and swallowed — a bad subscriber
    should never block the emitter.

    Args:
        db_path: Path to SQLite database for event persistence.
    """

    def __init__(self, db_path: str) -> None:
        self._store = _EventStore(db_path)
        self._subscriptions: dict[str, _Subscription] = {}
        self._sub_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        source: str = "",
        workflow_id: str | None = None,
    ) -> Event:
        """Create, persist, and dispatch an event to matching subscribers."""
        event = _make_event(event_type, payload or {}, source, workflow_id)
        self._store.insert(event)
        self._dispatch(event)
        return event

    def _dispatch(self, event: Event) -> None:
        with self._sub_lock:
            subs = list(self._subscriptions.values())

        for sub in subs:
            if self._matches(sub, event):
                try:
                    sub.callback(event)
                except Exception:
                    logger.exception(
                        "event_bus: subscriber %s raised on event %s",
                        sub.id,
                        event.type,
                    )

    @staticmethod
    def _matches(sub: _Subscription, event: Event) -> bool:
        if sub.is_pattern:
            return fnmatch.fnmatch(event.type, sub.pattern)
        return sub.pattern == event.type

    # ------------------------------------------------------------------
    # Subscribing
    # ------------------------------------------------------------------

    def subscribe(
        self, event_type: str, callback: Callable[[Event], None]
    ) -> str:
        """Subscribe to an exact event type. Returns subscription ID."""
        sub = _Subscription(
            id=uuid.uuid4().hex[:12],
            pattern=event_type,
            callback=callback,
            is_pattern=False,
        )
        with self._sub_lock:
            self._subscriptions[sub.id] = sub
        return sub.id

    def subscribe_pattern(
        self, pattern: str, callback: Callable[[Event], None]
    ) -> str:
        """Subscribe to events matching a glob pattern (e.g. ``"tool.*"``).

        Returns subscription ID.
        """
        sub = _Subscription(
            id=uuid.uuid4().hex[:12],
            pattern=pattern,
            callback=callback,
            is_pattern=True,
        )
        with self._sub_lock:
            self._subscriptions[sub.id] = sub
        return sub.id

    def unsubscribe(self, subscription_id: str) -> None:
        """Remove a subscription by ID. No-op if not found."""
        with self._sub_lock:
            self._subscriptions.pop(subscription_id, None)

    # ------------------------------------------------------------------
    # Query (for dashboard / replay)
    # ------------------------------------------------------------------

    def query(
        self,
        event_type: str | None = None,
        workflow_id: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """Query persisted events with optional filters."""
        return self._store.query(event_type, workflow_id, since, limit)

    def count(self) -> int:
        """Return total persisted event count."""
        return self._store.count()

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def prune(self, before: str) -> int:
        """Delete events older than *before* ISO timestamp."""
        return self._store.prune(before)

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._store.close()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

def _default_db_path() -> str:
    from hermes_constants import get_hermes_home
    return str(get_hermes_home() / "events.db")


_bus: EventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    """Return the process-wide EventBus singleton, creating it on first call."""
    global _bus
    if _bus is None:
        with _bus_lock:
            if _bus is None:
                _bus = EventBus(db_path=_default_db_path())
    return _bus
