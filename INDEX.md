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
| `packages/cowork-core/src/cowork_core/__init__.py` | Public surface of cowork-core (≤20 symbols) | `CoworkConfig`, `Workspace`, `ProjectRegistry`, `build_runner` |
| `packages/cowork-core/src/cowork_core/agents/__init__.py` | Agents subpackage exports | `build_root_agent` |
| `packages/cowork-core/src/cowork_core/agents/root_agent.py` | Root Cowork LlmAgent — now wired with execution-surface tools + skill-injection snippet | `build_root_agent` |
| `packages/cowork-core/src/cowork_core/config.py` | Pydantic models for `cowork.toml`; `env:` indirection for secrets | `CoworkConfig` |
| `packages/cowork-core/src/cowork_core/model/__init__.py` | Model subpackage exports | `build_model` |
| `packages/cowork-core/src/cowork_core/model/openai_compat.py` | The sole model boundary — wraps any OpenAI-compatible endpoint via ADK LiteLlm | `build_model` |
| `packages/cowork-core/src/cowork_core/runner.py` | `build_runtime` — assembles ADK Runner, tool registry, skill registry, project registry; `CoworkRuntime.open_session` injects CoworkToolContext into ADK state | `CoworkRuntime`, `build_runtime` |
| `packages/cowork-core/src/cowork_core/tools/__init__.py` | Tools subpackage exports (context + registry) | `ToolRegistry`, `CoworkToolContext` |
| `packages/cowork-core/src/cowork_core/tools/base.py` | Per-invocation cowork context stashed in ADK `tool_context.state` | `CoworkToolContext`, `get_cowork_context` |
| `packages/cowork-core/src/cowork_core/tools/registry.py` | Name-keyed registry of ADK `BaseTool` instances handed to the root agent | `ToolRegistry` |
| `packages/cowork-core/src/cowork_core/tools/fs/__init__.py` | fs tool family exports + `register_fs_tools` | `register_fs_tools` |
| `packages/cowork-core/src/cowork_core/tools/fs/_paths.py` | Resolves `scratch/...` and `files/...` into real session/project paths | `resolve_project_path` |
| `packages/cowork-core/src/cowork_core/tools/fs/read.py` | `fs.read` — read a UTF-8 text file (truncation-aware) | `fs_read` |
| `packages/cowork-core/src/cowork_core/tools/fs/write.py` | `fs.write` — create/overwrite a UTF-8 text file | `fs_write` |
| `packages/cowork-core/src/cowork_core/tools/fs/list.py` | `fs.list` — list directory entries with kind+size | `fs_list` |
| `packages/cowork-core/src/cowork_core/tools/fs/glob.py` | `fs.glob` — glob within `scratch/` or `files/` namespace | `fs_glob` |
| `packages/cowork-core/src/cowork_core/tools/fs/stat.py` | `fs.stat` — file/dir metadata (kind, size, mtime) | `fs_stat` |
| `packages/cowork-core/src/cowork_core/tools/fs/edit.py` | `fs.edit` — exact unique-match string replacement | `fs_edit` |
| `packages/cowork-core/src/cowork_core/tools/fs/promote.py` | `fs.promote` — move a scratch file into project `files/` | `fs_promote` |
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
| `packages/cowork-core/src/cowork_core/workspace/__init__.py` | Workspace subpackage exports | `Workspace`, `ProjectRegistry` |
| `packages/cowork-core/src/cowork_core/workspace/project.py` | Project/Session dataclasses and `ProjectRegistry` (create/list/new_session/promote) on top of Workspace | `ProjectRegistry` |
| `packages/cowork-core/src/cowork_core/workspace/workspace.py` | Filesystem sandbox rooted at one directory; traversal rejection | `Workspace` |

## `packages/cowork-server/`

| Path | Description | Core symbol |
|---|---|---|
| `packages/cowork-server/pyproject.toml` | cowork-server package manifest (fastapi, uvicorn) | — |
| `packages/cowork-server/src/cowork_server/__init__.py` | Public surface: `create_app` | `create_app` |
| `packages/cowork-server/src/cowork_server/__main__.py` | `python -m cowork_server`: picks port, prints `COWORK_READY` handshake, runs uvicorn | `main` |
| `packages/cowork-server/src/cowork_server/app.py` | FastAPI factory and `/v1` routes (health, sessions, messages, events WS) | `create_app` |
| `packages/cowork-server/src/cowork_server/auth.py` | Local single-user token guard for HTTP + WS | `TokenGuard` |
| `packages/cowork-server/src/cowork_server/transport.py` | Translate ADK events → JSON frames (M0: text only) | `event_to_frame` |

## `packages/cowork-cli/`

| Path | Description | Core symbol |
|---|---|---|
| `packages/cowork-cli/pyproject.toml` | cowork-cli package manifest (typer, rich, httpx, websockets) | — |
| `packages/cowork-cli/src/cowork_cli/__init__.py` | Package docstring | — |
| `packages/cowork-cli/src/cowork_cli/main.py` | Typer `cowork chat` — spawns server sidecar, streams deltas | `app` (Typer), `chat` |

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
