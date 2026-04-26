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

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from google.adk.apps.app import App, EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.runners import Runner

from cowork_core.agents.root_agent import build_mcp_toolset, build_root_agent
from cowork_core.audit import (
    AuditSink,
    NullAuditSink,
    SqliteAuditSink,
    open_audit_db,
)
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
from cowork_core.config import CoworkConfig, McpServerConfig
from cowork_core.execenv import LocalDirExecEnv, ManagedExecEnv
from cowork_core.sessions import SqliteCoworkSessionService
from cowork_core.memory import MemoryRegistry, register_memory_tools
from cowork_core.skills import SkillRegistry, register_skill_tools
from cowork_core.storage import (
    InMemoryProjectStore,
    InMemoryUserStore,
    ProjectStore,
    UserStore,
    WorkspaceSettingsStore,
    build_stores,
    build_workspace_settings_store,
)
from cowork_core.tools import (
    COWORK_AUTO_ROUTE_KEY,
    COWORK_CONTEXT_KEY,
    COWORK_MCP_DISABLED_KEY,
    COWORK_POLICY_MODE_KEY,
    COWORK_PYTHON_EXEC_KEY,
    COWORK_SKILLS_ENABLED_KEY,
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

# Valid skill names — alphanumeric + single dashes / underscores, no
# path separators or shell metacharacters. Applied to both the
# archive's top-level directory and the frontmatter ``name`` field
# during install.
_SKILL_NAME_PATTERN = __import__("re").compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


class SkillInstallError(Exception):
    """Raised by ``install_skill_zip`` / ``uninstall_skill`` for any
    user-facing validation failure. The server maps this to HTTP 400
    with the exception message as the detail."""


class MCPInstallError(Exception):
    """Raised by ``save_mcp_server`` / ``delete_mcp_server`` /
    ``dry_run_mcp_server`` for any user-facing failure (invalid
    name, dry-run connection failure, attempted bundled delete).
    Server maps to HTTP 400."""


# Same shape as ``_SKILL_NAME_PATTERN`` — letters / digits / dash /
# underscore, leading-alnum, capped at 64 chars. MCP server names land
# in URLs (``DELETE /v1/mcp/servers/{name}``) and JSON keys, so
# enforce a tight character set.
_MCP_NAME_PATTERN = __import__("re").compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")


def _validate_mcp_name(name: str) -> None:
    if not _MCP_NAME_PATTERN.match(name):
        raise MCPInstallError(
            f"invalid MCP server name {name!r} "
            f"(must match ``[A-Za-z0-9][A-Za-z0-9_-]{{0,63}}``)",
        )


@dataclass
class MCPServerStatus:
    """One entry in ``CoworkRuntime.mcp_status``.

    Populated when ``build_runtime`` constructs MCP toolsets — one
    per declared server. Exposed via ``/v1/health`` so Settings can
    show a green pill for `ok` servers and surface ``last_error``
    for `error` ones. ``tool_count`` stays ``None`` at startup
    (ADK's ``MCPToolset`` lazy-loads tools); Slice IV's add-server
    dry-run flow populates it on demand.
    """

    name: str
    status: Literal["ok", "error"]
    last_error: str | None = None
    tool_count: int | None = None
    transport: Literal["stdio", "sse", "http"] = "stdio"


def _validate_skill_name(name: str) -> None:
    if not _SKILL_NAME_PATTERN.match(name):
        raise SkillInstallError(
            f"invalid skill name {name!r} "
            f"(must match ``[A-Za-z0-9][A-Za-z0-9_-]{{0,63}}``)",
        )


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
    # Per-MCP-server status captured at startup. Surfaced via
    # ``/v1/health.mcp`` so Settings can show whether a configured
    # server actually built successfully.
    mcp_status: dict[str, MCPServerStatus] = field(default_factory=dict)
    # Slice VI — tool name → owning MCP server name. Populated at boot
    # (via ``asyncio.run``) and refreshed during ``restart_mcp``. The
    # Slice VI disable callback closes over this dict (by reference)
    # so a restart that adds/removes servers re-keys the gate without
    # rebuilding the closure. Tools not in the map are treated as
    # non-MCP and pass through.
    mcp_tool_owner: dict[str, str] = field(default_factory=dict)
    # Slice S1 — storage hierarchy. ``user_store`` and
    # ``project_store`` route to FS in single-user mode and to a
    # database backing (SQLite ships in S1; Postgres etc. via
    # ``register_backend``) in multi-user mode. Built once per
    # runtime by ``build_stores`` and threaded into every
    # ``CoworkToolContext`` so tools can read/write per-user and
    # per-project state without knowing the deployment shape.
    user_store: "UserStore" = field(
        default_factory=lambda: InMemoryUserStore(),
    )
    project_store: "ProjectStore" = field(
        default_factory=lambda: InMemoryProjectStore(),
    )
    # Slice S2 — produces the per-turn prompt snippet for the memory
    # subsystem. Stateless; one instance per runtime is fine.
    memory: MemoryRegistry = field(default_factory=MemoryRegistry)
    # Slice T1 — path to the ``cowork.toml`` this runtime was built
    # from. ``None`` when the server was started in env-only mode
    # (``COWORK_CONFIG_PATH`` unset). Settings PUT routes that mutate
    # workspace-wide config check this and 503 cleanly when None.
    config_path: Path | None = None
    # Slice U1 — workspace-wide settings store (FS-backed in SU,
    # SQLite-backed in MU). ``None`` in env-only SU mode (no editable
    # surface). PUT routes for model + compaction route through this
    # store; in MU it sits at ``<workspace>/multiuser.db`` keyed by
    # dotted setting names (``model.base_url``, etc.).
    workspace_settings_store: WorkspaceSettingsStore | None = None
    # Slice V1 — audit sink. SU: SQLite at ``<workspace>/audit.db``;
    # MU: ``audit_log`` table inside the existing ``multiuser.db``.
    # Wired into ``make_audit_callbacks`` so every tool call lands as
    # a structured row. Per-tool capture policy lives in
    # ``cowork_core.audit_policy``. ``NullAuditSink`` default for
    # contexts that haven't built a real one yet.
    audit_sink: AuditSink = field(default_factory=NullAuditSink)
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

        The session's skill registry starts from the global skills scanned
        at ``build_runtime`` and then layers on per-scope overrides:

        * **Managed mode** — scan ``<project_root>/skills/`` so a project
          can ship a custom skill that shadows a global one of the same
          name (spec-canonical path, ``Project.skills_dir``).
        * **Local-dir mode** — no managed project root exists; we fall
          back to ``<workdir>/.cowork/skills/`` so desktop users keep a
          way to drop per-workdir overrides alongside the session-state
          bookkeeping.
        """
        session_skills = SkillRegistry(_skills=dict(self.skills._skills))
        if workdir is not None:
            session_skills.scan(workdir / ".cowork" / "skills", source="workdir")
            env: Any = LocalDirExecEnv(workdir=workdir, session_id=session.id)
        else:
            session_skills.scan(project.skills_dir, source="project")
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
            user_store=self.user_store,
            project_store=self.project_store,
            user_id=user_id,
            audit_sink=self.audit_sink,
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

    def reload_skills(self) -> None:
        """Rescan all skill roots into ``self.skills``. Used by the
        install/uninstall routes to pick up a newly-dropped folder
        without a process restart. Preserves bundled-before-user
        precedence so a user-installed skill can still override a
        bundled one of the same name."""
        fresh = SkillRegistry()
        fresh.scan(_bundled_skills_dir(), source="bundled")
        fresh.scan(_user_config_dir() / "skills", source="user")
        fresh.scan(_user_skills_dir(self.workspace), source="user")
        # Mutate the existing dict in-place so any ReadonlyContext
        # closures still see the updated registry.
        self.skills._skills.clear()
        self.skills._skills.update(fresh._skills)

    def install_skill_zip(self, data: bytes) -> "Skill":
        """Install a user skill from a zip archive. Returns the parsed
        ``Skill`` on success; raises ``SkillInstallError`` with a
        user-safe message on any validation failure.

        The archive must contain exactly one top-level directory
        ``<name>/`` with a valid ``SKILL.md``. ``name`` is parsed
        from the frontmatter and must match the directory name. All
        files extract under ``<workspace>/global/skills/<name>/``
        atomically (via a temp dir + rename), so a validation error
        leaves the existing skill tree untouched.
        """
        import shutil

        # Stage + validate. Returns a parsed ``Skill`` whose ``root``
        # points into the staging dir; we still need to commit by
        # renaming the inner ``<top>/`` over the final location.
        staging, parsed, top = self._validate_and_stage_zip(data)
        try:
            dest_root = _user_skills_dir(self.workspace)
            dest_root.mkdir(parents=True, exist_ok=True)
            final_dir = dest_root / top
            if final_dir.exists():
                shutil.rmtree(final_dir)
            (staging / top).rename(final_dir)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

        self.reload_skills()
        installed = self.skills._skills.get(top)
        if installed is None:
            # Defensive — reload_skills should have re-picked it up.
            raise SkillInstallError(
                f"installed skill {top!r} did not reappear in registry",
            )
        return installed

    def validate_skill_zip(self, data: bytes) -> "Skill":
        """Dry-run install validation without writing to the
        user-skills directory. Returns the parsed ``Skill`` on
        success; raises ``SkillInstallError`` on any check failure.
        Used by ``POST /v1/skills/validate`` so devs writing skills
        can confirm a zip is acceptable before committing it.
        """
        import shutil

        staging, parsed, _ = self._validate_and_stage_zip(data)
        try:
            return parsed
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

    def _validate_and_stage_zip(
        self, data: bytes,
    ) -> tuple[Path, "Skill", str]:
        """Shared install/validate pipeline. Stages the zip into a
        temp dir, runs every check, and returns
        ``(staging_path, parsed_skill, top_name)``. Callers are
        responsible for either renaming ``staging / top`` over the
        final destination (install) or rmtree'ing the staging dir
        (validate / rollback)."""
        import io
        import shutil
        import uuid
        import zipfile
        from cowork_core.skills import SkillLoadError, parse_skill_md

        max_zip_bytes = 5 * 1024 * 1024        # 5 MB archive cap
        max_extracted_bytes = 10 * 1024 * 1024  # 10 MB total
        max_entries = 200

        if len(data) == 0:
            raise SkillInstallError("empty archive")
        if len(data) > max_zip_bytes:
            raise SkillInstallError(
                f"archive too large: {len(data)} bytes (max {max_zip_bytes})",
            )

        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as exc:
            raise SkillInstallError(f"not a valid zip: {exc}") from exc

        members = zf.infolist()
        if len(members) == 0:
            raise SkillInstallError("empty archive")
        if len(members) > max_entries:
            raise SkillInstallError(
                f"too many entries: {len(members)} (max {max_entries})",
            )

        top_names: set[str] = set()
        total_size = 0
        for m in members:
            n = m.filename
            if n.startswith("/") or ".." in Path(n).parts:
                raise SkillInstallError(f"unsafe path in archive: {n!r}")
            if not n:
                raise SkillInstallError("empty member name")
            if "\\" in n:
                raise SkillInstallError(f"unsafe path in archive: {n!r}")
            first = Path(n).parts[0]
            top_names.add(first)
            total_size += m.file_size
            if total_size > max_extracted_bytes:
                raise SkillInstallError(
                    f"archive expands to >{max_extracted_bytes} bytes",
                )

        if len(top_names) != 1:
            raise SkillInstallError(
                f"archive must contain exactly one top-level directory "
                f"(found {sorted(top_names)})",
            )
        top = next(iter(top_names))
        _validate_skill_name(top)

        existing = self.skills._skills.get(top)
        if existing is not None and existing.source == "bundled":
            raise SkillInstallError(
                f"cannot install {top!r}: a bundled skill already owns that name",
            )

        dest_root = _user_skills_dir(self.workspace)
        dest_root.mkdir(parents=True, exist_ok=True)
        staging = dest_root / f".install-{uuid.uuid4().hex[:12]}"
        try:
            staging.mkdir(parents=True)
            zf.extractall(staging)
            skill_md = staging / top / "SKILL.md"
            if not skill_md.is_file():
                raise SkillInstallError(
                    f"missing {top}/SKILL.md at archive root",
                )
            try:
                parsed = parse_skill_md(skill_md, source="user")
            except SkillLoadError as exc:
                raise SkillInstallError(str(exc)) from exc
            if parsed.name != top:
                raise SkillInstallError(
                    f"frontmatter name {parsed.name!r} does not match "
                    f"archive directory {top!r}",
                )
        except Exception:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            raise
        return staging, parsed, top

    def uninstall_skill(self, name: str) -> None:
        """Remove a user-installed skill from
        ``<workspace>/global/skills/<name>/`` and reload the registry.

        Raises ``SkillInstallError`` if the skill is bundled
        (not removable), unknown, or resolves to a path outside the
        user skills dir (defensive)."""
        import shutil

        _validate_skill_name(name)
        existing = self.skills._skills.get(name)
        if existing is None:
            raise SkillInstallError(f"unknown skill: {name!r}")
        if existing.source != "user":
            raise SkillInstallError(
                f"cannot uninstall {name!r}: source is {existing.source!r}",
            )
        # Confirm the on-disk path is under the user skills dir so a
        # stale registry entry can't delete somewhere unexpected.
        dest_root = _user_skills_dir(self.workspace).resolve()
        try:
            resolved = existing.root.resolve()
        except OSError as exc:
            raise SkillInstallError(f"cannot resolve skill root: {exc}") from exc
        if not resolved.is_relative_to(dest_root):
            raise SkillInstallError(
                f"refusing to delete {resolved} (outside {dest_root})",
            )
        if resolved.exists():
            shutil.rmtree(resolved)
        self.reload_skills()

    # ── MCP server management ────────────────────────────────────────

    def list_mcp_servers(self) -> dict[str, tuple["McpServerConfig", MCPServerStatus]]:
        """Return ``{name: (config, status)}`` for every configured
        server (bundled + user). Used by ``GET /v1/mcp/servers``."""
        effective = _effective_mcp_servers(self.cfg, self.workspace)
        out: dict[str, tuple[McpServerConfig, MCPServerStatus]] = {}
        for name, server_cfg in effective.items():
            status = self.mcp_status.get(name) or MCPServerStatus(
                name=name,
                status="error",
                last_error="not yet built",
                transport=server_cfg.transport,
            )
            out[name] = (server_cfg, status)
        return out

    async def dry_run_mcp_server(
        self, server_cfg: "McpServerConfig",
    ) -> list[str]:
        """Connect to the configured server, list its tools, and
        disconnect. Returns the discovered tool names so the
        add-server form can offer them as ``tool_filter`` options.

        Raises ``MCPInstallError`` on any failure. Doesn't touch
        ``self.mcp_status`` or persist anything — purely a probe.
        """
        toolset, error = build_mcp_toolset(server_cfg)
        if toolset is None:
            raise MCPInstallError(error or "failed to build toolset")
        try:
            tools = await toolset.get_tools()
            return [t.name for t in tools]
        except Exception as exc:
            raise MCPInstallError(f"{type(exc).__name__}: {exc}") from exc
        finally:
            try:
                await toolset.close()
            except Exception:
                pass

    def save_mcp_server(self, name: str, server_cfg: "McpServerConfig") -> None:
        """Add or update a user MCP server. Validates the name shape
        and refuses bundled-name collisions. Writes
        ``<workspace>/global/mcp/servers.json``; the change takes
        effect on the next ``restart_mcp()`` call."""
        _validate_mcp_name(name)
        # A collision with a TOML-declared (bundled) server is an
        # override — we let it through. Settings UI flags the
        # override visually.
        servers_path = _user_mcp_servers_path(self.workspace)
        current = _load_user_mcp_servers(servers_path)
        # Coerce ``bundled`` to False — user-saved servers are never
        # bundled, regardless of what the caller passed.
        cleaned = server_cfg.model_copy(update={"bundled": False})
        current[name] = cleaned
        _save_user_mcp_servers(servers_path, current)

    def delete_mcp_server(self, name: str) -> None:
        """Remove a user MCP server. Refuses bundled servers
        (those declared in ``cowork.toml``); the change takes effect
        on the next ``restart_mcp()`` call."""
        _validate_mcp_name(name)
        # Bundled-or-not is judged by whether the *effective* entry
        # has ``bundled=True``. A user can override a bundled name
        # via JSON; deleting that user override is fine — it falls
        # back to the TOML default.
        servers_path = _user_mcp_servers_path(self.workspace)
        current = _load_user_mcp_servers(servers_path)
        if name not in current:
            # Either unknown or bundled-only. Distinguish for the
            # route's error message.
            if name in self.cfg.mcp_servers:
                raise MCPInstallError(
                    f"cannot delete bundled MCP server {name!r} "
                    f"(declared in cowork.toml; edit the file instead)",
                )
            raise MCPInstallError(f"unknown MCP server: {name!r}")
        del current[name]
        _save_user_mcp_servers(servers_path, current)

    async def restart_mcp(self) -> None:
        """Tear down current MCP toolsets and re-mount from the
        effective config. Replaces ``self.mcp_status`` and the
        runner's root agent in place; ``session_service`` is
        preserved so existing sessions stay reachable.

        v1 trade-off: in-flight turns terminate when the agent's
        tool list mutates underneath them. The Settings UI confirms
        before calling this. Future: hot-swap without runner
        rebuild — Tier F.

        Async because the per-server tool discovery used by the
        Slice VI MCP-disable gate awaits ``MCPToolset.get_tools()``.
        Boot uses ``asyncio.run`` for the same call; here we stay
        on the route handler's loop.
        """
        # Build a fresh agent + Runner with the new MCP toolsets.
        agent_tools: list[Any] = list(self.tools.as_list())
        effective = _effective_mcp_servers(self.cfg, self.workspace)
        new_status: dict[str, MCPServerStatus] = {}
        new_owner: dict[str, str] = {}
        for name, mcp_cfg in effective.items():
            toolset, error = build_mcp_toolset(mcp_cfg)
            if toolset is not None:
                agent_tools.append(toolset)
                new_status[name] = MCPServerStatus(
                    name=name, status="ok", transport=mcp_cfg.transport,
                )
                # Capture tool names so the disable gate knows which
                # server owns which tool. Best-effort: a server that
                # connects but fails to list its tools simply isn't
                # gateable this restart.
                try:
                    tools = await toolset.get_tools()
                    for t in tools:
                        new_owner[t.name] = name
                    new_status[name].tool_count = len(tools)
                except Exception:
                    pass
            else:
                new_status[name] = MCPServerStatus(
                    name=name,
                    status="error",
                    last_error=error,
                    transport=mcp_cfg.transport,
                )
        # Mutate the *existing* dict so the Slice VI callback's
        # captured reference sees the updated mapping without
        # rebuilding the closure.
        self.mcp_tool_owner.clear()
        self.mcp_tool_owner.update(new_owner)
        new_agent = build_root_agent(
            self.cfg,
            tools=agent_tools,
            skills_snippet=self.skills.injection_snippet(),
            skills=self.skills,
            mcp_tool_owner=self.mcp_tool_owner,
            memory=self.memory,
        )
        # Keep the existing session_service (and therefore live
        # sessions); just give it a new agent. ADK's Runner accepts
        # this composition pattern.
        new_runner = Runner(
            app_name=APP_NAME,
            agent=new_agent,
            session_service=self.session_service,
        )
        self.runner = new_runner
        self.mcp_status = new_status

    async def reload(self) -> None:
        """Slice V2 — full runtime reload. Re-fetches workspace-
        settings overrides, merges into cfg, rebuilds the model + agent
        + App + Runner in place. ``session_service`` is preserved so
        existing sessions stay reachable.

        Use case: operator edits model.base_url or compaction settings
        via PUT /v1/config/{model,compaction}, then clicks "Reload now"
        in Settings. Lifts the "restart required" UX from a manual
        process restart to a single API call.

        **In-flight turns terminate** — the LiteLlm client + ADK App
        change underneath them. The route + UI confirm before calling.

        Compared to ``restart_mcp``, this is the broader rebuild:
        restart_mcp keeps the model + compaction config (only swaps
        toolsets), reload swaps everything that depends on cfg.
        """
        # Re-fetch and merge workspace-settings overrides into cfg.
        if self.workspace_settings_store is not None:
            overrides = self.workspace_settings_store.get_overrides()
            self.cfg = _merge_overrides(self.cfg, overrides)

        # Rebuild MCP toolsets (same as restart_mcp).
        agent_tools: list[Any] = list(self.tools.as_list())
        effective = _effective_mcp_servers(self.cfg, self.workspace)
        new_status: dict[str, MCPServerStatus] = {}
        new_owner: dict[str, str] = {}
        for name, mcp_cfg in effective.items():
            toolset, error = build_mcp_toolset(mcp_cfg)
            if toolset is not None:
                agent_tools.append(toolset)
                new_status[name] = MCPServerStatus(
                    name=name, status="ok", transport=mcp_cfg.transport,
                )
                try:
                    tools = await toolset.get_tools()
                    for t in tools:
                        new_owner[t.name] = name
                    new_status[name].tool_count = len(tools)
                except Exception:
                    pass
            else:
                new_status[name] = MCPServerStatus(
                    name=name, status="error",
                    last_error=error, transport=mcp_cfg.transport,
                )
        # Mutate dict in place so the disable callback's captured
        # reference still works after the reload.
        self.mcp_tool_owner.clear()
        self.mcp_tool_owner.update(new_owner)

        # Rebuild agent against the merged cfg (so cfg.model is fresh).
        new_agent = build_root_agent(
            self.cfg,
            tools=agent_tools,
            skills_snippet=self.skills.injection_snippet(),
            skills=self.skills,
            mcp_tool_owner=self.mcp_tool_owner,
            memory=self.memory,
        )

        # Rebuild Runner with fresh App + compaction config (so
        # cfg.compaction is fresh). Mirrors the build_runtime branch.
        if self.cfg.compaction.enabled:
            summarizer = LlmEventSummarizer(llm=build_model(self.cfg.model))
            compaction_config = EventsCompactionConfig(
                summarizer=summarizer,
                compaction_interval=self.cfg.compaction.compaction_interval,
                overlap_size=self.cfg.compaction.overlap_size,
                token_threshold=self.cfg.compaction.token_threshold,
                event_retention_size=self.cfg.compaction.event_retention_size,
            )
            app = App(
                name=APP_NAME,
                root_agent=new_agent,
                events_compaction_config=compaction_config,
            )
            new_runner = Runner(
                app=app,
                session_service=self.session_service,
            )
        else:
            new_runner = Runner(
                app_name=APP_NAME,
                agent=new_agent,
                session_service=self.session_service,
            )

        self.runner = new_runner
        self.mcp_status = new_status

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

    async def set_session_skills_enabled(
        self,
        session_id: str,
        enabled: dict[str, bool],
        user_id: str = "local",
    ) -> dict[str, bool]:
        """Persist the per-session skill enable map.

        Slice II. Skills absent from the dict default to enabled, so
        an empty map silences nothing — UIs send only the entries
        they want to override. The root prompt's skill registry omits
        disabled skills, and ``load_skill`` refuses them.
        """
        if not isinstance(enabled, dict):
            raise ValueError(
                f"skills_enabled must be a dict, got {type(enabled).__name__}",
            )
        normalised: dict[str, bool] = {}
        for name, flag in enabled.items():
            if not isinstance(name, str) or not name:
                raise ValueError(f"skill name must be a non-empty string, got {name!r}")
            if not isinstance(flag, bool):
                raise ValueError(
                    f"skills_enabled[{name!r}] must be a bool, got {type(flag).__name__}",
                )
            normalised[name] = flag

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
            actions=EventActions(state_delta={COWORK_SKILLS_ENABLED_KEY: normalised}),
        )
        await self.runner.session_service.append_event(session, event)
        return normalised

    async def get_session_skills_enabled(
        self,
        session_id: str,
        user_id: str = "local",
    ) -> dict[str, bool]:
        """Return the session's skill enable map (default ``{}``)."""
        session = await self.runner.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id,
        )
        if session is None:
            raise ValueError(f"no session {session_id}")
        stored = session.state.get(COWORK_SKILLS_ENABLED_KEY, {})
        if not isinstance(stored, dict):
            return {}
        return {k: bool(v) for k, v in stored.items() if isinstance(k, str)}

    async def set_session_mcp_disabled(
        self,
        session_id: str,
        disabled: list[str],
        user_id: str = "local",
    ) -> list[str]:
        """Persist the per-session MCP-server disable list.

        Slice VI. Servers absent from the list run normally; listed
        names are silenced — every tool the server owns is blocked
        with an explanatory error from the disable callback.
        """
        if not isinstance(disabled, list):
            raise ValueError(
                f"mcp_disabled must be a list, got {type(disabled).__name__}",
            )
        normalised: list[str] = []
        seen: set[str] = set()
        for name in disabled:
            if not isinstance(name, str) or not name:
                raise ValueError(f"server name must be a non-empty string, got {name!r}")
            if name in seen:
                continue
            seen.add(name)
            normalised.append(name)

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
            actions=EventActions(state_delta={COWORK_MCP_DISABLED_KEY: normalised}),
        )
        await self.runner.session_service.append_event(session, event)
        return normalised

    async def get_session_mcp_disabled(
        self,
        session_id: str,
        user_id: str = "local",
    ) -> list[str]:
        """Return the session's disabled-MCP-server list (default ``[]``)."""
        session = await self.runner.session_service.get_session(
            app_name=APP_NAME, user_id=user_id, session_id=session_id,
        )
        if session is None:
            raise ValueError(f"no session {session_id}")
        stored = session.state.get(COWORK_MCP_DISABLED_KEY, [])
        if not isinstance(stored, list):
            return []
        return [s for s in stored if isinstance(s, str)]

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


