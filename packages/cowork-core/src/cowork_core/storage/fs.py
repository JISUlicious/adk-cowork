"""Filesystem backings for ``UserStore`` / ``ProjectStore``.

Used in single-user mode. ``FSUserStore`` writes under
``~/.config/cowork/``; ``FSProjectStore`` writes under
``<workdir>/.cowork/``. Both honor path-shaped string keys
verbatim (e.g. key ``"memory/pages/scratch.md"`` lands at
``<scope_root>/memory/pages/scratch.md``).

Atomic writes via temp+rename so a crash mid-write can't produce
partial state. Path traversal (``..``) is rejected — the key must
resolve under the scope root.
"""

from __future__ import annotations

import os
import secrets
import threading
from collections.abc import Callable
from pathlib import Path

from cowork_core.storage.protocols import ProjectStore, UserStore


class StorageError(Exception):
    """Raised on bad keys (path traversal, absolute paths, …) or
    backing-specific I/O failures the caller should handle."""


def _resolve_under(root: Path, key: str) -> Path:
    """Map a path-shaped key to a concrete path under ``root``,
    rejecting any key that resolves outside ``root``. Reject empty
    keys and absolute keys explicitly so callers get a clear error
    rather than silently writing to the wrong place."""
    if not key:
        raise StorageError("storage key must be non-empty")
    if key.startswith("/") or "\\" in key:
        raise StorageError(f"storage key must be a relative path: {key!r}")
    target = (root / key).resolve()
    root_resolved = root.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError as exc:
        raise StorageError(
            f"storage key {key!r} resolves outside the scope root",
        ) from exc
    return target


def _atomic_write(path: Path, value: bytes) -> None:
    """Write ``value`` to ``path`` atomically (temp+rename). The temp
    file lives next to the target so the rename is on the same
    filesystem (POSIX rename(2) atomicity guarantee). Parent dirs are
    created on demand. The temp filename mixes pid + thread id + a
    cryptographically random nonce so concurrent writers from
    different threads/processes don't collide on the same temp path
    (which would leave one thread's ``.replace`` calling on a missing
    file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = (
        f".{os.getpid()}.{threading.get_ident()}."
        f"{secrets.token_hex(4)}.tmp"
    )
    tmp = path.with_suffix(path.suffix + suffix)
    tmp.write_bytes(value)
    tmp.replace(path)


def _list_under(root: Path, prefix: str) -> list[str]:
    """Walk ``root`` and return key strings (relative paths from
    ``root``, forward-slash separators) whose name starts with
    ``prefix``. Skips anything that fails to read."""
    if not root.exists():
        return []
    out: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        # Skip our own .tmp atomic-write artifacts.
        if p.suffix == ".tmp":
            continue
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            continue
        if rel.startswith(prefix):
            out.append(rel)
    return sorted(out)


class FSUserStore(UserStore):
    """Single-user filesystem ``UserStore``.

    The ``user_id`` parameter is ignored (single-user mode has one
    machine-user only). Kept in the signature for protocol uniformity.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root).expanduser()

    def read(self, user_id: str, key: str) -> bytes | None:
        path = _resolve_under(self._root, key)
        if not path.is_file():
            return None
        return path.read_bytes()

    def write(self, user_id: str, key: str, value: bytes) -> None:
        path = _resolve_under(self._root, key)
        _atomic_write(path, value)

    def list(self, user_id: str, prefix: str = "") -> list[str]:
        return _list_under(self._root, prefix)

    def delete(self, user_id: str, key: str) -> None:
        path = _resolve_under(self._root, key)
        if path.is_file():
            path.unlink()


class FSProjectStore(ProjectStore):
    """Single-user filesystem ``ProjectStore``.

    Resolves ``(user_id, project)`` to a workdir via
    ``workdir_resolver`` — in single-user mode the ``project`` slug
    IS the workdir path the user opened. The store writes under
    ``<workdir>/.cowork/`` to match the existing local-dir convention
    for hidden Cowork state inside a workdir.

    The ``user_id`` parameter is ignored (single-user mode has one
    machine-user only).
    """

    def __init__(
        self,
        workdir_resolver: Callable[[str, str], Path],
    ) -> None:
        self._resolver = workdir_resolver

    def _scope_root(self, user_id: str, project: str) -> Path:
        workdir = self._resolver(user_id, project)
        return Path(workdir).expanduser() / ".cowork"

    def read(self, user_id: str, project: str, key: str) -> bytes | None:
        path = _resolve_under(self._scope_root(user_id, project), key)
        if not path.is_file():
            return None
        return path.read_bytes()

    def write(self, user_id: str, project: str, key: str, value: bytes) -> None:
        path = _resolve_under(self._scope_root(user_id, project), key)
        _atomic_write(path, value)

    def list(
        self, user_id: str, project: str, prefix: str = "",
    ) -> list[str]:
        return _list_under(self._scope_root(user_id, project), prefix)

    def delete(self, user_id: str, project: str, key: str) -> None:
        path = _resolve_under(self._scope_root(user_id, project), key)
        if path.is_file():
            path.unlink()
