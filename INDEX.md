# File Index

Live manifest of every file under `cowork/`. Updated in the same PR as any file create / update / delete (see `CONSTITUTION.md` §2).

Columns: **Path** · **Description** · **Core symbol**

---

## Root

| Path | Description | Core symbol |
|---|---|---|
| `.editorconfig` | Editor defaults (LF, utf-8, 4-space Python / 2-space TS) | — |
| `.github/workflows/ci.yml` | GitHub Actions matrix (win/mac/linux × py3.12) for lint + type + test | — |
| `.gitignore` | Ignore Python/Node/Rust build output and local workspaces | — |
| `.pre-commit-config.yaml` | Pre-commit hooks: ruff, ruff-format, whitespace/toml/yaml checks | — |
| `CHANGELOG.md` | Append-only concise change log | — |
| `CONSTITUTION.md` | Non-negotiable project rules and bookkeeping mandate | — |
| `INDEX.md` | This file — live manifest of every tracked file | — |
| `LICENSE` | MIT license | — |
| `PLAN.md` | Milestone-by-milestone implementation plan with acceptance checks | — |
| `README.md` | Entry point linking to spec/plan/constitution/index/changelog | — |
| `SPEC.md` | Product + architecture specification v0.1 | — |
| `pyproject.toml` | uv workspace root: members, dev deps, ruff/mypy/pytest config | — |

## `packages/cowork-core/`

