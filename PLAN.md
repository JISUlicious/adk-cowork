# Cowork — Implementation Plan

Companion to `SPEC.md`. Where the spec says *what*, this says *how and in what order*. Every task is sized to be landable in one PR and has an acceptance check you can run.

Legend: `§` = spec section · `AC` = acceptance check · `dep` = depends on

---

## M0 — Skeleton (target: 1 week)

**Goal**: one developer can run `cowork chat` on macOS, Windows, and Linux, send "hello", and see a model reply streamed through the ADK loop. No office tools yet.

### M0.1 Repo + tooling
- [ ] Initialize `uv` workspace at `cowork/` with `pyproject.toml` declaring members `packages/cowork-core`, `packages/cowork-server`, `packages/cowork-cli`.
- [ ] Add `.editorconfig`, `.gitignore` (Python, Node, Rust, `.venv/`, `dist/`, `target/`, `CoworkWorkspaces/`).
- [ ] Add `ruff` + `ruff format` + `mypy --strict` configs at workspace root.
- [ ] Add `pre-commit` with ruff, mypy, end-of-file-fixer.
- [ ] `LICENSE` = MIT; `README.md` stub pointing at `SPEC.md` and `PLAN.md`.
- **AC**: `uv sync && uv run ruff check . && uv run mypy` passes on an empty workspace.

### M0.2 `cowork-core` package skeleton
- [ ] `cowork_core/__init__.py` exports only the public surface (≤20 symbols rule, §2.3).
- [ ] `cowork_core/config.py` — pydantic-settings model for `cowork.toml` (§2.12). `env:FOO` prefix resolver.
- [ ] `cowork_core/workspace/workspace.py` — `Workspace` class rooted at a path; `resolve(rel)` rejects traversal; `scratch_dir(session_id)`.
- [ ] `cowork_core/model/openai_compat.py` — ADK model adapter that wraps any OpenAI-compatible `/v1/chat/completions` with tool-calling. Uses `openai` SDK with custom `base_url`.
- [ ] `cowork_core/agents/root_agent.py` — minimal ADK `LlmAgent` with name, instruction, no tools yet.
- [ ] `cowork_core/runner.py` — thin factory: `build_runner(config) -> (Runner, Session)`.
- **AC**: `uv run python -c "from cowork_core import build_runner; …"` starts a session and streams a reply.

### M0.3 `cowork-server` package skeleton
- [ ] FastAPI app factory `cowork_server/app.py`.
- [ ] Routes (§2.7): `POST /v1/sessions`, `POST /v1/sessions/{id}/messages`, `WS /v1/sessions/{id}/events`.
- [ ] `transport.py` — translate ADK `Event` → JSON frames on the WS.
- [ ] `auth.py` — single local-token stub (generated at launch, written to `~/.cowork/token`).
- [ ] `cowork-server serve` entrypoint: picks random free port, prints `http://127.0.0.1:PORT` + token to stdout.
- **AC**: `curl -X POST .../sessions` + `websocat .../events` shows streamed text deltas end-to-end.

### M0.4 `cowork-cli` package skeleton
- [ ] Typer app `cowork_cli/main.py` with `chat` command.
- [ ] `chat` spawns `cowork-server` as subprocess (or attaches to `$COWORK_SERVER`), connects WS, prints streamed deltas.
- [ ] Uses `rich` for rendering (Windows-safe, no ANSI assumptions).
- **AC**: `cowork chat` works on Windows (cmd + PowerShell), macOS, Linux. Ctrl-C terminates the server cleanly.

### M0.5 CI matrix
- [ ] `.github/workflows/ci.yml` — matrix of `{windows-latest, macos-latest, ubuntu-latest}`, Python 3.12.
- [ ] Jobs: `lint` (ruff, mypy), `test` (pytest), `smoke` (spin server, send one message, assert reply).
- **AC**: green on all three OSes.

**M0 exit criteria**: fresh clone → `uv sync` → set `OPENAI_API_KEY` → `cowork chat` → get a reply on all three OSes.

---

## M1 — Execution surface + skills (target: 3 weeks) · dep: M0

**Goal**: the agent has a small, generic execution surface (`fs`, `fs.edit`, `shell.run`, `python_exec`, `http.fetch`, `search.web`) plus a skill loader that can pick up `SKILL.md`-format bundles from disk. Cowork ships seven MIT-owned default skills that cover the common office workflows without shelling out to LibreOffice / pandoc / Node. This replaces the earlier "bespoke per-format office tools" shape after the Anthropic-skills review (see `SPEC.md` §2.5 and `CHANGELOG.md` 2026-04-11).

