"""``fs.promote`` — move a scratch file into durable project files.

Only meaningful in managed-mode sessions (scratch/+files/ layout). In
local-dir sessions the agent already writes directly into the user's
chosen folder, so "promotion" is a no-op — we return a clear error
directing the agent at ``fs_write`` / ``fs_edit`` instead, rather than
silently mangling paths.
"""

from __future__ import annotations

from google.adk.tools.tool_context import ToolContext

from cowork_core.execenv import LocalDirExecEnv
from cowork_core.tools.base import get_cowork_context
from cowork_core.workspace.workspace import WorkspaceError


def fs_promote(rel_path: str, tool_context: ToolContext) -> dict[str, object]:
    """Promote a file from session scratch into the project ``files/`` dir.

    Args:
        rel_path: Path relative to the session scratch dir (e.g. ``draft.md``).

    Returns:
        ``{"path": "files/<name>"}`` on success, ``{"error": str, ...}`` otherwise.
    """
    ctx = get_cowork_context(tool_context)
    if isinstance(ctx.env, LocalDirExecEnv):
        return {
            "error": (
                "fs_promote is a no-op in local-dir mode: there is no "
                "scratch→files distinction because the agent already writes "
                "directly into the user's chosen folder. Use fs_write / "
                "fs_edit to place the file where you want it."
            ),
        }
    try:
        dst = ctx.registry.promote(ctx.session, rel_path)
    except FileNotFoundError:
        available = _list_scratch(ctx.session.scratch_dir)
        return {
            "error": f"No file at scratch/{rel_path}",
            "available": available,
            "hint": "rel_path must be relative to the session scratch dir. "
                    "If your file lives in a subdirectory, include it (e.g. "
                    "'drafts/report.docx').",
        }
    except WorkspaceError as e:
        return {"error": str(e)}
    rel = dst.relative_to(ctx.project.root)
    return {"path": str(rel)}


def _list_scratch(scratch_dir: object) -> list[str]:
    from pathlib import Path
    p = Path(str(scratch_dir))
    if not p.is_dir():
        return []
    return sorted(str(f.relative_to(p)) for f in p.rglob("*") if f.is_file())
