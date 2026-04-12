"""Shared path resolution for fs.* tools.

The agent sees a synthetic two-namespace view of the active project:

* ``scratch/...`` → the *current session's* scratch directory (drafts)
* ``files/...``  → the project's durable ``files/`` directory

Any other prefix, or any path that escapes its namespace, is rejected. This
keeps the agent-visible path space stable across sessions and hides the real
``projects/<slug>/sessions/<id>/`` layout behind a clean pair of roots.
"""

from __future__ import annotations

from pathlib import Path

from cowork_core.tools.base import CoworkToolContext
from cowork_core.workspace import WorkspaceError


def resolve_project_path(ctx: CoworkToolContext, rel: str) -> Path:
    parts = Path(rel).parts
    if not parts:
        raise WorkspaceError("empty path")
    head, tail = parts[0], Path(*parts[1:]) if len(parts) > 1 else Path()
    if head == "scratch":
        base = ctx.session.scratch_dir.resolve()
    elif head == "files":
        base = ctx.project.files_dir.resolve()
    else:
        raise WorkspaceError(f"path must start with 'scratch/' or 'files/': {rel}")
    candidate = (base / tail).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as e:
        raise WorkspaceError(f"path escapes {head}/: {rel}") from e
    return candidate