### M1.1 Workspace model (§2.11.1)
- [ ] `Project` + `Session` dataclasses in `cowork_core/workspace/`.
- [ ] `projects/<slug>/{project.toml,files/,skills/,sessions/<id>/{transcript.jsonl,scratch/,session.toml}}` layout created on demand.
- [ ] `ProjectRegistry.list/create/get` with filesystem as source of truth.
- [ ] `Session.promote(path)` — move file from `scratch/` to project `files/`.
- **AC**: unit tests covering traversal rejection, promote, project list.

### M1.2 Tool registry + base types
- [ ] `cowork_core/tools/base.py` — `Tool` protocol: name, description, pydantic args model, async `run(ctx, args)`, `requires_confirmation` flag.
- [ ] `cowork_core/tools/registry.py` — `ToolRegistry.register()`, `ToolRegistry.as_adk_tools()` (converts to ADK `FunctionTool`s), `get(name)`.
- [ ] `ToolContext` dataclass: workspace, session, project, policy mode.
- **AC**: a trivial `echo` tool registers and round-trips through ADK.

### M1.3 `fs` tool family
- [ ] `tools/fs.py` with functions `read`, `write`, `list`, `glob`, `stat`, `edit`, `promote_to_project`.
- [ ] `fs.edit` = exact-string-replace (Claude-Code semantics): arguments `path`, `old`, `new`; error if `old` is not unique; error if file was not previously read in this session (tracked in `ToolContext.session_reads`).
- [ ] All paths routed through `Workspace.resolve`; default scope is session scratch, explicit `scope="project"` for durable files.
- **AC**: unit tests for read/write/edit/unique-match failure/path traversal rejection.

### M1.4 `shell.run` (portable)
- [ ] `tools/shell.py`: `run(argv: list[str], cwd=None, timeout=30, env=None)`. Never accepts a single string.
- [ ] Interpreter selection in one place: on POSIX uses `subprocess.run` directly; on Windows, no shell unless the arg list needs one. Built-ins like `dir` are rejected with a message suggesting an `argv`-style equivalent.
- [ ] Policy: blocked unless mode allows it AND `argv[0]` is in `shell_allowlist`; otherwise emits a `confirmation_required` event.
- **AC**: cross-OS test runs `[sys.executable, "--version"]` through the tool; Windows test confirms allowlist + confirm flow.

### M1.5 `python_exec` sandbox
- [ ] `tools/python_exec.py`: `run(code: str, network: bool = False, timeout: int = 60)`.
- [ ] Spawns `sys.executable -c code` (or a temp `.py` for longer snippets) with `cwd=session_scratch`, `PYTHONNOUSERSITE=1`, and `env` minus `PYTHONPATH` except the pinned allow-list venv.
- [ ] Pinned allow-list libs installed into the runtime: `python-docx`, `openpyxl`, `pandas`, `pypdf`, `matplotlib`, `markdown-it-py`, `Pillow`. (Added to `cowork-core` deps.)
- [ ] Network off by default; when `network=False`, subprocess sees `HTTP_PROXY=http://127.0.0.1:1` so accidental requests fail fast.
- [ ] Captures stdout / stderr / exit; truncates to a configurable limit; returns structured result.
- **AC**: a skill can `python_exec` a snippet that reads a sample `.docx` with `python-docx` and returns its paragraphs, on all three OSes.

### M1.6 `http.fetch` and `search.web`
- [ ] `tools/http.py`: safe GET with a hostname allowlist from config (`[tools.http] allow = ["*"]` by default in v0.1), size cap, redirect cap.
- [ ] `tools/search.py`: `duckduckgo` provider via `ddgs` (zero setup); `brave` / `tavily` / `searxng` behind optional config keys.
- **AC**: a one-turn "search + fetch + summarize" session works without any API keys.

### M1.7 Skill loader + `load_skill` tool
- [ ] `cowork_core/skills/loader.py`: walks `<workspace_root>/global/skills/` and `projects/<slug>/skills/`, parses `SKILL.md` frontmatter (`name`, `description`, `license`, optional `triggers`), lazy-holds the body text.
- [ ] `SkillRegistry` exposes `list()`, `get(name)`, `injection_snippet()` (for the system prompt — only `name: description` lines).
- [ ] `load_skill` tool: argument `name`; returns the body markdown + a manifest of `scripts/` and `assets/` paths the skill exposes to `python_exec` / `shell.run`.
- [ ] Root agent's system prompt is built at runtime by composing `ROOT_INSTRUCTION` with `skill_registry.injection_snippet()`.
- **AC**: installing a `hello` skill (one SKILL.md) makes it show up in the agent's prompt; calling `load_skill("hello")` returns the body.

