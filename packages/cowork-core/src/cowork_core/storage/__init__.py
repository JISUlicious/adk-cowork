"""Storage hierarchy abstraction (Slice S1).

Two protocols (``UserStore``, ``ProjectStore``) with two backings
shipped in S1:

* **FS** — single-user mode. ``~/.config/cowork/`` for user-scope
  state, ``<workdir>/.cowork/`` for project-scope state. Mirrors
  OpenCode's filesystem layout.
* **SQLite** — multi-user mode. Single DB at
  ``<workspace>/multiuser.db`` with two tables (``user_state``,
  ``project_state``) keyed by ``(user_id, key)`` and
  ``(user_id, project, key)`` respectively.

Mode is auto-detected by ``build_stores`` from ``cfg.auth.keys`` (empty
→ single-user, non-empty → multi-user). A backend registry lets
future backings (Postgres, Turso, …) drop in by calling
``register_backend`` at module import time without touching call
sites.

Callers route through ``CoworkRuntime.user_store`` /
``runtime.project_store`` (or ``CoworkToolContext.user_store`` /
``ctx.project_store`` from inside a tool). Path-shaped string keys
(e.g. ``"memory/pages/scratch.md"``) work identically against either
backing — FS treats them as relative file paths under the scope root,
SQLite tokenizes them as opaque keys.
"""

from __future__ import annotations

from cowork_core.storage.factory import (
    build_stores,
    register_backend,
)
from cowork_core.storage.fs import FSProjectStore, FSUserStore
from cowork_core.storage.memory import (
    InMemoryProjectStore,
    InMemoryUserStore,
)
from cowork_core.storage.protocols import ProjectStore, UserStore
from cowork_core.storage.sqlite import (
    SqliteProjectStore,
    SqliteUserStore,
)

__all__ = [
    "FSProjectStore",
    "FSUserStore",
    "InMemoryProjectStore",
    "InMemoryUserStore",
    "ProjectStore",
    "SqliteProjectStore",
    "SqliteUserStore",
    "UserStore",
    "build_stores",
    "register_backend",
]
