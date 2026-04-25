# Memory schema

This file describes how the agent maintains the memory store for
this scope. Edit it to override the defaults; the agent reads it
via `memory_read(scope, "schema.md")` whenever it needs the
conventions.

## On-disk layout

- `schema.md` — this file. User-editable.
- `index.md` — catalog of pages. Agent-maintained.
- `log.md` — chronological event log. Append-only via `memory_log`.
- `pages/<name>.md` — agent-authored pages. Use kebab-case names.
- `raw/` — user-uploaded sources. Read-only from the agent's view.

## Conventions

- One topic per page. Long pages get split.
- `index.md` lists every page exactly once:
  `- [name](pages/name.md) — one-line summary`
- Cross-reference pages via relative links (`[other-page](pages/other-page.md)`).
- Use ISO dates inside pages (`2026-04-25`); the log stamps dates
  for you.

## Workflows

### Ingest

When the user introduces a new source — uploads a file, points at
a long external read, references a paper — file it:

1. Read the source.
2. Compose a 200–500 word summary as a new page or append to the
   most-related existing page.
3. Update `index.md` to reflect any new page.
4. Append to log: `memory_log(scope, "ingest", "<source title>")`.

A single source might touch 5–15 pages (entity pages, concept
pages, the index, the log). That's expected.

### Query

Before answering a question whose answer might already be in this
scope:

1. Read `index.md` to find relevant pages.
2. Read those pages.
3. Synthesize the answer using the page content + new context.
4. If the synthesis surfaces a new insight worth keeping, file it:
   append to the relevant page or create a new one, update the
   index, and `memory_log(scope, "query", "<question>")`.

### Remember

When the user says "remember X":

1. Call `memory_remember(content="X")`. This appends to
   `pages/scratch.md` with a timestamp.
2. On your next turn, decide whether the note belongs in an
   existing page or a new one. Move it accordingly. Clear the
   scratch entry by rewriting `pages/scratch.md` without it.

The default scope is `project` — most "remember X" calls are
project-bound. Pass `scope="user"` for cross-project facts.

### Lint

On request: scan pages for orphans (no inbound link from
`index.md`), contradictions across pages, stale dates, or topics
mentioned in passing that deserve their own page. Report
findings; let the user decide what to fix.

## Scopes

- **user** — cross-project. Things about the user themselves
  (preferences, recurring patterns, long-term goals).
- **project** — this project only. Decisions, constraints,
  domain knowledge, glossary, design notes.

When in doubt: project. Cross-project facts can be promoted later.
