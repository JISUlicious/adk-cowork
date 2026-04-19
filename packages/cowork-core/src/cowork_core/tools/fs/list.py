"""``fs.list`` — list the entries of a directory inside the project."""

from __future__ import annotations

from google.adk.tools.tool_context import ToolContext

from cowork_core.tools.base import get_cowork_context


def fs_list(path: str, tool_context: ToolContext) -> dict[str, object]:
    """List entries of a directory under the active project.

    Args:
        path: Project-relative directory path. Use ``"."`` for the project root.

    Returns:
        ``{"path": str, "entries": [{"name", "kind", "size"}, ...]}``.
    """
    ctx = get_cowork_context(tool_context)
    abspath = ctx.env.try_resolve(path)
    if isinstance(abspath, str):
        return {"error": abspath}
    if not abspath.is_dir():
        return {"error": f"not a directory: {path}"}
    entries: list[dict[str, object]] = []
    for child in sorted(abspath.iterdir()):
        if child.is_dir():
            entries.append({"name": child.name, "kind": "dir", "size": 0})
        else:
            entries.append({"name": child.name, "kind": "file", "size": child.stat().st_size})
    return {"path": path, "entries": entries}
