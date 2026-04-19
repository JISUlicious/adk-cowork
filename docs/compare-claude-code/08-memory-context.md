# 08 — Memory and context

How each system remembers things across turns and across sessions,
and how it fits within a finite context window.

## Claude Code

Two distinct systems: **short-term context management** (keeping the
current session's messages within the model's context window) and
**long-term memory** (persisting knowledge across sessions).

### Short-term compaction pipeline

`src/query.ts:365-410` runs five compaction stages in order before
each model call:

1. **`applyToolResultBudget()`** — caps the size of tool-result
   blocks so one big output can't dominate history.
2. **`snipModule.snipCompactIfNeeded()`** — removes middle-of-history
   material; emits a boundary marker message so the model knows.
3. **`deps.microcompact()`** — API-backed (Anthropic server-side)
   cached edits for repeated tool use.
4. **`contextCollapse.applyCollapsesIfNeeded()`** — read-time
   projection over REPL full history; stored summaries live in the
   collapse store, replayed from a commit log.
5. **`deps.autocompact()`** — triggered at a token threshold, runs
   a separate agent turn to summarize the session.

Plus **reactive compact** — only runs on API 413 ("prompt too
long"), not proactively.

### Token-budget continuation

`src/query/tokenBudget.ts` `createBudgetTracker()` tracks cumulative
API usage and enforces a `task_budget` (beta header). Separately,
the +500k auto-continue feature re-runs an iteration when the
current one approaches the output limit.

### Long-term memory

`src/memdir/memdir.ts` defines MEMORY.md semantics:

```ts
export const ENTRYPOINT_NAME = 'MEMORY.md'
export const MAX_ENTRYPOINT_LINES = 200
export const MAX_ENTRYPOINT_BYTES = 25_000

export function truncateEntrypointContent(raw: string): EntrypointTruncation
// Line-truncates first, then byte-truncates at last newline.
```

Typed memory files (user, feedback, project, reference) sit beside
MEMORY.md; the index points at them.

### Memory prefetch

`src/utils/attachments.ts` `startRelevantMemoryPrefetch()` fires once
per user turn, polls `settledAt` without blocking, and injects
relevant memories as attachment messages into the message history
before the API call. Uses `using` semantics to dispose cleanly on
any exit path.

### AutoDream consolidation

`src/services/autoDream/autoDream.ts` runs a background agent when
enough time and sessions have passed and no consolidation lock is
held. That agent (with constrained tools) writes consolidated
improvements back to the persistent memory files. Consolidation is
just another agent workflow, not a separate summarization backend.

### Cache-safe parameters

`src/utils/forkedAgent.ts` `CacheSafeParams` keeps the prompt
structure identical across side-line `sideQuestion` calls so the
API prompt-cache survives forks.

## Cowork

Session state via ADK's `SqliteSessionService`, a re-injected
in-memory `CoworkToolContext`, and a write-only audit transcript.
No compaction. No cross-session memory.

### Session persistence

`packages/cowork-core/src/cowork_core/runner.py:44-141`
`_CoworkSessionService` wraps ADK's `SqliteSessionService` so the
live, non-serializable `CoworkToolContext` can be re-hydrated on
resume:

```python
class _CoworkSessionService(BaseSessionService):
    def __init__(self, db_path: str) -> None:
        self._inner = SqliteSessionService(db_path)
        self._context_builders: dict[str, _ContextBuilder] = {}

    async def create_session(self, *, app_name, user_id, state=None, session_id=None):
        safe_state = dict(state or {})
        ctx = safe_state.pop(COWORK_CONTEXT_KEY, None)
        if ctx and isinstance(ctx, CoworkToolContext):
            safe_state["_cowork_meta"] = {
                "project_slug": ctx.project.slug,
                "session_id":   ctx.session.id,
            }
        adk_session = await self._inner.create_session(
            app_name=app_name, user_id=user_id,
            state=safe_state, session_id=session_id,
        )
        if ctx:
            adk_session.state[COWORK_CONTEXT_KEY] = ctx
        return adk_session

    async def get_session(self, *, app_name, user_id, session_id, config=None):
        adk_session = await self._inner.get_session(...)
        if adk_session is None:
            return None
        if COWORK_CONTEXT_KEY not in adk_session.state:
            builder = self._context_builders.get(session_id)
            if builder:
                adk_session.state[COWORK_CONTEXT_KEY] = builder()
        return adk_session
```

What lands in SQLite: ADK event history, `_cowork_meta`, and any
other JSON-safe state. What does not: the live `CoworkToolContext`
— it's rebuilt from a lambda registered at
`runner.py:187-189`:

```python
self.session_service.register_context(
    adk_sid, lambda p=project, s=session: self._build_context(p, s),
)
```

### Session-scoped tool state

`packages/cowork-core/src/cowork_core/tools/base.py:48-60` tracks
reads (for future "have you read this before?" logic):

```python
def record_read(tool_context: ToolContext, path: str) -> None:
    reads: list[str] = tool_context.state.setdefault(COWORK_READS_KEY, [])
    if path not in reads:
        reads.append(path)
```

A `list[str]` is used instead of a `set[str]` so the state remains
JSON-serializable for persistence.

### Transcript audit log

`packages/cowork-core/src/cowork_core/policy/hooks.py:28-36`
appends a JSON line per tool call + result to
`sessions/<id>/transcript.jsonl`. Write failures are swallowed:

```python
def _append_line(path: Any, record: dict[str, Any]) -> None:
    if path is None:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError:
        pass
```

The transcript is write-only; nothing ever reads it back.

### History replay

`packages/cowork-server/src/cowork_server/app.py:132-145` returns
the recorded ADK events for a session:

```python
@app.get("/v1/sessions/{session_id}/history")
async def session_history(session_id: str, user: UserIdentity = Depends(guard)):
    svc = runtime.runner.session_service
    existing = await svc.get_session(
        app_name=getattr(runtime.runner, "app_name", "cowork"),
        user_id=user.user_id,
        session_id=session_id,
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="session not found")
    return events_to_history(getattr(existing, "events", []) or [])
```

`packages/cowork-web/src/hooks/useChat.ts:232-272` `resumeSession`
re-runs each event through `handleEvent` to rebuild the message
timeline — verbatim replay, no summarization.

### Client-side session cache

`packages/cowork-web/src/hooks/useChat.ts:49-52` keeps an in-memory
cache of recent sessions so switching between them doesn't always
hit the server:

```typescript
const sessionCacheRef = useRef<
  Map<string, {
    messages: ChatMessage[];
    sending: boolean;
    pending: ChatMessage | null;
    toolMap: Map<string, [number, number]>;
  }>
>(new Map());
```

### Session on-disk layout

`packages/cowork-core/src/cowork_core/workspace/project.py:65-83`:

```
projects/{slug}/sessions/{session_id}/
├── scratch/              # drafts, temp files (persist across turns)
├── session.toml          # id, title, created_at
└── transcript.jsonl      # tool-call audit log
```

ADK's own event log lives in `workspace.root/global/sessions.db`
(`runner.py:264-267`).

## Gap / takeaway

**Filled since the last revision of this doc:**

- *Context-window guard (minimal).* `before_model_callback` in
  `cowork_core/callbacks/model.py:make_model_callbacks` increments a
  turn counter on session state and short-circuits past `max_turns`
  (default 50) with a synthesized assistant message. Prevents runaway
  agents from silently blowing the API limit; does **not** compact
  history.
- *Transcript round-trip is slightly less write-only.* The
  `after_model_callback` now appends a `model_call` record with token
  usage alongside the existing `tool_call` / `tool_result` lines
  (Phase 1b), giving future summarizers a complete record to work
  from.

**Still missing in Cowork:**

- *Short-term compaction.* Still zero stages beyond the turn-count
  guard. A long session blows the model's context window — the guard
  just bails out before the API error rather than summarizing.
- *Long-term memory.* No MEMORY.md, no typed memory files, no
  cross-session recall. Each session starts with nothing but the
  scratch dir.
- *Consolidation.* No autoDream equivalent.
- *Transcript as read surface.* The `transcript.jsonl` is written
  but never read back. It could feed a summarizer but currently
  doesn't.
- *Memory prefetch.* No "relevant memories injected as attachments"
  pipeline.

**Not missing, because the scope is different:**

- ADK's session service already does verbatim event persistence
  and replay, which is sufficient for short sessions.
- A scratch directory is not a memory system but plays a similar
  role for session-local durable state (draft .docx, intermediate
  data, etc.).

**Potentially worth adding (ordered by payoff):**

1. Real compaction — snip + summarize stages like Claude Code's
   `snip` / `microcompact` / `autocompact`, triggered in
   `before_model_callback` when the turn counter or token budget
   crosses a threshold.
2. A minimal long-term memory surface — at least a per-project
   `notes.md` the agent can read and update. Most of the machinery
   (scratch, transcript) already exists to support this.
3. Make the `transcript.jsonl` round-trip — on resume, surface the
   last N tool calls as a summary attachment instead of verbatim
   replay.
