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

from google.adk.apps.app import App, EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.runners import Runner

from cowork_core.agents.root_agent import build_root_agent
from cowork_core.model.openai_compat import build_model
from cowork_core.approvals import (
    ApprovalStore,
    InMemoryApprovalEventLog,
    InMemoryApprovalStore,
)
from cowork_core.notifications import (
    InMemoryNotificationStore,
    NotificationStore,
)
from cowork_core.config import CoworkConfig
from cowork_core.execenv import LocalDirExecEnv, ManagedExecEnv
from cowork_core.sessions import SqliteCoworkSessionService
from cowork_core.skills import SkillRegistry, register_skill_tools
from cowork_core.tools import (
    COWORK_AUTO_ROUTE_KEY,
    COWORK_CONTEXT_KEY,
    COWORK_POLICY_MODE_KEY,
    COWORK_PYTHON_EXEC_KEY,
    COWORK_TOOL_ALLOWLIST_KEY,
    CoworkToolContext,
    ToolRegistry,
)
from cowork_core.tools.email import register_email_tools
from cowork_core.tools.fs import register_fs_tools
from cowork_core.tools.http import register_http_tools
from cowork_core.tools.python_exec import register_python_exec_tools
from cowork_core.tools.search import register_search_tools
from cowork_core.tools.shell import register_shell_tools
from cowork_core.workspace import Project, ProjectRegistry, Session, Workspace

APP_NAME = "cowork"
DEFAULT_PROJECT_NAME = "Default"

# Directory local-dir sessions drop their bookkeeping into, sibling of the
# user's files.
_LOCAL_COWORK_DIR = ".cowork"