| Path | Description | Core symbol |
|---|---|---|
| `packages/cowork-core/pyproject.toml` | cowork-core package manifest (google-adk, litellm, pydantic) | — |
| `packages/cowork-core/src/cowork_core/__init__.py` | Public surface of cowork-core (≤20 symbols) | `CoworkConfig`, `Workspace`, `ProjectRegistry`, `CoworkRuntime`, `build_runtime` |
| `packages/cowork-core/src/cowork_core/agents/__init__.py` | Agents subpackage exports | `build_root_agent` |
| `packages/cowork-core/src/cowork_core/agents/root_agent.py` | Root LlmAgent — env-aware dynamic instruction, policy + audit + model callbacks, sub-agent callback propagation, env-aware specialist prompts | `build_root_agent` |
| `packages/cowork-core/src/cowork_core/agents/researcher.py` | Researcher specialist — search + fetch + scan project files | `RESEARCHER_INSTRUCTION` |
| `packages/cowork-core/src/cowork_core/agents/writer.py` | Writer specialist — draft/edit documents; env-agnostic prompt | `WRITER_INSTRUCTION` |
| `packages/cowork-core/src/cowork_core/agents/analyst.py` | Analyst specialist — data processing + charts via python_exec | `ANALYST_INSTRUCTION` |
| `packages/cowork-core/src/cowork_core/agents/reviewer.py` | Reviewer specialist — quality/accuracy/completeness checks | `REVIEWER_INSTRUCTION` |
| `packages/cowork-core/src/cowork_core/callbacks/__init__.py` | Callbacks subpackage exports | `make_model_callbacks` |
| `packages/cowork-core/src/cowork_core/callbacks/model.py` | ADK before/after_model_callback factory: turn-budget guard + model-call audit line | `make_model_callbacks` |
| `packages/cowork-core/src/cowork_core/execenv/__init__.py` | Agent-facing exec environment protocol + impls | `ExecEnv`, `ManagedExecEnv`, `LocalDirExecEnv` |
| `packages/cowork-core/src/cowork_core/execenv/base.py` | `ExecEnv` Protocol + `ExecEnvError`; resolve/try_resolve/glob/describe_for_prompt | `ExecEnv` |
| `packages/cowork-core/src/cowork_core/execenv/managed.py` | `ManagedExecEnv` — classic scratch/+files/ two-namespace view bound to Project+Session | `ManagedExecEnv` |
| `packages/cowork-core/src/cowork_core/execenv/localdir.py` | `LocalDirExecEnv` — agent operates on user-picked workdir; scratch at `<wd>/.cowork/sessions/<id>/scratch/` | `LocalDirExecEnv` |
| `packages/cowork-core/src/cowork_core/config.py` | Pydantic models for `cowork.toml`; `env:` indirection for secrets; `RuntimeConfig.backend` selector | `CoworkConfig`, `RuntimeConfig` |
| `packages/cowork-core/src/cowork_core/policy/__init__.py` | Policy subpackage exports | `make_permission_callback`, `make_audit_callbacks` |
| `packages/cowork-core/src/cowork_core/policy/permissions.py` | Plan/work/auto permission callback; reads per-session COWORK_POLICY_MODE_KEY with cfg fallback | `make_permission_callback` |
| `packages/cowork-core/src/cowork_core/policy/hooks.py` | Audit callbacks appending tool_call / tool_result lines to session transcript.jsonl | `make_audit_callbacks` |
| `packages/cowork-core/src/cowork_core/sessions/__init__.py` | `CoworkSessionService` protocol + re-export | `CoworkSessionService`, `SqliteCoworkSessionService` |
| `packages/cowork-core/src/cowork_core/sessions/sqlite.py` | Wraps ADK `SqliteSessionService` and re-injects `CoworkToolContext` via registered builders | `SqliteCoworkSessionService` |
| `packages/cowork-core/src/cowork_core/model/__init__.py` | Model subpackage exports | `build_model` |
| `packages/cowork-core/src/cowork_core/model/openai_compat.py` | The sole model boundary — wraps any OpenAI-compatible endpoint via ADK LiteLlm | `build_model` |
| `packages/cowork-core/src/cowork_core/runner.py` | `build_runtime` assembles ADK Runner + tool/skill/project registries; `open_session(workdir=...)` picks LocalDirExecEnv or ManagedExecEnv; per-session policy mode set/get via ADK `state_delta`; `workspace_for(user_id)` / `registry_for(user_id)` per-user subtree for multi-user auth | `CoworkRuntime`, `build_runtime` |
| `packages/cowork-core/src/cowork_core/tools/__init__.py` | Tools subpackage exports (context + registry + state keys) | `ToolRegistry`, `CoworkToolContext`, `COWORK_POLICY_MODE_KEY` |
| `packages/cowork-core/src/cowork_core/tools/base.py` | Per-invocation cowork context stashed in ADK `tool_context.state`; `env: ExecEnv` carries the path vocabulary | `CoworkToolContext`, `get_cowork_context` |
| `packages/cowork-core/src/cowork_core/tools/registry.py` | Name-keyed registry of ADK `BaseTool` instances handed to the root agent | `ToolRegistry` |
| `packages/cowork-core/src/cowork_core/tools/fs/__init__.py` | fs tool family exports + `register_fs_tools` | `register_fs_tools` |
| `packages/cowork-core/src/cowork_core/tools/fs/read.py` | `fs.read` — read UTF-8 via `ctx.env.try_resolve` | `fs_read` |
| `packages/cowork-core/src/cowork_core/tools/fs/write.py` | `fs.write` — create/overwrite via `ctx.env.try_resolve` | `fs_write` |
| `packages/cowork-core/src/cowork_core/tools/fs/list.py` | `fs.list` — directory listing via `ctx.env.try_resolve` | `fs_list` |
| `packages/cowork-core/src/cowork_core/tools/fs/glob.py` | `fs.glob` — delegates to `ctx.env.glob`; honors namespace prefix in managed mode | `fs_glob` |
| `packages/cowork-core/src/cowork_core/tools/fs/stat.py` | `fs.stat` — metadata via `ctx.env.try_resolve` | `fs_stat` |
| `packages/cowork-core/src/cowork_core/tools/fs/edit.py` | `fs.edit` — exact unique-match string replacement; requires prior `fs.read` | `fs_edit` |
| `packages/cowork-core/src/cowork_core/tools/fs/promote.py` | `fs.promote` — scratch → files in managed mode; returns clean error in local-dir mode | `fs_promote` |
| `packages/cowork-core/src/cowork_core/tools/shell/__init__.py` | Shell tool family exports + `register_shell_tools` | `register_shell_tools` |
| `packages/cowork-core/src/cowork_core/tools/shell/run.py` | `shell.run` — argv-only subprocess with allowlist, timeout, scratch cwd | `shell_run` |
| `packages/cowork-core/src/cowork_core/tools/python_exec/__init__.py` | python_exec exports + `register_python_exec_tools` | `register_python_exec_tools` |
| `packages/cowork-core/src/cowork_core/tools/python_exec/run.py` | `python_exec.run` — snippet in subprocess; scratch cwd, stripped env, network off by default | `python_exec_run` |
| `packages/cowork-core/src/cowork_core/tools/http/__init__.py` | HTTP tool family exports + `register_http_tools` | `register_http_tools` |
| `packages/cowork-core/src/cowork_core/tools/http/fetch.py` | `http.fetch` — safe GET with scheme check, size cap, redirect cap | `http_fetch` |
| `packages/cowork-core/src/cowork_core/tools/search/__init__.py` | Search tool family exports + `register_search_tools` | `register_search_tools` |
| `packages/cowork-core/src/cowork_core/tools/search/web.py` | `search.web` — zero-setup DuckDuckGo text search (via `ddgs`) | `search_web` |
| `packages/cowork-core/src/cowork_core/skills/__init__.py` | Skill subpackage exports | `SkillRegistry`, `load_skill` |
| `packages/cowork-core/src/cowork_core/skills/loader.py` | SKILL.md frontmatter parser + `SkillRegistry` (scan, lookup, injection snippet) | `SkillRegistry` |
| `packages/cowork-core/src/cowork_core/skills/load_skill_tool.py` | `load_skill` tool — fetches body + manifest for a named skill | `load_skill` |
| `packages/cowork-core/src/cowork_core/skills/bundled/docx-basic/SKILL.md` | Default skill: read/create/edit .docx via python-docx | — |
| `packages/cowork-core/src/cowork_core/skills/bundled/xlsx-basic/SKILL.md` | Default skill: read/create/edit .xlsx via openpyxl + pandas | — |
| `packages/cowork-core/src/cowork_core/skills/bundled/pdf-read/SKILL.md` | Default skill: extract text/metadata from PDF via pypdf | — |
| `packages/cowork-core/src/cowork_core/skills/bundled/md/SKILL.md` | Default skill: read/write/render Markdown via markdown-it-py | — |
| `packages/cowork-core/src/cowork_core/skills/bundled/plot/SKILL.md` | Default skill: charts/plots to PNG via matplotlib Agg | — |
| `packages/cowork-core/src/cowork_core/skills/bundled/research/SKILL.md` | Default skill: web research loop with search_web + http_fetch | — |
| `packages/cowork-core/src/cowork_core/skills/bundled/email-draft/SKILL.md` | Default skill: compose .eml drafts with attachments via email.mime | — |
| `packages/cowork-core/src/cowork_core/preview/__init__.py` | Preview subpackage exports | `PreviewResult`, `preview_file` |
| `packages/cowork-core/src/cowork_core/preview/converters.py` | File→preview converters: md→HTML, docx→JSON, pdf→JSON, xlsx→JSON, csv→JSON, images→passthrough | `preview_file`, `PreviewResult` |
| `packages/cowork-core/src/cowork_core/preview/cache.py` | Content-hash-based preview cache under workspace root | `PreviewCache` |
| `packages/cowork-core/src/cowork_core/workspace/__init__.py` | Workspace subpackage exports | `Workspace`, `ProjectRegistry` |
| `packages/cowork-core/src/cowork_core/workspace/project.py` | Project/Session dataclasses and `ProjectRegistry` (create/list/new_session/promote) on top of Workspace | `ProjectRegistry` |
| `packages/cowork-core/src/cowork_core/workspace/workspace.py` | Filesystem sandbox rooted at one directory; traversal rejection | `Workspace` |

