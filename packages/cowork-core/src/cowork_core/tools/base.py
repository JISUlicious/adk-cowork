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

    from cowork_core.approvals import ApprovalStore
    from cowork_core.config import CoworkConfig
    from cowork_core.execenv import ExecEnv
    from cowork_core.skills.loader import SkillRegistry

COWORK_CONTEXT_KEY = "cowork.tool_context"
COWORK_READS_KEY = "cowork.session_reads"
COWORK_POLICY_MODE_KEY = "cowork.policy_mode"
# Per-session override for ``PolicyConfig.python_exec`` — one of
# ``"confirm" | "allow" | "deny"``. Permission callback falls back to
# ``cfg.policy.python_exec`` when unset.
COWORK_PYTHON_EXEC_KEY = "cowork.python_exec"

# Per-session ``dict[str, list[str]]`` — agent name → allowed tool names.
# An agent absent from the dict runs unrestricted (default); an empty
# list effectively silences the agent. Enforced by
# ``make_allowlist_callback`` in ``policy/permissions.py`` — one closure
# per sub-agent, attached at agent-build time in ``root_agent.py``.
COWORK_TOOL_ALLOWLIST_KEY = "cowork.tool_allowlist"

# Per-session bool — when True (default), the root agent's instruction
# includes the ``@``-mention routing protocol. When False, the
# paragraph is omitted and ``@researcher ...`` goes to the root for a
# normal delegation decision (escape hatch if the protocol misbehaves).
# Tier E.E2.
COWORK_AUTO_ROUTE_KEY = "cowork.auto_route"

# Per-session ``dict[str, bool]`` — skill name → enabled. Absent skill
# defaults to enabled, so a skill installed mid-session shows up
# without further action. The root agent's prompt registry omits
# disabled skills; ``load_skill`` refuses them with an explanatory
# error so the model can't bypass the gate by guessing the name.
# Slice II.
COWORK_SKILLS_ENABLED_KEY = "cowork.skills_enabled"

# Per-session ``list[str]`` — names of MCP servers disabled this
# session. Absent / empty list = all configured servers enabled.
# Mirrors Claude Code's settings-level ``disabledMcpServers`` but
# scoped per-session because Cowork runs concurrent sessions on
# one process. Tools owned by a disabled server are blocked at the
# ``before_tool_callback`` layer with an explanatory error. Slice VI.
COWORK_MCP_DISABLED_KEY = "cowork.mcp_disabled"


@dataclass(frozen=True)
class CoworkToolContext:
    workspace: Workspace
    registry: ProjectRegistry
    project: Project
    session: Session
    config: CoworkConfig
    skills: SkillRegistry
    env: ExecEnv
    approvals: ApprovalStore


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
    reads: list[str] = tool_context.state.setdefault(COWORK_READS_KEY, [])
    if path not in reads:
        reads.append(path)


def was_read(tool_context: ToolContext, path: str) -> bool:
    """Check whether a project-relative path has been read in this session."""
    reads = tool_context.state.get(COWORK_READS_KEY)
    if not isinstance(reads, list):
        return False
    return path in reads
