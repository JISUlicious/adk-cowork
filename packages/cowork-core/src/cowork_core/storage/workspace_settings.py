"""Workspace-wide settings store (Slice U1).

Workspace-wide settings — model + compaction — that are editable
at runtime via the Settings UI. Two backings:

* **FS backing** (single-user) — wraps the existing
  ``config_writer.update_toml_section`` so single-user edits keep
  writing ``cowork.toml`` directly. No behaviour change vs T1.
* **SQLite backing** (multi-user) — opens its own connection
  against the same ``<workspace>/multiuser.db`` already used by
  ``UserStore`` / ``ProjectStore``, with a new
  ``workspace_settings(key, value, updated_at)`` table. Schemaless
  KV with dotted keys (``model.base_url``, ``compaction.enabled``,
  …) so adding a new setting needs no migration.

The protocol exposes section-level operations
(``get_overrides`` / ``set_section``) so callers don't deal with
key flattening — that's the SQLite backing's internal concern.
``cowork.toml`` stays as bootstrap defaults; DB values override
key-by-key at runtime build (see ``runner._merge_overrides``).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from cowork_core.config_writer import ConfigWriteError, update_toml_section

_WORKSPACE_SETTINGS_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspace_settings (
    key TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspace_settings_meta (
    section TEXT NOT NULL PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);
"""


class WorkspaceSettingsStore(Protocol):
    """Workspace-wide editable config (model + compaction).

    ``get_overrides`` returns the full ``{section: {key: value}}``
    map (empty on a fresh DB). ``set_section`` merges a patch into
    a section and returns the resulting section.
    """

    def get_overrides(self) -> dict[str, dict[str, Any]]:
        """Return all sections with their current values."""
        ...

    def set_section(
        self, section: str, patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge ``patch`` into ``section``. ``None`` values are
        treated as 'leave alone'. Returns the resulting section."""
        ...

    def get_version(self, section: str) -> int:
        """Slice V4b — return the OCC version for ``section``.
        Increments on every successful ``set_section``. SU FS
        backing returns 0 always (one writer, no OCC needed); the
        SQLite backing returns the persisted counter."""
        ...


class FSWorkspaceSettingsStore(WorkspaceSettingsStore):
    """Single-user FS backing — wraps ``cowork.toml`` via the
    existing atomic TOML writer. Behaviour identical to T1's
    direct calls to ``config_writer.update_toml_section``."""

    def __init__(self, config_path: Path) -> None:
        self._config_path = config_path

    def get_overrides(self) -> dict[str, dict[str, Any]]:
        if not self._config_path.is_file():
            return {}
        import tomllib
        try:
            data = tomllib.loads(self._config_path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            return {}
        # Return only the sections that are workspace-settings-shaped
        # (dict of scalars). Skip everything else so callers can
        # safely treat the result as overrides.
        out: dict[str, dict[str, Any]] = {}
        for section in ("model", "compaction"):
            value = data.get(section)
            if isinstance(value, dict):
                out[section] = dict(value)
        return out

    def set_section(
        self, section: str, patch: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            data = update_toml_section(self._config_path, section, patch)
        except ConfigWriteError:
            raise
        out = data.get(section)
        return dict(out) if isinstance(out, dict) else {}

    def get_version(self, section: str) -> int:
        """SU FS backing — version 0 always. Single-user mode has
        one client; concurrent-PUT collisions don't happen."""
        return 0


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SqliteWorkspaceSettingsStore(WorkspaceSettingsStore):
    """Multi-user SQLite backing.

    Owns its own ``sqlite3.Connection`` (R1 mitigation — avoids
    refactoring ``_build_sqlite_stores`` to share). SQLite WAL mode
    handles concurrent connections without contention; the
    per-instance lock keeps writes serialised inside this connection.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()
        self._conn.executescript(_WORKSPACE_SETTINGS_SCHEMA)

    def get_overrides(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT key, value FROM workspace_settings",
            ).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for key, raw in rows:
            if "." not in key:
                continue  # malformed, skip
            section, _, leaf = key.partition(".")
            try:
                value = json.loads(raw)
            except (ValueError, TypeError):
                continue
            out.setdefault(section, {})[leaf] = value
        return out

    def set_section(
        self, section: str, patch: dict[str, Any],
    ) -> dict[str, Any]:
        if "." in section:
            raise ValueError(
                f"section name {section!r} must not contain '.'",
            )
        timestamp = _now_iso()
        with self._lock:
            for leaf, value in patch.items():
                if value is None:
                    continue  # 'leave alone' semantics matches FS backing
                key = f"{section}.{leaf}"
                self._conn.execute(
                    """
                    INSERT INTO workspace_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE
                      SET value = excluded.value,
                          updated_at = excluded.updated_at
                    """,
                    (key, json.dumps(value), timestamp),
                )
            # V4b — bump the OCC version for this section. UPSERT so
            # the first write to a new section starts at 1.
            self._conn.execute(
                """
                INSERT INTO workspace_settings_meta (section, version, updated_at)
                VALUES (?, 1, ?)
                ON CONFLICT(section) DO UPDATE
                  SET version = version + 1,
                      updated_at = excluded.updated_at
                """,
                (section, timestamp),
            )
            # Read back the resulting section.
            rows = self._conn.execute(
                "SELECT key, value FROM workspace_settings WHERE key LIKE ? || '.%'",
                (section,),
            ).fetchall()
        out: dict[str, Any] = {}
        for key, raw in rows:
            _, _, leaf = key.partition(".")
            try:
                out[leaf] = json.loads(raw)
            except (ValueError, TypeError):
                continue
        return out

    def get_version(self, section: str) -> int:
        """V4b — current OCC version for ``section``. Returns 0 for
        sections never written. Clients use this for If-Match style
        OCC on PUT routes."""
        with self._lock:
            row = self._conn.execute(
                "SELECT version FROM workspace_settings_meta WHERE section = ?",
                (section,),
            ).fetchone()
        return int(row[0]) if row else 0