## `packages/cowork-server/`

| Path | Description | Core symbol |
|---|---|---|
| `packages/cowork-server/pyproject.toml` | cowork-server package manifest (fastapi, uvicorn) | — |
| `packages/cowork-server/src/cowork_server/__init__.py` | Public surface: `create_app` | `create_app` |
| `packages/cowork-server/src/cowork_server/__main__.py` | `python -m cowork_server`: picks port, prints `COWORK_READY` handshake, runs uvicorn | `main` |
| `packages/cowork-server/src/cowork_server/app.py` | FastAPI factory + `/v1` routes: sessions (project or workdir), per-session policy mode, local-sessions CRUD, SSE/WS events, projects/files, health with per-component status | `create_app` |
| `packages/cowork-server/src/cowork_server/auth.py` | `TokenGuard` (sidecar) + `MultiKeyGuard` (multi-user); `create_guard` factory | `TokenGuard`, `MultiKeyGuard`, `create_guard`, `UserIdentity` |
| `packages/cowork-server/src/cowork_server/bus/__init__.py` | `EventBus` protocol + re-export of default impl | `EventBus`, `InMemoryEventBus` |
| `packages/cowork-server/src/cowork_server/bus/memory.py` | Single-process asyncio fan-out bus with bounded per-subscriber queues | `InMemoryEventBus` |
| `packages/cowork-server/src/cowork_server/queues.py` | Deprecated re-export shim → `cowork_server.bus` | — |
| `packages/cowork-server/src/cowork_server/limiter/__init__.py` | `ConnectionLimiter` protocol + re-export of default impl | `ConnectionLimiter`, `InMemoryConnectionLimiter` |
| `packages/cowork-server/src/cowork_server/limiter/memory.py` | Per-user asyncio.Lock-guarded concurrent-stream limiter | `InMemoryConnectionLimiter` |
| `packages/cowork-server/src/cowork_server/connections.py` | Deprecated re-export shim → `cowork_server.limiter` | — |
| `packages/cowork-server/src/cowork_server/transport.py` | Translate ADK events → JSON frames; events_to_history replay | `event_to_payload`, `events_to_history` |

