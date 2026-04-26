# Changelog

Append-only. One concise line per change. Format: `- <verb> <path> — <why>`.
Verbs: `add`, `update`, `remove`, `rename`, `move`.

---

## 2026-04-11

- add SPEC.md — initial Cowork specification v0.1 (landscape analysis + architecture + milestones)
- update SPEC.md — add cowork-app Tauri desktop package, deployment row, Python bundling section
- update SPEC.md — lock decisions: non-tech audience, OpenAI-compat model layer, local-only hosting, project/session workspace, DuckDuckGo search, MIT license, confirm-gated email send
- move SPEC.md → cowork/SPEC.md — create project dir under working dir
- add PLAN.md — implementation plan with PR-sized tasks and acceptance checks for M0–M6
- add CONSTITUTION.md — project rules including bookkeeping mandate for INDEX and CHANGELOG
- add CHANGELOG.md — start append-only change log
- add INDEX.md — start live file manifest
- add pyproject.toml — uv workspace root with ruff/mypy/pytest config
- add .gitignore — ignore build output and local workspaces
- add .editorconfig — cross-editor defaults (LF, utf-8)
- add .pre-commit-config.yaml — ruff + whitespace + toml/yaml hooks
- add LICENSE — MIT
- add README.md — entry point linking to spec/plan/constitution
- add .github/workflows/ci.yml — CI matrix for win/mac/linux × py3.12
- add packages/cowork-core/** — M0.2 core package: config, workspace sandbox, OpenAI-compat model adapter, root LlmAgent, runner factory
- add packages/cowork-server/** — M0.3 FastAPI server: create_app, /v1 routes, WS event stream, local token auth, COWORK_READY handshake
- add packages/cowork-cli/** — M0.4 developer CLI: `cowork chat` spawns server sidecar and streams deltas via rich
- add tests/test_smoke.py — import + workspace traversal + server factory smoke tests
- update INDEX.md — record all M0 skeleton files with descriptions and core symbols
- update SPEC.md — restructure tool catalog around execution surface (fs/shell/python_exec) + add §2.5.1 skills spec with SKILL.md format and MIT-only defaults
- update SPEC.md — restructure M1 milestone around execution surface + skill loader instead of bespoke per-format office tools
- update PLAN.md — rewrite M1 (3 wk) as execution-surface + skill-loader with nine sub-steps; list seven MIT default skills
- update CONSTITUTION.md — add §5.5 third-party content licensing rule explicitly forbidding redistribution of Anthropic's proprietary skill materials
- add packages/cowork-core/src/cowork_core/workspace/project.py — M1.1 Project/Session/ProjectRegistry (create/list/new_session/promote) with slugify
- update packages/cowork-core/src/cowork_core/workspace/__init__.py — export Project/Session/ProjectRegistry/slugify
- update packages/cowork-core/src/cowork_core/__init__.py — re-export workspace model types
- add tests/test_workspace_model.py — M1.1 unit tests for registry, sessions, promote, traversal
- add packages/cowork-core/src/cowork_core/tools/** — M1.2 tool registry and CoworkToolContext stashed in ADK tool_context.state
- add tests/test_tool_registry.py — M1.2 unit tests for ToolRegistry and cowork context roundtrip
- add packages/cowork-core/src/cowork_core/tools/fs/** — M1.3 fs tool family (read/write/list/glob/stat/edit/promote) anchored on scratch+files namespace
- add tests/test_fs_tools.py — M1.3 unit tests for fs tool family (incl. unique-match edit and traversal rejection)
- add packages/cowork-core/src/cowork_core/tools/shell/** — M1.4 shell.run (argv-only, allowlist, timeout, scratch cwd)
- add tests/test_shell_run.py — M1.4 unit tests for shell.run covering argv validation, allowlist, timeout, traversal
- add packages/cowork-core/src/cowork_core/tools/python_exec/** — M1.5 python_exec.run in subprocess with stripped env, scratch cwd, network off by default
- add tests/test_python_exec.py — M1.5 unit tests for python_exec.run (cwd, exit, timeout, proxy, cleanup)
- update packages/cowork-core/pyproject.toml — add httpx and ddgs for M1.6
- add packages/cowork-core/src/cowork_core/tools/http/** — M1.6 http.fetch with scheme/size/redirect caps
- add packages/cowork-core/src/cowork_core/tools/search/** — M1.6 search.web via zero-setup DuckDuckGo provider
- add tests/test_http_and_search.py — M1.6 unit tests for http.fetch and search.web
- update packages/cowork-core/pyproject.toml — add pyyaml for SKILL.md frontmatter parsing
- add packages/cowork-core/src/cowork_core/skills/** — M1.7 SkillRegistry, SKILL.md parser, load_skill tool
- update packages/cowork-core/src/cowork_core/tools/base.py — add `skills: SkillRegistry` to CoworkToolContext
- add tests/test_skills.py — M1.7 unit tests for SKILL.md parsing, registry, injection, load_skill
- update packages/cowork-core/src/cowork_core/runner.py — introduce CoworkRuntime, wire all M1 tools and skills, inject CoworkToolContext via open_session
- update packages/cowork-core/src/cowork_core/agents/root_agent.py — accept tools + skills snippet; expand base instruction for M1 execution surface
- update packages/cowork-core/src/cowork_core/config.py — add from_env/apply_env_overrides for COWORK_MODEL_* and COWORK_WORKSPACE_ROOT
- update packages/cowork-server/src/cowork_server/app.py — use CoworkRuntime; create_session bootstraps project/session and injects CoworkToolContext
- update packages/cowork-server/src/cowork_server/__main__.py — load config via CoworkConfig.from_env for env-driven local model setup
- update packages/cowork-core/src/cowork_core/runner.py — three-tier skill scan: bundled (package) → global (workspace) → project (per session)
- update packages/cowork-core/src/cowork_core/runner.py — adopt opencode-style multi-level skill dirs: bundled → ~/.config/cowork/skills/ (user) → {workspace}/.cowork/skills/ (project)
- add packages/cowork-core/src/cowork_core/preview/** — M1.9 preview converters (md→HTML, docx→JSON, pdf→JSON, xlsx→JSON, csv→JSON, images→passthrough) with content-hash cache
- update packages/cowork-server/src/cowork_server/app.py — add GET /v1/projects/{project}/preview/{path} endpoint backed by PreviewCache
- update packages/cowork-core/src/cowork_core/__init__.py — export PreviewResult, PreviewCache, preview_file
- add tests/test_preview.py — M1.9 unit tests for all six preview types, cache, content hash (14 tests)
- update packages/cowork-server/src/cowork_server/transport.py — upgrade event_to_frame to serialize tool_call, tool_result, and multi-part frames (was text-only)
- add packages/cowork-core/src/cowork_core/skills/bundled/** — M1.8 seven MIT default skills (docx-basic, xlsx-basic, pdf-read, md, plot, research, email-draft)
- update packages/cowork-core/pyproject.toml — add python-docx, openpyxl, pandas, pypdf, matplotlib, markdown-it-py, Pillow for skill sandbox

---

## 2026-04-18

Re-architecture around a shared agent core + two surfaces (desktop local-dir,
web managed) plus multi-user auth and dev ergonomics.

### Phase 1 — surface-aware core

- add packages/cowork-core/src/cowork_core/execenv/** — ExecEnv protocol, ManagedExecEnv (scratch+files), LocalDirExecEnv (user-picked folder) with path-confinement resolve/try_resolve/glob
- remove packages/cowork-core/src/cowork_core/tools/fs/_paths.py — superseded by ExecEnv.try_resolve
- update packages/cowork-core/src/cowork_core/tools/fs/{read,write,list,stat,edit,glob}.py — route path resolution through ctx.env.try_resolve
- update packages/cowork-core/src/cowork_core/tools/shell/run.py — route cwd resolution through ctx.env.try_resolve
- update packages/cowork-core/src/cowork_core/tools/python_exec/run.py — use ctx.env.scratch_dir() for snippet temp-file location
- update packages/cowork-core/src/cowork_core/tools/base.py — add env: ExecEnv field to CoworkToolContext; export COWORK_POLICY_MODE_KEY + COWORK_READS_KEY
- add packages/cowork-core/src/cowork_core/callbacks/** — before/after_model_callback factory: turn-budget guard (default 50) + model-call audit line
- update packages/cowork-core/src/cowork_core/agents/root_agent.py — env-aware _dynamic_instruction reading ctx.env.describe_for_prompt() per turn; _sub_agent_instruction wrapper for specialists; propagate policy + audit + model callbacks to researcher/writer/analyst/reviewer
- update packages/cowork-core/src/cowork_core/policy/permissions.py — read per-session COWORK_POLICY_MODE_KEY from state with cfg.policy.mode as fallback
- update packages/cowork-core/src/cowork_core/runner.py — seed per-session policy_mode; set/get_session_policy_mode via ADK EventActions.state_delta; materialize/rehydrate local-dir sessions under <workdir>/.cowork/sessions/<id>/; registry_for(user_id) and workspace_for(user_id) for multi-user subtree
- update packages/cowork-core/src/cowork_core/config.py — add RuntimeConfig.backend = local | distributed (distributed is forward-compatible, raises NotImplementedError today)

### Phase 2 — desktop workdir surface

- update packages/cowork-app/src-tauri/Cargo.toml — add tauri-plugin-dialog + dotenvy
- update packages/cowork-app/src-tauri/capabilities/default.json — grant dialog:allow-open
- update packages/cowork-app/src-tauri/src/lib.rs — tauri-plugin-dialog init, pick_workdir/recent_workdir/set_recent_workdir commands, "Open Folder…" menu item (Cmd/Ctrl+O), debug-only dotenvy autoload of repo-root .env
- update packages/cowork-app/src-tauri/src/sidecar.rs — COWORK_PYTHON env override + 0-byte binary detection so corrupt bundles fall through instead of spawning an empty process
- add packages/cowork-app/src-tauri/.taurignore — exclude resources/ target/ gen/ from dev-mode watcher to stop rebuild loops on .pyc touches
- update packages/cowork-server/src/cowork_server/app.py — POST /v1/sessions accepts workdir (mutually exclusive with project); POST /v1/sessions/{id}/resume accepts workdir; GET /v1/local-sessions?workdir=…; DELETE /v1/local-sessions/{id}?workdir=…; GET/PUT /v1/sessions/{id}/policy/mode
- update packages/cowork-web/src/transport/client.ts — createSession/resumeSession take {project|workdir} scope; listLocalSessions/deleteLocalSession client methods
- update packages/cowork-web/src/transport/tauri.ts — pickWorkdir/getRecentWorkdir/setRecentWorkdir bridges
- add packages/cowork-web/src/components/DesktopSidebar.tsx — workdir breadcrumb + local-session list with inline delete confirmation
- update packages/cowork-web/src/App.tsx — surface = isTauri() ? "desktop" : "web"; scope = {workdir} or {project}; surface-aware sidebar swap; recent-workdir autoload on desktop boot
- update packages/cowork-web/src/hooks/useChat.ts — Scope type threaded through send/resumeSession/newSession

### Phase 3 — web abstractions + multi-user

- add packages/cowork-server/src/cowork_server/bus/{__init__.py,memory.py} — EventBus protocol + InMemoryEventBus (moved from queues.py)
- update packages/cowork-server/src/cowork_server/queues.py — re-export shim; kept for backward compat until callers migrate
- add packages/cowork-server/src/cowork_server/limiter/{__init__.py,memory.py} — ConnectionLimiter protocol + InMemoryConnectionLimiter (moved from connections.py)
- update packages/cowork-server/src/cowork_server/connections.py — re-export shim
- add packages/cowork-core/src/cowork_core/sessions/{__init__.py,sqlite.py} — CoworkSessionService protocol + SqliteCoworkSessionService (moved from runner.py); future Postgres impl plugs in here
- update packages/cowork-server/src/cowork_server/app.py — registry_for(user_id)/workspace_for(user_id) per-user scoping on projects + files endpoints; GET /v1/health returns {backend, auth, components: {eventbus, limiter, sessions}}
- update cowork/SPEC.md — §2.9 deployment modes table includes multi-user web row; §2.9.3 documents surface modes + distributed upgrade path; non-goal reworded to call out deferred distributed backends
- update cowork/README.md — new "Surface modes" section; tool list bumped to 13 (added email_draft/email_send line); desktop section notes folder picker and Cmd/Ctrl+O shortcut
- add cowork/docs/compare-claude-code/** — 10-file comparison set (README + 9 chapter files) between Cowork and Claude Code

### Bonus / dev ergonomics

- add packages/cowork-web/src/components/ToolWidgets.tsx — 12 typed per-tool renderers (fs_edit diff, fs_read/write/list/glob/stat/promote, shell_run, python_exec_run, http_fetch, search_web, load_skill)
- update packages/cowork-web/src/components/ToolCallCard.tsx — dispatch to renderToolWidget, fall back to generic args/result view
- update packages/cowork-web/src/components/Sidebar.tsx — drop unused selectedProject local
- update .env.sample — add "Desktop dev" block documenting COWORK_PYTHON
- add tests/test_execenv.py — 21 unit tests for ManagedExecEnv + LocalDirExecEnv
- add tests/test_local_session.py — integration tests for local-dir session flow (create/resume/list/delete + fs tools + full picker sequence + fs_promote rejection + nonexistent-workdir rejection + ghost-session 404)
- add tests/test_multi_user.py — MultiKeyGuard + per-user workspace isolation + /v1/health auth-mode field
- add tests/test_callbacks_and_prompt.py — model callbacks + dynamic instruction + sub-agent env propagation (10 tests)
- update tests/test_policy.py — per-session policy mode overrides + sub-agent callback regression + runtime set/get_session_policy_mode roundtrip
- update tests/test_smoke.py — runtime config defaults + build_runtime rejects distributed backend
- update tests/{test_fs_tools,test_python_exec,test_shell_run,test_tool_registry,test_email,test_http_and_search,test_skills}.py — construct CoworkToolContext with env=ManagedExecEnv(project, session)
- update packages/cowork-app/src-tauri/src/lib.rs — extract RecentWorkdir.{get,set} methods + inline unit tests (starts_empty, roundtrips, overwrites, concurrent access)

### Tier A polish (2026-04-18)

- update packages/cowork-core/src/cowork_core/agents/{writer,analyst}.py — drop hard-coded scratch/ vocabulary; rely on env description
- update packages/cowork-core/src/cowork_core/tools/fs/promote.py — return clear error in LocalDirExecEnv mode instead of mangling paths
- update cowork/docs/compare-claude-code/{03-hooks-callbacks,04-policies,07-subagents,08-memory-context}.md — move filled gaps (model callbacks, sub-agent callback propagation, per-session policy mode, turn-count guard) from "missing" to "filled"
- update cowork/docs/compare-claude-code/README.md — TL;DR table reflects 4 wired callbacks and env-aware sub-agent prompts

### Tier F polish (2026-04-18)

Closes the "nice-to-have" list from the rearchitecture plan: UI toggles
for policy mode + python_exec, smarter fs_edit diff, desktop file-drop,
desktop file browser. Plus the missing ``COWORK_CONFIG_PATH`` loader
surfaced during D3 QA.

- update packages/cowork-server/src/cowork_server/__main__.py — add ``COWORK_CONFIG_PATH`` env var that loads a cowork.toml at startup; loud SystemExit if the path doesn't exist (silent fallback hid multi-user config typos during QA)
- update packages/cowork-web/src/main.tsx — browser mode reads ``?token=…`` URL param as a per-tab override of the build-time ``__COWORK_TOKEN__`` define, so different tabs can authenticate as different users in multi-user dev
- update packages/cowork-web/vite.config.ts — drop the proxy's ``x-cowork-token`` header injection; client owns the token, proxy was overwriting per-tab values
- update packages/cowork-web/src/transport/client.ts — ``getSessionPolicyMode`` / ``setSessionPolicyMode`` (F4); ``getSessionPythonExec`` / ``setSessionPythonExec`` (F5); ``listLocalFiles`` / ``readLocalFile`` (F2)
- update packages/cowork-web/src/components/TopBar.tsx — F4 dropdown now targets per-session ``/v1/sessions/{id}/policy/mode`` instead of the deprecated global endpoint; F5 python_exec dropdown next to it with confirm/allow/deny colors
- update packages/cowork-web/src/components/ToolWidgets.tsx — F1 real LCS-based line diff in ``fs_edit`` widget (was all-old-then-all-new)
- add packages/cowork-web/src/components/DesktopFileCanvas.tsx — F2 right-panel file browser for the workdir: flat list per directory with breadcrumb/up navigation and a plain-text preview pane; polls every 3s while a session is active
- update packages/cowork-web/src/App.tsx — F2 mounts ``DesktopFileCanvas`` on desktop surface (``FileCanvas`` still serves managed/web); F3 file-drop in desktop mode now copies via Tauri into the workdir (was informational-only)
- update packages/cowork-app/src-tauri/src/lib.rs — F3 new ``copy_into_workdir(src, workdir)`` Tauri command doing a native ``std::fs::copy`` with path-confinement check
- update packages/cowork-web/src/transport/tauri.ts — F3 ``copyIntoWorkdir`` bridge
- update packages/cowork-core/src/cowork_core/config.py — F5 ``PolicyConfig.python_exec = confirm|allow|deny`` (default confirm)
- update packages/cowork-core/src/cowork_core/policy/permissions.py — F5 per-session override via ``COWORK_PYTHON_EXEC_KEY`` with cfg fallback; gate ``python_exec_run`` in work mode (closes the 'silent bypass' bug D1 surfaced)
- update packages/cowork-core/src/cowork_core/tools/base.py — F5 export ``COWORK_PYTHON_EXEC_KEY``
- update packages/cowork-core/src/cowork_core/runner.py — F5 ``set_session_python_exec`` / ``get_session_python_exec`` via ADK state_delta
- update packages/cowork-server/src/cowork_server/app.py — F5 GET/PUT ``/v1/sessions/{id}/policy/python_exec``; F2 ``/v1/local-files`` + ``/v1/local-files/content``
- update tests/test_policy.py — per-session python_exec override regression (TestWorkMode)
- update tests/test_local_session.py — local-files list/read/escape coverage
- update tests/test_multi_user.py — cross-tenant session history 404, project delete 404, no-token 401, COWORK_CONFIG_PATH TOML loader happy path + missing-file SystemExit

### Safety fix: gate python_exec_run + real approve/deny (2026-04-18)

QA found that denying a shell_run confirmation let the agent pivot to
python_exec_run, which silently ran. The gap: python_exec_run had no
approval gate, and the UI Approve/Deny buttons only sent a text
message — no server-side binding. Fix makes both work.

- update packages/cowork-core/src/cowork_core/config.py — add PolicyConfig.python_exec = confirm|allow|deny (default confirm)
- update packages/cowork-core/src/cowork_core/policy/permissions.py — gate python_exec_run with confirmation_required in work mode (honoring policy.python_exec); fix email_send == "confirm" to actually prompt instead of pass through; consume per-tool approval counter on match
- update packages/cowork-core/src/cowork_core/tools/base.py — add COWORK_TOOL_APPROVALS_KEY state key
- update packages/cowork-core/src/cowork_core/tools/__init__.py — export COWORK_TOOL_APPROVALS_KEY
- update packages/cowork-core/src/cowork_core/runner.py — CoworkRuntime.grant_tool_approval(sid, tool_name) appends an ADK state_delta event; list_tool_approvals(sid) reads the dict
- update packages/cowork-server/src/cowork_server/app.py — GET/POST /v1/sessions/{id}/approvals endpoints (one POST grants one approval for a named tool)
- update packages/cowork-web/src/transport/client.ts — approveTool(sessionId, toolName) method
- update packages/cowork-web/src/components/ToolCallCard.tsx — onApprove/onDeny now pass (toolName, summary)
- update packages/cowork-web/src/components/ChatPane.tsx — Approve button calls onApproveTool (hits /approvals endpoint) BEFORE sending the text follow-up
- update packages/cowork-web/src/App.tsx — handleApproveTool posts to /v1/sessions/{sid}/approvals then the existing send() nudges the model
- update tests/test_policy.py — new tests for python_exec confirm/allow/deny, approval counter consumption, and email_send confirm-prompt


### Phase F + Tier E + post-Tier-E refactor + Swagger surface (2026-04-21 → 2026-04-23)

Phase F (commit ea921f2) shipped the wire-up plan: cleanup pass, file-updated dot, session waiting dot, session stats, pin/favourite, composer attachments, ephemeral notifications, ⌘K command palette. E3 compaction integrated alongside.

Tier E (commit 8f0768e) added per-agent tool allowlist (E1) and inline @-mention routing with auto-route pill revival (E2). Agent enable/disable roster culled to Tier F.

Post-Tier-E refactor (commit f2052cb) — net 332 deletions, 269 insertions:
- remove COWORK_TOOL_APPROVALS_KEY (declared but never set/read)
- remove deprecated PUT /v1/policy/mode (no client consumers; GET stays as display fallback)
- remove CoworkClient.connect() WebSocket entry point (unused)
- remove trustedToolNames / markToolTrusted / TRUSTED_STORAGE_PREFIX (unwired from approval flow)
- simplify Settings SecProfile to single user-id row
- collapse tool-call style (collapsed/expanded/terminal) to single unified collapsible card; drop ToolStyle preference
- add transport/types.ts named types: PolicyMode, PythonExecPolicy, ToolAllowlist, SearchResults, UploadFileResult, ToolApprovalResult, LocalFileListResult, LocalFileReadResult, LocalSessionListItem
- split CoworkClient.headers() into jsonHeaders() + authHeaders(); extract sessionStreamUrl() helper
- add active-model field to /v1/health + Settings → System "Model" row

Swagger / OpenAPI surface (S1+S2):
- add openapi_tags grouping (10 tags); every HTTP route gets tag + summary
- register cowork-token APIKeyHeader security scheme so Swagger Authorize works
- add cowork_server/api_models.py with Pydantic models mirroring transport/types.ts
- replace dict[str, Any] request/response shapes with named models throughout app.py
- add tests/test_openapi.py (6 tests) covering metadata, tags, security scheme, named request bodies, policy enums

Documentation overhaul (S3):
- update README.md feature table — flip rows for unified tool-call style, agent-monogram cull, Settings agents (now interactive), System (now carries model), API reference; bump intro paragraph to mention Tier E + post-E
- update README.md — new "API reference" section pointing at /docs, /redoc, /openapi.json
- update ARCHITECTURE.md §2 — note OpenAPI publishing and Pydantic model location
- update SPEC.md §2.7 — mention OpenAPI / Swagger surface

### Skills + MCP production hardening (2026-04-23 → 2026-04-24)

Slice I — skills operational completeness (commit 6a963a8):
- update cowork_core/skills/loader.py — accept optional `version` + `triggers` frontmatter, compute SHA-256 `content_hash`, reject control chars in string fields
- add cowork_core/skills/bundled/plot/scripts/quick_chart.py + xlsx-basic/scripts/table_io.py — exercise the scripts/ contract against real bundled content
- add cowork_server validate route — `POST /v1/skills/validate` runs the full install pipeline without persisting; returns `SkillInfo` on success, 400 on rejection
- update SkillInfo (server + types.ts) — add `version`, `triggers`, `content_hash`
- update Settings → Skills — render version pill + sha-256 tooltip
- add docs/WRITING_A_SKILL.md — frontmatter schema, on-disk layout, install/uninstall/validate flows, Claude-Code compatibility note
- add tests/test_skills.py — 7 new tests (28 total)

Slice III — MCP transports + tool_filter + status surface (commit c28dfb9):
- update cowork_core/config.py McpServerConfig — add `transport` (`stdio`/`sse`/`http`), `url`, `headers`, `tool_filter`, `description`, `bundled` fields
- rename `_build_mcp_toolset` → public `build_mcp_toolset(cfg) -> (toolset, last_error)` in cowork_core/agents/root_agent.py — dispatch on transport, switch to non-deprecated `McpToolset`
- add cowork_core/runner.py MCPServerStatus dataclass + `CoworkRuntime.mcp_status` populated during build
- add cowork_server `MCPServerStatusInfo` Pydantic model + HealthResponse.mcp list — `/v1/health` now surfaces per-server ok/error + last_error
- update Settings → System — render MCP servers row with green/red counts and last_error tooltip
- add tests/test_mcp.py — 7 transport / status tests; extend tests/test_openapi.py — verify HealthResponse.mcp `$ref` to MCPServerStatusInfo

Slice IV — MCP dynamic config + CRUD routes + Settings UI + restart (commit d6f29bd):
- add cowork_core/runner.py `_user_mcp_servers_path` / `_load_user_mcp_servers` / `_save_user_mcp_servers` / `_effective_mcp_servers` — TOML (bundled) + `<workspace>/global/mcp/servers.json` (user) merge with user-overrides-bundled-on-collision
- add CoworkRuntime methods: `list_mcp_servers`, `dry_run_mcp_server`, `save_mcp_server`, `delete_mcp_server`, `restart_mcp` — restart rebuilds agent + Runner in place, preserving `session_service`
- add MCPInstallError + `_validate_mcp_name` (alphanumeric / `_-`, ≤64 chars) — same error shape as skills install
- add cowork_server/api_models.py models: `McpServerInfo`, `McpServerRecord`, `McpServersListResponse`, `AddMcpServerRequest`, `AddMcpServerResponse`, `DeleteMcpServerResult`, `RestartMcpResult`
- add cowork_server routes: `GET/POST /v1/mcp/servers`, `DELETE /v1/mcp/servers/{name}`, `POST /v1/mcp/restart` — POST dry-runs the connection (and returns discovered tool names) before persisting; DELETE refuses `bundled` with 400, unknown with 404
- add new `mcp` openapi tag — Swagger Authorize + tag-grouping invariant
- add cowork-web client methods: `listMcpServers`, `addMcpServer`, `deleteMcpServer`, `restartMcp` + matching types (`McpServerInfo`, `McpServerRecord`, `AddMcpServerRequest`, `AddMcpServerResponse`)
- add Settings → Agents → MCP servers subsection — per-row status pill + transport badge + delete button (gated on `bundled`), inline "+ add server" form (transport selector, command/args/env or url/headers, description), "↻ restart" with confirm
- extend tests/test_mcp.py — 5 new tests (file-backed CRUD round-trip, bundled-delete refusal, 404 on unknown delete, restart rebuilds status); 12 total in test_mcp.py, 231 total
- update README.md — new feature row "MCP: dynamic config (servers.json) + add / delete / restart routes + Settings UI"
- update ARCHITECTURE.md — extend MCP paragraph with two-scope merge model, dry-run-on-POST, restart-only reload contract

Slice V — MCP docs + Settings preset dropdown (commit f9b4be8):
- add docs/MCP.md — transports, dynamic config, three worked examples (filesystem / GitHub / memory) using official Anthropic MCP servers via `npx -y`, restart-only reload contract, recovery and tool_filter notes
- add Settings → MCP add-form "Common servers" dropdown — pre-fills name + transport + command/args/env from the same three presets so users avoid hand-typing the npx invocation
- update README.md Documentation section — link to docs/MCP.md
- update SPEC.md §2.13 M3 — tick MCP adapter milestone (Slices III + IV); footnote pointing at docs/MCP.md for the npx-based filesystem worked example (cull-audit decision: do not bundle a Cowork-specific FS MCP server)

Slice II — skills safety + per-session enable/disable (commit db1f00f):
- update cowork_core/skills/loader.py — add `DESCRIPTION_PROMPT_CAP = 300`; `injection_snippet` caps per-skill description at the cap (with `…` ellipsis) and accepts an optional `enabled` predicate that omits disabled skills entirely
- update cowork_core/agents/root_agent.py — `_dynamic_instruction` reads `cowork.skills_enabled` from session state and threads a closure into `injection_snippet`
- update cowork_core/skills/load_skill_tool.py — refuse disabled skills at the tool layer with an explanatory error so the gate holds even if the model guesses the name
- add COWORK_SKILLS_ENABLED_KEY to cowork_core/tools/base.py + re-export
- add CoworkRuntime.set_session_skills_enabled / get_session_skills_enabled — OCC-safe via session_service.append_event with state_delta
- add cowork_server `SkillsEnabledResponse` + `SetSkillsEnabledRequest` and `GET/PUT /v1/sessions/{id}/policy/skills_enabled` routes
- add cowork-web client methods `getSessionSkillsEnabled` / `setSessionSkillsEnabled` and Settings → Skills per-row on/off toggle (gated on active session)
- add tests/test_skills.py — 3 new tests (description cap truncation + ellipsis, predicate-omits-disabled, load_skill refuses disabled); 31 total in test_skills.py, 234 overall
- update SPEC.md §2.5.1 — note the prompt-side description cap and per-session enable gate
- update ARCHITECTURE.md — extend skills paragraph with the cap + predicate
- update README.md — new feature row "Skills: 300-char description cap + per-session enable/disable"

Slice VI — per-session MCP server gating (this commit):
- add COWORK_MCP_DISABLED_KEY (`cowork.mcp_disabled`, list[str]) — server names silenced for the session; absent / empty = all enabled
- add CoworkRuntime.mcp_tool_owner: dict[tool_name, server_name] — populated at boot via asyncio.run + during async restart_mcp via await; survives restart by mutating in place so the disable callback's closure stays valid
- convert CoworkRuntime.restart_mcp to async — boot stays synchronous via asyncio.run; the route handler awaits restart so tool discovery runs on the same loop without nesting
- add CoworkRuntime.set_session_mcp_disabled / get_session_mcp_disabled with input validation (list[str], dedupe, reject non-strings)
- add cowork_core/policy/permissions.py make_mcp_disable_callback(tool_owner) — single closure mounted on every agent's before_tool_callback that reads session state per-call and blocks owned tools when the server is in the disable list
- thread mcp_tool_owner through build_runtime → build_root_agent; sub-agent + root callback chains both gain the gate (light test harnesses that pass mcp_tool_owner=None skip it)
- add McpDisabledResponse + SetMcpDisabledRequest to api_models.py + GET/PUT /v1/sessions/{id}/policy/mcp_disabled routes
- add cowork-web client methods getSessionMcpDisabled / setSessionMcpDisabled
- add Settings → MCP servers per-row on/off toggle (active session only) — disable takes effect on next tool call, no restart needed
- update tests/test_mcp.py — convert test_restart_rebuilds_status to async; add 2 new tests (callback gating logic, session state round-trip + validation); 14 total in test_mcp.py, 236 overall
- update README.md — new feature row for Slice VI
- update ARCHITECTURE.md — extend MCP paragraph with tool-owner discovery + disable-callback wiring

### Settings UI — Slice T2 (Profile + System editors + Memory tab) (2026-04-26)

User-visible payoff for T1's backend. The Settings overlay grows
three editable surfaces wired to the new routes.

- update `transport/types.ts` — `ConfigModelPatch/View`,
  `ConfigCompactionPatch/View`, `UserProfile/Patch`,
  `MemoryPageInfo/List/Content`. `HealthInfo` gains optional
  `is_multi_user` + `has_config_file`.
- update `transport/client.ts` — 7 new methods:
  `updateConfigModel`, `updateConfigCompaction`, `getProfile`,
  `updateProfile`, `listMemoryPages`, `readMemoryPage`,
  `deleteMemoryPage`.
- update `components/Settings.tsx`:
  - **Profile** — replace read-only `SecProfile` with an editable
    form (display_name + email). user_id stays read-only. Save +
    Reset buttons; ✓ saved tick on success; error inline. Loads
    via `getProfile()` on mount.
  - **System** — extract two new sub-blocks above the existing
    health rows:
    - `SecConfigModel` — base_url, model, api_key inputs. The
      api_key input branches: `env:` prefix renders as plain text
      with an "env-resolved" badge; otherwise masked password
      with a show/hide toggle.
    - `SecConfigCompaction` — number inputs + checkbox; child
      inputs disabled when `enabled=false`.
    - Both blocks send only changed fields (PATCH semantics).
    - On save: a yellow "Restart required" banner pins to the top
      of the System tab with a Dismiss link.
    - In multi-user mode OR env-only mode: every input renders
      `disabled` with a small notice ("configured by operator —
      edit cowork.toml on the server and restart" / "server is in
      env-only mode — set COWORK_CONFIG_PATH and restart").
    - Existing read-only Status / Tools loaded / Skills loaded /
      MCP servers / Backends rows remain. Read-only Model +
      Compaction rows removed (the editors own those now).
  - **Memory** — new tab between Approvals and System under the
    Agents group. Scope picker (`<Chips>` user/project), page list
    with name + size + 80-char preview, view (inline expansion),
    delete (with confirm), refresh button. Project scope without
    an active session shows "Open a session to browse project
    memory."
  - New `TabId = "memory"` and `NAV` entry with the brain icon.
  - `editorInputStyle` + `editorBtnStyle` shared style helpers.
- web build clean. Backend tests still green (305).

### Settings UI — Slice T1 (backend + atomic TOML writer) (2026-04-26)

Backend foundation for in-app settings editing. Seven new routes
under three new OpenAPI tags (`config`, `profile`, `memory`) plus
two new `HealthResponse` fields (`is_multi_user`, `has_config_file`)
the UI uses to render workspace-wide config blocks read-only when
appropriate. Workspace-wide config (model + compaction) edits write
directly to `cowork.toml` via a new atomic writer; comments are NOT
preserved (`tomli_w` is a writer not a round-tripper). Per-user
profile + memory pages route through the S1 `UserStore` /
`ProjectStore` so MU mode just works without further code.

- add `cowork-core` dep on `tomli-w >=1.0`
- add `packages/cowork-core/src/cowork_core/config_writer.py` —
  `update_toml_section(path, section, patch)` reads full TOML,
  merges patch (None = leave alone), atomic temp+rename write.
  Same pid/tid/nonce-suffixed temp pattern as the S1 storage layer.
- update `cowork_core/runner.py` — `build_runtime` accepts
  `config_path: Path | None`; `CoworkRuntime` carries it so PUT
  routes know where to write
- update `cowork-server/__main__.py` — `_load_config` returns
  `(cfg, path)` tuple; passes path through to `create_app`
- update `cowork_server/app.py` — `create_app` takes optional
  `config_path`; threads to `build_runtime`. Three new tag groups
  registered in `_OPENAPI_TAGS`. Health route surfaces
  `is_multi_user` + `has_config_file`.
- new routes (7):
  - `PUT /v1/config/model` — atomic `cowork.toml` `[model]` edit;
    503 in env-only mode, 403 in MU
  - `PUT /v1/config/compaction` — same shape; Pydantic validates
    field ranges (`compaction_interval >= 1` etc.)
  - `GET /v1/profile` — reads `settings/profile.json` from calling
    user's `UserStore`; defaults to empty strings when unset
  - `PUT /v1/profile` — per-user write; rejects `email` without `@`
  - `GET /v1/memory/{scope}/pages` — lists pages with name + size +
    80-char preview; `?session_id=` required for `scope=project`
  - `GET /v1/memory/{scope}/pages/{name:path}` — read full content
  - `DELETE /v1/memory/{scope}/pages/{name:path}` — idempotent
- update `cowork_server/api_models.py` — new models:
  `ConfigModelPatch` / `ConfigModelView`,
  `ConfigCompactionPatch` / `ConfigCompactionView`,
  `UserProfile` / `UserProfilePatch`,
  `MemoryPageInfo` / `MemoryPageList` / `MemoryPageContent`.
  `HealthResponse` gains `is_multi_user` + `has_config_file`.
- update `tests/test_openapi.py` — expected tag set includes new
  `config` / `profile` / `memory` groups
- update `tests/test_multi_user.py` — `_load_config` now returns a
  tuple; existing test follows the new shape
- add `tests/test_settings.py` — 19 new tests: TOML writer round-
  trip + missing-file + invalid-toml + None-key-drop + creates-
  missing-section, model PUT happy path + MU 403 + env-only 503,
  compaction PUT + range validation, profile GET defaults + PUT
  round-trip + email-no-@ rejection + per-user MU isolation,
  memory list/read/delete + project-scope-requires-session +
  invalid-scope-400 + missing-page-404, health is_multi_user +
  has_config_file in SU + MU. Autouse `_isolate_home` fixture
  redirects `$HOME` so FS user-store writes don't pollute the
  developer's real `~/.config/cowork/`.
- update `README.md` — feature row for T1
- 305 total tests green (was 286, +19)

Tier F (deferred): operator self-service in MU (would lift the 403),
per-user model overrides via `UserStore`, live runtime reload, schema
editing in the Memory tab, `cowork.toml` backup-on-write.

### Memory subsystem — Slice S2 (LLM Wiki on top of stores) (2026-04-25)

First consumer of the S1 storage abstraction. Karpathy's "LLM Wiki"
pattern: per-scope markdown wiki the agent maintains, no embeddings,
just `index.md` + ripgrep at scale. Two scopes (`user` cross-project
+ `project` per-project) routed through `ctx.user_store` /
`ctx.project_store` — same call sites in SU (filesystem) and MU
(SQLite). Per-turn prompt injection is one line per scope (page
count + pointer to `memory_read(scope, "schema.md")`); the schema
body loads on demand, mirroring the skills name+description / load
body pattern.

- add `packages/cowork-core/src/cowork_core/memory/` package — `tools.py` (memory_read, memory_write, memory_log, memory_remember + register_memory_tools), `bootstrap.py` (memory_key, is_writable_target, ensure_bootstrapped, bundled_default_schema, _project_id resolver), `registry.py` (MemoryRegistry with injection_snippet), `bundled/default_schema.md` (Karpathy-flavoured default conventions for both scopes)
- update `cowork_core/runner.py` — call register_memory_tools alongside register_skill_tools; construct MemoryRegistry; thread it into build_root_agent (both fresh build and restart_mcp paths); add `runtime.memory: MemoryRegistry` field
- update `cowork_core/agents/root_agent.py` — `build_root_agent` accepts `memory: MemoryRegistry | None`; `_dynamic_instruction` calls `memory.injection_snippet(ctx)` when the cowork context is on session state and threads the result into `_compose_instruction(memory_snippet=...)`. Snippet is empty when both scopes have zero pages so a fresh session prompt isn't cluttered with a "no memory yet" line.
- update `cowork_core/tools/base.py` — `CoworkToolContext` gains `user_id: str = "local"` (defaults so existing test fixtures don't need updating; runner.py passes the real user_id from `_build_context`)
- writes are gated: agent may only `memory_write` to `index.md` or `pages/*.md`. `schema.md` is user-edited (the agent must not rewrite its own conventions); `log.md` uses `memory_log` (server-stamped dates); `raw/*` is user uploads. `memory_log` validates `kind` against `^[a-z][a-z0-9_]{0,31}$` so a malicious value can't smuggle markdown into the log.
- bootstrap is lazy — first memory tool call for a scope copies the bundled default `schema.md` if missing, idempotent thereafter
- `memory_remember(content, scope="project")` stays dumb — appends to `pages/scratch.md` with a timestamp. Filing into proper pages is the agent's *next-turn* job per the schema's "Remember" workflow. Sub-LLM routing inside a tool was rejected as either heavy (new LlmAgent) or layering-violating (direct build_model in a tool).
- add `tests/test_memory.py` — 27 new tests: key namespacing + path-traversal guards, write-target allowlist, bundled schema sanity, bootstrap on first read, bootstrap idempotency (doesn't clobber user-edited schema), memory_read missing/invalid, memory_write round-trip + rejections (schema/log/raw), memory_log dated entries + kind validation + multi-line title rejection, memory_remember scratch append + default-scope=project + scope=user routing + empty rejection, MemoryRegistry empty + page-count snippet, register_memory_tools, build_runtime smoke, end-to-end SU mode (FS file at `<workdir>/.cowork/memory/...`), end-to-end MU mode (SQLite row at `<workspace>/multiuser.db`)
- add `docs/MEMORY.md` — concept doc + scope/storage matrix + tool reference + schema flow + Tier F deferred list
- update `SPEC.md` §2.5.2 (peer of skills §2.5.1) — memory pattern + reference to docs/MEMORY.md
- update `ARCHITECTURE.md` — extend Storage section with the memory paragraph (write-target allowlist + lazy bootstrap + dumb-remember rationale)
- update `README.md` — feature row "Memory: LLM-Wiki pattern (4 tools, schema-as-config, two scopes) on top of storage" + Documentation row
- 286 total tests green (was 259, +27)

### Storage hierarchy — Slice S1 (UserStore + ProjectStore + dual backings) (2026-04-25)

Foundational refactor settling Cowork's storage model so future subsystems
(memory first, eventually skills + MCP) plug into the right scope based
on deployment mode. Single-user side mirrors OpenCode's
`~/.config/opencode/` filesystem layout; multi-user side adds a SQLite
backing at `<workspace>/multiuser.db` with rows keyed by user_id (and
user_id+project for project-scope state). Auto-detected from
`cfg.auth.keys`. A backend registry leaves room for Postgres/Turso/etc.
without rewriting the factory.

- add `packages/cowork-core/src/cowork_core/storage/` package — `protocols.py` (`UserStore`, `ProjectStore`), `fs.py` (`FSUserStore`, `FSProjectStore`), `sqlite.py` (`SqliteUserStore`, `SqliteProjectStore`, `_open_sqlite`), `memory.py` (`InMemoryUserStore`, `InMemoryProjectStore` for tests/ephemeral), `factory.py` (`build_stores`, `register_backend`, `_BACKENDS` registry)
- update `cowork_core/config.py` — new `StorageConfig` Pydantic model with `backend`, `dsn`, `pool_size`, `extras`; added to `CoworkConfig.storage`
- update `cowork_core/runner.py` — `build_runtime` calls `build_stores`, populates `runtime.user_store` / `.project_store`; `_build_context` threads stores into every `CoworkToolContext`
- update `cowork_core/tools/base.py` — `CoworkToolContext` gains required `user_store: UserStore` + `project_store: ProjectStore` fields
- update tests/* — 7 test files (test_email, test_skills, test_fs_tools, test_python_exec, test_http_and_search, test_tool_registry, test_shell_run) — pass `InMemoryUserStore()` + `InMemoryProjectStore()` when constructing `CoworkToolContext` directly
- fix `_atomic_write` in `storage/fs.py` — original implementation used a fixed `.tmp` suffix that collided between concurrent writers; new code mixes pid + thread id + cryptographic nonce so simultaneous writers get unique temp paths and the rename never lands on a missing file (caught by the new concurrent-write test)
- add `tests/test_storage.py` — 18 new tests: FS round-trip + list-by-prefix + delete + path-traversal rejection + atomic concurrent writes; FS project store isolation across workdirs; SQLite round-trip + user/project isolation + upsert + delete; factory routes FS in SU + SQLite in MU + raises with available-backend listing on unknown name; backend registry dispatch via a fake backend (proves the Postgres seam without shipping a second real backend); runtime + context wiring; cross-mode key-shape compat smoke
- update `ARCHITECTURE.md` §5 — new "Storage hierarchy" subsection with the protocol/backing matrix
- update `README.md` — feature row "Storage: UserStore / ProjectStore protocols + FS + SQLite backings (OpenCode-style FS layout)"
- 259 total tests green (was 241, +18)

### M4 desktop closeout — Slice A (workdir persistence) (2026-04-25)

- update packages/cowork-app/src-tauri/src/lib.rs — replace in-memory-only `RecentWorkdir` with a JSON-backed store that writes atomically (temp + rename) to `recent_workdir.json` under the platform `app_config_dir()`. Reads on `with_storage` construction; ignores malformed files / empty `"path"` strings to fail safely. I/O errors log + degrade to in-memory only — never panic.
- add 4 new Rust unit tests covering survive-across-construction round-trip, atomic-temp absence after success, malformed-file → empty fallback, empty-string-in-file → empty fallback. 8 total in cowork-app/src-tauri (was 4).
- update README.md — new feature row "Desktop: persistent recent-workdir across launches"
- M4-B (Tauri auto-updater wiring) tracked separately as the next slice — needs CI signing keypair + `latest.json` publishing.

### M5 verification — email send end-to-end (2026-04-25)

- fix permission callback for `email_send` — was reading `to`/`subject`/`body` from args (which only contain `eml_id` + `confirmed`), producing a "Send email to None" prompt; the tool body already returns a properly formatted `confirmation_required` from the .eml file, so the callback now passes through on first call and only enforces the approval token on `confirmed=True` (model can't bypass consent by flipping the flag)
- update tests/test_policy.py — replace the now-obsolete `test_email_send_requires_confirmation_by_default` with three tests covering the new flow: pass-through on first call, block on `confirmed=True` without approval, consume-and-pass on `confirmed=True` with a granted approval (one-shot)
- add tests/test_email.py end-to-end SMTP coverage — three new tests monkey-patching `smtplib.SMTP` to verify (1) TLS + auth path (`starttls` + `login` + `sendmail` + `quit` in order), (2) plain-relay path (no `starttls` / no `login`), (3) connection failure surfaces as `{"error": ...}` rather than propagating; 11 total in test_email.py, 241 overall (was 236)
- tick SPEC.md §2.13 M5 — note the two-layer confirm gate, the `smtplib`-monkey-patched test approach, and that "Gmail via MCP" is now satisfied by `docs/MCP.md`'s server-preset add-flow rather than a Cowork-specific GMail integration (cull-audit decision: stay neutral on which MCP server users pick)
- update README.md — new feature row "Email: end-to-end SMTP send with two-layer confirm gate"
