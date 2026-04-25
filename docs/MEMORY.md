# Memory

Cowork agents accumulate domain knowledge in a **markdown wiki**
the LLM maintains itself — pattern after Andrej Karpathy's
[LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
gist. No embeddings, no vector store: just `index.md` + ripgrep at
scale, with a per-store `schema.md` that tells the agent how to
keep the wiki consistent.

This page covers:

- the two scopes (`user` + `project`) and where they live on disk
  / in the database;
- the four agent-callable tools and what they do;
- how the bundled default `schema.md` works (and when to edit it);
- single-user vs multi-user storage shape.

## Scopes

| Scope | Single-user (CLI / desktop) | Multi-user (server) |
|---|---|---|
| **user** — cross-project facts | `~/.config/cowork/memory/` | SQLite `user_state` rows under `<workspace>/multiuser.db`, keyed by `user_id` |
| **project** — per-project knowledge | `<workdir>/.cowork/memory/` | SQLite `project_state` rows, keyed by `(user_id, project)` |

Mode is auto-detected from `cowork.toml`: if `[auth] keys = {...}`
is non-empty, the server is in multi-user mode; otherwise
single-user. The same agent code path works in both — Cowork's
`UserStore` / `ProjectStore` abstractions (Slice S1) hide the
backing.

A session-scope wiki layer was considered and deferred. Sessions
persist their event history natively, and any cross-session
knowledge worth keeping belongs in the project scope (or user
scope for cross-project facts).

## On-disk layout (per scope)

```
<scope_root>/
  schema.md     # conventions; user-editable; bundled default copied on bootstrap
  index.md      # catalog of pages — agent-maintained
  log.md        # append-only event log — `## [YYYY-MM-DD] kind | title`
  pages/        # agent-authored markdown pages (kebab-case names)
  raw/          # user-uploaded sources — agent reads, never modifies
```

The same shape applies in multi-user / SQLite mode — the keys are
`memory/schema.md`, `memory/index.md`, `memory/pages/<name>.md`,
etc., living in the appropriate state table.

## The four agent tools

The agent does the synthesis; the tools are dumb file-I/O
primitives. The schema (loaded on demand) tells the agent when to
call them.

| Tool | What it does |
|---|---|
| `memory_read(scope, name)` | Read `schema.md`, `index.md`, `log.md`, or any `pages/*.md`. Bootstraps the default schema on first call. |
| `memory_write(scope, name, content)` | Create or overwrite a page. Allowed targets: `index.md` and `pages/*.md`. Refuses `schema.md` (user-only), `log.md` (use `memory_log`), `raw/*` (uploads). |
| `memory_log(scope, kind, title, body="")` | Append a dated entry to `log.md`. Server stamps `[YYYY-MM-DD]` so the format stays consistent. `kind` is constrained to `^[a-z][a-z0-9_]{0,31}$`. |
| `memory_remember(content, scope="project")` | Append a timestamped scratch note to `pages/scratch.md`. The agent's *next* turn (per the schema) decides whether to file it into a proper page. |

`memory_remember` defaults to `scope="project"` since most "remember
X" requests are project-bound. Pass `scope="user"` for cross-project
facts.

## The schema

`schema.md` per scope is the system's "AGENTS.md" — a markdown
document that tells the agent how to maintain *this* memory store.
Cowork ships a bundled default (`cowork_core/memory/bundled/default_schema.md`)
that's copied on first use; you edit it freely. The agent reads
it on demand via `memory_read(scope, "schema.md")`.

The default schema describes:

- on-disk layout + conventions (one topic per page, kebab-case
  names, cross-reference via relative links)
- the **ingest** workflow — what to do when a new source enters
  the wiki
- the **query** workflow — read `index.md` first, find related
  pages, synthesize, file insights worth keeping
- the **remember** workflow — `memory_remember` appends to
  scratch; the next turn does proper filing
- the **lint** workflow — orphans, contradictions, stale claims

You and the LLM co-evolve `schema.md` over time as you figure out
what works for your domain. The agent never overwrites
`schema.md` (it's user-only); to update, edit the file directly
or ask the LLM to draft a diff and review it before saving.

## Prompt budget

The root agent's system prompt gets exactly **one line** per turn
when memory is non-empty:

```
Memory: 'user' (12 pages) · 'project' (3 pages). Read `memory_read(scope, "schema.md")` for conventions.
```

When both scopes have zero pages, the line is omitted entirely —
no point cluttering the prompt with a "no memory yet" notice. The
schema content itself never auto-loads; the agent reads it on
demand. This mirrors how skills inject `name + capped description`
in the prompt and load the body via `load_skill` only when needed.

## Workflows

### Ingest

User uploads a source → agent reads it → writes a 200–500 word
summary as a new page (or appends to an existing page) → updates
`index.md` → calls `memory_log(scope, "ingest", "<source title>")`.

A single source might touch 5–15 pages. That's expected.

### Query

Before answering a question that might already be filed, the agent
reads `index.md`, drills into matching pages, synthesises, and (if
the answer surfaces a new insight worth keeping) appends it back
to the wiki + logs the query.

### Lint

Periodic health check — orphan pages (no inbound link from
`index.md`), contradictions across pages, stale dates. The agent
reports findings; the user decides what to fix.

## Single-user filesystem layout (mirrors OpenCode)

User scope at `~/.config/cowork/memory/` matches OpenCode's
`~/.config/opencode/`-shaped global config dir. Project scope
under `<workdir>/.cowork/memory/` matches the same hidden namespace
Cowork already uses for session scratch (so `git status` doesn't
trip on it; add `.cowork/` to `.gitignore` if you want the wiki
out of source control too).

## Multi-user database shape

```sql
CREATE TABLE user_state (
  user_id TEXT NOT NULL,
  key TEXT NOT NULL,         -- e.g. "memory/pages/profile.md"
  value BLOB NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, key)
);

CREATE TABLE project_state (
  user_id TEXT NOT NULL,
  project TEXT NOT NULL,
  key TEXT NOT NULL,
  value BLOB NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, project, key)
);
```

DB lives at `<workspace>/multiuser.db`. Replace SQLite with
Postgres / Turso / etc. by registering a backend in
`cowork_core/storage/factory.py:register_backend(name, builder)` —
no other code changes needed.

## Non-goals (Tier F)

- Embeddings / vector store — `index.md` + ripgrep scales to
  hundreds of pages; vector infra deferred until a real workload
  demands it
- Session-scope wiki — sessions persist their event history;
  cross-session facts live in project scope
- Auto-ingest hook on file upload — the schema instructs the agent
  to ingest after reading new sources; server-side hooks would
  race the model
- Wiki sync between users / machines — git is the answer; the wiki
  is plain markdown
- Per-page YAML frontmatter (Dataview-style) — possible later if
  query patterns need structured filters