## `packages/cowork-cli/`

| Path | Description | Core symbol |
|---|---|---|
| `packages/cowork-cli/pyproject.toml` | cowork-cli package manifest (typer, rich, httpx, websockets) | — |
| `packages/cowork-cli/src/cowork_cli/__init__.py` | Package docstring | — |
| `packages/cowork-cli/src/cowork_cli/main.py` | Typer `cowork chat` — spawns server sidecar, streams deltas | `app` (Typer), `chat` |

## `packages/cowork-web/` (React UI, shared between browser + Tauri)

| Path | Description | Core symbol |
|---|---|---|
| `packages/cowork-web/src/App.tsx` | Surface-aware root: `isTauri()` picks desktop vs web sidebar; scope = `{workdir}` or `{project}` | `App` |
| `packages/cowork-web/src/hooks/useChat.ts` | Chat state machine; `Scope` threaded through send/resume/newSession; per-session cache | `useChat` |
| `packages/cowork-web/src/transport/client.ts` | HTTP + SSE client; createSession/resumeSession accept `{project\|workdir}`; local-sessions CRUD | `CoworkClient` |
| `packages/cowork-web/src/transport/tauri.ts` | Tauri invoke bridges: `pickWorkdir`, `getRecentWorkdir`, `setRecentWorkdir`, `onFileDrop`, `notify` | `pickWorkdir`, `isTauri` |
| `packages/cowork-web/src/components/Sidebar.tsx` | Managed-mode sidebar: project list + session list | `Sidebar` |
| `packages/cowork-web/src/components/DesktopSidebar.tsx` | Local-dir sidebar: workdir breadcrumb + local-session list | `DesktopSidebar` |
| `packages/cowork-web/src/components/DesktopFileCanvas.tsx` | Right-panel file browser for local-dir sessions (flat list + text preview + 3s polling) | `DesktopFileCanvas` |
| `packages/cowork-web/src/components/ToolCallCard.tsx` | Tool-call card with status chip, confirmation banner, expand toggle; dispatches to per-tool widget | `ToolCallCard` |
| `packages/cowork-web/src/components/ToolWidgets.tsx` | 12 typed renderers (fs_edit diff, fs_read/write/list/glob/stat/promote, shell_run, python_exec_run, http_fetch, search_web, load_skill) | `renderToolWidget` |
| `packages/cowork-web/src/components/ChatPane.tsx` | Scrollable message stream + composer | `ChatPane` |
| `packages/cowork-web/src/components/FileCanvas.tsx` | Right-panel file browser with preview (managed/web mode only) | `FileCanvas` |

## `packages/cowork-app/` (Tauri desktop shell)

| Path | Description | Core symbol |
|---|---|---|
| `packages/cowork-app/src-tauri/Cargo.toml` | Rust manifest: tauri, tauri-plugin-dialog, dotenvy | — |
| `packages/cowork-app/src-tauri/tauri.conf.json` | Tauri bundler config: resources, CSP, windows | — |
| `packages/cowork-app/src-tauri/.taurignore` | Exclude `resources/` `target/` `gen/` from dev-mode file watcher | — |
| `packages/cowork-app/src-tauri/capabilities/default.json` | Plugin permissions (dialog:allow-open for folder picker) | — |
| `packages/cowork-app/src-tauri/src/lib.rs` | Window lifecycle, native menu, tauri::commands (pick_workdir, recent_workdir, etc.), debug-only dotenvy .env autoload | `run`, `RecentWorkdir` |
| `packages/cowork-app/src-tauri/src/sidecar.rs` | Spawn cowork-server sidecar; honors COWORK_PYTHON override; 0-byte binary detection | `spawn`, `shutdown` |
| `packages/cowork-app/src-tauri/src/main.rs` | Entry stub calling `app_lib::run()` | — |

