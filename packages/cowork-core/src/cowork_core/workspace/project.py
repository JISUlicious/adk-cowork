"""Project and session layout on top of ``Workspace``.

A **project** is the user-facing long-lived unit (e.g. "Q4 Report"). A
**session** is one conversation inside a project; sessions have their own
``scratch/`` dir where the agent drops drafts. "Promoting" moves a file from
scratch into the project's durable ``files/``.

See ``SPEC.md`` §2.11.1 for the on-disk layout this module bootstraps.
"""

from __future__ import annotations

import re
import tomllib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from typing import Protocol, runtime_checkable

from cowork_core.workspace.workspace import Workspace, WorkspaceError

_SLUG_RE = re.compile(r"[^a-z0-9_-]+")
_MAX_SLUG_LEN = 64


def slugify(name: str) -> str:
    lower = name.strip().lower().replace(" ", "-")
    slug = _SLUG_RE.sub("", lower).strip("-_")
    if not slug:
        raise ValueError(f"cannot slugify name: {name!r}")
    return slug[:_MAX_SLUG_LEN]


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Project:
    slug: str
    name: str
    root: Path
    created_at: str

    @property
    def files_dir(self) -> Path:
        return self.root / "files"

    @property
    def sessions_dir(self) -> Path:
        return self.root / "sessions"

    @property
    def skills_dir(self) -> Path:
        return self.root / "skills"

    @property
    def toml_path(self) -> Path:
        return self.root / "project.toml"


@dataclass(frozen=True)
class Session:
    id: str
    project_slug: str
    root: Path
    created_at: str
    title: str | None = None

    @property
    def scratch_dir(self) -> Path:
        return self.root / "scratch"

    @property
    def transcript_path(self) -> Path:
        return self.root / "transcript.jsonl"

    @property
    def toml_path(self) -> Path:
        return self.root / "session.toml"


@runtime_checkable
class ProjectRegistryBase(Protocol):
    """Abstract interface for project/session storage.

    Enables swapping the filesystem-backed ``ProjectRegistry`` for a
    database-backed implementation without changing callers.
    """

    def list(self) -> list[Project]: ...
    def create(self, name: str) -> Project: ...
    def get(self, slug: str) -> Project: ...
    def get_or_create(self, name: str) -> Project: ...
    def new_session(self, project_slug: str, title: str | None = None) -> Session: ...
    def get_session(self, project_slug: str, session_id: str) -> Session: ...
    def delete_session(self, project_slug: str, session_id: str) -> None: ...
    def delete_project(self, slug: str) -> None: ...


@dataclass(frozen=True)
class ProjectRegistry:
    """Filesystem-backed directory of projects under a ``Workspace``."""

    workspace: Workspace
    _read_tracking: dict[str, set[Path]] = field(default_factory=dict)

    @property
    def projects_root(self) -> Path:
        root = self.workspace.resolve("projects")
        root.mkdir(parents=True, exist_ok=True)
        return root

    def list(self) -> list[Project]:
        out: list[Project] = []
        for entry in sorted(self.projects_root.iterdir()):
            if not entry.is_dir():
                continue
            try:
                out.append(self._load_project(entry.name))
            except FileNotFoundError:
                continue
        return out

    def create(self, name: str) -> Project:
        slug = slugify(name)
        root = self.workspace.resolve(Path("projects") / slug)
        if root.exists():
            raise WorkspaceError(f"project already exists: {slug}")
        (root / "files").mkdir(parents=True)
        (root / "sessions").mkdir(parents=True)
        (root / "skills").mkdir(parents=True)
        created = _utcnow_iso()
        _write_toml(
            root / "project.toml",
            {"name": name, "slug": slug, "created_at": created},
        )
        return Project(slug=slug, name=name, root=root, created_at=created)

    def get(self, slug: str) -> Project:
        return self._load_project(slug)

    def get_or_create(self, name: str) -> Project:
        slug = slugify(name)
        try:
            return self.get(slug)
        except FileNotFoundError:
            return self.create(name)

    def new_session(self, project_slug: str, title: str | None = None) -> Session:
        project = self.get(project_slug)
        session_id = uuid.uuid4().hex
        root = project.sessions_dir / session_id
        (root / "scratch").mkdir(parents=True)
        created = _utcnow_iso()
        _write_toml(
            root / "session.toml",
            {"id": session_id, "title": title or "", "created_at": created},
        )
        (root / "transcript.jsonl").touch()
        return Session(
            id=session_id,
            project_slug=project_slug,
            root=root,
            created_at=created,
            title=title,
        )

    def get_session(self, project_slug: str, session_id: str) -> Session:
        project = self.get(project_slug)
        root = project.sessions_dir / session_id
        toml_path = root / "session.toml"
        if not toml_path.exists():
            raise FileNotFoundError(f"no session {session_id} in {project_slug}")
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        return Session(
            id=data["id"],
            project_slug=project_slug,
            root=root,
            created_at=data["created_at"],
            title=data.get("title") or None,
        )

    def delete_session(self, project_slug: str, session_id: str) -> None:
        """Remove a session directory entirely."""
        import shutil

        project = self.get(project_slug)
        root = project.sessions_dir / session_id
        toml_path = root / "session.toml"
        if not toml_path.exists():
            raise FileNotFoundError(f"no session {session_id} in {project_slug}")
        shutil.rmtree(root)

    def delete_project(self, slug: str) -> None:
        """Remove a project directory entirely."""
        import shutil

        root = self.workspace.resolve(f"projects/{slug}")
        if not (root / "project.toml").exists():
            raise FileNotFoundError(f"no project {slug}")
        shutil.rmtree(root)

    def promote(self, session: Session, rel_path: str | Path) -> Path:
        """Move ``rel_path`` (relative to session scratch) into project files."""
        src = session.scratch_dir / rel_path
        src = src.resolve()
        try:
            src.relative_to(session.scratch_dir.resolve())
        except ValueError as e:
            raise WorkspaceError(f"not in session scratch: {rel_path}") from e
        if not src.exists():
            raise FileNotFoundError(src)
        project = self.get(session.project_slug)
        dst = project.files_dir / src.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)
        return dst

    def _load_project(self, slug: str) -> Project:
        root = self.workspace.resolve(Path("projects") / slug)
        toml_path = root / "project.toml"
        if not toml_path.exists():
            raise FileNotFoundError(f"no project {slug}")
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        return Project(
            slug=data.get("slug", slug),
            name=data.get("name", slug),
            root=root,
            created_at=data.get("created_at", _utcnow_iso()),
        )


def _write_toml(path: Path, data: dict[str, str]) -> None:
    lines = [f'{key} = "{_escape(value)}"\n' for key, value in data.items()]
    path.write_text("".join(lines), encoding="utf-8")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
