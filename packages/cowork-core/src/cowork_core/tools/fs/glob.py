"""``fs.glob`` — match files in the project by pathname pattern."""

from __future__ import annotations

from pathlib import Path

from google.adk.tools.tool_context import ToolContext

from cowork_core.tools.base import get_cowork_context

_MAX_RESULTS = 500


def fs_glob(pattern: str, tool_context: ToolContext) -> dict[str, object]:
    """Return project-relative paths matching a glob pattern.

    Patterns may start with ``scratch/`` or ``files/`` to limit the search to
    one namespace.  A bare pattern (e.g. ``**/*.md``) searches both namespaces
    and returns combined results prefixed with their namespace.
    """
    ctx = get_cowork_context(tool_context)
    parts = Path(pattern).parts
    if not parts:
        return {"error": "empty pattern"}

    head = parts[0]
    if head == "scratch":
        namespaces = [("scratch", ctx.session.scratch_dir.resolve())]
        sub = "/".join(parts[1:]) or "*"
    elif head == "files":
        namespaces = [("files", ctx.project.files_dir.resolve())]
        sub = "/".join(parts[1:]) or "*"
    else:
        # No prefix — search both namespaces with the full pattern as the glob.
        namespaces = [
            ("scratch", ctx.session.scratch_dir.resolve()),
            ("files", ctx.project.files_dir.resolve()),
        ]
        sub = pattern

    matches: list[str] = []
    for ns, base in namespaces:
        for hit in sorted(base.glob(sub)):
            try:
                rel = hit.resolve().relative_to(base)
            except ValueError:
                continue
            matches.append(f"{ns}/{rel}")
            if len(matches) >= _MAX_RESULTS:
                return {"pattern": pattern, "matches": matches, "truncated": True}

    return {"pattern": pattern, "matches": matches, "truncated": False}