@dataclass
class CoworkRuntime:
    cfg: CoworkConfig
    workspace: Workspace
    projects: ProjectRegistry
    skills: SkillRegistry
    tools: ToolRegistry
    runner: Runner
    # Process-local per-session approval counters. Deliberately not ADK
    # session state — see ``cowork_core/approvals.py`` for the race that
    # motivates this split.
    approvals: ApprovalStore = field(default_factory=InMemoryApprovalStore)
    # Side-channel record of each approval action so the UI can replay
    # "user approved this call" on history fetch without us writing
    # into the ADK session's event list (which races the runner's
    # OCC-guarded appends).
    approval_log: InMemoryApprovalEventLog = field(
        default_factory=InMemoryApprovalEventLog,
    )
    # Per-user notification inbox. Same "never write ADK session state"
    # rule as ``approvals``: see ``cowork_core/notifications.py``.
    notifications: NotificationStore = field(
        default_factory=InMemoryNotificationStore,
    )
    session_service: SqliteCoworkSessionService = field(init=False)

    def __post_init__(self) -> None:
        # Expose the session service for context registration
        svc = self.runner.session_service
        assert isinstance(svc, SqliteCoworkSessionService)
        self.session_service = svc

    # ── Per-user workspace / registry (multi-user auth) ────────────────

    @property
    def multi_user(self) -> bool:
        """True when the config declares multiple API keys.

        In multi-user mode, each request's workspace is scoped to
        ``<workspace.root>/users/<user_id>/`` so tenants can't see each
        other's projects.
        """
        return bool(self.cfg.auth.keys)

    def workspace_for(self, user_id: str) -> Workspace:
        if not self.multi_user or user_id == "local":
            return self.workspace
        # Lazy subdir; Workspace.__post_init__ mkdir's it.
        user_root = self.workspace.root / "users" / user_id
        return Workspace(root=user_root)

    def registry_for(self, user_id: str) -> ProjectRegistry:
        if not self.multi_user or user_id == "local":
            return self.projects
        return ProjectRegistry(workspace=self.workspace_for(user_id))

    def _build_context(
        self,
        project: Project,
        session: Session,
        *,
        workdir: Path | None = None,
        user_id: str = "local",
    ) -> CoworkToolContext:
        """Build the per-invocation CoworkToolContext.

        ``workdir`` is set for local-dir (desktop) sessions; the env is a
        ``LocalDirExecEnv`` rooted at that path. Otherwise a ``ManagedExecEnv``
        bound to (project, session) gives the classic two-namespace view.
        """
        session_skills = SkillRegistry(_skills=dict(self.skills._skills))
        session_skills.scan(self.workspace.root / ".cowork" / "skills")
        if workdir is not None:
            env: Any = LocalDirExecEnv(workdir=workdir, session_id=session.id)
        else:
            env = ManagedExecEnv(project=project, session=session)
        return CoworkToolContext(
            workspace=self.workspace_for(user_id),
            registry=self.registry_for(user_id),
            project=project,
            session=session,
            config=self.cfg,
            skills=session_skills,
            env=env,
            approvals=self.approvals,
        )

    def _materialize_local_session(
        self, workdir: Path, session_id: str | None = None,
    ) -> tuple[Project, Session]:
        """Create on-disk session dirs under ``<workdir>/.cowork/sessions/``.

        Returns a synthetic ``Project`` whose ``root`` is the workdir and a
        ``Session`` whose ``root`` holds the transcript + scratch. Re-using
        the existing dataclasses lets audit hooks and tools stay surface-
        agnostic.
        """
        import uuid
        from datetime import UTC, datetime

        workdir = workdir.resolve()
        if not workdir.is_dir():
            raise ValueError(f"workdir is not a directory: {workdir}")
        sessions_root = workdir / _LOCAL_COWORK_DIR / "sessions"
        sessions_root.mkdir(parents=True, exist_ok=True)

        sid = session_id or uuid.uuid4().hex
        session_root = sessions_root / sid
        (session_root / "scratch").mkdir(parents=True, exist_ok=True)
        (session_root / "transcript.jsonl").touch()

        created_at = datetime.now(UTC).isoformat(timespec="seconds")
        # Slug is just the workdir name; not stored in any registry. It only
        # flows through audit records and sub-agent delegation.
        slug = workdir.name or "localdir"
        project = Project(
            slug=slug,
            name=workdir.name or str(workdir),
            root=workdir,
            created_at=created_at,
        )
        session = Session(
            id=sid,
            project_slug=slug,
            root=session_root,
            created_at=created_at,
            title=None,
        )
        return project, session

    def _rehydrate_local_session(
        self, workdir: Path, session_id: str,
    ) -> tuple[Project, Session]:
        """Reconstruct an existing local-dir session from the filesystem."""
        import tomllib
        from datetime import UTC, datetime

        workdir = workdir.resolve()
        session_root = workdir / _LOCAL_COWORK_DIR / "sessions" / session_id
        if not session_root.is_dir():
            raise FileNotFoundError(f"no local session {session_id} in {workdir}")

        # Use filesystem mtime as created_at if no session.toml was written.
        toml_path = session_root / "session.toml"
        if toml_path.exists():
            with toml_path.open("rb") as f:
                data = tomllib.load(f)
            created_at = data.get("created_at", "")
            title = data.get("title") or None
            pinned = bool(data.get("pinned", False))
        else:
            created_at = (
                datetime.fromtimestamp(session_root.stat().st_mtime, tz=UTC)
                .isoformat(timespec="seconds")
            )
            title = None
            pinned = False

        slug = workdir.name or "localdir"
        project = Project(
            slug=slug,
            name=workdir.name or str(workdir),
            root=workdir,
            created_at=created_at,
        )
        session = Session(
            id=session_id,
            project_slug=slug,
            root=session_root,
            created_at=created_at,
            title=title,
            pinned=pinned,
        )
        return project, session

    def list_local_sessions(self, workdir: Path) -> list[Session]:
        """Return session objects for a local-dir workspace, newest first."""
        workdir = workdir.resolve()
        sessions_root = workdir / _LOCAL_COWORK_DIR / "sessions"
        if not sessions_root.is_dir():
            return []
        out: list[Session] = []
        for entry in sessions_root.iterdir():
            if not entry.is_dir():
                continue
            try:
                _, session = self._rehydrate_local_session(workdir, entry.name)
            except FileNotFoundError:
                continue
            out.append(session)
        out.sort(key=lambda s: s.created_at, reverse=True)
        return out

    def set_local_session_pinned(
        self, workdir: Path, session_id: str, pinned: bool,
    ) -> Session:
        """Toggle ``pinned`` on a local-dir session's TOML.

        Mirrors ``ProjectRegistry.set_session_pinned`` for managed mode.
        Uses the same ``_session_toml_lock`` to serialise writes across
        concurrent handlers. Writes a session.toml if one doesn't
        exist yet — local sessions are created without one today.
        """

        from cowork_core.workspace.project import _session_toml_lock, _write_toml

        with _session_toml_lock:
            _, session = self._rehydrate_local_session(workdir, session_id)
            _write_toml(
                session.toml_path,
                {
                    "id": session.id,
                    "title": session.title or "",
                    "created_at": session.created_at,
                    "pinned": bool(pinned),
                },
            )
            return Session(
                id=session.id,
                project_slug=session.project_slug,
                root=session.root,
                created_at=session.created_at,
                title=session.title,
                pinned=bool(pinned),
            )

    async def delete_local_session(
        self,
        workdir: Path,
        session_id: str,
        user_id: str = "local",
    ) -> None:
        """Remove a local-dir session's bookkeeping + ADK state."""
        import shutil

        workdir = workdir.resolve()
        session_root = workdir / _LOCAL_COWORK_DIR / "sessions" / session_id
        if session_root.is_dir():
            shutil.rmtree(session_root)
        self.approvals.clear(session_id)
        self.approval_log.clear(session_id)
        # Best-effort ADK cleanup — ignore if the ADK session was never created.
        try:
            await self.runner.session_service.delete_session(
                app_name=APP_NAME, user_id=user_id, session_id=session_id,
            )
        except Exception:
            pass

    async def open_session(
        self,
        user_id: str = "local",
        project_name: str | None = None,
        workdir: Path | str | None = None,
        adk_session_id: str | None = None,
    ) -> tuple[Project, Session, str]:
        """Create a Cowork session + matching ADK session.

        If ``workdir`` is supplied, the session is a *local-dir* session: the
        agent operates directly on the user's folder (desktop surface). If
        not, a *managed* session is created under the workspace root using
        the classic scratch/+files/ layout (web surface / default).
        """
        if workdir is not None:
            workdir_path = Path(workdir).resolve()
            project, session = self._materialize_local_session(workdir_path)
            ctx = self._build_context(
                project, session, workdir=workdir_path, user_id=user_id,
            )

            def _builder(
                p: Project = project,
                s: Session = session,
                w: Path = workdir_path,
                uid: str = user_id,
            ) -> CoworkToolContext:
                return self._build_context(p, s, workdir=w, user_id=uid)
        else:
            registry = self.registry_for(user_id)
            project = registry.get_or_create(project_name or DEFAULT_PROJECT_NAME)
            session = registry.new_session(project.slug)
            ctx = self._build_context(project, session, user_id=user_id)

            def _builder(
                p: Project = project,
                s: Session = session,
                uid: str = user_id,
            ) -> CoworkToolContext:
                return self._build_context(p, s, user_id=uid)

        state: dict[str, Any] = {
            COWORK_CONTEXT_KEY: ctx,
            COWORK_POLICY_MODE_KEY: self.cfg.policy.mode,
        }
        adk_sid = adk_session_id or session.id
        self.session_service.register_context(adk_sid, _builder)
        await self.runner.session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=adk_sid,
            state=state,
        )
        return project, session, adk_sid

    async def set_session_policy_mode(
        self,
        session_id: str,
        mode: str,
        user_id: str = "local",
    ) -> str:
        """Persist a new policy mode on the session via an ADK state_delta event.

        Raises ``ValueError`` if the mode is unknown or the session is missing.
        Returns the applied mode string.
        """
        if mode not in ("plan", "work", "auto"):
            raise ValueError(f"unknown policy mode: {mode!r}")
        session = await self.runner.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id,
        )
        if session is None:
            raise ValueError(f"no session {session_id}")

        # Lazy imports so cowork_core can be imported without a live ADK runtime.
        from google.adk.events.event import Event
        from google.adk.events.event_actions import EventActions

        event = Event(
            author="cowork-server",
            invocation_id="",
            actions=EventActions(state_delta={COWORK_POLICY_MODE_KEY: mode}),
        )
        await self.runner.session_service.append_event(session, event)
        return mode

    async def get_session_policy_mode(
        self,
        session_id: str,
        user_id: str = "local",
    ) -> str:
        """Return the session's current policy mode (fallback: cfg default)."""
        session = await self.runner.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id,
        )
        if session is None:
            raise ValueError(f"no session {session_id}")
        return session.state.get(COWORK_POLICY_MODE_KEY, self.cfg.policy.mode)

    async def set_session_python_exec(
        self,
        session_id: str,
        policy: str,
        user_id: str = "local",
    ) -> str:
        """Persist a per-session override for ``policy.python_exec``.

        Values: ``"confirm" | "allow" | "deny"``. Raises ``ValueError`` on
        unknown values or missing session.
        """
        if policy not in ("confirm", "allow", "deny"):
            raise ValueError(f"unknown python_exec policy: {policy!r}")
        session = await self.runner.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id,
        )
        if session is None:
            raise ValueError(f"no session {session_id}")

        from google.adk.events.event import Event
        from google.adk.events.event_actions import EventActions

        event = Event(
            author="cowork-server",
            invocation_id="",
            actions=EventActions(state_delta={COWORK_PYTHON_EXEC_KEY: policy}),
        )
        await self.runner.session_service.append_event(session, event)
        return policy

    async def get_session_python_exec(
        self,
        session_id: str,
        user_id: str = "local",
    ) -> str:
        """Return the session's python_exec policy (cfg fallback)."""
        session = await self.runner.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id,
        )
        if session is None:
            raise ValueError(f"no session {session_id}")
        return session.state.get(
            COWORK_PYTHON_EXEC_KEY, self.cfg.policy.python_exec,
        )

    async def set_session_tool_allowlist(
        self,
        session_id: str,
        allowlist: dict[str, list[str]],
        user_id: str = "local",
    ) -> dict[str, list[str]]:
        """Persist a per-agent tool allowlist override for the session.

        Tier E.E1. Structure: ``{agent_name: [tool_name, ...]}``. Agents
        absent from the dict run unrestricted; an empty list silences an
        agent (every tool call is blocked). Passing ``{}`` clears all
        restrictions — same as removing the key entirely, since the
        allowlist callback falls back to "no restriction" on an absent
        agent.
        """

        if not isinstance(allowlist, dict):
            raise ValueError("tool allowlist must be a dict")
        cleaned: dict[str, list[str]] = {}
        for agent_name, tools_for_agent in allowlist.items():
            if not isinstance(agent_name, str):
                raise ValueError(
                    f"allowlist agent name must be str, got {type(agent_name).__name__}",
                )
            if not isinstance(tools_for_agent, list) or not all(
                isinstance(t, str) for t in tools_for_agent
            ):
                raise ValueError(
                    f"allowlist for agent {agent_name!r} must be list[str]",
                )
            cleaned[agent_name] = list(tools_for_agent)

        session = await self.runner.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id,
        )
        if session is None:
            raise ValueError(f"no session {session_id}")

        from google.adk.events.event import Event
        from google.adk.events.event_actions import EventActions

        event = Event(
            author="cowork-server",
            invocation_id="",
            actions=EventActions(state_delta={COWORK_TOOL_ALLOWLIST_KEY: cleaned}),
        )
        await self.runner.session_service.append_event(session, event)
        return cleaned

    async def get_session_tool_allowlist(
        self,
        session_id: str,
        user_id: str = "local",
    ) -> dict[str, list[str]]:
        """Return the session's tool allowlist (empty dict when unset)."""
        session = await self.runner.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id,
        )
        if session is None:
            raise ValueError(f"no session {session_id}")
        stored = session.state.get(COWORK_TOOL_ALLOWLIST_KEY)
        if not isinstance(stored, dict):
            return {}
        return {
            str(k): list(v) if isinstance(v, list) else []
            for k, v in stored.items()
        }

    async def set_session_auto_route(
        self,
        session_id: str,
        enabled: bool,
        user_id: str = "local",
    ) -> bool:
        """Toggle the `@`-mention routing protocol for the session.

        Tier E.E2. When True (default), the root agent's prompt
        includes the ``@<agent_name>`` routing directive. When False,
        the paragraph is omitted and the root decides delegation
        normally — escape hatch.
        """
        if not isinstance(enabled, bool):
            raise ValueError(f"auto_route must be a bool, got {type(enabled).__name__}")
        session = await self.runner.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id,
        )
        if session is None:
            raise ValueError(f"no session {session_id}")

        from google.adk.events.event import Event
        from google.adk.events.event_actions import EventActions

        event = Event(
            author="cowork-server",
            invocation_id="",
            actions=EventActions(state_delta={COWORK_AUTO_ROUTE_KEY: enabled}),
        )
        await self.runner.session_service.append_event(session, event)
        return enabled

    async def get_session_auto_route(
        self,
        session_id: str,
        user_id: str = "local",
    ) -> bool:
        """Return the session's auto-route flag (default True)."""
        session = await self.runner.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id,
        )
        if session is None:
            raise ValueError(f"no session {session_id}")
        stored = session.state.get(COWORK_AUTO_ROUTE_KEY, True)
        return stored if isinstance(stored, bool) else True

    async def grant_tool_approval(
        self,
        session_id: str,
        tool_name: str,
        user_id: str = "local",
    ) -> int:
        """Increment the pending-approvals counter for ``tool_name``.

        Called when the user hits "Approve" in the UI. The next time the
        permission callback sees that tool name, it consumes one approval
        and lets the call through. Writes to ``self.approvals`` (process-
        local) instead of ADK session state, so the write can't race with
        ``runner.run_async`` and trip ``last_update_time`` errors.

        Returns the new counter value.
        """
        # Cheap existence check against the session store — avoids granting
        # approvals against ghost session ids. ADK's stale-session OCC isn't
        # a concern for read-only ``get_session`` calls.
        session = await self.runner.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id,
        )
        if session is None:
            raise ValueError(f"no session {session_id}")
        return self.approvals.grant(session_id, tool_name)

    async def list_tool_approvals(
        self,
        session_id: str,
        user_id: str = "local",
    ) -> dict[str, int]:
        """Return the pending-approvals dict for a session."""
        session = await self.runner.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id,
        )
        if session is None:
            raise ValueError(f"no session {session_id}")
        return self.approvals.list(session_id)

    async def resume_session(
        self,
        session_id: str,
        project_slug: str | None = None,
        workdir: Path | str | None = None,
        user_id: str = "local",
    ) -> tuple[Project, Session, str]:
        """Resume an existing cowork session.

        Exactly one of ``project_slug`` (managed mode) or ``workdir``
        (local-dir / desktop mode) must be supplied.
        """
        if workdir is not None:
            workdir_path = Path(workdir).resolve()
            project, session = self._rehydrate_local_session(
                workdir_path, session_id,
            )

            def _builder(
                p: Project = project,
                s: Session = session,
                w: Path = workdir_path,
                uid: str = user_id,
            ) -> CoworkToolContext:
                return self._build_context(p, s, workdir=w, user_id=uid)
        else:
            if not project_slug:
                raise ValueError("resume_session: project_slug or workdir is required")
            registry = self.registry_for(user_id)
            project = registry.get(project_slug)
            session = registry.get_session(project_slug, session_id)

            def _builder(
                p: Project = project,
                s: Session = session,
                uid: str = user_id,
            ) -> CoworkToolContext:
                return self._build_context(p, s, user_id=uid)

        adk_sid = session.id
        self.session_service.register_context(adk_sid, _builder)

        # Check if ADK session exists; if not, create it
        existing = await self.runner.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=adk_sid,
        )
        if existing:
            return project, session, adk_sid

        ctx = _builder()
        state: dict[str, Any] = {
            COWORK_CONTEXT_KEY: ctx,
            COWORK_POLICY_MODE_KEY: self.cfg.policy.mode,
        }
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
    if cfg.runtime.backend != "local":
        raise NotImplementedError(
            f"runtime backend {cfg.runtime.backend!r} is not implemented yet; "
            f"use 'local' (single-process in-memory + SQLite). Distributed "
            f"backends (Redis bus, Postgres sessions) will land in a later "
            f"phase against the same protocols."
        )
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
    session_service = SqliteCoworkSessionService(db_path)

    # Build an ``App`` when compaction is enabled so ADK can run its
    # native sliding-window + token-threshold compaction at the end of
    # each invocation. When disabled we fall back to the legacy
    # ``app_name + agent`` path so nothing extra is loaded.
    if cfg.compaction.enabled:
        summarizer = LlmEventSummarizer(llm=build_model(cfg.model))
        compaction_config = EventsCompactionConfig(
            summarizer=summarizer,
            compaction_interval=cfg.compaction.compaction_interval,
            overlap_size=cfg.compaction.overlap_size,
            token_threshold=cfg.compaction.token_threshold,
            event_retention_size=cfg.compaction.event_retention_size,
        )
        app = App(
            name=APP_NAME,
            root_agent=agent,
            events_compaction_config=compaction_config,
        )
        runner = Runner(
            app=app,
            session_service=session_service,
        )
    else:
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
