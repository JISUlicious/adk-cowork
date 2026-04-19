"""``fs.read`` — read a UTF-8 text file inside the active project."""

from __future__ import annotations

from google.adk.tools.tool_context import ToolContext

from cowork_core.tools.base import get_cowork_context, record_read

_MAX_BYTES = 2_000_000


def fs_read(path: str, tool_context: ToolContext) -> dict[str, object]:
    """Read a UTF-8 text file from the active project.

    Args:
        path: Project-relative path (e.g. ``scratch/draft.md``).

    Returns:
        ``{"path": str, "content": str, "truncated": bool}``.
    """
    ctx = get_cowork_context(tool_context)
    abspath = ctx.env.try_resolve(path)
    if isinstance(abspath, str):
        return {"error": abspath}
    if not abspath.is_file():
        return {"error": f"not a file: {path}"}
    data = abspath.read_bytes()
    truncated = len(data) > _MAX_BYTES
    if truncated:
        data = data[:_MAX_BYTES]
    record_read(tool_context, path)
    return {
        "path": path,
        "content": data.decode("utf-8", errors="replace"),
        "truncated": truncated,
    }
