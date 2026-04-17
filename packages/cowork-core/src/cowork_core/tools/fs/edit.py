"""``fs.edit`` — exact, unique-match string replacement inside a text file.

The agent supplies ``old`` (a literal substring) and ``new``. The tool refuses
to edit if ``old`` does not appear exactly once: zero matches means the file
is not what the agent thinks it is; multiple matches means the edit is
ambiguous and the agent should widen its context first.
"""

from __future__ import annotations

from google.adk.tools.tool_context import ToolContext

from cowork_core.tools.base import get_cowork_context, was_read
from cowork_core.tools.fs._paths import try_resolve_project_path


def fs_edit(
    path: str,
    old: str,
    new: str,
    tool_context: ToolContext,
) -> dict[str, object]:
    """Replace a unique ``old`` substring with ``new`` in a text file.

    Args:
        path: Project-relative path to an existing UTF-8 file.
        old: Literal substring to match. Must appear exactly once.
        new: Replacement text.

    Returns:
        ``{"path": str, "bytes": int}`` on success, ``{"error": str}`` otherwise.
    """
    if old == new:
        return {"error": "old and new are identical"}
    if not was_read(tool_context, path):
        return {"error": f"must read {path} before editing (call fs_read first)"}
    ctx = get_cowork_context(tool_context)
    abspath = try_resolve_project_path(ctx, path)
    if isinstance(abspath, str):
        return {"error": abspath}
    if not abspath.is_file():
        return {"error": f"not a file: {path}"}
    text = abspath.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        return {"error": f"no match for old in {path}"}
    if count > 1:
        return {"error": f"{count} matches for old in {path}; widen context"}
    updated = text.replace(old, new, 1)
    data = updated.encode("utf-8")
    abspath.write_bytes(data)
    return {"path": path, "bytes": len(data)}
