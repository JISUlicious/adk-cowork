"""Filesystem sandbox rooted at a single directory.

Every file tool resolves user-supplied paths through ``Workspace.resolve``,
which rejects anything that escapes the root. Projects and sessions are
subdirectories; see ``SPEC.md`` §2.11.1 for the layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class WorkspaceError(Exception):
    """Raised when a requested path escapes the workspace root."""


@dataclass(frozen=True)
class Workspace:
    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

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
