# 01 — Agent loop

How one user message becomes one (or many) model-and-tool round trips.

## Claude Code

Three nested loop layers.

### Layer A — session wrapper (`QueryEngine`)

`src/QueryEngine.ts:209` `submitMessage()` owns conversation-level
state: mutable message history, transcript persistence, read-file
cache, usage accumulation, system-init event. It preprocesses input
(slash commands, user-input hooks, attachments), then delegates to
the turn loop. Cache-only skills/plugins lookup runs here so the
system-init event is deterministic.

### Layer B — turn loop (`query()` generator)

`src/query.ts:219` defines `export async function* query(...)` which
immediately enters `src/query.ts:241` `queryLoop(...)` — an explicit
`while (true)` state machine, not a recursive function.

State carried between iterations (`src/query.ts:204-217`):

```ts
type State = {
  messages: Message[]
  toolUseContext: ToolUseContext
  autoCompactTracking: AutoCompactTrackingState | undefined
  maxOutputTokensRecoveryCount: number
  hasAttemptedReactiveCompact: boolean
  pendingToolUseSummary: Promise<ToolUseSummaryMessage | null> | undefined
  turnCount: number
  transition: Continue | undefined  // why last iter continued
}
```

Per-iteration (`src/query.ts:337-579`):

1. Start iteration: assign `queryTracking.chainId/depth`, kick off
   skill-discovery and memory prefetches.
2. Prepare history — five compaction stages run in order (snip →
   microcompact → context collapse → autocompact).
3. Assemble `fullSystemPrompt = asSystemPrompt(appendSystemContext(...))`.
4. Stream the model (`queryModelWithStreaming` in
   `src/services/api/claude.ts`) with streaming on.
5. As each `tool_use` block arrives, the
   `StreamingToolExecutor.addTool()` (`src/services/tools/StreamingToolExecutor.ts:40-62`)
   queues it and may start execution in parallel.
6. After streaming: call `runTools()`
   (`src/services/tools/toolOrchestration.ts:19-82`) to drain any
   remaining calls. It partitions into *concurrency-safe parallel*
   and *serial* groups based on `tool.isConcurrencySafe(input)`.
7. If the turn produced no tool calls, take the *completion path* —
   stop hooks, token-budget continuation, return. Otherwise append
   assistant + tool results, bump `turnCount`, continue.

### Layer C — tool/subagent loops

Tools themselves can recurse. `AgentTool`
(`src/tools/AgentTool/runAgent.ts`) launches a subagent that runs
another `query()`; task objects under `src/tasks/` wrap long-running
subagent loops with durable state.

### Recovery paths

Explicit, not implicit (`src/query.ts:365-410`):

- **Context overflow** → drain staged collapses, reactive compact.
- **Max output tokens** → escalate output budget up to 3 retries.
  `isWithheldMaxOutputTokens()` at `src/query.ts:175-179` withholds
  these intermediate errors from SDK callers so the loop can recover
  silently.
- **Model fallback** → switch model, synthesize missing tool
  results, strip thinking blocks.
- **Interruption** → synthesize tool-result failures and emit an
  abort reason.

### Per-query shape

```
submitMessage() → query() → queryLoop()
                              │
                              ├─ compact stages
                              ├─ assemble prompt
                              ├─ stream model ───────┐
                              │                      │
                              │    StreamingTool ◄───┤ tool_use blocks
                              │    Executor          │
                              ├─ runTools() remainder
                              ├─ tool_use? ── yes → append + continue
                              └─ no → stop hooks → return
```

## Cowork

One layer. ADK owns the loop; the server just marshals messages.

### FastAPI entry

`packages/cowork-server/src/cowork_server/app.py:147-159`
`send_message` accepts `{text: str}`, schedules `_run_turn` as an
asyncio task, returns 202 immediately:

```python
task = asyncio.create_task(
    _run_turn(runtime.runner, bus, session_id, str(text), user.user_id)
)
task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
return {"status": "accepted"}
```

### Turn driver

`packages/cowork-server/src/cowork_server/app.py:376-415` `_run_turn`
calls `runner.run_async(...)` and forwards each ADK `Event` to the
event bus verbatim:

```python
content = genai_types.Content(role="user", parts=[genai_types.Part(text=text)])
async for event in runner.run_async(
    user_id=user_id, session_id=session_id, new_message=content
):
    event_count += 1
    last_event = event
    await bus.publish(session_id, event_to_payload(event))
```

If `run_async` raises, `_run_turn` publishes a synthesized error
`Event` with `turn_complete=True` so the client knows the turn is
over. If the last real event didn't set `turn_complete`, a sentinel
`turn_complete` event is published (`app.py:409-414`).

### Agent assembly

`packages/cowork-core/src/cowork_core/runner.py:242-281`
`build_runtime` builds the tool registry, skill registry, root
agent, session service, and ADK `Runner`:

```python
agent = build_root_agent(
    cfg,
    tools=tool_registry.as_list(),
    skills_snippet=skills.injection_snippet(),
)
runner = Runner(app_name=APP_NAME, agent=agent, session_service=session_service)
```

The root `LlmAgent`
(`packages/cowork-core/src/cowork_core/agents/root_agent.py:159-167`)
gets `sub_agents=[researcher, writer, analyst, reviewer]`,
`before_tool_callback=[permission_cb, audit_before]`, and
`after_tool_callback=[audit_after]`. The rest of the loop — the
actual LLM round-trips, tool invocation, sub-agent routing,
streaming — lives inside `google.adk.runners.Runner`.

### Per-query shape

```
POST /v1/sessions/{sid}/messages
      │
      ▼
send_message() ── creates task ──► _run_turn()
                                     │
                                     ▼
                                runner.run_async()
                                  (ADK owns this)
                                     │
                                     ▼
                                yields Event's
                                     │
                                     ▼
                                bus.publish(session_id, payload)
                                     │
                                     ▼
                                SSE stream consumes bus
```

## Gap / takeaway

**Missing in Cowork (present in Claude Code):**

- *Iteration state.* No explicit `turnCount`,
  `maxOutputTokensRecoveryCount`, or `transition` — ADK's runner is
  a black box from Cowork's perspective.
- *Streaming tool overlap.* Claude Code executes read-only tools in
  parallel while the model is still emitting. Cowork waits for ADK
  to finish its internal decode step before the next tool fires.
- *Recovery paths.* No reactive compact, no max-output recovery, no
  model fallback. If ADK raises, `_run_turn` catches it at the
  outer layer and publishes an `INTERNAL` error event
  (`app.py:396-404`).
- *Stop hooks / token-budget continuation.* ADK does not expose
  these; a turn ends when ADK says it does.

**Not missing, because the scope is different:**

- Cowork is a hosted server with multi-user sessions; the async
  fire-and-forget pattern is structurally appropriate and does not
  need the same back-pressure plumbing as a TTY REPL.
- ADK already implements the LLM-tool ping-pong loop. Duplicating
  that in Cowork would be pointless.

**Potentially worth adding:**

- An ADK `before_model_callback` to inject per-turn context or to
  bound `turnCount` (ADK supports this — see chapter 03).
- A server-side recovery wrapper for common 4xx/5xx model errors so
  a blown turn surfaces as a retry rather than a hard
  `INTERNAL` error.
