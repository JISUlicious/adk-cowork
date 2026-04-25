"""SQLite backings for ``UserStore`` / ``ProjectStore``.

Used in multi-user mode. One DB at ``<workspace>/multiuser.db`` with
two tables (``user_state``, ``project_state``). WAL mode for
concurrent readers; FOREIGN KEYS off (we don't have real referential
constraints across these tables — ``user_state`` and ``project_state``
are independent).

Connection lifecycle: a single ``sqlite3.Connection`` is shared by
``SqliteUserStore`` and ``SqliteProjectStore`` instances built off
the same DB path. The connection is owned by ``CoworkRuntime`` (or
whoever called ``_open_sqlite``) and closed when the runtime tears
down — callers don't manage it per-request.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from cowork_core.storage.protocols import ProjectStore, UserStore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_state (
    user_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value BLOB NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
CREATE TABLE IF NOT EXISTS project_state (
    user_id TEXT NOT NULL,
    project TEXT NOT NULL,
    key TEXT NOT NULL,
    value BLOB NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, project, key)
);
CREATE INDEX IF NOT EXISTS project_state_user_project
    ON project_state (user_id, project);
"""


def _open_sqlite(path: Path | str) -> sqlite3.Connection:
    """Open a SQLite connection in WAL mode with sensible defaults
    for a multi-user backing. Accepts a ``:memory:`` shortcut for
    tests. Creates the schema if missing — idempotent on existing
    databases."""
    if path == ":memory:":
        conn = sqlite3.connect(":memory:", check_same_thread=False)
    else:
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(path_obj),
            check_same_thread=False,
            isolation_level=None,  # autocommit; explicit txns via BEGIN/COMMIT
        )
        # WAL only makes sense for file-backed DBs.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_SCHEMA)
    return conn


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class _SqliteStoreBase:
    """Shared lock for the single connection — sqlite3 connections
    are not thread-safe for concurrent writes even in WAL mode."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()


class SqliteUserStore(_SqliteStoreBase, UserStore):
    """Multi-user SQLite ``UserStore``. Rows live in ``user_state``."""

    def read(self, user_id: str, key: str) -> bytes | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM user_state WHERE user_id = ? AND key = ?",
                (user_id, key),
            ).fetchone()
        if row is None:
            return None
        return bytes(row[0])

    def write(self, user_id: str, key: str, value: bytes) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO user_state (user_id, key, value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, key) DO UPDATE
                  SET value = excluded.value,
                      updated_at = excluded.updated_at
                """,
                (user_id, key, value, _now_iso()),
            )

    def list(self, user_id: str, prefix: str = "") -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT key FROM user_state
                WHERE user_id = ? AND key LIKE ? || '%'
                ORDER BY key
                """,
                (user_id, prefix),
            ).fetchall()
        return [row[0] for row in rows]

    def delete(self, user_id: str, key: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM user_state WHERE user_id = ? AND key = ?",
                (user_id, key),
            )


class SqliteProjectStore(_SqliteStoreBase, ProjectStore):
    """Multi-user SQLite ``ProjectStore``. Rows live in
    ``project_state``."""

    def read(self, user_id: str, project: str, key: str) -> bytes | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT value FROM project_state
                WHERE user_id = ? AND project = ? AND key = ?
                """,
                (user_id, project, key),
            ).fetchone()
        if row is None:
            return None
        return bytes(row[0])

    def write(
        self, user_id: str, project: str, key: str, value: bytes,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO project_state
                  (user_id, project, key, value, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id, project, key) DO UPDATE
                  SET value = excluded.value,
                      updated_at = excluded.updated_at
                """,
                (user_id, project, key, value, _now_iso()),
            )

    def list(
        self, user_id: str, project: str, prefix: str = "",
    ) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT key FROM project_state
                WHERE user_id = ? AND project = ? AND key LIKE ? || '%'
                ORDER BY key
                """,
                (user_id, project, prefix),
            ).fetchall()
        return [row[0] for row in rows]

    def delete(self, user_id: str, project: str, key: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                DELETE FROM project_state
                WHERE user_id = ? AND project = ? AND key = ?
                """,
                (user_id, project, key),
            )
