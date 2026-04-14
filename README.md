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

The React UI under `packages/cowork-web` talks to the same FastAPI server as the CLI.

```bash
# Terminal 1: start the server (prints COWORK_READY host=... port=... token=...)
uv run python -m cowork_server

# Terminal 2: start Vite. It proxies /v1 to the server on port 8765 by default.
cd packages/cowork-web
npm install
npm run dev
```

Open the printed Vite URL (usually `http://localhost:5173`). On first load the UI
uses the token from `VITE_COWORK_TOKEN` or a `?token=` query param.

## Running the desktop app (Tauri)

The desktop app under `packages/cowork-app` bundles an embedded CPython and the
Cowork server, so end users don't need `uv` or Python installed.

For day-to-day development against the **system** Python (faster iteration):

```bash
cd packages/cowork-app
npm install
npm run dev        # launches Tauri dev window with hot-reload
```

For a **production** build with embedded Python (what release CI does):

```bash
# 1. Download python-build-standalone for your triple and pip-install cowork
#    packages into it. Writes to packages/cowork-app/src-tauri/resources/python/.
uv run python scripts/bundle_python.py --target aarch64-apple-darwin

# 2. Build the installer. Output lands in src-tauri/target/release/bundle/.
cd packages/cowork-app
npm install
npx tauri build
```

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
| `COWORK_WORKSPACE_ROOT` | `~/CoworkWorkspaces` | Where projects, sessions, and skills live on disk |

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

12 tools are registered with the root agent:

| Tool | What it does |
|---|---|
| `fs_read / fs_write / fs_edit` | Read, write, exact-match-replace text files |
| `fs_list / fs_glob / fs_stat` | Directory listing, glob search, file metadata |
| `fs_promote` | Move a draft from session `scratch/` into project `files/` |
| `shell_run` | argv-only subprocess (allowlist-gated, no shell expansion) |
| `python_exec_run` | Run a Python snippet in a sandbox (network off by default) |
| `http_fetch` | GET a URL (scheme + size + redirect caps) |
| `search_web` | DuckDuckGo text search (zero setup, no API key) |
| `load_skill` | Load a named skill's body into the agent's context |

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
- [Implementation plan](PLAN.md) -- milestones and sub-tasks
- [Constitution](CONSTITUTION.md) -- project rules
- [File index](INDEX.md) -- every file with a one-liner
- [Changelog](CHANGELOG.md) -- append-only change log

## License

MIT