def _user_skills_dir(workspace: Workspace) -> Path:
    """Where the user-install flow lands skills — the spec-canonical
    ``<workspace>/global/skills/`` directory. Separate from
    ``_user_config_dir() / "skills"`` (which is for shared-across-
    workspaces XDG config) so a user's managed workspace has a
    stable, writable, uninstallable skill home."""
    return workspace.root / "global" / "skills"


def _user_mcp_servers_path(workspace: Workspace) -> Path:
    """JSON file under ``<workspace>/global/mcp/servers.json`` where
    runtime-added MCP server configs are persisted. Mirrors the skills
    layout (workspace-global, writable from the server, separate from
    static ``cowork.toml``)."""
    return workspace.root / "global" / "mcp" / "servers.json"


def _load_user_mcp_servers(path: Path) -> dict[str, "McpServerConfig"]:
    """Read the user-managed MCP server file. Missing file or empty
    JSON is returned as an empty dict — never an error — so a fresh
    workspace doesn't fail to boot."""
    from cowork_core.config import McpServerConfig

    if not path.is_file():
        return {}
    import json

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, McpServerConfig] = {}
    for name, payload in raw.items():
        if not isinstance(name, str) or not isinstance(payload, dict):
            continue
        try:
            # User entries are never bundled by definition.
            payload.pop("bundled", None)
            out[name] = McpServerConfig(**payload, bundled=False)
        except Exception:
            # Skip malformed entries so one bad config doesn't break
            # boot; the next reload after the user fixes the JSON
            # will pick it up.
            continue
    return out


