"""File storage abstraction for workspace data.

``LocalFileStorage`` wraps the current filesystem operations. The
``FileStorage`` protocol allows drop-in replacements (S3, GCS, etc.)
without changing callers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class FileStorage(Protocol):
    """Abstract interface for binary file storage."""

    async def read(self, key: str) -> bytes: ...
    async def write(self, key: str, data: bytes) -> None: ...
    async def list_dir(self, prefix: str) -> list[str]: ...
    async def exists(self, key: str) -> bool: ...
    async def delete(self, key: str) -> None: ...


class LocalFileStorage:
    """Filesystem-backed storage rooted at a directory.

    Keys are relative paths resolved under ``root``. Path traversal
    outside root raises ``ValueError``.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        target = (self._root / key).resolve()
        try:
            target.relative_to(self._root)
        except ValueError as e:
            raise ValueError(f"path escapes storage root: {key}") from e
        return target

    async def read(self, key: str) -> bytes:
        path = self._resolve(key)
        if not path.is_file():
            raise FileNotFoundError(f"not found: {key}")
        return path.read_bytes()

    async def write(self, key: str, data: bytes) -> None:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def list_dir(self, prefix: str) -> list[str]:
        path = self._resolve(prefix)
        if not path.is_dir():
            return []
        return sorted(child.name for child in path.iterdir())

    async def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    async def delete(self, key: str) -> None:
        path = self._resolve(key)
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            import shutil
            shutil.rmtree(path)

    @property
    def root(self) -> Path:
        return self._root
