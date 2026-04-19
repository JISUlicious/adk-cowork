"""``fs.write`` — create or overwrite a UTF-8 text file inside the project."""

from __future__ import annotations

from google.adk.tools.tool_context import ToolContext

from cowork_core.tools.base import get_cowork_context


def fs_write(path: str, content: str, tool_context: ToolContext) -> dict[str, object]:
    """Create or overwrite a UTF-8 text file at ``path``.

    Args:
        path: Project-relative path. Parents are created if needed.
        content: Full file contents to write.

    Returns:
        ``{"path": str, "bytes": int}``.
    """
    ctx = get_cowork_context(tool_context)
    abspath = ctx.env.try_resolve(path)
    if isinstance(abspath, str):
        return {"error": abspath}
    abspath.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    abspath.write_bytes(data)
    return {"path": path, "bytes": len(data)}
