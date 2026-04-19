# 04 — Policies and permissions

How tool execution is gated before the model's side effects hit the
filesystem or network.

## Claude Code

A rule engine plus a sandbox adapter. The policy decision is
recomputed per tool call from rules merged out of multiple sources.

### Context object

`src/Tool.ts:123-138` defines the immutable context the rule engine
operates on:

```ts
export type ToolPermissionContext = DeepImmutable<{
  mode: PermissionMode           // 'default' | 'plan' | 'auto' | 'bypassPermissions'
  additionalWorkingDirectories: Map<string, AdditionalWorkingDirectory>
  alwaysAllowRules: ToolPermissionRulesBySource
  alwaysDenyRules: ToolPermissionRulesBySource
  alwaysAskRules: ToolPermissionRulesBySource
  isBypassPermissionsModeAvailable: boolean
  isAutoModeAvailable?: boolean
  strippedDangerousRules?: ToolPermissionRulesBySource
  shouldAvoidPermissionPrompts?: boolean
  awaitAutomatedChecksBeforeDialog?: boolean
  prePlanMode?: PermissionMode
}>
```

### Modes

- **default** — prompts on sensitive operations.
- **plan** — denies shell writes and file edits, allows reads only.
- **auto** — auto-approves after classifier passes.
- **bypassPermissions** — explicit user opt-in; all allow.

### Rule engine

`src/utils/permissions/permissions.ts` evaluates rules in source
priority order: CLI args > session > managed > project > user >
policy. For each tool call it produces `allow | deny | ask` plus a
reason.

Extra decision gates layered on top:

- **Denial tracking** — repeated denials flip to ask.
- **Classifier** — ML classifier for bash commands that would
  otherwise ask; can fail-closed or defer.
- **Hook-driven approval** — `executePermissionRequestHooks` lets
  external hooks return `{decision: 'allow'|'deny'|'ask'}` and
  optionally rewrite args.

### Sandbox adapter

`src/utils/sandbox/sandbox-adapter.ts` translates the rule state
into a real sandbox policy via `@anthropic-ai/sandbox-runtime`:

- `WebFetch(domain:...)` → network allow/deny
- `Read(path)` / `Edit(path)` patterns → filesystem policy
- Writes to `.claude/skills` and managed settings are explicitly
  blocked (they are code-execution surfaces).

### Bash-specific policy

`src/tools/BashTool/shouldUseSandbox.ts` decides per-command whether
to run sandboxed. Global enablement, explicit unsandboxed overrides,
and excluded command patterns all contribute.

### Ask-flow

When `ask` wins, the UI shows a permission dialog; the user's choice
is recorded as an `alwaysAllowRules` entry at the chosen scope
(session / project / managed), which affects future calls.

## Cowork

A hand-rolled switch on mode, plus a shell allowlist. No rule
engine.

### Config

`packages/cowork-core/src/cowork_core/config.py:47-50`:

```python
class PolicyConfig(BaseModel):
    mode: Literal["plan", "work", "auto"] = "work"
    shell_allowlist: list[str] = Field(default_factory=lambda: ["git", "python"])
    email_send: Literal["confirm", "deny"] = "confirm"
```

### Modes

| Mode   | File reads | File writes          | Shell        | Email       | Python      |
| ------ | ---------- | -------------------- | ------------ | ----------- | ----------- |
| plan   | yes        | `scratch/plan.md` only | no           | no          | no          |
| work   | yes        | yes                  | allowlist    | confirm     | yes         |
| auto   | yes        | yes                  | allowlist    | yes         | yes         |

### Enforcement

`packages/cowork-core/src/cowork_core/policy/permissions.py:24-27`
declares the write set:

```python
_WRITE_TOOLS = frozenset({
    "fs_write", "fs_edit", "fs_promote",
    "shell_run", "python_exec_run",
})
```

`permissions.py:30-72` is the whole gate: plan mode lets `fs_write`
through only for `scratch/plan.md`, blocks the rest of `_WRITE_TOOLS`
outright, and in `work` mode conditionally blocks `email_send` when
the config says `deny`. `auto` mode adds no gates here (tool-level
allowlists still apply).

### Confirmation protocol

Tools that want user confirmation return a dict with
`confirmation_required: true`. For example
`packages/cowork-core/src/cowork_core/tools/shell/run.py` returns:

```python
return {
    "confirmation_required": True,
    "tool": "shell_run",
    "summary": f"Run `{' '.join(argv)}` (not in allowlist: {sorted(allowlist)})",
    "argv": argv,
}
```

The React client sees the resulting event and flips the tool call's
`status` to `"confirmation"`
(`packages/cowork-web/src/hooks/useChat.ts:88-92`). There is no
built-in "approve-and-retry" UI yet; the user must re-issue the
request.

### Policy mode API (per-session, shipped Phase 1d)

Two pairs of endpoints in
`packages/cowork-server/src/cowork_server/app.py`:

- `GET/PUT /v1/policy/mode` — server-wide default. The PUT today only
  echoes (documented as deprecated; clients should move to the
  per-session endpoint).
- `GET/PUT /v1/sessions/{session_id}/policy/mode` — per-session. The
  PUT delegates to `runtime.set_session_policy_mode`, which appends an
  ADK event with `state_delta={COWORK_POLICY_MODE_KEY: mode}`.
  Subsequent permission checks read from session state, falling back
  to the server default for fresh sessions (`policy/permissions.py`).

So the UI's mode toggle is no longer a lie: a user can switch a live
session from `work` → `plan` mid-turn and the next tool call honors
the new mode.

## Gap / takeaway

**Filled since the last revision of this doc:**

- *Mutable per-session mode.* Session state carries
  `cowork.policy_mode`; `PUT /v1/sessions/{id}/policy/mode` persists
  via an ADK `state_delta` event (Phase 1d).
- *Sub-agent plan-mode enforcement.* Phase 1c propagated the
  permission + audit callbacks to researcher/writer/analyst/reviewer,
  so plan mode is no longer a root-only lie.

**Still missing in Cowork:**

- *Rule engine.* No path patterns, no per-project or per-tool rules,
  no source priority. One mode flag governs everything.
- *Sandbox.* No filesystem or network sandbox. `python_exec_run`
  does force `PYTHONNOUSERSITE=1` and a dead proxy
  (`127.0.0.1:1`) to disable network, but that's ad-hoc per-tool,
  not policy-driven.
- *Classifier.* No ML-assisted auto-approval.
- *Ask-flow.* The confirmation wire exists, but there is no UI for
  the user to approve a pending call in-place — they just see a
  "confirmation" status and have to re-ask.

**Not missing, because the scope is different:**

- A Google-ADK-hosted desktop copilot on local files doesn't need
  `WebFetch(domain:*.github.com)` style allow patterns — the
  surface is smaller.

**Potentially worth adding:**

- A small path-pattern layer for `files/` vs `scratch/` writes so
  the plan-mode rule (currently `path == "scratch/plan.md"`) isn't
  hard-coded as a string equality.
- In-UI approve-and-retry for `confirmation_required` results so
  the user doesn't have to re-issue the message.
