"""Audit sink (Slice V1).

Captures every tool call + workspace-settings change as a structured
row. Shape works in both deployment modes:

* **SU** — SQLite at ``<workspace>/audit.db``. Independent file so
  desktop users (no ``multiuser.db``) still get an audit trail.
* **MU** — SQLite ``audit_log`` table inside the existing
  ``<workspace>/multiuser.db``. Shares the connection seam with
  ``UserStore`` / ``ProjectStore`` / ``WorkspaceSettingsStore`` —
  but owns its own ``sqlite3.Connection`` (matches R1's per-store
  isolation pattern from S1/U1).

Capture is filtered through ``cowork_core.audit_policy.policy_for``
so file contents, email bodies, memory pages etc. don't end up in
the log unless the operator explicitly opts a tool in.

The sink is append-only — there's no UPDATE or DELETE on rows.
Rotation/retention is operator concern (Tier F).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from cowork_core.audit_policy import ToolAuditPolicy, policy_for

_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    session_id TEXT,
    project_id TEXT,
    args_json TEXT,
    result_json TEXT,
    error_text TEXT,
    duration_ms INTEGER
);
CREATE INDEX IF NOT EXISTS audit_log_ts ON audit_log (ts);
CREATE INDEX IF NOT EXISTS audit_log_user_ts ON audit_log (user_id, ts);
CREATE INDEX IF NOT EXISTS audit_log_session_ts ON audit_log (session_id, ts);
CREATE INDEX IF NOT EXISTS audit_log_tool_ts ON audit_log (tool_name, ts);
"""


@dataclass
class AuditEntry:
    """One audit row — what crossed the audit boundary at one point
    in time. ``kind`` discriminates the event class:

    * ``"tool_call"`` — pre-invocation snapshot (args captured here)
    * ``"tool_result"`` — post-invocation summary (result captured
      here per the per-tool policy; ``duration_ms`` set)
    * ``"settings_change"`` — workspace-settings PUT (replaces the
      pre-V1 ``[settings]`` print line; ``tool_name`` carries the
      section, e.g. ``"config.model"``)
    """

    ts: str
    user_id: str
    kind: str
    tool_name: str
    session_id: str | None = None
    project_id: str | None = None
    args_json: str | None = None
    result_json: str | None = None
    error_text: str | None = None
    duration_ms: int | None = None


class AuditSink(Protocol):
    """Append-only sink for audit rows. Implementations must be
    thread-safe for concurrent ``record`` calls — the agent loop
    fires audit events from any worker thread."""

    def record(self, entry: AuditEntry) -> None:
        """Persist a single audit row. Must not raise; on failure
        the sink should swallow the error (audit is best-effort —
        a logging failure must never crash the agent)."""
        ...

    def query(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        tool_name: str | None = None,
        since_ts: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Return rows matching the filters, newest-first. ``limit``
        is hard-capped at 1000."""
        ...


class NullAuditSink(AuditSink):
    """No-op sink used by tests and pre-runtime contexts. Drops
    everything; ``query`` always returns empty."""

    def record(self, entry: AuditEntry) -> None:
        return

    def query(self, **_: Any) -> list[AuditEntry]:
        return []


class SqliteAuditSink(AuditSink):
    """SQLite-backed audit sink. Owns its own connection (R1 — per-
    store isolation, WAL handles concurrent connections without
    contention). Schema is created idempotently on init."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()
        self._conn.executescript(_AUDIT_SCHEMA)

    def record(self, entry: AuditEntry) -> None:
        try:
            with self._lock:
                self._conn.execute(
                    """
                    INSERT INTO audit_log (
                        ts, user_id, kind, tool_name, session_id,
                        project_id, args_json, result_json,
                        error_text, duration_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.ts, entry.user_id, entry.kind,
                        entry.tool_name, entry.session_id,
                        entry.project_id, entry.args_json,
                        entry.result_json, entry.error_text,
                        entry.duration_ms,
                    ),
                )
        except Exception:
            # Audit must never crash the agent — swallow + drop the row.
            pass

    def query(
        self,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        tool_name: str | None = None,
        since_ts: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        limit = max(1, min(1000, limit))
        clauses: list[str] = []
        params: list[Any] = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if tool_name is not None:
            clauses.append("tool_name = ?")
            params.append(tool_name)
        if since_ts is not None:
            clauses.append("ts >= ?")
            params.append(since_ts)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT ts, user_id, kind, tool_name, session_id, "
            f"project_id, args_json, result_json, error_text, "
            f"duration_ms FROM audit_log {where} "
            f"ORDER BY id DESC LIMIT ?"
        )
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            AuditEntry(
                ts=row[0], user_id=row[1], kind=row[2],
                tool_name=row[3], session_id=row[4],
                project_id=row[5], args_json=row[6],
                result_json=row[7], error_text=row[8],
                duration_ms=row[9],
            )
            for row in rows
        ]


# ── Helpers used by the audit hook callbacks ──


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def serialize_args(
    args: dict[str, Any], policy: ToolAuditPolicy,
) -> str | None:
    """Apply the tool's args-capture policy + return the JSON to
    persist. Empty whitelist → ``None`` (skip the column). Each
    captured value is JSON-serialized then truncated."""
    if not policy.args_keys:
        return None
    captured: dict[str, Any] = {}
    for key in policy.args_keys:
        if key not in args:
            continue
        try:
            value = json.dumps(args[key], default=str)
        except (TypeError, ValueError):
            value = repr(args[key])
        captured[key] = _truncate(value, policy.truncate_arg_to_bytes)
    if not captured:
        return None
    return json.dumps(captured)


def serialize_result(
    result: dict[str, Any], policy: ToolAuditPolicy,
) -> tuple[str | None, str | None]:
    """Apply the tool's result-capture policy + return
    ``(result_json, error_text)``. Errors are extracted from the
    result dict's ``error`` key into ``error_text`` regardless of
    capture kind so the audit can answer "did this tool fail" without
    parsing JSON."""
    error = result.get("error")
    error_text: str | None = (
        _truncate(str(error), 1024) if error else None
    )

    if policy.capture_result_kind == "none":
        # Just record ok/error.
        return json.dumps({"ok": error is None}), error_text

    if policy.capture_result_kind == "summary":
        # Summary captures ONLY a fixed allowlist of indicator keys
        # (no arbitrary repr — that would leak small payloads like
        # file content or memory page bodies into the audit). If the
        # operator wants richer capture for a specific tool they can
        # opt it into ``"full"`` capture via cfg (Tier F).
        summary: dict[str, Any] = {"ok": error is None}
        for key in (
            "exit_code", "status", "count", "size", "bytes",
            "tool", "name", "scope",
        ):
            if key in result:
                summary[key] = result[key]
        if "confirmation_required" in result:
            summary["confirmation_required"] = bool(
                result["confirmation_required"]
            )
        return json.dumps(summary), error_text

    # "full" — log everything truncated to 4 KB
    try:
        full = json.dumps(result, default=str)
    except (TypeError, ValueError):
        full = repr(result)
    return _truncate(full, 4096), error_text


def open_audit_db(path: Path | str) -> sqlite3.Connection:
    """Open / create a SQLite database for audit storage. WAL mode
    + a small synchronous penalty for durability + write speed
    balance. Mirrors ``cowork_core.storage.sqlite._open_sqlite``
    but keeps audit-specific defaults local."""
    if path == ":memory:":
        conn = sqlite3.connect(":memory:", check_same_thread=False)
    else:
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(path_obj),
            check_same_thread=False,
            isolation_level=None,
        )
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    return conn