## `docs/`

| Path | Description | Core symbol |
|---|---|---|
| `docs/compare-claude-code/README.md` | Orientation + TL;DR mapping between Claude Code and Cowork | — |
| `docs/compare-claude-code/01-agent-loop.md` | Turn loop: three-layer `QueryEngine→query→StreamingToolExecutor` vs ADK `Runner.run_async` | — |
| `docs/compare-claude-code/02-system-prompt.md` | Prompt composition + cache boundary vs static ROOT_HEADER + env-aware working context | — |
| `docs/compare-claude-code/03-hooks-callbacks.md` | 28 HOOK_EVENTS + external runners vs 4 ADK callbacks (tool + model) | — |
| `docs/compare-claude-code/04-policies.md` | Rule engine + sandbox vs mode switch + per-session state | — |
| `docs/compare-claude-code/05-tools.md` | `Tool<I,O>` + zod + MCP pool vs FunctionTool auto-schema (13 tools) | — |
| `docs/compare-claude-code/06-skills.md` | Multi-source + conditional activation vs 3-source `load_skill` | — |
| `docs/compare-claude-code/07-subagents.md` | Forked context + task objects vs ADK sub_agents with shared state and uniform callbacks | — |
| `docs/compare-claude-code/08-memory-context.md` | 5-stage compaction + MEMORY.md vs session events + turn-count guard | — |
| `docs/compare-claude-code/09-streaming-ui.md` | Streaming tool overlap vs SSE/WS event bus | — |

## `scripts/`

| Path | Description | Core symbol |
|---|---|---|
| `scripts/bundle_python.py` | Download python-build-standalone, pip-install cowork packages into `resources/python/<triple>/` | — |
| `scripts/installer_qa.md` | Manual smoke checklist for Windows / macOS / Linux installers | — |

## `tests/`

| Path | Description | Core symbol |
|---|---|---|
| `tests/__init__.py` | Test package marker | — |
| `tests/test_smoke.py` | Import + structural smoke tests (no LLM credentials required) | — |
| `tests/test_workspace_model.py` | M1.1 tests for Project/Session/ProjectRegistry: slugify, create/get, new_session, promote, traversal | — |
| `tests/test_tool_registry.py` | M1.2 tests for ToolRegistry (register/list/duplicate) and CoworkToolContext roundtrip | — |
| `tests/test_fs_tools.py` | M1.3 tests for fs.read/write/list/glob/stat/edit/promote (incl. traversal, unique-match edit) | — |
| `tests/test_shell_run.py` | M1.4 tests for shell.run: argv validation, allowlist, timeout, scratch cwd | — |
| `tests/test_python_exec.py` | M1.5 tests for python_exec.run: cwd, exit code, timeout, network off, cleanup | — |
| `tests/test_http_and_search.py` | M1.6 tests for http.fetch and search.web (with MockTransport and monkeypatched provider) | — |
| `tests/test_skills.py` | M1.7 tests for SkillRegistry, SKILL.md parsing, injection snippet, load_skill tool | — |
| `tests/test_preview.py` | M1.9 tests for preview converters (md/docx/pdf/xlsx/csv/image), cache, content hash | — |
| `tests/test_policy.py` | Permission callback: plan/work/auto modes, per-session override, sub-agent callback regression, runtime set/get_session_policy_mode | — |
| `tests/test_transport.py` | Event serialization + history replay | — |
| `tests/test_email.py` | email.draft + email.send with confirm/deny policy | — |
| `tests/test_execenv.py` | ManagedExecEnv + LocalDirExecEnv resolve/glob/describe_for_prompt (21 tests) | — |
| `tests/test_callbacks_and_prompt.py` | Model callbacks (turn guard, transcript line) + dynamic instruction + sub-agent env propagation | — |
| `tests/test_local_session.py` | Local-dir session flow: create/resume/list/delete, fs tools end-to-end, picker full sequence, fs_promote rejection | — |
| `tests/test_multi_user.py` | MultiKeyGuard + per-user workspace isolation + /v1/health auth-mode field | — |
