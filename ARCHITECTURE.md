# Cowork — Architecture

One-page map of how the pieces fit together. Seeded in Phase F.P1;
subsequent phases fill in their own paragraphs. For the "why we're
building it" view see [`SPEC.md`](SPEC.md).

## 1. Packages and their boundaries

```
┌─────────────────────────┐
│ cowork-app (Tauri/Rust) │   Desktop shell. Bundles cowork-web +
│                         │   cowork-server + an embedded CPython
└───────┬─────────────────┘   sidecar (python-build-standalone).
        │ bridges ↓
┌───────▼─────────────────┐
│ cowork-web (React/TS)   │   Browser UI. Talks to /v1 over SSE
│                         │   for events, REST for everything else.
└───────┬─────────────────┘
        │ HTTP/SSE/WS ↓
┌───────▼─────────────────┐
│ cowork-server (FastAPI) │   Stateless-ish HTTP surface. Owns the
│                         │   event bus, session service, and the
│                         │   per-turn runner task lifecycle.
└───────┬─────────────────┘
        │ calls ↓
┌───────▼─────────────────┐
│ cowork-core (Python)    │   Agents, tools, skills, workspace,
│                         │   approvals, notifications (F.P5),
│                         │   compaction config. Built on Google ADK.
└───────┬─────────────────┘
        │ wraps ↓
┌───────▼─────────────────┐
│ Google ADK              │   App, Runner, SessionService, Event,
│                         │   LlmAgent, Tool, compaction pipeline.
└─────────────────────────┘
```

Layer rule: each layer only reaches **down**. UI never imports core;
server never imports UI; core never imports ADK plumbing it doesn't
need. Cross-cutting concerns (approvals, notifications) live beside
the core, not inside it.

## 2. UI panes and the `/v1` routes each calls

The web UI has four functional regions. Each owns a narrow slice of
`/v1`.

| Pane | What it does | Routes it calls |
|---|---|---|
| **Titlebar** | Brand, breadcrumb, policy + python-exec dropdowns, settings/search/bell icons | `GET /v1/sessions/{id}/policy/mode`, `PUT /v1/sessions/{id}/policy/mode`, `GET /v1/sessions/{id}/policy/python_exec`, `PUT /v1/sessions/{id}/policy/python_exec`, `GET /v1/notifications`, `POST /v1/notifications/{id}/read`, `DELETE /v1/notifications`, `GET /v1/search` |
| **Sessions** | Project grouping, session list + stats, session create / resume / delete, pin / unpin | `GET /v1/projects`, `POST /v1/projects`, `DELETE /v1/projects/{slug}`, `GET /v1/projects/{slug}/sessions`, `POST /v1/sessions`, `POST /v1/sessions/{id}/resume`, `DELETE /v1/projects/{slug}/sessions/{id}`, `PATCH /v1/projects/{slug}/sessions/{id}`, `GET /v1/local-sessions`, `DELETE /v1/local-sessions/{id}`, `PATCH /v1/local-sessions/{id}` |
| **Chat** | Messages + tool calls (unified collapsible card; shellish tools get a terminal-framed body, everything else uses the typed widget renderer) + approvals + composer | `POST /v1/sessions/{id}/messages`, `GET /v1/sessions/{id}/history`, `GET /v1/sessions/{id}/events/stream` (SSE), `POST /v1/sessions/{id}/approvals`, `GET /v1/sessions/{id}/approvals`, `POST /v1/projects/{slug}/upload` (F.P4 attach) |
| **Canvas** | File tree / preview, multi-tab, rendered / source toggle | `GET /v1/projects/{slug}/files/{path}`, `GET /v1/projects/{slug}/preview/{path}` (+ `?raw=1`), `GET /v1/local-files`, `GET /v1/local-files/content` |

Settings reads `GET /v1/health` for its read-only System /
Agents-and-tools panes. The health payload carries the active LLM
model identifier (`cfg.model.model` from `cowork.toml`) under the
`model` field so the Settings → System pane can surface what the
agent is running against without a separate route.

The same pane → routes mapping is auto-published as an OpenAPI
schema at `/openapi.json` (Swagger UI at `/docs`, ReDoc at
`/redoc`). Routes are tagged into the ten groups above; auth uses
an `x-cowork-token` header advertised as the `cowork-token`
security scheme so Swagger's Authorize button unlocks "Try it
out". Request and response shapes are declared as Pydantic models
in `cowork_server/api_models.py` and mirrored on the client side
in `cowork-web/src/transport/types.ts` — kept in sync by hand for
now; auto-generated TS codegen from the OpenAPI schema is a future
step. WebSocket routes don't appear in the OpenAPI schema (the
spec doesn't model them); SSE / WS frame shapes are documented in
§4 (`_run_turn` lifecycle) instead.

