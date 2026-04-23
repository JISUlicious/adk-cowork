# Cowork

Office-work copilot agent built on [Google ADK Python](https://google.github.io/adk-docs/). Works with any OpenAI-compatible model endpoint (LM Studio, Ollama, vLLM, OpenRouter, OpenAI, etc.).

## Quick start

```bash
# 1. Install dependencies
cd cowork
uv sync

# 2. Configure your model (copy and edit .env.sample, or export directly)
cp .env.sample .env
# Edit .env with your model endpoint, then:
source .env

# 3. Run
uv run cowork
```

That's it. Cowork spawns a local server, creates a session, and drops you into a chat loop. Type `exit` to quit.

## Running the web UI (browser)

The React UI under `packages/cowork-web` talks to the same FastAPI server as
the CLI. For a zero-friction dev loop, pin the port + token in `.env`:

```bash
# In the repo-root .env (copy from .env.sample first):
COWORK_PORT=9100
COWORK_TOKEN="cowork-local-dev-token"
```

Then either use the **one-command launcher**:

```bash
scripts/dev.sh    # starts cowork-server + Vite in parallel; Ctrl+C stops both
```

…or two terminals by hand:

```bash
# Terminal 1: server picks up COWORK_PORT + COWORK_TOKEN from .env
uv run python -m cowork_server

# Terminal 2: Vite proxies /v1 → 127.0.0.1:$COWORK_PORT and embeds the token
cd packages/cowork-web
npm install
npm run dev
```

Open `http://localhost:5173`. Both processes pull from the same `.env`, so
there's nothing to pass on the command line — and nothing to copy-paste out
of stdout between restarts.

Without `COWORK_PORT` set, the server picks a random free port each launch
(production behavior). Vite's proxy then defaults to `9100` and they won't
agree — set it explicitly in `.env` or pass `COWORK_PORT=…` inline.

## Surface modes

One `cowork-core`, two surfaces, selected at session-create time:

| Mode | Surface | Session creation | Where files live |
|---|---|---|---|
| **Desktop (local-dir)** | Tauri app | `POST /v1/sessions {"workdir": "/path"}` — user picks a folder via `tauri-plugin-dialog` | The picked folder. Agent paths are relative to it; scratch at `<workdir>/.cowork/sessions/<id>/`. |
| **Web (managed)** | Browser | `POST /v1/sessions {"project": "Name"}` | `~/CoworkWorkspaces/projects/<slug>/{files,sessions}` — classic `scratch/` + `files/` two-namespace view. |
| **Web multi-user** | Browser + `cowork.toml` `[auth].keys` | Same as web, but each API key maps to its own `user_id` | `~/CoworkWorkspaces/users/<user_id>/projects/<slug>/…` — each tenant is isolated. |

Both surfaces speak the same `/v1/*` + SSE contract. The only differences
are the system-prompt "Working context" paragraph (which comes from the
session's `ExecEnv.describe_for_prompt()`) and whether `fs_read("draft.md")`
resolves to a cowork-managed file or a file in the user's chosen folder.

The runtime backend (event bus, connection limiter, session service) is
selected by `[runtime] backend` in `cowork.toml`; today only `"local"`
(single-process asyncio + SQLite) is implemented. `"distributed"` (Redis +
Postgres + multi-worker) is a forward-compatible drop-in — see SPEC §2.9.3.

## Running the desktop app (Tauri)

The desktop app under `packages/cowork-app` bundles an embedded CPython and the
Cowork server, so end users don't need `uv` or Python installed. On launch
the user picks a working directory via **File → Open Folder…** (`Cmd/Ctrl+O`)
and the agent operates on that folder for the session.

### Dev loop (recommended)

Point the Tauri sidecar at the repo's `.venv` instead of rebundling
Python every iteration. One-time setup:

```bash
cp .env.sample .env
# In .env, uncomment and set:
#   COWORK_PYTHON="<repo-abs-path>/.venv/bin/python"
```

The desktop shell reads this file via `dotenvy` at startup **in debug
builds only** (`packages/cowork-app/src-tauri/src/lib.rs`), so release
installers ignore it. Then:

```bash
cd packages/cowork-app
npm install
npm run dev        # launches Tauri dev window; picks COWORK_PYTHON from .env
```

First-run UX: the window opens, you click **File → Open Folder…**
(`Cmd/Ctrl+O`), pick a directory, and the agent operates on it. Path
confinement keeps writes inside the chosen folder. Recent picks are
remembered across reloads.

**If `npm run dev` rebuilds forever**: the `.taurignore` in
`src-tauri/` already excludes `resources/` (bundled Python) from the
file watcher; restart `npm run dev` after first setup so it picks that
up.

### Release build (embedded Python)

```bash
# 1. Download python-build-standalone for your triple and pip-install cowork
#    packages into it. Writes to packages/cowork-app/src-tauri/resources/python/.
uv run python scripts/bundle_python.py --target aarch64-apple-darwin

# 2. Build the installer. Output lands in src-tauri/target/release/bundle/.
cd packages/cowork-app
npm install
npx tauri build
```

If the bundle is corrupted (any 0-byte file under
`resources/python/<triple>/`), the sidecar falls through to
`COWORK_PYTHON` with a clear log; re-run step 1 with `--editable` to
repair.

Supported triples: `aarch64-apple-darwin`, `x86_64-apple-darwin`,
`x86_64-unknown-linux-gnu`, `aarch64-unknown-linux-gnu`, `x86_64-pc-windows-msvc`.

## Release QA

Installers are built by `.github/workflows/release.yml` on `v*` tag push. Before
promoting a draft release to published, run through `scripts/installer_qa.md`
on a clean VM for each OS (macOS arm64, Ubuntu 24.04, Windows 11).

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `COWORK_MODEL_BASE_URL` | `http://localhost:8000/v1` | OpenAI-compatible `/v1/chat/completions` endpoint |
| `COWORK_MODEL_API_KEY` | `env:OPENAI_API_KEY` | API key (or literal `env:VAR` to read from another env var) |
| `COWORK_MODEL_NAME` | *(see config.py)* | Model identifier your endpoint expects |
| `COWORK_WORKSPACE_ROOT` | `~/CoworkWorkspaces` | Where managed projects, sessions, and skills live on disk. Local-dir (desktop) sessions store their bookkeeping under `<workdir>/.cowork/` instead. |

### Example: LM Studio

```bash
export COWORK_MODEL_BASE_URL="http://localhost:1234/v1"
export COWORK_MODEL_API_KEY="lm-studio"
export COWORK_MODEL_NAME="qwen3-8b"
uv run cowork
```

### Example: Ollama

```bash
export COWORK_MODEL_BASE_URL="http://localhost:11434/v1"
export COWORK_MODEL_API_KEY="ollama"
export COWORK_MODEL_NAME="qwen3:8b"
uv run cowork
```

## What's wired

13 tools are registered with the root agent (+ researcher, writer, analyst, reviewer sub-agents that inherit the pool):

| Tool | What it does |
|---|---|
| `fs_read / fs_write / fs_edit` | Read, write, exact-match-replace text files |
| `fs_list / fs_glob / fs_stat` | Directory listing, glob search, file metadata |
| `fs_promote` | Move a draft from session `scratch/` into project `files/` (managed mode) |
| `shell_run` | argv-only subprocess (allowlist-gated, no shell expansion) |
| `python_exec_run` | Run a Python snippet in a sandbox (network off by default) |
| `http_fetch` | GET a URL (scheme + size + redirect caps) |
| `search_web` | DuckDuckGo text search (zero setup, no API key) |
| `email_draft / email_send` | Compose an `.eml` in scratch; SMTP-send with confirm/deny policy |
| `load_skill` | Load a named skill's body into the agent's context |

Path vocabulary depends on the session's `ExecEnv`: managed sessions use the
`scratch/` + `files/` namespaces; local-dir (desktop) sessions use plain
relative paths rooted at the user's chosen folder.

## Feature wire-up status

Every UI affordance introduced by the Phase V visual overhaul, the E3
compaction pipeline, or the Phase F wire-up plan. Rows flip as each
phase lands. `culled` entries were intentionally removed (dupes or
cosmetic variants); `deferred` entries are planned for a later tier.

| Affordance | Surface | Status | Phase |
|---|---|---|---|
| Auto-save stamp | Titlebar | wired | V2 |
| Project / session breadcrumb | Titlebar | wired | V2 |
| Search button (⌘K) | Titlebar | wired (global) | P6 |
| Notification bell | Titlebar | wired (ephemeral) | P5 |
| Notification bell (sessions footer) | Sessions | culled | P1 |
| Status dots (running / done) | Sessions | wired | V3 |
| Status dot (waiting) | Sessions | wired | P2b |
| Agent monogram stack | Sessions | wired | V3 |
| Session search (local) | Sessions | wired | V3 |
| Session search (global, ⌘K) | Sessions | wired (global) | P6 |
| Session meta (N msgs · M files) | Sessions | wired | P3a |
| Session pin / favourite | Sessions | wired | P3b |
| Tree / grid / list toggle | Canvas | wired | V5 |
| Multi-tab preview | Canvas | wired | V5 |
| Rendered / source toggle | Canvas | wired | V5 / V7 |
| File updated dot | Canvas | wired | P2a |
| Approval card (inline) | Chat | wired | V4 |
| Approval card (banner / queue) | Chat | culled | P1 |
| Tool-call style (unified collapsible) | Chat | wired | post-E |
| Composer attach | Chat | wired (ref-path v1) | P4 |
| Composer auto-route pill | Chat | wired (revived) | E2 |
| Composer @-mention | Chat | wired | E2 |
| Compaction separator | Chat | wired | E3 |
| Settings → Appearance (theme / accent) | Settings | wired | V6 / post-E |
| Settings → Appearance → approval style | Settings | culled | P1 |
| Settings → Appearance → refinement | Settings | culled | P1 |
| Settings → Appearance → density / layout | Settings | culled | P4 |
| Settings → Agents & tools (read-only) | Settings | wired | V6 / P1 |
| Settings → Agents enable / disable | Settings | culled | deferred (Tier F) |
| Settings → Per-agent tool allowlist | Settings | wired | E1 |
| Settings → Approvals policy | Settings | wired | V6 |
| Settings → System (health + compaction) | Settings | wired | V6 / E3 |

## Project layout

```
cowork/
  packages/
    cowork-core/    # ADK agents, tools, skills, workspace, config
    cowork-server/  # FastAPI + WebSocket transport
    cowork-cli/     # Typer CLI (developer tool)
    cowork-web/     # React + TypeScript + Tailwind chat UI
    cowork-app/     # Tauri desktop shell (Rust) that embeds Python + UI
  scripts/
    bundle_python.py  # Fetch python-build-standalone + pip-install Cowork
    installer_qa.md   # Manual smoke-test checklist for release installers
  tests/            # pytest unit + smoke tests
```

## Development

```bash
uv sync
uv run ruff check .              # lint
uv run ruff format --check .     # format check
uv run mypy packages             # type check
uv run pytest -q                 # run tests
```

## Documentation

- [Specification](SPEC.md) -- what we're building and why
- [Architecture](ARCHITECTURE.md) -- how the pieces fit together
- [Implementation plan](PLAN.md) -- milestones and sub-tasks
- [Constitution](CONSTITUTION.md) -- project rules
- [File index](INDEX.md) -- every file with a one-liner
- [Changelog](CHANGELOG.md) -- append-only change log

## License

MIT
