# 07 — Subagents

How the root agent hands work to another agent that runs its own
turn loop.

## Claude Code

Subagents are first-class. They are tracked as durable task objects,
get an isolated context, can run on a different git worktree or a
remote host, and can bring their own MCP servers.

### Entry point

`src/tools/AgentTool/runAgent.ts` is the subagent launcher. Agents
are declared by `AgentDefinition` records loaded from multiple
sources (bundled, user, project, plugin) via
`src/tools/AgentTool/loadAgentsDir.ts`.

### Context isolation

`src/utils/forkedAgent.ts` `createSubagentContext()`:

- Clones the read-file cache (parent's file-knowledge doesn't leak).
- Creates a child `AbortController` so a subagent cancel doesn't
  kill the parent.
- Gives the subagent its own mutable state.
- Suppresses permission prompts unless the parent explicitly shares
  them (`shouldAvoidPermissionPrompts: true`).
- Clones content-replacement state so prompt-cache hits stay stable.

`src/tools/AgentTool/agentToolUtils.ts` resolves the subagent's tool
pool: filters out disallowed tools, applies agent-specific
`allowedTools`, and merges any agent-owned MCP clients in with the
parent's.

### Task lifecycle

`src/tasks/*.ts` gives subagents a first-class object identity:

- `LocalAgentTask` — in-process agent with a transcript file.
- `RemoteAgentTask` — routed to a remote CCR session.
- `LocalMainSessionTask` — long-running op on the main session.
- `DreamTask` — background memory-consolidation agent.
- `ShellTask*` — long-running shell operations.

Task state includes id, status, output file path, progress summary,
queued follow-up messages, and notification state — meaning agents
are manageable work items, not ephemeral promises.

### Agent variants

- **Synchronous local** — parent turn blocks until the subagent
  returns.
- **Background local (`Task`)** — spawn, keep running; parent can
  poll or receive via `TaskOutput`.
- **Worktree-isolated** — a temporary git worktree per agent so
  parallel edits don't conflict.
- **Remote** — routed through `RemoteSessionManager`.
- **Swarm / coordinator teammates** — extra orchestration tools
  (`SendMessageTool`, `TeamCreateTool`, `AskUserQuestionTool`) turn
  multiple agents into collaborators.

## Cowork

ADK's native `sub_agents` list, four specialists, no isolation.

### Wiring

`packages/cowork-core/src/cowork_core/agents/root_agent.py:134-167`
defines researcher, writer, analyst, reviewer as plain `LlmAgent`s
sharing the same model and the root's tool pool, then passes them
as `sub_agents=[…]` on the root:

```python
researcher = LlmAgent(name="researcher", model=model,
    instruction=RESEARCHER_INSTRUCTION, tools=adk_tools)
writer    = LlmAgent(name="writer",    model=model,
    instruction=WRITER_INSTRUCTION,    tools=adk_tools)
analyst   = LlmAgent(name="analyst",   model=model,
    instruction=ANALYST_INSTRUCTION,   tools=adk_tools)
reviewer  = LlmAgent(name="reviewer",  model=model,
    instruction=REVIEWER_INSTRUCTION,  tools=adk_tools)

return LlmAgent(
    name="cowork_root",
    model=model,
    instruction=_dynamic_instruction,
    tools=adk_tools,
    sub_agents=[researcher, writer, analyst, reviewer],
    before_tool_callback=before_tool_cbs,
    after_tool_callback=after_tool_cbs,
)
```

Note that the sub-agents do **not** receive
`before_tool_callback` or `after_tool_callback` — so policy
enforcement and audit logging only apply to calls made by the
root. A subagent that invokes `shell_run` is not gated by
`permission_cb`.

### Prompt-driven delegation

`root_agent.py:48-58` tells the model when to delegate:

```
Sub-agent delegation:
You have four specialist sub-agents. Delegate to them for complex tasks:
- **researcher**: Gather information from the web or project files. Use for
  research-heavy requests before drafting.
- **writer**: Draft or edit documents (memos, reports, emails, docx/xlsx).
- **analyst**: Analyze data, run calculations, produce charts and tables.
- **reviewer**: Review documents for quality, accuracy, and completeness.

For simple requests (read a file, quick answer), handle them yourself.
For multi-step workflows (research → draft → review), delegate to the
appropriate sub-agents in sequence.
```

ADK exposes `sub_agents` to the model as an implicit transfer
mechanism; there is no explicit `invoke_agent` tool in Cowork's
registry.

### Sub-agent instructions

Each specialist has its own instruction file:

- `packages/cowork-core/src/cowork_core/agents/researcher.py`
- `packages/cowork-core/src/cowork_core/agents/writer.py`
- `packages/cowork-core/src/cowork_core/agents/analyst.py`
- `packages/cowork-core/src/cowork_core/agents/reviewer.py`

They all share:

- The same model config.
- The same tool pool (`adk_tools`).
- The same `CoworkToolContext` through `tool_context.state` (no
  fork).
- **The same callbacks** — `before_tool_callback`,
  `after_tool_callback`, `before_model_callback`,
  `after_model_callback` — all wired identically on root + all four
  specialists (Phase 1c, `root_agent.py:169-217`).
- An **env-aware instruction** wrapped in `_sub_agent_instruction`
  so the Working Context paragraph is injected per turn from the
  session's `ExecEnv` (Phase A1, `root_agent.py:146-160`). A desktop
  session delegating to `writer` now tells it to write into the
  user's picked folder, not `scratch/`.

## Gap / takeaway

**Filled since the last revision of this doc:**

- *Policy callback on sub-agents.* Plan-mode enforcement and audit
  logging now fire uniformly whether the root or a specialist
  initiates the tool call (Phase 1c). Regression test:
  `tests/test_policy.py::TestSubAgentCallbacks`.
- *Env-aware sub-agent prompts.* Each specialist renders its
  instruction per-turn with the session's `describe_for_prompt()`
  paragraph injected. Tests:
  `tests/test_callbacks_and_prompt.py::test_sub_agents_receive_local_dir_working_context`
  and its managed-fallback sibling.

**Still missing in Cowork:**

- *Context isolation.* A sub-agent can see the parent's read-file
  cache and session state by default because they share the same
  ADK session.
- *Task objects.* No durable record of an agent invocation. When
  the session ends, nothing remembers "the analyst was working on
  X".
- *Background agents.* No async spawn-and-poll equivalent — every
  sub-agent call is synchronous inside the parent's turn.
- *Worktree isolation.* No temp-worktree mechanism; two sub-agents
  editing the same file race.
- *Remote agents.* No remote routing. (ADK does have
  agent-to-agent networking in the roadmap, not wired here.)
- *Per-agent tool allowlists.* All four agents see every tool; a
  reviewer can call `shell_run` just as easily as the root.

**Not missing, because the scope is different:**

- Four specialists with shared tools is a reasonable starting
  topology for an office-work copilot. Introducing fork-and-isolate
  before the need is clear would be premature.

**Potentially worth adding (ordered by payoff):**

1. Per-agent tool allowlists — e.g. reviewer gets only
   `fs_read`, `fs_glob`, `http_fetch`. Matches Claude Code's
   `allowedTools` pattern and tightens the blast radius.
2. A minimal task-log record so the transcript records "root
   delegated to writer for ~3 turns" as a structured entry, not
   just as a stream of events.