**Transport typing.** The web client (`transport/client.ts`) talks
to `/v1` through a small `CoworkClient` whose methods return named
types from `transport/types.ts` — every response shape has a
declared interface (`SessionListItem`, `HealthInfo`,
`UploadFileResult`, `SearchResults`, `ToolApprovalResult`,
`LocalFileListResult`, `LocalFileReadResult`,
`LocalSessionListItem`). Policy-related methods return literal
unions (`PolicyMode = "plan" | "work" | "auto"`,
`PythonExecPolicy = "confirm" | "allow" | "deny"`) rather than
bare `string`, so a typo at the call site is a build error. Auth
headers are split into two helpers: `jsonHeaders()` for JSON
bodies and `authHeaders()` for DELETE + `FormData` uploads where
the browser sets `Content-Type` itself. SSE URL construction is
centralised in a `sessionStreamUrl(sessionId)` helper shared by
`connectStream` (primary session) and `subscribeBackground`
(auxiliary listeners for sessions whose turn is running while the
user is looking elsewhere).

## 3. `CoworkRuntime` — the seam between server and ADK

`cowork_core/runner.py::CoworkRuntime` is the one object both the
HTTP server and the CLI hand off work to. It owns:

- `config: CoworkConfig` — the parsed `cowork.toml`.
- `workspace: Workspace` + `registry: ProjectRegistry` — on-disk
  layout of projects / sessions / files.
- `skills: SkillRegistry` + `tools: ToolRegistry` — tool catalog.
- `approvals: ApprovalStore` — per-tool approval counters
  (side-channel; see §5).
- `approval_log: InMemoryApprovalEventLog` — queue of approval
  envelopes waiting to be promoted into ADK session events (see §5).
- `notifications: NotificationStore` — *added in Phase F.P5*.
- `runner: google.adk.runners.Runner` — configured with an `App`
  (when compaction is enabled) or `app_name + agent` (when not).

Compaction: when `cfg.compaction.enabled` is true, `Runner` is built
from an `App` with `events_compaction_config=EventsCompactionConfig(…)
` + `LlmEventSummarizer`. ADK runs sliding-window compaction at the
end of every invocation and token-threshold compaction inline when
the prompt size crosses the configured threshold. See
`google.adk.apps.EventsCompactionConfig` and the Phase E3 plan
entries.

## 4. `_run_turn` lifecycle and the bus

Every user message hits `POST /v1/sessions/{id}/messages`, which
fires an async `_run_turn` task and returns `202` immediately. The
task:

1. **Flushes pending approvals** — drains `approval_log` and
   `session_service.append_event`s each approval envelope into the
   session. This is the only race-free window for HTTP handlers to
   mutate session events (see §5).
2. **Runs ADK** — `runner.run_async(user_id, session_id, new_message)`
   yields `Event`s (model calls, tool calls, function responses,
   compaction events). Each event is published verbatim on the event
   bus.
3. **Falls-through sentinel** — if the last ADK event wasn't a
   `turn_complete`, publish one (server-authored) so SSE clients
   finalise the turn. Error events synthesise an `INTERNAL` error +
   turn_complete.
4. **Produces notifications** — each event is inspected (via
   `_notify_from_event`) for `confirmation_required` tool responses,
   `turn_complete`, and `error_code`. Matches are pushed into the
   per-user `NotificationStore` so the Titlebar bell lights up even
   when the user is looking at a different session. Producers write
   only to the store and the bus — never to session state.

```
POST /messages ─► asyncio.create_task(_run_turn)
                                    │
                                    ▼
                        _flush_pending_approvals  ◄── approval_log
                                    │
                                    ▼
                        runner.run_async ─► events ─► bus.publish
                                                          │
                                                          ▼
                                       ┌────────────── bus queue ──────────────┐
                                       ▼                                         ▼
                                SSE /events/stream                        WS /events
```

The bus is an `InMemoryEventBus` keyed by session id. SSE / WS just
drain the queue and stream JSON frames. History fetch
(`GET /v1/sessions/{id}/history`) reads the stored events directly
from `session_service`.

## 5. Side-channel stores — approvals, notifications

**Why they exist**: `InMemorySessionService` uses optimistic
concurrency control against `session.last_update_time`. Any HTTP
handler that fetches a session handle and calls `append_event`
competes with the runner's own internal appends during a turn. We
hit this exact race in early approval work and the fix was to stop
writing to session state from HTTP handlers entirely. That's
documented in `cowork_core/approvals.py:11–22`; every new
side-channel follows the same rule.

Current side-channel stores:

