# Cowork Agent — Specification v0.1

A Claude-Cowork–style office-work agent built on **Google ADK (Python)**, with a file-canvas UI and a client/server architecture that runs the same core locally or as a service.

---

## 1. Landscape Analysis (coding agents we learn from)

| Agent | Language | Shape | Key ideas worth stealing |
|---|---|---|---|
| **Claude Code** | TS core + shell/PS/Python | Terminal-first CLI; extensible via hooks, slash-commands, subagents, skills, MCP, plugins | Hook model; MCP tools; subagents (isolated context); skills bundle (name+desc surfaced, content lazy-loaded); permission modes; Windows via PowerShell installer |
| **opencode** (sst/opencode) | TypeScript | **Client/server split**: core runs as a server, TUI/mobile/web are thin clients | Provider-agnostic LLM layer; LSP built in; `build`/`plan` modes; remote-drive ability; agent = one of several clients |
| **pi-mono** (badlogic) | TS monorepo | Clean layering: `pi-ai` (LLM unifier) → `pi-agent-core` (loop+tools+state) → `pi-coding-agent` / `pi-mom` / `pi-tui` / `pi-web-ui` (surfaces) | Radical separation of *loop* from *surface*; the same core drives a CLI, a Slack bot, a TUI, and a web UI |
| **Cline / Roo** | TS, VS Code | IDE-embedded; repo-indexed at startup; persona modes (Architect/Code/Ask) | Role-scoped permissions; repo map up front |
| **Aider** | Python | Terminal + Git-first; diffs/commits as the interface | Edit-as-diff; commit-per-turn audit trail |
| **Continue** | TS | Multi-IDE, multi-provider | Provider registry pattern |

### Common core agent loop (distilled)

```
while not done:
    msg = read_user_or_tool_result()
    response = llm.complete(system, history + msg, tools)
    for tool_call in response.tool_calls:
        check_permission(tool_call)          # policy layer
        result = dispatch(tool_call)         # tool registry
        history.append(result)
    if response.text: render(response.text)
    if response.stop_reason == "end_turn": break
```

Every agent above is a variation on this. The *interesting* differences are orthogonal to the loop:

1. **Provider abstraction** — decouple LLM vendor from loop (pi-ai, opencode providers).
2. **Tool registry + permission layer** — plain functions, schema-described, filtered by a policy (Claude Code permission modes; opencode build/plan).
3. **Context strategy** — skills (lazy), subagents (isolated), repo map (Cline), diffs (Aider).
4. **Surface decoupling** — loop runs in a headless core; TUIs, web, IDE, chatbots are clients (pi-mono, opencode). This is the single most important architectural lesson.
5. **Extension points** — hooks (pre/post tool), MCP tools, slash commands, skills/personas.

### Summary
The winning shape is: **a tiny, well-typed core loop + a provider abstraction + a tool registry with a policy layer + extension hooks + a transport that lets multiple surfaces drive the same core.** ADK already gives us Agent/Tool/Session/Runner/Event/Memory primitives that map cleanly onto this shape, so we build Cowork as **thin opinionated layers on top of ADK**, not a re-implementation.

---

## 2. Cowork Specification

### 2.1 Goals & non-goals

**Primary users**: non-technical office workers. Their surfaces are **web UI** and **desktop app (`cowork-app`)**. The CLI/TUI exists only for developers building and debugging Cowork.

**Goals**
- Office-work copilot (docs, sheets, slides, PDFs, data, email drafts, research) — not a coding-only agent.
- Built on **Google ADK Python** so we inherit Agent/Tool/Session/Runner/Memory.
- **Local-first** in v0.1: one installable desktop app / one local server; no cloud dependency to try or use the product.
- **OpenAI-compatible model layer** — any endpoint that speaks the OpenAI chat-completions API with tool-calling works (OpenAI, OpenRouter, vLLM, LM Studio, Ollama `/v1`, LiteLLM proxy, …). Users who care about privacy can point Cowork at a local model without any code change.
- **Sustainable**: small, legible modules; strict layer boundaries; every extension point is a plain Python function + a manifest.
- **Portable**: Windows, macOS, Linux are equal priority; no shell-specific assumptions in the core.
- **File-canvas UI**: previews for md / pdf / docx / csv / xlsx / images / plots alongside the chat.

