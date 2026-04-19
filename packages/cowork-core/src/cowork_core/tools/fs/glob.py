"""``fs.glob`` — match files in the project by pathname pattern."""

from __future__ import annotations

from google.adk.tools.tool_context import ToolContext

from cowork_core.tools.base import get_cowork_context

_MAX_RESULTS = 500


def fs_glob(pattern: str, tool_context: ToolContext) -> dict[str, object]:
    """Return agent-relative paths matching a glob pattern.

    Namespace prefixes (e.g. ``scratch/``, ``files/``) are honored in
    ManagedExecEnv and ignored in LocalDirExecEnv. A bare pattern in managed
    mode searches both namespaces; in local-dir mode a bare pattern matches
    the whole workdir.
    """
    if not pattern:
        return {"error": "empty pattern"}
    ctx = get_cowork_context(tool_context)
    matches, truncated = ctx.env.glob(pattern, limit=_MAX_RESULTS)
    return {"pattern": pattern, "matches": matches, "truncated": truncated}
