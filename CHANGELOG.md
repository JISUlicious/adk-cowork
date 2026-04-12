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
