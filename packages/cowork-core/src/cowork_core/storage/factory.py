"""Factory + backend registry for the storage hierarchy.

Auto-detects single-user vs multi-user mode from ``cfg.auth.keys``:
empty → single-user (FS backings), non-empty → multi-user (a registered
DB backing; SQLite is the only one shipped in S1).

The registry pattern lets future backings (Postgres, Turso, …) drop in
without rewriting the factory: implement the two protocol classes,
call ``register_backend("postgres", _build_postgres_stores)`` at
module import, no other change needed at the call site.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from cowork_core.storage.fs import FSProjectStore, FSUserStore
from cowork_core.storage.protocols import ProjectStore, UserStore
from cowork_core.storage.sqlite import (
    SqliteProjectStore,
    SqliteUserStore,
    _open_sqlite,
)

if TYPE_CHECKING:
    from cowork_core.config import CoworkConfig
    from cowork_core.workspace.workspace import Workspace

StoreBuilder = Callable[
    ["CoworkConfig", "Workspace"], tuple[UserStore, ProjectStore],
]

_BACKENDS: dict[str, StoreBuilder] = {}


class StorageBackendError(Exception):
    """Raised when ``cfg.storage.backend`` names an unregistered backing."""


def register_backend(name: str, builder: StoreBuilder) -> None:
    """Register a storage backend builder under ``name``. Builders are
    called with ``(cfg, workspace)`` and must return
    ``(UserStore, ProjectStore)``. Idempotent — re-registering the
    same name overwrites (useful in tests)."""
    _BACKENDS[name] = builder


def _build_sqlite_stores(
    cfg: "CoworkConfig", workspace: "Workspace",
) -> tuple[UserStore, ProjectStore]:
    """SQLite backend builder. The DSN, when non-empty, is treated
    as a path (``:memory:`` is honored verbatim); empty DSN falls
    back to ``<workspace>/multiuser.db``."""
    dsn = cfg.storage.dsn or str(workspace.root / "multiuser.db")
    conn = _open_sqlite(dsn if dsn == ":memory:" else Path(dsn))
    return SqliteUserStore(conn), SqliteProjectStore(conn)


# Built-in registration. Future backings (Postgres, …) register
# themselves the same way at their own module's import time.
register_backend("sqlite", _build_sqlite_stores)


def _default_workdir_resolver(user_id: str, project: str) -> Path:
    """Single-user FS ``ProjectStore`` resolver. The ``project`` slug
    in single-user mode is the workdir path itself (the user opened a
    folder; that folder IS the project). ``user_id`` is ignored —
    single-user mode has one machine-user only."""
    return Path(project).expanduser()


def build_stores(
    cfg: "CoworkConfig", workspace: "Workspace",
) -> tuple[UserStore, ProjectStore]:
    """Construct the ``(UserStore, ProjectStore)`` pair for this
    deployment. Mode is auto-detected from ``cfg.auth.keys``."""
    if not cfg.auth.keys:
        # Single-user — filesystem under XDG home + workdir/.cowork.
        return (
            FSUserStore(Path("~/.config/cowork").expanduser()),
            FSProjectStore(workdir_resolver=_default_workdir_resolver),
        )
    backend = cfg.storage.backend or "sqlite"
    if backend not in _BACKENDS:
        raise StorageBackendError(
            f"unknown storage backend {backend!r}; "
            f"available: {sorted(_BACKENDS)}",
        )
    return _BACKENDS[backend](cfg, workspace)
