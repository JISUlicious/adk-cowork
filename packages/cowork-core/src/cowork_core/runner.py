"""Assemble the full Cowork runtime — runner, registries, tool wiring.

``build_runtime(cfg)`` is the single entry point a surface (CLI, server, app)
uses to get everything it needs:

* an ADK ``Runner`` whose root agent has all execution-surface tools
  registered and all installed skills listed in its system prompt
* the ``Workspace``, ``ProjectRegistry``, and ``SkillRegistry`` instances so
  the surface can create project-scoped sessions and inject a
  ``CoworkToolContext`` into session state
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService

from cowork_core.agents.root_agent import build_root_agent
from cowork_core.config import CoworkConfig
from cowork_core.skills import SkillRegistry, register_skill_tools
from cowork_core.tools import COWORK_CONTEXT_KEY, CoworkToolContext, ToolRegistry
from cowork_core.tools.fs import register_fs_tools
from cowork_core.tools.http import register_http_tools
from cowork_core.tools.python_exec import register_python_exec_tools
from cowork_core.tools.search import register_search_tools
from cowork_core.tools.shell import register_shell_tools
from cowork_core.workspace import Project, ProjectRegistry, Session, Workspace

APP_NAME = "cowork"
DEFAULT_PROJECT_NAME = "Default"


@dataclass
class CoworkRuntime:
    cfg: CoworkConfig
    workspace: Workspace
    projects: ProjectRegistry
    skills: SkillRegistry
    tools: ToolRegistry
    runner: Runner

    async def open_session(
        self,
        user_id: str = "local",
        project_name: str | None = None,
        adk_session_id: str | None = None,
    ) -> tuple[Project, Session, str]:
        """Create a Cowork session + matching ADK session with wired state.

        Returns ``(project, session, adk_session_id)``.
        """
        project = self.projects.get_or_create(project_name or DEFAULT_PROJECT_NAME)
        session = self.projects.new_session(project.slug)

        ctx = CoworkToolContext(
            workspace=self.workspace,
            registry=self.projects,
            project=project,
            session=session,
            config=self.cfg,
            skills=self.skills,
        )
        state: dict[str, Any] = {COWORK_CONTEXT_KEY: ctx}
        adk_sid = adk_session_id or session.id
        await self.runner.session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=adk_sid,
            state=state,
        )
        return project, session, adk_sid


def build_runtime(cfg: CoworkConfig) -> CoworkRuntime:
    workspace = Workspace(root=cfg.workspace.root)
    projects = ProjectRegistry(workspace=workspace)
    skills = SkillRegistry()
    skills.scan(Path(cfg.workspace.root) / "global" / "skills")

    tool_registry = ToolRegistry()
    register_fs_tools(tool_registry)
    register_shell_tools(tool_registry)
    register_python_exec_tools(tool_registry)
    register_http_tools(tool_registry)
    register_search_tools(tool_registry)
    register_skill_tools(tool_registry)

    agent = build_root_agent(
        cfg,
        tools=tool_registry.as_list(),
        skills_snippet=skills.injection_snippet(),
    )
    runner = Runner(
        app_name=APP_NAME,
        agent=agent,
        session_service=InMemorySessionService(),
    )
    return CoworkRuntime(
        cfg=cfg,
        workspace=workspace,
        projects=projects,
        skills=skills,
        tools=tool_registry,
        runner=runner,
    )


def build_runner(cfg: CoworkConfig) -> Runner:
    """Back-compat shim — returns just the ADK ``Runner``."""
    return build_runtime(cfg).runner
