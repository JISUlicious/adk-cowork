"""Per-invocation cowork context passed to every tool call.

ADK's ``ToolContext`` exposes ``.state`` — a session-scoped key/value store.
Cowork stores a single ``CoworkToolContext`` there under ``COWORK_CONTEXT_KEY``
so tools (fs, shell, python_exec, …) can look up the active workspace, project
and session without importing anything global.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from cowork_core.workspace import Project, ProjectRegistry, Session, Workspace

if TYPE_CHECKING:
    from google.adk.tools.tool_context import ToolContext

    from cowork_core.config import CoworkConfig
    from cowork_core.skills.loader import SkillRegistry

COWORK_CONTEXT_KEY = "cowork.tool_context"
COWORK_READS_KEY = "cowork.session_reads"


@dataclass(frozen=True)
class CoworkToolContext:
    workspace: Workspace
    registry: ProjectRegistry
    project: Project
    session: Session
    config: CoworkConfig
    skills: SkillRegistry


def get_cowork_context(tool_context: ToolContext) -> CoworkToolContext:
    """Fetch the cowork context stashed in ADK's session state."""
    ctx = tool_context.state.get(COWORK_CONTEXT_KEY)
    if ctx is None:
        raise RuntimeError(
            f"cowork context missing from tool_context.state[{COWORK_CONTEXT_KEY!r}]"
        )
    if not isinstance(ctx, CoworkToolContext):
        raise TypeError(f"expected CoworkToolContext, got {type(ctx).__name__}")
    return ctx


def record_read(tool_context: ToolContext, path: str) -> None:
    """Mark a project-relative path as read in this session."""
    reads: set[str] = tool_context.state.setdefault(COWORK_READS_KEY, set())
    reads.add(path)


def was_read(tool_context: ToolContext, path: str) -> bool:
    """Check whether a project-relative path has been read in this session."""
    reads = tool_context.state.get(COWORK_READS_KEY)
    if not isinstance(reads, set):
        return False
    return path in reads
