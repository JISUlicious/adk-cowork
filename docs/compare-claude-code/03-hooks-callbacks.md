# 03 — Hooks and callbacks

Lifecycle interception points the loop exposes to external code.

## Claude Code

Claude Code has a first-class hook system. 28 named events, each
dispatchable to shell scripts, HTTP endpoints, or subagents, with a
structured JSON response protocol that can approve, block, or
rewrite tool calls.

### Event registry

`src/entrypoints/sdk/coreTypes.ts:25-53` lists every hook event:

```ts
export const HOOK_EVENTS = [
  'PreToolUse', 'PostToolUse', 'PostToolUseFailure',
  'Notification', 'UserPromptSubmit',
  'SessionStart', 'SessionEnd',
  'Stop', 'StopFailure',
  'SubagentStart', 'SubagentStop',
  'PreCompact', 'PostCompact',
  'PermissionRequest', 'PermissionDenied',
  'Setup', 'TeammateIdle',
  'TaskCreated', 'TaskCompleted',
  'Elicitation', 'ElicitationResult',
  'ConfigChange',
  'WorktreeCreate', 'WorktreeRemove',
  'InstructionsLoaded', 'CwdChanged', 'FileChanged',
] as const
```

### Execution pipeline

`src/utils/hooks.ts` is the central dispatcher. Key entry points:

- `executePreToolUseHooks` / `executePostToolUseHooks`
  (`src/services/tools/toolHooks.ts:39+`) wrap every tool call.
- `executeUserPromptSubmitHooks` (`src/utils/hooks.ts:3826`) runs
  before input reaches the model.
- `executeStopHooks` (`src/query/stopHooks.ts`) fires when the turn
  would otherwise end without tool calls — can force a continuation.
- `executePermissionRequestHooks` (`src/utils/hooks.ts:1617`) runs
  when a tool needs user approval.

### Hook I/O contract

Hooks receive JSON on stdin (the event-specific `HookInput`
variant in `src/types/hooks.ts`) and may print JSON on stdout
matching `syncHookResponseSchema` at
`src/types/hooks.ts:50-99`:

```ts
{
  continue?: boolean,
  suppressOutput?: boolean,
  stopReason?: string,
  decision?: 'approve' | 'block',
  reason?: string,
  systemMessage?: string,
  hookSpecificOutput?: {
    hookEventName: 'PreToolUse',
    permissionDecision?: 'allow' | 'deny' | 'ask',
    permissionDecisionReason?: string,
    updatedInput?: Record<string, unknown>,
    additionalContext?: string,
  } | ...
}
```

The `updatedInput` field lets a `PreToolUse` hook rewrite a tool's
arguments before execution — a real extension point, not just a
veto.

### Sources

Hooks come from multiple sources simultaneously, registered via
`src/utils/hooks/sessionHooks.ts`,
`src/utils/hooks/registerFrontmatterHooks.ts`, and
`src/utils/hooks/registerSkillHooks.ts`. They can be defined in:

- `settings.json` (user, project, managed)
- skill frontmatter (per-skill hook bindings)
- plugin manifests
- SDK `onCanUseTool` callback

### Async hooks

`src/utils/hooks/hooksConfigManager.ts` owns the async-hook registry
for long-running hooks (HTTP or agent-based), tracking in-flight
invocations and telemetry.

## Cowork

Two callbacks, both registered on the root agent, both ADK-native.

### Registration

`packages/cowork-core/src/cowork_core/agents/root_agent.py:127-131`:

```python
permission_cb = make_permission_callback(cfg.policy)
audit_before, audit_after = make_audit_callbacks()
before_tool_cbs = [permission_cb, audit_before]
after_tool_cbs = [audit_after]
```

`root_agent.py:159-167` wires them into the root `LlmAgent`:

```python
return LlmAgent(
    name="cowork_root",
    ...
    before_tool_callback=before_tool_cbs,
    after_tool_callback=after_tool_cbs,
)
```