def _save_user_mcp_servers(
    path: Path,
    servers: dict[str, "McpServerConfig"],
) -> None:
    """Write the user-managed MCP server file atomically (temp +
    rename) so a crash mid-write doesn't leave a half-truncated JSON
    that fails to parse on next boot."""
    import json
    import os

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        name: cfg.model_dump(exclude={"bundled"}) for name, cfg in servers.items()
    }
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8",
    )
    tmp.replace(path)


def _effective_mcp_servers(
    cfg: CoworkConfig, workspace: Workspace,
) -> dict[str, "McpServerConfig"]:
    """Merge TOML-declared servers (treated as ``bundled=True``) with
    the user-managed ``servers.json`` file. User entries override
    TOML on name collision — same scan-last-wins rule the skills
    registry uses for project / workdir overlays.
    """
    out: dict[str, "McpServerConfig"] = {}
    for name, mcp_cfg in cfg.mcp_servers.items():
        # TOML-declared entries are bundled defaults: not removable
        # via the runtime API even though they came from a user-edited
        # file. The user can edit cowork.toml manually if they want
        # to change them.
        out[name] = mcp_cfg.model_copy(update={"bundled": True})
    user_servers = _load_user_mcp_servers(_user_mcp_servers_path(workspace))
    for name, user_cfg in user_servers.items():
        out[name] = user_cfg
    return out


