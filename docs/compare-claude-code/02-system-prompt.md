# 02 — System prompt

How the instructions sent with each request are assembled.

## Claude Code

The system prompt is composed at session start from several pieces
and then re-used for every turn (with a cache boundary).

### Assembly pipeline

`src/utils/queryContext.ts:44-74` `fetchSystemPromptParts()` returns
three things in parallel:

```ts
const [defaultSystemPrompt, userContext, systemContext] = await Promise.all([
  customSystemPrompt !== undefined
    ? Promise.resolve([])
    : getSystemPrompt(tools, mainLoopModel, ...),
  getUserContext(),
  customSystemPrompt !== undefined ? Promise.resolve({}) : getSystemContext(),
])
```

`src/QueryEngine.ts:288-325` stitches them with any
memory-mechanics prompt, the `--append-system-prompt` override, and
coordinator context:

```ts
const systemPrompt = asSystemPrompt([
  ...(customPrompt !== undefined ? [customPrompt] : defaultSystemPrompt),
  ...(memoryMechanicsPrompt ? [memoryMechanicsPrompt] : []),
  ...(appendSystemPrompt ? [appendSystemPrompt] : []),
])
```

### Cache boundary

`src/constants/prompts.ts:114-115` defines a literal marker:

```ts
export const SYSTEM_PROMPT_DYNAMIC_BOUNDARY =
  '__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__'
```

Everything before the boundary is global (cacheable across
conversations); everything after is session-specific. `getSystemPrompt`
at `src/constants/prompts.ts:444` injects the boundary once
`shouldUseGlobalCacheScope()` is true (`src/constants/prompts.ts:573`).

### Sections inside the default prompt

`getSystemPrompt` assembles dynamic sections — hooks
(`getHooksSection` near line 127), system reminders
(`getSystemRemindersSection` near line 131), Ant-only model overrides
(`getAntModelOverrideSection` line 136), language preference
(`getLanguageSection` line 142), the built-in tool descriptions, and
the skills/commands catalog.

### User + system context

`src/context.ts` owns the "context" maps (environment, tools, model,
mode, working dir, additional roots, cyber-risk instruction). These
are appended to the prompt via `appendSystemContext` at prompt-use
time, post-boundary, so they don't blow the cache when a session
state changes.

### Shape

```
[cacheable]          [not cacheable]
──────────────── ≪ boundary ≫ ─────────────
default prompt   │  appendSystemContext(
tool catalog     │    user context,
hook rules       │    system context,
skill list       │    mode, cwd, roots
reminders        │  )
language         │
```

## Cowork

One static instruction, dynamically chosen per turn, with skills
appended at build time.

### Base instruction

`packages/cowork-core/src/cowork_core/agents/root_agent.py:30-59`
`ROOT_INSTRUCTION_BASE` is a single triple-quoted string:

```python
ROOT_INSTRUCTION_BASE = """\
You are Cowork, an office-work copilot.

You help the user with documents, spreadsheets, PDFs, research, and drafting.
Be concise and practical. Ask for confirmation before any destructive action.

Working context:
- `scratch/` is the current session's draft directory — work here freely.
- `files/` is the project's durable storage — call `fs_promote` to move a
  draft from scratch into it.

Tool use:
- Use `fs_read` / `fs_write` / `fs_edit` for text files.
- Use `python_exec_run` for programmatic document work (docx, xlsx, pdf, …).
- Use `search_web` + `http_fetch` for research.
- Use `load_skill` to fetch the body of a named skill before doing
  format-specific work.

Sub-agent delegation:
...
"""
```

### Plan-mode addendum

`packages/cowork-core/src/cowork_core/agents/root_agent.py:61-79`
`PLAN_MODE_ADDENDUM` is appended only when the current policy mode
is `plan`:

```python
def _dynamic_instruction(_ctx: ReadonlyContext) -> str:
    if cfg.policy.mode == "plan":
        return base_instruction + PLAN_MODE_ADDENDUM
    return base_instruction
```

The addendum tells the agent it is read-only except for writing
`scratch/plan.md`. See chapter 04 for how the policy actually
enforces this (the prompt alone would not be enough).

### Skills injection

Skills are discovered at runtime assembly and injected as a one-line
bullet list into the base instruction:

`packages/cowork-core/src/cowork_core/agents/root_agent.py:108-110`:

```python
base_instruction = ROOT_INSTRUCTION_BASE
if skills_snippet:
    base_instruction = f"{ROOT_INSTRUCTION_BASE}\n{skills_snippet}\n"
```

`packages/cowork-core/src/cowork_core/skills/loader.py:123-128`
produces the snippet:

```python
def injection_snippet(self) -> str:
    if not self._skills:
        return ""
    lines = [f"- {s.name}: {s.description}" for s in self.all_skills()]
    return "Available skills (call `load_skill(name)` to load):\n" + "\n".join(lines)
```

Skills are scanned in `runner.py:245-247` (bundled → user config).
Per-session project skills are layered on in `runner.py:162-172`
`_build_context`, but those only affect the `SkillRegistry` carried
in `CoworkToolContext` — they don't re-generate the prompt.

### Shape

```
ROOT_INSTRUCTION_BASE
  └ skills_snippet appended
     └ PLAN_MODE_ADDENDUM (only when policy.mode == "plan")
```

The assembled string is passed to `LlmAgent(instruction=…)` as a
callable so ADK resolves it on every turn.

## Gap / takeaway

**Missing in Cowork:**

- *Cache boundary.* The prompt is one blob. If a model client cares
  about prompt-cache granularity (some do), the scaffolding for
  splitting it doesn't exist.
- *User/system context split.* No "environment" or "runtime state"
  section — the prompt has no idea of current working directory,
  attached files, or tool availability beyond the hard-coded list.
- *Hook / reminder / language sections.* All absent. Reminders like
  "don't commit secrets" would need to be added to the base string.
- *Custom system prompt plumbing.* No `--append-system-prompt` or
  `customPrompt` analog. The instruction is literally hard-coded in
  `root_agent.py`.

**Not missing, because the scope is different:**

- A desktop copilot doesn't need to differentiate REPL / coordinator
  / simple modes — there is only one agent surface.
- Per-tool doc strings live in Python docstrings and ADK renders
  them automatically; a separate "tool catalog" section would
  duplicate that.

**Potentially worth adding:**

- An `appendSystemPrompt`-style hook so operators can extend the
  instruction without editing `root_agent.py`.
- Per-session context injection (current project slug, scratch path,
  file count) — these are known at `_build_context` time but never
  reach the prompt.
- A "reminder" section the agent sees every turn, e.g. "respect
  policy mode `<mode>` currently active". The mode is already
  communicated via the addendum only when `plan`; other modes have
  no mention at all.