### M1.8 Default Cowork skills (MIT)
Each skill is a directory under `packages/cowork-core/src/cowork_core/skills/bundled/<name>/` containing `SKILL.md` plus any `scripts/` or `assets/`. On first launch they are copied (or symlinked via copy) into `<workspace_root>/global/skills/` so the user can edit them.

- [ ] `docx-basic` — read/create/edit .docx via `python-docx`. Out of scope: tracked changes, XML unpack, Node docx-js.
- [ ] `xlsx-basic` — read/create/edit .xlsx via `openpyxl` + `pandas`. Formulas persist as strings.
- [ ] `pdf-read` — extract text + metadata via `pypdf`. Out of scope: form filling, PDF→image.
- [ ] `md` — read/write markdown via `markdown-it-py`; render HTML for preview.
- [ ] `plot` — matplotlib Agg → PNG in scratch, returns `file_id`.
- [ ] `research` — short `search.web` + `http.fetch` loop producing a sourced summary.
- [ ] `email-draft` — compose `.eml` files with attachments.
- **AC**: each skill has a scripted session test that loads it, calls its Python, and asserts a plausible output file.

### M1.9 Preview endpoints
- [ ] `GET /v1/files/{id}/preview?format=…` in `cowork-server`.
- [ ] Conversions (all Python-only; no LibreOffice / mammoth / pypdfium2 in v0.1), cached by content hash under `<workspace_root>/global/.preview-cache/`:
  - `.md` → HTML (markdown-it-py + light allowlist sanitization)
  - `.docx` → structured JSON (paragraphs + styles, rendered client-side)
  - `.pdf` → text + metadata JSON (first-page image deferred to M2 stretch)
  - `.xlsx` → JSON rows + schema (openpyxl)
  - `.csv` → JSON rows + schema
  - images → passthrough
- **AC**: all six preview types return 200 with correct Content-Type and a stable payload shape.

**M1 exit criteria**: a non-technical user on any of the three OSes can ask "read `notes.docx` and draft a one-page summary in `summary.md`" and "take `sales.csv`, plot monthly revenue, save as `revenue.png`", and Cowork does it using only the bundled MIT skills — no LibreOffice, no Node, no pandoc required.

---

## M2 — Web canvas (target: 2 weeks) · dep: M1

**Goal**: non-technical user can open the app in a browser, pick a project, chat, and watch files land in the canvas with live previews.

### M2.1 `cowork-web` bootstrap
- [ ] Vite + React + TypeScript + TailwindCSS at `packages/cowork-web/`.
- [ ] `transport/client.ts` — typed client for the `/v1` protocol; one class, no state libs yet.
- [ ] `App.tsx` layout: left = chat, right = canvas, top bar = project/session switcher.
- **AC**: `npm run dev` loads against a running `cowork-server`, shows project list.

### M2.2 Chat pane
- [ ] Message list with streamed text deltas.
- [ ] Tool-call cards (collapsed by default, expand to show args + result).
- [ ] Confirmation modal for `confirmation_required` events (§2.6) — modal blocks the chat until approve/deny is sent back over WS.
- **AC**: manual test of a confirm-gated tool call shows modal, approving dispatches, denying cancels cleanly.

### M2.3 File canvas
- [ ] Left-canvas file tree (project files + current session scratch).
- [ ] Viewers (§2.8): react-markdown (md), pdfjs-dist (pdf), server-rendered HTML for docx, @tanstack/react-table for csv/xlsx, `<img>` for images, PNG for plots, JSON tree for json.
- [ ] "Promote to project" button on scratch files.
- **AC**: dropping a sample set (md, pdf, docx, csv, xlsx, png) into a session renders every type.

### M2.4 Project/session management UI
- [ ] Create project, rename, delete (with confirmation).
- [ ] Session list per project; "new session" button; session titles auto-suggested from first user message.
- **AC**: full CRUD loop via UI, backed by M1.1 registry.

---

## M3 — Multi-agent + skills + MCP (target: 1 week) · dep: M2