Sub-agents (`researcher`, `writer`, `analyst`, `reviewer`) do **not**
get these callbacks — only the root does. (See chapter 07.)

### Permission callback

`packages/cowork-core/src/cowork_core/policy/permissions.py:30-72`.
Returning a dict short-circuits the tool call with that dict as the
result; returning `None` lets the call proceed:

```python
def _check_permission(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
) -> dict[str, Any] | None:
    name = tool.name
    mode = policy.mode

    if mode == "plan":
        if name == "fs_write":
            path = str(args.get("path", ""))
            if path == "scratch/plan.md" or path.endswith("/plan.md"):
                return None
            return {"error": "Blocked by policy: ..."}
        if name in _WRITE_TOOLS:
            return {"error": f"Blocked by policy: `{name}` ..."}
    ...
    return None
```

### Audit callbacks

`packages/cowork-core/src/cowork_core/policy/hooks.py:39-94`.
`_before_tool` appends a `tool_call` record and stashes a start time
on `tool_context.state`; `_after_tool` computes `duration_ms` and
appends a `tool_result` record:

```python
def _before_tool(tool, args, tool_context):
    tool_context.state["_audit_tool_start"] = time.time()
    path = _get_transcript_path(tool_context)
    _append_line(path, {
        "event": "tool_call",
        "ts": time.time(),
        "tool": tool.name,
        "args": args,
    })
    return None
```

Transcript path is derived from the `CoworkToolContext` stashed in
`tool_context.state[COWORK_CONTEXT_KEY]`
(`policy/hooks.py:20-25`); see chapter 08 for how the context is
injected.

`_append_line` silently swallows `OSError` so a broken transcript
never kills an agent turn (`policy/hooks.py:28-36`).

### Model callbacks (shipped Phase 1)

`before_model_callback` and `after_model_callback` are now wired on the
root **and every sub-agent** via
`cowork_core/callbacks/model.py:make_model_callbacks`. The before-hook
maintains a turn counter in session state and short-circuits past
`max_turns=50` with a synthesized assistant message; the after-hook
appends a `model_call` record (with token usage when present) to the
session transcript.

## Gap / takeaway

**Filled since the last revision of this doc:**

- *Model-level callbacks* — `before/after_model_callback` wired
  uniformly on root + sub-agents (Phase 1b, see
  `cowork_core/callbacks/model.py`). Supports turn-budget guarding
  and per-model-call audit.
- *Sub-agent callback propagation* — `before_tool_callback`,
  `after_tool_callback`, and the model callbacks are now attached to
  every sub-agent in `root_agent.py:169-217`, so plan-mode enforcement
  and audit logging fire uniformly when the root delegates.

**Still missing in Cowork:**

- *Session-level events.* Nothing equivalent to `SessionStart`,
  `SessionEnd`, `UserPromptSubmit`. User input can be reacted to only
  inside the permission callback after the model already issued a
  tool call.
- *Compact/context events.* `PreCompact` / `PostCompact` have no
  counterpart because Cowork has no compaction (chapter 08).
- *External hook runner.* Shell scripts and HTTP endpoints cannot
  plug in. The callbacks are Python closures compiled into the
  binary.
- *JSON decision protocol.* Returning `{"error": ...}` from the
  permission callback is a minimal analog of `decision: 'block'`,
  but there is no `updatedInput`, no `stopReason`, no
  `additionalContext`.

**Not missing, because the scope is different:**

- ADK provides enough of a callback surface for the current product
  goals (policy gating + audit + turn budget). A full external hook
  runner is a project onto itself.

**Potentially worth adding:**

- A `session_start` equivalent — today session setup happens entirely
  in `runner.open_session` (`runner.py`), with no hookable seam.
- A JSON decision envelope for the permission callback so tool args
  can be rewritten instead of only vetoed. Claude Code's
  `updatedInput` pattern is a cheap win.
- A `UserPromptSubmit` analog so hooks can inspect/rewrite incoming
  messages before they reach the model.
