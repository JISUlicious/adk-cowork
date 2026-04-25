# MCP servers

The **Model Context Protocol** ([modelcontextprotocol.io](https://modelcontextprotocol.io))
lets external programs expose tools to an LLM. Cowork adds those
tools to the agent's catalog at startup, so anything you reach via
MCP — a filesystem, a GitHub repo, a memory store, an internal API
— shows up alongside Cowork's built-in `fs_read` / `shell_run` /
`python_exec_run` / etc.

This page covers:

- the three transports Cowork supports;
- how to add a server through Settings or by editing
  `<workspace>/global/mcp/servers.json` directly;
- three worked examples using the official Anthropic MCP servers;
- the restart-only reload contract and how to recover from a
  misconfigured server.

## Transports

Cowork dispatches on `transport`:

| Transport | When to use | Connection fields |
|---|---|---|
| `stdio` | Local subprocess. Most community servers (npx, uvx, native binary). Network-isolated. | `command`, `args`, `env` |
| `sse` | Remote HTTP server using Server-Sent Events. Older protocol. | `url`, `headers` |
| `http` | Remote streamable-HTTP server (the current MCP spec). | `url`, `headers` |

For local development the answer is almost always `stdio` — the
server runs as a child process and Cowork talks to it on stdin /
stdout, so there's no network surface to authenticate or expose.

## Add a server through Settings

Open **Settings → Agents → MCP servers** and click **+ add server**.
The form takes:

- **Name** — alphanumeric, `_` and `-` allowed, ≤64 chars. Must
  not collide with a bundled server declared in `cowork.toml`.
- **Transport** — `stdio` / `sse` / `http`.
- **Command + args + env** (stdio) or **URL + headers** (sse / http).
- **Description** — surfaced in the row.

Saving runs a **dry-run probe**: Cowork connects, lists the tools
the server advertises, disconnects, then writes the entry to
`<workspace>/global/mcp/servers.json`. The discovered tool list
comes back so you can see what the agent will gain. The change
does **not** take effect until you click **↻ restart** — restart
tears down the current toolsets, rebuilds from the merged config,
and replaces the runner in place. **In-flight turns terminate**
when restart fires, so the button confirms first.

## Add a server by editing `servers.json`

Equivalent to the form. The file is a flat object keyed by name:

```json
{
  "fs": {
    "transport": "stdio",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/me/notes"],
    "env": {},
    "description": "Local notes folder"
  }
}
```

Edit, save, then call `POST /v1/mcp/restart` (Settings → MCP
servers → ↻ restart). Bundled servers (those in `cowork.toml`)
are not represented here; the runtime merges both sources at
startup with user entries winning on name collision.

## Worked examples

All three are official Anthropic-maintained servers from
[github.com/modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers).
They run via `npx` so you need `node` ≥ 18 and `npm` on `PATH`.
(Tauri desktop builds without Node can substitute Python servers
via `uvx`; the shape is identical.)

### 1. Filesystem

Read + write a directory tree. Useful when Cowork's own
`fs_read` / `fs_write` aren't enough — e.g. you want the agent to
work outside the project sandbox.

```json
{
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
  "description": "Filesystem MCP server (read/write under /path/to/dir)"
}
```

The first positional arg after the package name is the root
directory. Pass multiple to expose several roots.

### 2. GitHub

Search repos, list issues, read PRs, post comments — all gated
by a personal access token.

```json
{
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "env:GITHUB_TOKEN" },
  "description": "GitHub API"
}
```

The `env:GITHUB_TOKEN` form tells Cowork to read `GITHUB_TOKEN`
from the **server's** environment at startup — the literal
token never lands in `servers.json`. Plain `"value"` works too
if you accept the file storing the secret.

### 3. Memory

A simple key-value store the agent can write to and read back.
Useful for cross-turn memory inside a single session.

```json
{
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-memory"],
  "description": "Persistent key-value memory"
}
```

## Restricting which tools the agent sees

A server may expose more tools than you want available. Set
`tool_filter` to an explicit allowlist:

```json
{
  "transport": "stdio",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path"],
  "tool_filter": ["read_file", "list_directory"],
  "description": "Read-only access"
}
```

`null` or absent = all tools. The Settings add-form does not yet
expose this field; edit `servers.json` and restart for now.

Per-session gating (disable a server entirely without removing
it) is tracked under Slice VI of the production-hardening plan.

## Status surface

`/v1/health.mcp` returns one entry per configured server:

```json
{
  "name": "fs",
  "status": "ok",
  "last_error": null,
  "tool_count": 12,
  "transport": "stdio"
}
```

Settings → System renders green/red counts here; Settings →
Agents → MCP servers renders per-row badges. `last_error` shows
in a hover tooltip when `status: "error"` — common causes are a
missing `command` / `url`, a wrong path argument, an expired
auth token, or the server crashing on start.

## Recovering from a broken server

A server with a typo'd command or a bad token won't crash
Cowork — `build_mcp_toolset` returns `(None, error)` and the
runtime records the failure. The agent simply doesn't get those
tools. Fix the entry in `servers.json` (or delete it via Settings)
and restart MCP. If a restart itself misbehaves, restart the
Cowork server process — `servers.json` survives, and the next
boot rebuilds from the same config.

## Non-goals (Tier F)

- A bundled Cowork-specific MCP server. Use the community
  ecosystem above instead — that keeps Cowork's surface
  recognisable to anyone who has used Claude Code.
- OS-keychain credential vault. Use `env:VAR` / shell
  environment for secrets.
- Hot-swap without restart. ADK's `Runner` owns the toolset
  lifecycle; mid-call mutation isn't safe.
- Auto-upgrade and version pinning of MCP server packages. `npx
  -y <pkg>@<version>` if you need to pin.