**Non-goals (v0.1)**
- No hosted service, no Cloud Run / Vertex deploy. (Architecture keeps the door open — see §2.9.)
- No custom model hosting, no fine-tuning. (Local inference is the user's responsibility, via LM Studio / Ollama / vLLM behind the OpenAI-compatible adapter.)
- No IDE plugin.
- No distributed backend (Redis bus, Postgres sessions, multi-worker Uvicorn) *yet*. A small-team web deployment with multi-user auth runs on the single-process in-memory backend; distributed backends are a forward-compatible drop-in against the `EventBus` / `ConnectionLimiter` / `CoworkSessionService` protocols (see §2.9.3).

### 2.2 High-level architecture

```
┌────────────────────────────────────────────────────────────┐
│                      Surfaces (clients)                    │
│   Web UI (canvas)     CLI/TUI     Future: Slack, mobile    │
└────────────┬──────────────┬───────────────┬────────────────┘
             │              │               │
             ▼              ▼               ▼
          ┌───────────────────────────────────┐
          │   Transport  (HTTP + WebSocket)   │   ← same wire protocol
          │        /sessions  /events  /files │
          └───────────────┬───────────────────┘
                          │
                          ▼
          ┌───────────────────────────────────┐
          │           Cowork Core             │
          │  ┌─────────────────────────────┐  │
          │  │  ADK Runner + Root Agent    │  │
          │  │  Sub-agents (researcher,    │  │
          │  │    writer, analyst, …)      │  │
          │  └──────────────┬──────────────┘  │
          │                 │                 │
          │  ┌──────────────┴──────────────┐  │
          │  │  Tool Registry (ADK Tools)  │  │
          │  │  fs · shell · doc · sheet · │  │
          │  │  pdf · http · email · mcp   │  │
          │  └──────────────┬──────────────┘  │
          │                 │                 │
          │  ┌──────────────┴──────────────┐  │
          │  │ Policy / Permissions / Hooks│  │
          │  └──────────────┬──────────────┘  │
          │                 │                 │
          │  ┌──────────────┴──────────────┐  │
          │  │ Session · Memory · Workspace│  │
          │  └─────────────────────────────┘  │
          └───────────────┬───────────────────┘
                          │
                          ▼
                ┌───────────────────┐
                │   Remote LLM      │  (Gemini / Claude / OpenAI via ADK model adapter)
                └───────────────────┘
```

Surfaces **never** import core modules; they only speak the transport protocol. The same core, same transport, same protocol — whether bound to `127.0.0.1` in local mode or deployed behind auth on a server.

### 2.3 Repository layout (monorepo, `uv` workspace)

```
cowork/
├─ packages/
│  ├─ cowork-core/              # ADK agents, tools, policy, session, memory, skills
│  │  ├─ cowork_core/
│  │  │  ├─ agents/             # root_agent.py, researcher.py, writer.py, analyst.py
│  │  │  ├─ tools/              # execution surface: fs.py, shell.py, python_exec.py, http.py, search.py, email.py
│  │  │  ├─ skills/             # skill loader + bundled Cowork default skills (MIT)
│  │  │  ├─ policy/             # permissions.py, hooks.py
│  │  │  ├─ workspace/          # workspace.py (sandbox root), preview.py
│  │  │  ├─ memory/             # adk memory adapters
│  │  │  └─ config.py
│  │  └─ pyproject.toml
│  ├─ cowork-server/            # FastAPI app wrapping ADK Runner
│  │  ├─ cowork_server/
│  │  │  ├─ app.py              # FastAPI factory
│  │  │  ├─ routes/             # sessions, events, files, previews
│  │  │  ├─ transport.py        # WS event stream
│  │  │  └─ auth.py
│  │  └─ pyproject.toml
│  ├─ cowork-cli/               # Typer CLI + Textual TUI (cross-platform)
│  │  └─ cowork_cli/
│  ├─ cowork-web/               # React + Vite (TS) file-canvas UI
│  │  └─ src/
│  │     ├─ chat/
│  │     ├─ canvas/             # md, pdf, docx, csv, xlsx, image, plot previews
│  │     ├─ transport/          # typed client for the core protocol
│  │     └─ App.tsx
│  └─ cowork-app/               # Tauri v2 desktop shell (Win/mac/Linux)
│     ├─ src-tauri/             # Rust shell: window, tray, auto-update, IPC
│     │  ├─ src/
│     │  │  ├─ main.rs          # app entry, window lifecycle
│     │  │  ├─ sidecar.rs       # spawns cowork-server as child process
│     │  │  ├─ paths.rs         # OS-native workspace + config dirs
│     │  │  └─ menu.rs          # native menus, tray, shortcuts
│     │  ├─ tauri.conf.json     # bundler targets: msi, nsis, dmg, deb, AppImage
│     │  └─ Cargo.toml
│     └─ ui/                    # thin wrapper that reuses cowork-web bundle
├─ docs/
│  ├─ architecture.md
│  ├─ tools.md                  # how to write a tool (single file, one function)
│  ├─ agents.md                 # how to add a sub-agent (one file + register)
│  └─ protocol.md               # wire protocol spec
├─ examples/
└─ pyproject.toml               # workspace root
```

**Sustainability rules (enforced in `docs/architecture.md` + CI):**
1. One concept per file; a new tool = one new `.py` under `tools/` + one line in the registry.
2. No cross-layer imports: `surfaces → transport → core`. Core never imports surfaces.
3. Public surface of each package is ≤ 20 exported symbols.
4. Every tool has: docstring, pydantic arg schema, example, unit test.
5. No implicit global state; state lives in ADK Session or the Workspace object.

### 2.4 Core agent design (ADK)

**Root agent** = orchestrator (`LlmAgent`). Delegates to sub-agents via ADK's `sub_agents`:

- **researcher** — web search, fetch, summarize
- **writer** — draft/edit md/docx
- **analyst** — csv/xlsx load, pandas, plot generation
- **reviewer** — critique pass before final output
- **assistant** (default) — small asks, file ops, email drafts

Each sub-agent is one file, ≤150 lines, declaring: name, model, instruction, tools, optional sub-agents. Adding a new specialist = copy a file, register in `agents/__init__.py`.

**User-directed routing (@-mentions).** When the user starts a message with `@<agent_name>` (e.g. `@researcher gather sources on X`), the root agent transfers to that sub-agent on the first move rather than answering itself. The directive lives in the root's system prompt (an `AT_MENTION_PROTOCOL` paragraph in `cowork_core.agents.root_agent`) and is gated by the per-session `cowork.auto_route` state flag (default True). Toggling auto-route off — from the composer pill — omits the paragraph and lets the root handle `@`-text as plain input. This rides ADK's native `sub_agents` delegation rather than adding a manual `transfer_to_agent` tool; determinism depends on the model honoring the prompt directive, which manual QA validates.

**Model layer** — a single **OpenAI-compatible adapter** plugged into ADK's model abstraction. Any endpoint that implements OpenAI's `/v1/chat/completions` with tool-calling is supported: OpenAI, OpenRouter, Groq, Together, vLLM, LM Studio, Ollama (`/v1`), LiteLLM proxy, etc. Model choice is config-driven (`cowork.toml`: `base_url`, `api_key`, `model`). No vendor-specific code paths in the core.

Office workers will typically use a cloud endpoint; privacy-sensitive users point `base_url` at `http://localhost:11434/v1` (Ollama) or similar — same binary, same UI, zero code change.

### 2.5 Tool catalog (v0.1)

Cowork takes the **Claude-Code-style execution-surface** approach rather than building a bespoke per-format tool for every office file type. A small set of generic, battle-tested tools lets the agent — guided by skills (§2.5.1) — handle docx/xlsx/pdf/md and everything else via Python. This is what Anthropic's own office skills assume, and it scales cleanly: adding support for a new format is a new skill, not a new tool.

| Tool | Purpose | Notes |
|---|---|---|
| `fs.read` / `fs.write` / `fs.list` / `fs.glob` / `fs.stat` | workspace-scoped file I/O | pure `pathlib`; traversal rejected at `Workspace.resolve` |
| `fs.edit` | exact-string-replace edit of a file | Claude-Code-style: `path`, `old`, `new`, fail if `old` not unique |
| `shell.run` | run a command | `argv: list[str]` only; picks `pwsh`/`cmd`/`sh` per OS in one file; subject to `shell_allowlist` + confirm |
| `python_exec` | run a Python snippet in an isolated subprocess | uses the bundled interpreter; inherits a pinned allow-list venv (`python-docx`, `pypdf`, `openpyxl`, `pandas`, `matplotlib`, `markdown-it-py`); cwd is the session scratch dir; network off by default |
| `http.fetch` | safe GET with allowlist | `httpx` |
| `search.web` | zero-setup web search | default **DuckDuckGo** via `ddgs` (no API key); pluggable with Brave / Tavily / SearXNG if a key is set |
| `plot.render` | matplotlib → PNG in scratch, returns `file_id` for preview | convenience wrapper over `python_exec`; Agg backend |
| `email.draft` | build a draft `.eml` in workspace | always allowed |
| `email.send` | send an email | **requires explicit user confirmation per send** via the hook layer; default transport is SMTP in `cowork.toml`; Gmail/Outlook later via MCP |
| `load_skill` | load a skill body into the active context | §2.5.1 |
| `mcp.*` | MCP-server tools (Gmail, Google Calendar, Drive, Slack, …) | mounted via ADK's MCP adapter; how Cowork grows integrations without core changes |

**Shell portability rule:** there is exactly one `shell.run`. It takes `argv: list[str]`, never a single string, and OS dispatch lives in one file. Agents are instructed to prefer `python_exec` + `fs.edit` over `shell.run`; shell is an escape hatch.

**`python_exec` sandbox rule:** the subprocess runs with `cwd = session_scratch_dir`, `PYTHONNOUSERSITE=1`, network disabled by default (opt-in per call), and a wall-clock timeout. The allowed libraries are a fixed pinned set that ships with the interpreter bundle — no `pip install` at runtime. This is what makes skills able to manipulate docx/xlsx/pdf without us bundling LibreOffice, Node, or pandoc.

### 2.5.1 Skills (Cowork-native, Claude-Code-compatible format)

A **skill** is a filesystem bundle the agent loads on demand. Cowork adopts Anthropic's public `SKILL.md` frontmatter format so skills written for Claude Code are portable *in format* — but Cowork ships only skills it owns under MIT (or skills the user has installed themselves).

**On-disk layout:**

```
<workspace_root>/global/skills/<skill-name>/
├─ SKILL.md        # YAML frontmatter: name, description, license, triggers
├─ scripts/        # optional helper .py files the skill body tells the agent to run
└─ assets/         # optional static files (templates, reference tables)
```

**`SKILL.md` frontmatter:**

```yaml
---
name: docx-basic
description: "Use when the user wants to read, write, or edit .docx files..."
license: MIT
version: 0.1.0     # optional, free-form; defaults to "0.0.0"
triggers:          # optional; surfaced to the user, not to the model
  - docx
---
```

`name` and `description` are required; `license`, `version`, and
`triggers` are optional and accepted only as a permissive parse —
skills authored for Claude Code (which doesn't write these) round-
trip cleanly. Cowork additionally records a SHA-256 of each
`SKILL.md` at scan time as `content_hash`, surfaced via
`/v1/health.skills` and Settings so users can confirm a skill on
disk matches what they installed. See `docs/WRITING_A_SKILL.md`
for a longer treatment.

Only `name` + `description` are injected into the root agent's system prompt (a registry line). The body is loaded into context only when the agent calls `load_skill("docx-basic")`. This is the Claude Code skills pattern and keeps system prompts small even with many skills installed.

**Default bundled skills (Cowork, MIT):**

| Skill | Stack | Scope |
|---|---|---|
| `docx-basic` | `python-docx` | read + create + simple edit of Word docs. No LibreOffice, no Node, no docx-js. Covers ~90% of everyday office docx work; complex tracked-changes / XML unpack is out of scope. |
| `xlsx-basic` | `openpyxl` + `pandas` | read + create + formula strings + simple formatting. No LibreOffice recalc step — formulas persist as strings and are evaluated by the user's spreadsheet app on open. |
| `pdf-read` | `pypdf` | text + metadata extraction. Form filling and PDF→image rendering are out of scope for v0.1 (would need Poppler / LibreOffice). |
| `md` | `markdown-it-py` | read/write Markdown with a light HTML renderer for preview. |
| `plot` | `matplotlib` Agg | quick charts to PNG in scratch. |
| `research` | `search.web` + `http.fetch` | short research loop with source list. |
| `email-draft` | `email.mime` | compose a `.eml` with attachments from scratch. |

**Third-party skills:** users may install skills from other sources, including Anthropic's [`anthropics/skills`](https://github.com/anthropics/skills) repository. Those skills are **not** bundled with Cowork: Anthropic's skill materials are proprietary and their license forbids redistribution and derivative works, so we cannot ship them, download them on the user's behalf, or port their contents into Cowork-owned code. A user with the appropriate Anthropic agreement may drop those skills into their own `global/skills/` directory at their own risk, and is responsible for installing whatever heavy dependencies they need (LibreOffice, pandoc, Node + `docx-js`, Poppler, …). Cowork will load them through the same skill loader but treats them as user-supplied content.

**Why this split is the right call:**

1. **Legally clean defaults.** Every skill shipped in the installer is MIT-owned by Cowork.
2. **Bundled install stays small.** The M4 Tauri sidecar only needs the pinned Python allow-list, not LibreOffice or Node.
3. **Works on small local models.** Short MIT skills (50–150 lines) are far more reliable on a local 4-bit Qwen than a 590-line instruction bundle tuned for Sonnet/Opus.
4. **Power-user escape hatch intact.** The execution surface (`shell.run` + `python_exec` + `fs.edit`) can drive any skill a user installs, including Anthropic's, if they've installed the prerequisites.

### 2.6 Policy / permissions / hooks

- **Permission modes** (borrowed from Claude Code / opencode): `plan` (read-only, no writes, no shell), `work` (writes inside workspace, shell requires confirm), `auto` (full, used in server mode with a pre-approved allowlist).
- **Hook points**: `before_tool`, `after_tool`, `before_model`, `after_model`, `on_event`. Hooks are plain async Python callables registered in `policy/hooks.py`; they can mutate, block, or annotate. This is where audit logging, redaction, and rate-limiting live.
- **Workspace sandbox**: every file tool is rooted at a `Workspace` dir; path traversal is rejected before the tool runs.
- **Confirm-gated actions**: any tool marked `requires_confirmation=True` (email send, shell run outside allowlist, destructive file ops) emits a `confirmation_required` event; the surface (web/app) shows a modal; the tool only dispatches after an approval event returns. This is enforced in core, not in surfaces, so the CLI/TUI/app all inherit it.
- **Notifications**: turn-complete, approval-needed, and error events are pushed onto a per-user `NotificationStore` (ephemeral, in-process) that the UI polls via `/v1/notifications`. Like approvals, the store lives outside ADK session state to avoid the OCC race on `session.last_update_time`; see `ARCHITECTURE.md §5`.
- **Per-agent tool allowlist**: each sub-agent (researcher / writer / analyst / reviewer) can be restricted to a subset of the tool catalog for the session, via ADK state key `cowork.tool_allowlist` (`dict[str, list[str]]` — agent name → allowed tool names). Absent agent = unrestricted (default); empty list = silenced. The root agent is unrestricted by design. Enforced by a per-agent `before_tool_callback` closure created at agent-build time in `cowork_core.policy.permissions.make_allowlist_callback`.
- **@-mention auto-route**: ADK state key `cowork.auto_route` (bool, default True) gates whether the root agent's prompt includes the `@<agent_name>` routing protocol. See §2.4.

### 2.7 Transport protocol

HTTP + WebSocket, JSON, versioned at `/v1`:

- `POST /v1/sessions` → create session, returns `session_id`
- `POST /v1/sessions/{id}/messages` → user message
- `WS   /v1/sessions/{id}/events` → stream of ADK `Event`s (text deltas, tool_call, tool_result, file_created, preview_ready, error)
- `GET  /v1/sessions/{id}/files` → list workspace files
- `GET  /v1/files/{id}/preview?format=…` → rendered preview (html/png/json)
- `POST /v1/files` → upload into workspace

ADK `Event` objects map 1:1 onto the WS stream — no impedance mismatch.

The full route inventory is auto-published as an OpenAPI 3 schema at `/openapi.json` (Swagger UI at `/docs`, ReDoc at `/redoc`). Request and response shapes are declared as Pydantic models in `cowork_server/api_models.py`; auth uses an `x-cowork-token` header advertised as the `cowork-token` security scheme. WebSocket routes don't appear in the OpenAPI schema; the SSE / WS event payload format is `Event.model_dump_json(exclude_none=True, by_alias=True)` per ADK's `/run_sse` contract.

### 2.8 File-canvas UI

React + Vite. Left pane = chat. Right pane = **canvas** listing workspace files, each openable in a type-specific viewer:

| Type | Viewer |
|---|---|
| `.md` | `react-markdown` + remark/rehype |
| `.pdf` | `pdfjs-dist` |
| `.docx` | render via server-side `mammoth` → HTML (sent as preview) |
| `.csv` / `.xlsx` | virtualized table (`@tanstack/react-table`), server converts xlsx→json |
| `.png/.jpg/.svg` | `<img>` |
| plots | same PNG path |
| `.json` | JSON tree |

Heavy conversions (docx→html, xlsx→json, pdf thumbnailing) run in the **server**, cached by content hash, served via `/v1/files/{id}/preview`. The web client stays light and does not need Python.

### 2.9 Deployment modes

| Mode | How | Notes |
|---|---|---|
| **Desktop app** (`cowork-app`) — *primary end-user surface* | Tauri v2 shell spawns `cowork-server` as a sidecar on `127.0.0.1:random`, loads the `cowork-web` bundle into a native webview | One installer per OS: `.msi`/`.exe` (Windows), `.dmg` (macOS), `.deb`/`.AppImage` (Linux). Native menus, tray, file-drop, OS notifications, auto-update via **GitHub Releases**. v0.1 ships **unsigned dev builds**; code-signing is deferred. Python runtime shipped as an embedded `uv`-built standalone interpreter + wheels — users install nothing. User picks a **local working directory**; the agent operates directly on the files there (see §2.9.3). |
| **Local web** — *alternative end-user surface* | User runs `cowork serve`, opens `http://127.0.0.1:PORT` in a browser | Same `cowork-server` + `cowork-web` bundle, just without the Tauri shell. Useful on machines where users prefer not to install a desktop app. Runs in managed mode with projects and sessions under `~/CoworkWorkspaces`. |
| **Multi-user web** — *small team* | Same server with `[auth].keys = { ... }` in `cowork.toml`; each API key maps to a distinct user | In-process asyncio backend (bus + limiter + SQLite sessions), comfortable for roughly one or two dozen concurrent sessions. Per-user isolation is enforced via a `<workspace>/users/<user_id>/` subtree; Alice cannot see Bob's projects (§2.9.3). |
| **Local CLI** — *developer surface only* | `cowork chat` — CLI/TUI speaks to same local server | Same protocol, no browser, no Tauri. Not shipped as a primary end-user experience. |
| **Hosted service** — *future, not in v0.1* | `cowork-server` behind a reverse proxy on a VPS, or eventually Cloud Run / Vertex Agent Engine | Architecture is already service-ready (§2.2 client/server split). Adding hosted mode later means wiring TLS + scaling the runtime backend; see §2.9.3 for the forward-compatible upgrade path. |

The core does not know which mode it is in. Mode is a config file and a launcher.

### 2.10 Cross-platform rules (Windows + POSIX)

1. No hardcoded path separators; always `pathlib`.
2. No backtick shell strings anywhere; `argv` only.
3. Line endings: write LF in workspace, let viewers normalize.
4. `shell.run` selects `COMSPEC` / `pwsh` / `/bin/sh` via an OS switch in one place (`tools/shell.py`).
5. CI runs the full test matrix on `windows-latest`, `macos-latest`, `ubuntu-latest`.
6. No symlinks in the workspace contract (Windows perms vary).
7. Long-path awareness on Windows (`\\?\` prefix helper).

### 2.11 Observability & audit

- Every tool call, model call, and hook outcome is an ADK `Event`; events are persisted per session.
- Optional OpenTelemetry exporter (off by default locally, on in server mode).
- Session export: `cowork session export <id>` → zip of transcript + workspace snapshot.

### 2.11.1 Workspace layout (project- and session-based)

```
<workspace_root>/                     # e.g. ~/CoworkWorkspaces  (OS-native app data dir by default)
├─ projects/
│  ├─ <project-slug>/
│  │  ├─ project.toml                 # name, description, default skills, per-project model override
│  │  ├─ files/                       # the project's durable files (docs, sheets, etc.)
│  │  ├─ skills/                      # project-scoped skill bundles
│  │  └─ sessions/
│  │     ├─ <session-id>/
│  │     │  ├─ transcript.jsonl       # ADK Event stream
│  │     │  ├─ scratch/               # session-only files (drafts, generated plots)
│  │     │  └─ session.toml           # id, title, created_at, pinned
│  │     └─ …
│  └─ …
└─ global/
   ├─ skills/                         # user-global skill bundles (~/.cowork/skills)
   └─ config/
```

Rules:
- A **project** is the long-lived unit: the user sees "Quarterly Report", "Hiring", "Vendor X". Files in `files/` persist across sessions.
- A **session** is a conversation inside a project; it has its own `scratch/` for drafts the agent generates. "Save to project" promotes a file from `scratch/` to `files/`.
- File tools default to the active session's scratch dir; promoting to project files is an explicit tool call, so the agent cannot silently pollute the durable area.
- Path-traversal protection is rooted at `<workspace_root>`, not at the project — agents can be asked to move files between projects when the user explicitly requests it.

### 2.12 Config (`cowork.toml`)

```toml
[model]
# Any OpenAI-compatible endpoint with tool-calling.
base_url = "https://api.openai.com/v1"   # or http://localhost:11434/v1 (Ollama), http://localhost:1234/v1 (LM Studio), etc.
api_key  = "env:OPENAI_API_KEY"          # env: prefix reads from environment
model    = "gpt-4o-mini"                 # free-form; passed through to the endpoint

[server]
host = "127.0.0.1"
port = 0                                 # random; app picks and tells the UI

[workspace]
root = "~/CoworkWorkspaces"              # projects/ and global/ live under here

[policy]
mode = "work"                            # plan | work | auto
shell_allowlist = ["git", "python"]
email_send = "confirm"                   # always "confirm" in v0.1

[search]
provider = "duckduckgo"                  # zero-setup default; "brave" | "tavily" | "searxng" if a key is set

[tools.mcp]
servers = []                             # MCP tool servers to mount (Gmail, Calendar, Drive, Slack, …)

[updates]
channel = "github"                       # github releases feed
repo    = "<owner>/cowork"
```

### 2.9.1 Why Tauri for `cowork-app`

- **Cross-platform with one codebase** — Windows, macOS, Linux from the same Rust shell + reused `cowork-web` bundle.
- **Small installers** — uses the OS webview (WebView2 / WKWebView / WebKitGTK), typically 5–15 MB shell vs. ~150 MB for Electron.
- **Sidecar pattern fits our architecture** — Tauri's `sidecar` was designed for exactly this: ship a bundled binary (`cowork-server`) that the shell spawns and tears down with the window. No IPC refactor: the webview talks to `127.0.0.1` over the same `/v1` protocol the web UI already uses.
- **Native integration** — file drag-and-drop onto the canvas, OS notifications, menu bar, tray, global shortcuts, deep links.
- **Signing & auto-update built in** — Tauri updater + code-signing workflows for all three OSes.
- **Alternative considered**: Electron (bigger, heavier, but larger ecosystem). We pick Tauri; Electron stays a fallback if a blocker appears (e.g. WebView2 feature gap).

### 2.9.2 Python runtime bundling

The Python server must run without the user installing Python. Two supported strategies:

1. **Embedded interpreter** (default): ship a relocatable CPython (via `python-build-standalone` / `uv python install`) + a frozen venv of `cowork-core` and `cowork-server` wheels, inside the Tauri resource dir. `sidecar.rs` launches `python -m cowork_server`.
2. **PyInstaller one-file** (fallback for tiny installers): freeze `cowork-server` into a single executable per OS and ship that as the sidecar. Loses hot-patching but simplifies signing.

Choice is per-release and invisible to the UI layer.

### 2.9.3 Surface modes: desktop (local-dir) vs web (managed)

The agent core (`cowork-core`) is surface-agnostic. Two deployment shapes
plug in via two concerns that the core does *not* hard-code:

- **Where files live** — the `ExecEnv` protocol
  (`cowork_core/execenv/`). `ManagedExecEnv` gives the classic
  `scratch/` + `files/` two-namespace view rooted under
  `<workspace>/projects/<slug>/`. `LocalDirExecEnv` points the agent
  at a user-picked directory; agent paths are plain relative paths
  under that root; session bookkeeping lives at
  `<workdir>/.cowork/sessions/<id>/`.
- **Which runtime backend serves requests** — three protocols carry
  the distributed seam without any route surgery:
  `EventBus` (`cowork_server/bus/`), `ConnectionLimiter`
  (`cowork_server/limiter/`), and `CoworkSessionService`
  (`cowork_core/sessions/`). Today the only implementations are the
  in-memory / SQLite ones; future `RedisEventBus`,
  `RedisConnectionLimiter`, and `PostgresCoworkSessionService`
  slot in as new files against the same protocols.

The **surface selector** is `POST /v1/sessions`:

- Body `{ "workdir": "/abs/path" }` → local-dir / desktop mode.
  `cowork-app` uses the Tauri `tauri-plugin-dialog` folder picker,
  then passes the chosen absolute path.
- Body `{ "project": "<slug or name>" }` → managed / web mode. The
  session lives under `<workspace.root>/projects/<slug>/` (or
  `<workspace.root>/users/<user_id>/projects/<slug>/` when
  multi-user auth is active).

Both modes speak the same `/v1/*` contract otherwise. SSE events,
history replay, tool execution, and the system prompt are identical;
only the `describe_for_prompt()` text and path vocabulary change
per env.

**Multi-user isolation.** When `[auth].keys` is non-empty in
`cowork.toml`, `MultiKeyGuard` maps each API key to a stable
`user_id`. `CoworkRuntime.workspace_for(user_id)` /
`registry_for(user_id)` route all project operations into
`<workspace.root>/users/<user_id>/`, so tenants cannot list or
resolve each other's files. In sidecar (single-token) mode the
user_id is always `"local"` and this subtree is skipped.

**Sandboxing posture (desktop).** Path confinement is the
mechanism: `LocalDirExecEnv.resolve()` absolutizes the candidate
and rejects anything that escapes the chosen root. Shell and Python
tools retain their own hardening
(`shell_run` argv allowlist + `python_exec_run` subprocess lockdown).
OS-level sandboxes (macOS seatbelt, Linux landlock, Windows
AppContainer) are **explicitly deferred** — path confinement is
sufficient for v1, and operators who need defense in depth can pair
it with an external container.

**Distributed upgrade path (deferred).** When a deployment needs
horizontal scale, the in-memory bus + SQLite sessions become the
bottleneck. The plan is a one-file addition per backend:

- `packages/cowork-server/src/cowork_server/bus/redis.py` —
  `RedisEventBus` publishing to a Redis stream keyed by `session_id`.
- `packages/cowork-server/src/cowork_server/limiter/redis.py` —
  `RedisConnectionLimiter` with per-user counters in Redis.
- `packages/cowork-core/src/cowork_core/sessions/postgres.py` —
  `PostgresCoworkSessionService` wrapping ADK's database session
  service (or equivalent) with the same
  `register_context` builder seam.

Selection will happen via `[runtime] backend = "distributed"` in
`cowork.toml`; today `build_runtime` raises `NotImplementedError` on
that value so configs can't silently misroute. Multi-worker Uvicorn
follows once shared state is wired. No route or core-loop change is
expected — surfaces already go through the protocols.

### 2.13 Milestones

1. **M0 — Skeleton (1 wk)**: monorepo, ADK root agent with OpenAI-compatible model adapter, FastAPI transport, CLI client. Hello-world session end-to-end on macOS + Windows + Linux. ✅
2. **M1 — Execution surface + skills (3 wk)**: project/session workspace sandbox; generic tool set (`fs.*`, `fs.edit`, `shell.run`, `python_exec`, `http.fetch`, `search.web`); skill loader using the `SKILL.md` frontmatter format; bundled MIT default skills (`docx-basic`, `xlsx-basic`, `pdf-read`, `md`, `plot`, `research`, `email-draft`); preview endpoints. This milestone intentionally replaces the former "bespoke office tools" M1 — see §2.5.
3. **M2 — Web canvas (2 wk)**: React UI, WS event stream, project/session switcher, all viewers, confirmation modal, skill list in the sidebar.
4. **M3 — Multi-agent + MCP (1 wk)**: researcher / writer / analyst / reviewer sub-agents; permission modes; hooks; MCP tool adapter — done across Slices III + IV (transports, dynamic `<workspace>/global/mcp/servers.json`, Settings UI, restart-only reload). The original "first integration target = a local-files MCP server" goal is met by [`docs/MCP.md`](docs/MCP.md)'s worked example for `@modelcontextprotocol/server-filesystem` (npx-based; users install themselves rather than it shipping bundled — cull-audit kept Cowork's surface neutral). Skill loader already lives in M1. ✅
5. **M4 — Desktop app (2 wk)**: `cowork-app` Tauri shell, sidecar launcher, embedded Python runtime, **unsigned dev builds** for Windows/macOS/Linux via GitHub Releases, Tauri updater wired to the same feed.
6. **M5 — Email + confirm flow (1 wk)**: `email.draft` + `email.send` with confirm-gated dispatch end-to-end; SMTP config; begin Gmail via MCP.
7. **M6 — Hardening (ongoing)**: cross-platform CI matrix green, audit log, session export, docs for writing a tool / sub-agent / skill (skill docs at [`docs/WRITING_A_SKILL.md`](docs/WRITING_A_SKILL.md) — Slice I).

Hosted mode, code-signing, and auth are explicitly **post-v0.1** and tracked as separate tracks.

### 2.14 Open questions

- Memory: ADK `Memory` vs. our own vector store? Start with ADK's; revisit if office-doc recall needs change.
- docx write fidelity — is `python-docx` enough, or do we need a templating layer?
- First MCP server to ship with the default install — local-files only, or also a web-fetch MCP for symmetry?
- When we do enable code-signing post-v0.1, do we go Apple Developer ID + Azure Trusted Signing, or keep unsigned + publish checksums?

### 2.15 License

MIT.

---

## Sources

- [Claude Code repo](https://github.com/anthropics/claude-code)
- [opencode repo](https://github.com/sst/opencode)
- [pi-mono repo](https://github.com/badlogic/pi-mono)
- [Google ADK Python](https://github.com/google/adk-python)
- [Best Open Source Coding Agents 2026 — Open Source AI Review](https://www.opensourceaireview.com/blog/best-open-source-coding-agents-in-2026-reviewed-ranked)
- [Open-source coding agents — The New Stack](https://thenewstack.io/open-source-coding-agents-like-opencode-cline-and-aider-are-solving-a-huge-headache-for-developers/)
- [Roo Code vs Cline — Qodo](https://www.qodo.ai/blog/roo-code-vs-cline/)