### M3.1 Sub-agents
- [ ] `agents/researcher.py`, `writer.py`, `analyst.py`, `reviewer.py` — one file each, ≤150 LOC, declared via ADK `sub_agents`.
- [ ] Root agent instruction explains when to delegate.
- **AC**: a "research + draft + review" prompt visibly delegates across sub-agents (tool-call cards show agent name).

### M3.2 Permission modes
- [ ] `policy/permissions.py`: `plan | work | auto`. `plan` disallows writes + shell + email send; `work` allows writes, confirms shell and send; `auto` uses allowlists only.
- [ ] Mode switcher in web UI top bar (starts in `work`).
- **AC**: switching to `plan` blocks a write tool call with an event explaining why.

### M3.3 Hooks
- [ ] `policy/hooks.py`: `before_tool`, `after_tool`, `before_model`, `after_model`, `on_event`. Registered as list of async callables.
- [ ] Default hooks: audit log → `sessions/<id>/transcript.jsonl`; redaction hook stub.
- **AC**: transcript file contains every tool call + result for a session.

### M3.4 Skill bundles (Claude-Code-style)
- [ ] Loader walks `<workspace_root>/global/skills/` and `projects/<slug>/skills/`, reads `skill.md` frontmatter (`name`, `description`, `triggers`). Only name+description are injected into the system prompt; body is loaded on demand via a `load_skill` tool.
- [ ] Ship 2 example skills: `meeting-notes` (templates md), `expense-report` (csv → xlsx pipeline).
- **AC**: asking "take meeting notes on this" causes `load_skill("meeting-notes")` then applies the template.

### M3.5 MCP adapter
- [ ] Mount MCP servers declared in `[tools.mcp]` via ADK's MCP tool adapter.
- [ ] Ship one default: a local-files MCP server (for parity across installs; also an integration test target).
- **AC**: MCP tools appear in the agent's tool list and can be called through the same policy layer.

---

## M4 — Desktop app (target: 2 weeks) · dep: M2 (can overlap M3)

**Goal**: one double-clickable installer per OS that non-technical users can run.

### M4.1 Tauri v2 project
- [ ] `packages/cowork-app/src-tauri/` — `cargo tauri init`, bundler targets set to `msi`, `nsis`, `dmg`, `deb`, `appimage`.
- [ ] `tauri.conf.json` — window 1280×800, fullscreen toggle, file-drop enabled, tray icon.
- **AC**: `cargo tauri dev` launches an empty window on all three OSes.

### M4.2 Embedded Python runtime
- [ ] Build step: download `python-build-standalone` CPython 3.12 per OS; `uv pip install` `cowork-core` + `cowork-server` wheels into a relocatable venv inside `src-tauri/resources/python/<os>/`.
- [ ] Checksum the bundle, cache between CI runs.
- **AC**: bundle size under 120 MB per OS; launch test executes `python -m cowork_server --help`.

### M4.3 Sidecar launcher
- [ ] `src-tauri/src/sidecar.rs` — spawns `python -m cowork_server` with random port + generated token, parses the stdout handshake line `COWORK_READY host=… port=… token=…`.
- [ ] Passes `COWORK_SERVER_URL` + token to the webview via Tauri `invoke`.
- [ ] On window close → graceful shutdown of the sidecar.
- **AC**: closing the app leaves no orphan `python` process (verified on all three OSes).

### M4.4 Webview points at bundled web UI
- [ ] Build `cowork-web` → static assets → bundled under `src-tauri/resources/ui/`.
- [ ] Tauri loads `tauri://localhost/index.html`; `transport/client.ts` resolves base URL from `invoke("get_server")`.
- **AC**: desktop app loads the same UI the browser mode does.

### M4.5 Native integration
- [ ] Native menu: File → New Project / Open Workspace Dir / Quit; Edit; Help.
- [ ] File drag-and-drop onto canvas → upload into active session scratch.
- [ ] OS notifications for long-running task completion.
- [ ] Open workspace dir in OS file manager (Finder / Explorer / xdg-open).
- **AC**: drag a pdf onto the canvas → it appears, preview renders.

### M4.6 Auto-update via GitHub Releases
- [ ] Tauri updater configured with GitHub Releases feed (public repo).
- [ ] CI workflow `.github/workflows/release.yml`: on tag `v*`, build per OS, create draft GH Release, attach installers + `latest.json`.
- [ ] **Unsigned** for v0.1; updater verifies SHA256 only.
- **AC**: publishing v0.1.1 while v0.1.0 is running triggers an update prompt in the app.

