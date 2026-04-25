# Writing a skill

A **skill** is a folder the agent loads on demand. Cowork follows
Anthropic's public `SKILL.md` frontmatter format, so a skill
written for Claude Code installs cleanly here, and skills you
write for Cowork should round-trip the other way.

## On-disk layout

```
my-skill/
├─ SKILL.md             # required — frontmatter + body markdown
├─ scripts/             # optional — reusable .py helpers
└─ assets/              # optional — templates, reference tables
```

## Frontmatter

```yaml
---
name: my-skill
description: "Use when the user wants to do X. Mention triggers, inputs, and output format."
license: MIT
version: 0.1.0           # optional, defaults to "0.0.0"
triggers:                # optional, defaults to []
  - keyword-one
  - keyword-two
---
```

| Field         | Required | Notes                                                                                       |
| ------------- | -------- | ------------------------------------------------------------------------------------------- |
| `name`        | yes      | Must match the parent directory. Validated at install (`[A-Za-z0-9][A-Za-z0-9_-]{0,63}`).   |
| `description` | yes      | First line the agent sees in its prompt registry — make it action-oriented.                 |
| `license`     | no       | Free-form string. Defaults to `"unspecified"`. Use `MIT` for community contributions.       |
| `version`     | no       | Free-form string (semver recommended).                                                      |
| `triggers`    | no       | Hints surfaced to the user; the agent does its own retrieval.                               |

Cowork rejects frontmatter values containing control characters
(below `0x20`, except tab) as a prompt-injection guard.

## Body

Everything after the closing `---` fence is markdown. The agent
calls `load_skill("my-skill")` to pull the body — keep it short,
action-oriented, and code-heavy. Common shape:

1. One-paragraph "what this skill does and when to call it."
2. Two or three runnable code snippets (Python, shell — the agent
   pastes them into `python_exec_run` or `shell_run`).
3. A "Notes" or "Reusable helpers" section pointing at any
   `scripts/` files.

## `scripts/` and `assets/`

Optional sub-directories. The skill body should mention them
explicitly so the agent knows they exist (it sees them via
`load_skill(...)["scripts"]` / `["assets"]`). Two patterns:

- **Inline-paste pattern.** The script is a reference
  implementation; the agent reads it via `fs_read` and pastes its
  contents into a `python_exec_run` call. The python sandbox
  can't import from outside `scratch/`, so direct `import` of a
  script in `<workspace>/global/skills/...` is not supported.
- **Asset reference pattern.** A template file (e.g. a docx with
  branding) the agent copies into `scratch/` and edits.

The bundled `plot/scripts/quick_chart.py` and
`xlsx-basic/scripts/table_io.py` skills demonstrate the inline-
paste pattern.

## Installing your skill

Three options once the folder is laid out:

1. **Drop it into `<workspace>/global/skills/`.** Picked up on
   the next runtime start; replaces a same-named user skill.
2. **Zip the folder and upload via Settings → Skills → "+ install
   (.zip)".** The server validates frontmatter, rejects path
   traversal, refuses to shadow a bundled skill, and extracts
   atomically.
3. **Validate before installing.** `POST /v1/skills/validate`
   (try it from `/docs`) runs the same pipeline as install
   without touching `<workspace>/global/skills/`. Fast feedback
   loop while iterating on a new skill.

The zip must contain exactly one top-level directory whose name
matches the frontmatter `name`. The validator caps archive size
(5 MB), extracted size (10 MB total), and entry count (200) as
zip-bomb / DoS guards.

## Uninstalling

User-installed skills get a `×` button in Settings → Skills.
Bundled skills are immutable (locked icon). Uninstall removes
the folder under `<workspace>/global/skills/<name>/`; the next
turn's prompt registry no longer mentions it.

## Per-session enable / disable

(Coming in Slice II.) Settings → Skills will gain a per-row toggle
for the active session, so a user can hide a skill from the prompt
registry without uninstalling it. `load_skill` will refuse disabled
names with a clear error.

## Compatibility with Claude Code

Cowork's required frontmatter (`name`, `description`) matches the
Anthropic public spec. Cowork-only optional fields (`version`,
`triggers`, `content_hash` — the last is computed, not authored)
are ignored by Claude Code's parser. Nothing in this guide
introduces a divergence; a skill works in both products as long
as you stick to the on-disk layout above.

## Troubleshooting

- **Install returns 400 with "frontmatter name does not match
  archive directory."** Rename either the directory or the
  `name:` field so they match.
- **`load_skill` returns `{error}` after install.** The skill
  was rejected by the registry scan. Check `/v1/health.skills`
  (Swagger UI → `health` tag) — only successfully-parsed skills
  appear; the failed one will be missing.
- **The agent isn't using your skill.** Make sure the
  `description` is a clear "use when ..." sentence — that one
  line is everything the agent sees during routing.