| Store | File | Rule |
|---|---|---|
| `ApprovalStore` | `cowork_core/approvals.py` | Process-local counter. HTTP handler increments, tool's permission callback consumes. Never touched inside a turn. |
| `InMemoryApprovalEventLog` | same file | Buffer of approval envelopes. Drained into session events by `_run_turn` *before* `runner.run_async` starts, so the write happens when no runner is active. |
| `NotificationStore` (F.P5) | `cowork_core/notifications.py` | Per-user ephemeral list of turn-complete / approval-needed / error events. Never promoted into session events; served directly via `/v1/notifications`. |

Rule of thumb: **if new state might need to be written from an HTTP
handler, it belongs in a side-channel store, not in
`session_service`.** Read `approvals.py:11–22` before adding one.

## 6. File surfaces — managed vs local-dir

Two `ExecEnv` implementations select the agent's filesystem view:

- **`ManagedExecEnv`** (`cowork_core/execenv/managed.py`) — classic
  cowork layout. Agent sees `scratch/` + `files/` namespaces bound
  to a Project + Session. `agent_cwd()` returns `session.scratch_dir`
  so shell / python snippets stay sandboxed.
- **`LocalDirExecEnv`** (`cowork_core/execenv/localdir.py`) — desktop
  surface. Agent operates on the user-picked workdir; paths are
  plain relative. Scratch lives in `<workdir>/.cowork/sessions/<id>/`.
  `agent_cwd()` returns the resolved workdir so `open("data.csv")`
  matches what the user actually sees.

Tools that spawn subprocesses (`shell_run`, `python_exec_run`) always
call `ctx.env.agent_cwd()` instead of `scratch_dir()` directly. This
is the one file-surface rule any new process-spawning tool must
follow.

**`session.toml` metadata.** `Session` carries a small metadata record
persisted in `session.toml` (id, title, created_at, `pinned`).
Writes are full-file rewrites guarded by `_session_toml_lock` (a
process-local `threading.Lock`) so concurrent PATCHes don't race.
Managed mode writes the TOML at session creation; local-dir mode
lazily creates it the first time `set_local_session_pinned` fires,
which keeps fresh local sessions free of boilerplate.

## 7. Client-side status derivations

*Added in Phase F.P2.* Some UI signals are derived from per-session
state already owned by `useChat`, not from dedicated server fields:

