"""``fs.stat`` — return metadata for a single file or directory."""

from __future__ import annotations

from google.adk.tools.tool_context import ToolContext

from cowork_core.tools.base import get_cowork_context


def fs_stat(path: str, tool_context: ToolContext) -> dict[str, object]:
    """Return ``{path, kind, size, mtime}`` for a project entry.

    Args:
        path: Project-relative path.
    """
    ctx = get_cowork_context(tool_context)
    abspath = ctx.env.try_resolve(path)
    if isinstance(abspath, str):
        return {"error": abspath}
    if not abspath.exists():
        return {"error": f"no such path: {path}"}
    st = abspath.stat()
    return {
        "path": path,
        "kind": "dir" if abspath.is_dir() else "file",
        "size": st.st_size,
        "mtime": int(st.st_mtime),
    }
