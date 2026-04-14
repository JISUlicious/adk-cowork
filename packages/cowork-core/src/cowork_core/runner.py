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

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from google.adk.runners import Runner
from google.adk.sessions import Session as AdkSession
from google.adk.sessions.base_session_service import (
    BaseSessionService,
    GetSessionConfig,
    ListSessionsResponse,
)
from google.adk.sessions.sqlite_session_service import SqliteSessionService

from cowork_core.agents.root_agent import build_root_agent
from cowork_core.config import CoworkConfig
from cowork_core.skills import SkillRegistry, register_skill_tools
from cowork_core.tools import COWORK_CONTEXT_KEY, CoworkToolContext, ToolRegistry
from cowork_core.tools.email import register_email_tools
from cowork_core.tools.fs import register_fs_tools
from cowork_core.tools.http import register_http_tools
from cowork_core.tools.python_exec import register_python_exec_tools
from cowork_core.tools.search import register_search_tools
from cowork_core.tools.shell import register_shell_tools
from cowork_core.workspace import Project, ProjectRegistry, Session, Workspace

APP_NAME = "cowork"
DEFAULT_PROJECT_NAME = "Default"


class _CoworkSessionService(BaseSessionService):
    """Wraps SqliteSessionService, injecting non-serializable CoworkToolContext.

    ADK's SqliteSessionService persists session state as JSON. Our
    CoworkToolContext contains live Python objects (Workspace, ProjectRegistry)
    that can't be serialized. This wrapper:

    1. Stores a lightweight ``_cowork_meta`` dict (project_slug, session_id) in
       the ADK state — this *is* JSON-safe and persists to SQLite.
    2. On ``get_session``, injects the full ``CoworkToolContext`` back into the
       session's in-memory state using the persisted metadata.
    """

    def __init__(self, db_path: str) -> None:
        self._inner = SqliteSessionService(db_path)
        self._context_builders: dict[str, _ContextBuilder] = {}

    def register_context(self, session_id: str, builder: _ContextBuilder) -> None:
        self._context_builders[session_id] = builder

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> AdkSession:
        # Extract CoworkToolContext before persisting — it's not JSON-safe
        safe_state = dict(state or {})
        ctx = safe_state.pop(COWORK_CONTEXT_KEY, None)
        if ctx and isinstance(ctx, CoworkToolContext):
            safe_state["_cowork_meta"] = {
                "project_slug": ctx.project.slug,
                "session_id": ctx.session.id,
            }

        adk_session = await self._inner.create_session(
            app_name=app_name,
            user_id=user_id,
            state=safe_state,
            session_id=session_id,
        )

        # Inject the live context into the in-memory session
        if ctx:
            adk_session.state[COWORK_CONTEXT_KEY] = ctx
        return adk_session

    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: GetSessionConfig | None = None,
    ) -> AdkSession | None:
        adk_session = await self._inner.get_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            config=config,
        )
        if adk_session is None:
            return None

        # Re-inject CoworkToolContext from the registered builder
        if COWORK_CONTEXT_KEY not in adk_session.state:
            builder = self._context_builders.get(session_id)
            if builder:
                adk_session.state[COWORK_CONTEXT_KEY] = builder()
        return adk_session

    async def list_sessions(
        self,
        *,
        app_name: str,
        user_id: str | None = None,
    ) -> ListSessionsResponse:
        return await self._inner.list_sessions(
            app_name=app_name, user_id=user_id,
        )

    async def delete_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> None:
        self._context_builders.pop(session_id, None)
        await self._inner.delete_session(
            app_name=app_name, user_id=user_id, session_id=session_id,
        )

    async def append_event(self, session: AdkSession, event: Any) -> Any:
        return await self._inner.append_event(session, event)


_ContextBuilder = Any  # Callable[[], CoworkToolContext]


@dataclass
class CoworkRuntime:
    cfg: CoworkConfig
    workspace: Workspace
    projects: ProjectRegistry
    skills: SkillRegistry
    tools: ToolRegistry
    runner: Runner
    session_service: _CoworkSessionService = field(init=False)

    def __post_init__(self) -> None:
        # Expose the session service for context registration
        svc = self.runner.session_service
        assert isinstance(svc, _CoworkSessionService)
        self.session_service = svc

    def _build_context(self, project: Project, session: Session) -> CoworkToolContext:
        session_skills = SkillRegistry(_skills=dict(self.skills._skills))
        session_skills.scan(self.workspace.root / ".cowork" / "skills")
        return CoworkToolContext(
            workspace=self.workspace,
            registry=self.projects,
            project=project,
            session=session,
            config=self.cfg,
            skills=session_skills,
        )

    async def open_session(
        self,
        user_id: str = "local",
        project_name: str | None = None,
        adk_session_id: str | None = None,
    ) -> tuple[Project, Session, str]:
        """Create a Cowork session + matching ADK session with wired state."""
        project = self.projects.get_or_create(project_name or DEFAULT_PROJECT_NAME)
        session = self.projects.new_session(project.slug)

        ctx = self._build_context(project, session)
        state: dict[str, Any] = {COWORK_CONTEXT_KEY: ctx}
        adk_sid = adk_session_id or session.id
        self.session_service.register_context(
            adk_sid, lambda p=project, s=session: self._build_context(p, s),
        )
        await self.runner.session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=adk_sid,
            state=state,
        )
        return project, session, adk_sid

    async def resume_session(
        self,
        project_slug: str,
        session_id: str,
        user_id: str = "local",
    ) -> tuple[Project, Session, str]:
        """Resume an existing cowork session."""
        project = self.projects.get(project_slug)
        session = self.projects.get_session(project_slug, session_id)
        adk_sid = session.id

        # Register context builder so get_session can inject it
        self.session_service.register_context(
            adk_sid, lambda p=project, s=session: self._build_context(p, s),
        )

        # Check if ADK session exists; if not, create it
        existing = await self.runner.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=adk_sid,
        )
        if existing:
            return project, session, adk_sid

        ctx = self._build_context(project, session)
        state: dict[str, Any] = {COWORK_CONTEXT_KEY: ctx}
        await self.runner.session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=adk_sid,
            state=state,
        )
        return project, session, adk_sid


def _bundled_skills_dir() -> Path:
    """Path to default skills shipped inside the cowork-core package."""
    return Path(__file__).parent / "skills" / "bundled"


def _user_config_dir() -> Path:
    """``~/.config/cowork`` (XDG-style user config root)."""
    return Path.home() / ".config" / "cowork"


def build_runtime(cfg: CoworkConfig) -> CoworkRuntime:
    workspace = Workspace(root=cfg.workspace.root)
    projects = ProjectRegistry(workspace=workspace)
    skills = SkillRegistry()
    skills.scan(_bundled_skills_dir())
    skills.scan(_user_config_dir() / "skills")

    tool_registry = ToolRegistry()
    register_fs_tools(tool_registry)
    register_shell_tools(tool_registry)
    register_python_exec_tools(tool_registry)
    register_http_tools(tool_registry)
    register_search_tools(tool_registry)
    register_email_tools(tool_registry)
    register_skill_tools(tool_registry)

    agent = build_root_agent(
        cfg,
        tools=tool_registry.as_list(),
        skills_snippet=skills.injection_snippet(),
    )

    global_dir = workspace.root / "global"
    global_dir.mkdir(parents=True, exist_ok=True)
    db_path = str(global_dir / "sessions.db")
    session_service = _CoworkSessionService(db_path)

    runner = Runner(
        app_name=APP_NAME,
        agent=agent,
        session_service=session_service,
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