### M4.7 Installer QA
- [ ] Smoke test per OS: download installer on a clean VM, install, launch, complete a one-turn session.
- **AC**: all three OSes pass the smoke test.

---

## M5 — Email + confirm flow (target: 1 week) · dep: M3

### M5.1 SMTP transport
- [ ] `tools/email.py`: `draft(to, subject, body, attachments=[])` → writes `.eml` to scratch; `send(eml_id)` → SMTP via `smtplib` using `[email]` config block.
- **AC**: local MailHog integration test passes.

### M5.2 Confirmation wiring
- [ ] `email.send` declared with `requires_confirmation=True`. Emits `confirmation_required` event with a human-readable summary of the email.
- [ ] Web UI modal shows recipient/subject/body preview before approving.
- **AC**: denying a send cancels the tool call; approving actually sends.

### M5.3 Gmail via MCP (stretch)
- [ ] Document how to mount a Gmail MCP server under `[tools.mcp]`; ship a sample config.
- **AC**: with user-provided Gmail MCP, a "draft + send" loop works without SMTP config.

---

## M6 — Hardening (continuous from M1)

Not time-boxed; runs in parallel and must be green before tagging v0.1.

- [ ] CI matrix green on all three OSes for every package.
- [ ] Long-path test on Windows (`\\?\` prefix path under `<workspace_root>`).
- [ ] Line-ending test: write from agent, open in viewer, round-trip.
- [ ] Session export: `cowork session export <id>` → zip of transcript + session scratch.
- [ ] Docs:
  - [ ] `docs/architecture.md` — layers, invariants, "how to add X" table.
  - [ ] `docs/tools.md` — tool authoring walkthrough with a real example PR.
  - [ ] `docs/agents.md` — adding a sub-agent.
  - [ ] `docs/skills.md` — skill bundle format.
  - [ ] `docs/protocol.md` — wire protocol reference.
- [ ] Pre-release checklist automated: `scripts/release-check.sh` runs lint + type + tests + smoke across OSes.

---

## Cross-cutting decisions locked in

- **Python** 3.12, managed via `uv`.
- **Node** 20 LTS for `cowork-web`.
- **Rust** stable for `cowork-app`.
- **Transport** JSON over HTTP + WS; event schema mirrors ADK `Event` 1:1 (see `docs/protocol.md`, written in M6).
- **Workspace root default**:
  - macOS: `~/Library/Application Support/Cowork`
  - Windows: `%APPDATA%/Cowork`
  - Linux: `${XDG_DATA_HOME:-~/.local/share}/cowork`
- **Config file**: `<workspace_root>/global/config/cowork.toml`; first launch writes defaults.
- **Logs**: `<workspace_root>/global/logs/`, rotated daily.
- **Python bundling for M4**: `python-build-standalone` (primary). PyInstaller stays as documented fallback only — do not branch code on it.

---

## Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| ADK OpenAI-compat adapter doesn't exist / is thin | Blocks M0 | Wrap `openai` SDK ourselves as an ADK `BaseLlm` subclass; keep the boundary tiny so replacing it is one file. |
| Tauri sidecar + Python bundle exceeds 150 MB | Hurts UX | Prune stdlib unused modules; consider per-OS wheel stripping; if still too big, evaluate PyInstaller fallback. |
| MCP adapter in ADK lags behind MCP spec | Blocks M3.5 | Have a thin local shim ready; one of the test servers is in-tree so we control the version. |
| Matplotlib cold start is slow | UX regression in M1.3 | Use Agg backend + import lazily inside `plot.render`. |
| WebView2 not installed on older Windows | M4.7 failure | Tauri installer bundles the WebView2 bootstrapper; document fallback for offline Windows. |
| `ddgs` rate-limits / breaks | Search outage | Provider interface already in place; swap to SearXNG self-hosted or Brave with user key. |
| Non-technical user cannot edit `cowork.toml` | Onboarding friction | Build a minimal settings UI in M2 so the config file is optional for common tweaks (model endpoint, email). |

---

## Immediate next action (M0.1)

1. `cd cowork && uv init --package cowork-core packages/cowork-core` (repeat for `-server`, `-cli`).
2. Root `pyproject.toml` with `[tool.uv.workspace] members = ["packages/*"]`.
3. Land ruff + mypy + pre-commit.
4. Open a PR titled `chore: workspace skeleton` and get CI green on all three OSes before touching any agent code.

That PR is the smallest unit of forward progress — everything else depends on it.
