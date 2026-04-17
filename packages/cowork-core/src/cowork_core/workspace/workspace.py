"""Filesystem sandbox rooted at a single directory.

Every file tool resolves user-supplied paths through ``Workspace.resolve``,
which rejects anything that escapes the root. Projects and sessions are
subdirectories; see ``SPEC.md`` §2.11.1 for the layout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cowork_core.workspace.storage import FileStorage, LocalFileStorage


class WorkspaceError(Exception):
    """Raised when a requested path escapes the workspace root."""


@dataclass(frozen=True)
class Workspace:
    root: Path
    storage: FileStorage | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        # Lazily attach a LocalFileStorage if none provided
        if self.storage is None:
            from cowork_core.workspace.storage import LocalFileStorage
            object.__setattr__(self, "storage", LocalFileStorage(self.root))

    def resolve(self, rel: str | Path) -> Path:
        candidate = (self.root / rel).resolve()
        try:
            candidate.relative_to(self.root.resolve())
        except ValueError as e:
            raise WorkspaceError(f"path escapes workspace: {rel}") from e
        return candidate

    def scratch_dir(self, project: str, session_id: str) -> Path:
        p = self.resolve(Path("projects") / project / "sessions" / session_id / "scratch")
        p.mkdir(parents=True, exist_ok=True)
        return p

    def project_files(self, project: str) -> Path:
        p = self.resolve(Path("projects") / project / "files")
        p.mkdir(parents=True, exist_ok=True)
        return p
