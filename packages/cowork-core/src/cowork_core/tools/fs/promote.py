"""``fs.promote`` — move a scratch file into durable project files."""

from __future__ import annotations

from google.adk.tools.tool_context import ToolContext

from cowork_core.tools.base import get_cowork_context


def fs_promote(rel_path: str, tool_context: ToolContext) -> dict[str, object]:
    """Promote a file from session scratch into the project ``files/`` dir.

    Args:
        rel_path: Path relative to the session scratch dir (e.g. ``draft.md``).

    Returns:
        ``{"path": "files/<name>"}`` on success, ``{"error": str}`` otherwise.
    """
    ctx = get_cowork_context(tool_context)
    dst = ctx.registry.promote(ctx.session, rel_path)
    rel = dst.relative_to(ctx.project.root)
    return {"path": str(rel)}
