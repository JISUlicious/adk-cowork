"""Protocol definitions for the storage hierarchy.

The protocols are deliberately bytes-at-the-boundary — memory pages
are markdown (str) but future subsystems may store binary, and
forcing callers to encode keeps the contract honest.

Path-shaped string keys (e.g. ``"memory/pages/scratch.md"``) are the
lingua franca: FS backings map them to relative file paths under the
scope root, SQLite backings tokenize them as opaque keys. Same call
site works against either backing without conditionals.
"""

from __future__ import annotations

from typing import Protocol


class UserStore(Protocol):
    """Per-user state.

    Single-user backing: filesystem under ``~/.config/cowork/``.
    Multi-user backing: SQLite ``user_state`` table keyed by
    ``user_id``.

    The ``user_id`` parameter is part of every method signature even
    in single-user mode (where it's ignored) so call sites stay
    deployment-agnostic.
    """

    def read(self, user_id: str, key: str) -> bytes | None:
        """Return the value at ``key`` for ``user_id``, or ``None``
        if the key is unset."""
        ...

    def write(self, user_id: str, key: str, value: bytes) -> None:
        """Persist ``value`` under ``(user_id, key)``. Atomic on the
        FS backing (temp+rename); upsert on the SQLite backing."""
        ...

    def list(self, user_id: str, prefix: str = "") -> list[str]:
        """Return all keys for ``user_id`` whose name starts with
        ``prefix``. ``""`` returns every key for the user."""
        ...

    def delete(self, user_id: str, key: str) -> None:
        """Remove ``(user_id, key)`` if present. Idempotent — no
        error on missing key."""
        ...


class ProjectStore(Protocol):
    """Per-(user, project) state.

    Single-user backing: filesystem under ``<workdir>/.cowork/``
    (the workdir IS the project in single-user mode).
    Multi-user backing: SQLite ``project_state`` table keyed by
    ``(user_id, project)``.
    """

    def read(self, user_id: str, project: str, key: str) -> bytes | None:
        """Return the value at ``key`` for ``(user_id, project)``,
        or ``None`` if unset."""
        ...

    def write(self, user_id: str, project: str, key: str, value: bytes) -> None:
        """Persist ``value`` under ``(user_id, project, key)``."""
        ...

    def list(self, user_id: str, project: str, prefix: str = "") -> list[str]:
        """Return all keys for ``(user_id, project)`` starting with
        ``prefix``."""
        ...

    def delete(self, user_id: str, project: str, key: str) -> None:
        """Remove ``(user_id, project, key)`` if present. Idempotent."""
        ...