- `waitingIds: Set<string>` — union over the active session's
  `messages` state and every entry in `sessionCacheRef`. A session is
  "waiting" when it has an unresolved `confirmation_required` tool
  call and isn't in `sendingIds`. Rendered as the yellow `.dot
  .waiting` on the Sessions row.
- File "updated" dot — `Canvas` compares each entry's
  `modified` mtime (unix epoch seconds) against a
  `cowork:fileseen:<CanvasFile.id>` localStorage entry managed by
  `fileSeenStore.ts`. The `CanvasFile.id` already encodes scope
  (`m:<project>:<path>` or `local:<workdir>:<path>`) so the key
  naturally isolates per-project and per-workdir state. Marking
  seen happens on `openFile` and on tab-activation click.
- Auto-save stamp — `lastEventAt` in `useChat` is bumped on every
  event; the Titlebar renders "auto-saved Ns ago" relative to it.

These derivations live in the client because the underlying data is
already there; adding a server field would just duplicate state.

## 8. Composer attachments — ref-path v1

*Added in Phase F.P4.* When the user attaches files in the composer,
the client uploads them through the **existing** file plumbing and
injects a reference into the outgoing message body — the
`/v1/sessions/{id}/messages` route is unchanged.

- **Managed mode.** Each picked file is POSTed to
  `/v1/projects/{slug}/upload?prefix=files` (same endpoint native
  file-drop already uses). The response's relative path (e.g.
  `files/notes.md`) is kept in the composer's `attached[]` state.
- **Local-dir mode.** The Tauri `pick_files` command returns
  absolute source paths; `copy_into_workdir` places each file next to
  the agent's view. The destination absolute path is what `attached[]`
  records.
- **Send.** `submit()` prepends
  `Attached files:\n- @<path>\n...\n\n` to the user's typed body,
  clears the chips, and hands off to the normal `onSend`. The root
  agent resolves each `@<path>` through `fs_read` via its usual
  reasoning — no new tool, no new message part type, no ADK `Content`
  construction.

Bytes never pass through the ADK session or the approval pipeline;
the upload/copy is finished before the message is dispatched, so a
failed attach stays local to the composer and doesn't partially
commit session state.

Multimodal inline bytes (images, PDFs as `Part`s) is a follow-up —
v1 stops at the ref-path contract.

## 9. ⌘K command palette

*Added in Phase F.P6.* The palette is split into two tiers so the
common case is instant and the cross-session search stays cheap.

**P6a — client-only (instant).** `CommandPalette.tsx` filters two
local sources: the active session's `messages` (already in `useChat`
state — narration text, segment text, tool names, tool arg strings)
and the current scope's top-level file listing fetched on open via
`listFiles` / `listLocalFiles`. No server round-trip; matches appear
as the user types.

**P6b — server-backed (global, naive).** `GET /v1/search?q=` scans
the user's projects for three sections: `sessions` (title
substring), `files` (within each project's `files/` artifact dir —
`scratch/` and `sessions/` are runtime bookkeeping and excluded),
and `messages` (event-text substring, bounded to the 15 most-recent
sessions per project because full event-list reads are the only
expensive operation). Each section is capped at 50 hits; results
are cached per `(user_id, q.lower())` for 30 seconds to absorb a
debounced typing burst. The cache is a plain dict cleared at 128
entries — not an LRU, since active queries are counted in dozens
not thousands.

Results are scoped per authenticated user. In multi-user mode
`registry_for(user.user_id)` already segments projects by user; the
search inherits that isolation and a regression test in
`test_search.py::test_search_scope_limited_to_user` pins it down.

Selection handlers live in `App.tsx`:

- **Current-session message** → scroll `[data-msg-index=i]` into view
  with a brief flash.
- **Current-scope file** → dispatch `cowork:palette-open-file` which
  the Canvas pane listens for and opens as a new tab.
- **Other session** → resume the session (switching project first if
  needed in managed mode).
- **Other project file** → switch project, then dispatch the same
  open-file event.
- **Cross-session message** → resume + retry the scroll until the
  row lands (capped at 20 attempts / ~2 s).

## 10. User-directed agent routing

### Per-agent tool allowlist (Tier E.E1)

Each sub-agent — researcher, writer, analyst, reviewer — can be
restricted to a subset of the tool catalog for the session. Data
lives in ADK state at `cowork.tool_allowlist`
(`dict[str, list[str]]` — agent name → allowed tool names); absent
agent = unrestricted, empty list = silenced, empty dict = no
restrictions anywhere.

Enforcement happens in a **per-agent closure**, not in the shared
permission callback. `make_allowlist_callback(agent_name)` in
`policy/permissions.py` returns a `before_tool_callback` that
captures `agent_name` at build time. `build_root_agent` attaches
the matching closure to each sub-agent's callback list as the
*first* gate, ahead of the existing permission callback. Closure
over the agent name avoids reaching into ADK's private
`InvocationContext.agent` attribute — the public `ToolContext`
doesn't expose "which agent am I guarding", and coupling to a
private attribute would be fragile across ADK upgrades.

The **root agent is unrestricted by design.** The allowlist scopes
specialist sub-agents; users who need to block a capability
everywhere should use the existing policy layer
(`python_exec = "deny"`, `email_send = "deny"`). Settings surfaces
this boundary in the Agents pane copy.

Why state-backed rather than a callback with captured state: the
allowlist needs to change *during* a session without rebuilding
the agent (which would cost an interpreter-level restart of the
runner). State reads inside the callback are cheap and ADK's
`session_service.append_event` handles the write OCC-safely
(called from the HTTP PUT handler when no runner is active for
the session).

### `@`-mentions and auto-route (Tier E.E2)

User types `@researcher gather sources on X`; researcher (not root)
responds. The mechanism is **prompt-level**, not a manual routing
tool: `AT_MENTION_PROTOCOL` in `cowork_core/agents/root_agent.py`
is a paragraph inserted into the root's dynamic instruction that
tells it to transfer on a leading `@<agent_name>`. ADK's existing
`sub_agents=[...]` delegation handles the actual hand-off — the
root already has the machinery; the protocol just tells it when
to use it.

Two reasons for going prompt-level over a bespoke
`transfer_to_agent` tool or a client-side parse-and-redispatch:

1. **No fight with ADK.** The runner is built around the root
   agent; replacing it per-turn (path B in the plan) either
   requires a per-agent Runner or a Runner override, both fragile
   across ADK versions. The prompt directive threads the needle
   without touching Runner at all.
2. **Determinism is earnable later.** If QA shows the model
   ignoring the directive, the targeted hardening is server-side
   message rewriting (strip `@name` from the user message, then
   `session_service.append_event` the rewritten turn) — not a
   framework-level restructure. Upgrading to that is cheap; living
   with a framework restructure is not.

The `cowork.auto_route` state key (bool, default True) gates the
paragraph. A per-session composer chip toggles it via the same
PUT/GET route pattern as `python_exec` and `tool_allowlist`; when
off, the directive is omitted and the root handles `@`-text as
plain input. This is the escape hatch — ship the default on, flip
off per session if the routing misbehaves, no code change needed.

Client support: the composer shows an `@`-triggered autocomplete
popover (keyboard: ↑/↓ navigate, Enter/Tab pick, Escape dismiss)
listing the four sub-agents. The autocomplete is purely
client-side; the typed `@name` arrives at the server as part of
the user's message body and the root reads it from there. No
new routes are needed for the autocomplete itself — only the
auto-route toggle has a server-side representation.
