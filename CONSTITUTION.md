# Cowork Constitution

The non-negotiable rules for this project. If a PR violates one of these, it is rejected regardless of how good the change looks.

---

## 1. Source-of-truth documents

| File | Role |
|---|---|
| `SPEC.md` | What we are building and why. Change means scope change. |
| `PLAN.md` | How and in what order. Change means schedule change. |
| `CONSTITUTION.md` | The rules themselves. Change only by deliberate amendment. |
| `INDEX.md` | Live manifest of every file in `cowork/` with a one-liner and core symbol. |
| `CHANGELOG.md` | Append-only log of concise change statements. |

`INDEX.md` and `CHANGELOG.md` are load-bearing: a PR that touches files without updating them is incomplete.

## 2. Bookkeeping rules (the core of this constitution)

1. **Every file create / update / delete updates `INDEX.md` in the same change.** One line per file: `` `path` — one-liner description — `CoreClassOrFunction` ``.
2. **Every change appends one concise line to `CHANGELOG.md`** under today's date. Format: `- <verb> <path> — <why>`. Verbs: `add`, `update`, `remove`, `rename`, `move`.
3. Both files live at `cowork/` root. They are never rewritten historically — only appended to (changelog) or edited in place (index).
4. `INDEX.md` is sorted by path; group by top-level dir for readability.
5. If a file has no meaningful "core symbol" (e.g. config, docs), put `—` in that column.

## 3. Architecture invariants (from `SPEC.md` §2.3, §2.10)

1. **One concept per file.** A new tool = one new `.py` + one registry line.
2. **Layer direction is one-way**: `surfaces → transport → core`. Core never imports surfaces.
3. **Public surface of each package ≤ 20 exported symbols.** Anything else stays private (`_name`).
4. **No implicit global state.** State lives in ADK `Session` or the `Workspace` object.
5. **No cross-platform shell strings.** `shell.run` takes `argv: list[str]` only; OS dispatch happens in exactly one file.
6. **No hardcoded path separators.** `pathlib` always. No symlinks in the workspace contract.
7. **No vendor-specific model code in core.** The OpenAI-compatible adapter is the only model boundary.

## 4. Quality rules

1. Every tool has: docstring, pydantic arg schema, example, unit test.
2. `ruff check`, `ruff format --check`, `mypy --strict`, and `pytest` must pass before merge.
3. CI runs on `windows-latest`, `macos-latest`, `ubuntu-latest`. A change that passes two OSes but fails one is not merged.
4. No comments that describe *what* code does. Only *why*, and only when non-obvious.
5. No speculative abstractions. Three similar lines beat a premature base class.

## 5. Process rules

1. One PR = one milestone sub-task from `PLAN.md`. Bigger PRs get split.
2. If reality diverges from `SPEC.md` or `PLAN.md`, update the document in the same PR that diverges. No silent drift.
3. Decisions recorded in memory (`~/.claude/projects/.../memory/`) supersede older memories; update, do not stack.
4. Destructive ops (`rm`, `git reset --hard`, force-push) require explicit human approval every time, never implicit.
5. **Third-party content licensing.** Any file committed to `cowork/` — code, skill, prompt, asset — must be either (a) authored by the project and licensed MIT, or (b) copied under a permissive, redistributable license (MIT/Apache-2.0/BSD/CC0) with the license header preserved. Proprietary-licensed material (including Anthropic's [`anthropics/skills`](https://github.com/anthropics/skills), whose `LICENSE.txt` forbids extraction, redistribution, and derivative works) must **not** be committed, bundled in installers, downloaded on the user's behalf, or ported into Cowork-owned code. Users who want such material install it themselves into their own workspace, under their own agreements.

## 6. Amendment

This file is amended by a PR that edits it and updates `CHANGELOG.md` with `- update CONSTITUTION.md — <reason>`. Amendments must cite which rule is changing and why.
