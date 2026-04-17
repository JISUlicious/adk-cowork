"""Workspace sandbox, projects, and sessions."""

from cowork_core.workspace.project import (
    Project,
    ProjectRegistry,
    ProjectRegistryBase,
    Session,
    slugify,
)
from cowork_core.workspace.storage import FileStorage, LocalFileStorage
from cowork_core.workspace.workspace import Workspace, WorkspaceError

__all__ = [
    "FileStorage",
    "LocalFileStorage",
    "Project",
    "ProjectRegistry",
    "ProjectRegistryBase",
    "Session",
    "Workspace",
    "WorkspaceError",
    "slugify",
]