def build_runtime(
    cfg: CoworkConfig,
    config_path: "Path | None" = None,
) -> CoworkRuntime:
    if cfg.runtime.backend != "local":
        raise NotImplementedError(
            f"runtime backend {cfg.runtime.backend!r} is not implemented yet; "
            f"use 'local' (single-process in-memory + SQLite). Distributed "
            f"backends (Redis bus, Postgres sessions) will land in a later "
            f"phase against the same protocols."
        )
    workspace = Workspace(root=cfg.workspace.root)

    # Slice V1 — audit sink. SU: per-workspace audit.db. MU: shares
    # multiuser.db with the user/project/workspace_settings stores
    # (its own connection — same pattern as those stores). The sink
    # is built before anything else mutates state so all subsequent
    # work has a non-null sink to record into.
    workspace.root.mkdir(parents=True, exist_ok=True)
    if cfg.auth.keys:
        audit_db_path = workspace.root / "multiuser.db"
    else:
        audit_db_path = workspace.root / "audit.db"
    audit_sink: AuditSink = SqliteAuditSink(open_audit_db(audit_db_path))

    # Slice U1 — boot-time workspace-settings merge.
    # Build the workspace settings store FIRST (it needs only workspace +
    # config_path), pull any DB/TOML overrides, and merge them into cfg
    # before the agent + model + compaction config are materialised.
    # ``_merge_overrides`` is module-private (R2): no re-export from
    # ``__init__.py``, friction prevents accidental per-turn use.
    # ``_warn_mode_mismatch`` (R4) emits a startup notice if SU mode
    # boots over a populated MU ``workspace_settings`` table.
    workspace_settings_store = build_workspace_settings_store(
        cfg, workspace, config_path,
    )
    if workspace_settings_store is not None:
        overrides = workspace_settings_store.get_overrides()
        cfg = _merge_overrides(cfg, overrides)
    _warn_mode_mismatch(cfg, workspace)

    projects = ProjectRegistry(workspace=workspace)
    skills = SkillRegistry()
    # Three scan scopes, in precedence order (later scans override on
    # name collision): bundled → XDG user config → workspace-global.
    # The workspace-global path is the target of the install/uninstall
    # flow (``POST /v1/skills`` + ``DELETE /v1/skills/{name}``).
    skills.scan(_bundled_skills_dir(), source="bundled")
    skills.scan(_user_config_dir() / "skills", source="user")
    skills.scan(_user_skills_dir(workspace), source="user")

    tool_registry = ToolRegistry()
    register_fs_tools(tool_registry)
    register_shell_tools(tool_registry)
    register_python_exec_tools(tool_registry)
    register_http_tools(tool_registry)
    register_search_tools(tool_registry)
    register_email_tools(tool_registry)
    register_skill_tools(tool_registry)
    register_memory_tools(tool_registry)

    # Mount configured MCP servers as toolsets, recording per-server
    # status so /v1/health and Settings can surface failures rather
    # than silently dropping a misconfigured server.
    agent_tools: list[Any] = list(tool_registry.as_list())
    effective_servers = _effective_mcp_servers(cfg, workspace)
    mcp_status: dict[str, MCPServerStatus] = {}
    mcp_tool_owner: dict[str, str] = {}
    _mounted_toolsets: list[tuple[str, Any]] = []
    for name, mcp_cfg in effective_servers.items():
        toolset, error = build_mcp_toolset(mcp_cfg)
        if toolset is not None:
            agent_tools.append(toolset)
            _mounted_toolsets.append((name, toolset))
            mcp_status[name] = MCPServerStatus(
                name=name, status="ok", transport=mcp_cfg.transport,
            )
        else:
            mcp_status[name] = MCPServerStatus(
                name=name,
                status="error",
                last_error=error,
                transport=mcp_cfg.transport,
            )

    # Slice VI — discover which MCP server owns which tool name so
    # the disable gate knows what to block. Boot is sync; we use
    # ``asyncio.run`` here. If we're unexpectedly inside a running
    # loop (e.g. an embedded test), fall back silently — the gate
    # then over-permits, which is safe.
    if _mounted_toolsets:
        async def _collect() -> None:
            for srv, ts in _mounted_toolsets:
                try:
                    tools = await ts.get_tools()
                    for t in tools:
                        mcp_tool_owner[t.name] = srv
                    mcp_status[srv].tool_count = len(tools)
                except Exception:
                    continue

        try:
            asyncio.run(_collect())
        except RuntimeError:
            pass

    memory = MemoryRegistry()
    agent = build_root_agent(
        cfg,
        tools=agent_tools,
        # Pass the live registry so mid-process reloads (via
        # ``reload_skills()``) land in existing sessions' next turn.
        # ``skills_snippet`` is still the fallback for tests that
        # don't want a registry.
        skills_snippet=skills.injection_snippet(),
        skills=skills,
        mcp_tool_owner=mcp_tool_owner,
        memory=memory,
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
    user_store, project_store = build_stores(cfg, workspace)
    return CoworkRuntime(
        cfg=cfg,
        workspace=workspace,
        projects=projects,
        skills=skills,
        tools=tool_registry,
        runner=runner,
        mcp_status=mcp_status,
        mcp_tool_owner=mcp_tool_owner,
        user_store=user_store,
        project_store=project_store,
        memory=memory,
        config_path=config_path,
        workspace_settings_store=workspace_settings_store,
        audit_sink=audit_sink,
    )


# Slice U1 — module-private helpers. ``_merge_overrides`` is NOT
# re-exported by any ``__init__.py`` so future contributors can't
# import it from elsewhere — friction prevents per-turn footguns.
# Boot-only is the contract.


def _merge_overrides(
    cfg: CoworkConfig, overrides: dict[str, dict[str, object]],
) -> CoworkConfig:
    """Merge workspace-settings overrides into cfg.

    ``overrides`` is the ``{section: {key: value}}`` map returned by
    ``WorkspaceSettingsStore.get_overrides()``. Only ``model`` and
    ``compaction`` sections are recognised today; other sections are
    silently ignored (forward compat with future schema additions).

    Returns a new ``CoworkConfig`` — the input is untouched. Pydantic
    v2's ``model_copy(update={...})`` is used so validation runs on
    the merged result; an out-of-range override (e.g. negative
    ``compaction_interval``) raises here, fail-loud at boot.
    """
    updates: dict[str, object] = {}
    if "model" in overrides and isinstance(overrides["model"], dict):
        model_patch = {
            k: v for k, v in overrides["model"].items() if v is not None
        }
        if model_patch:
            updates["model"] = cfg.model.model_copy(update=model_patch)
    if "compaction" in overrides and isinstance(overrides["compaction"], dict):
        comp_patch = {
            k: v for k, v in overrides["compaction"].items() if v is not None
        }
        if comp_patch:
            updates["compaction"] = cfg.compaction.model_copy(
                update=comp_patch,
            )
    if not updates:
        return cfg
    return cfg.model_copy(update=updates)


def _warn_mode_mismatch(cfg: CoworkConfig, workspace: Workspace) -> None:
    """R4 — log a startup warning when SU mode boots over a populated
    ``workspace_settings`` table from a prior MU deployment. Operator
    notices instead of being silently surprised that their TOML
    edits aren't reflected in agent behaviour."""
    if cfg.auth.keys:
        return  # MU mode: nothing to warn about
    db_path = workspace.root / "multiuser.db"
    if not db_path.is_file():
        return
    import sqlite3 as _sqlite3

    try:
        conn = _sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM workspace_settings",
            ).fetchone()
            count = row[0] if row else 0
        finally:
            conn.close()
    except _sqlite3.OperationalError:
        # Table doesn't exist yet — nothing to warn about.
        return
    except Exception:
        # Any other DB read failure: best-effort warning, don't block boot.
        return
    if count > 0:
        print(
            f"[storage] SU mode but workspace_settings table has "
            f"{count} rows from prior MU deployment — those overrides "
            f"are inactive in SU. Edit cowork.toml directly or switch "
            f"back to MU mode to use them.",
            flush=True,
        )


def build_runner(cfg: CoworkConfig) -> Runner:
    """Back-compat shim — returns just the ADK ``Runner``."""
    return build_runtime(cfg).runner
