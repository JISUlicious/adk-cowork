"""``fs.glob`` — match files in the project by pathname pattern."""

from __future__ import annotations

from pathlib import Path

from google.adk.tools.tool_context import ToolContext

from cowork_core.tools.base import get_cowork_context
from cowork_core.workspace import WorkspaceError

_MAX_RESULTS = 500


def fs_glob(pattern: str, tool_context: ToolContext) -> dict[str, object]:
    """Return project-relative paths matching a glob pattern.

    Patterns must start with the ``scratch/`` or ``files/`` namespace prefix
    (e.g. ``scratch/**/*.md``). Results are prefixed the same way.
    """
    ctx = get_cowork_context(tool_context)
    parts = Path(pattern).parts
    if not parts:
        raise WorkspaceError("empty pattern")
    head = parts[0]
    sub = "/".join(parts[1:]) or "*"
    if head == "scratch":
        base = ctx.session.scratch_dir.resolve()
    elif head == "files":
        base = ctx.project.files_dir.resolve()
    else:
        raise WorkspaceError(f"pattern must start with 'scratch/' or 'files/': {pattern}")
    matches: list[str] = []
    for hit in sorted(base.glob(sub)):
        try:
            rel = hit.resolve().relative_to(base)
        except ValueError:
            continue
        matches.append(f"{head}/{rel}")
        if len(matches) >= _MAX_RESULTS:
            return {"pattern": pattern, "matches": matches, "truncated": True}
    return {"pattern": pattern, "matches": matches, "truncated": False}
