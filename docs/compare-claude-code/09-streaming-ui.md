# 09 — Streaming and UI

How model and tool output flow from the agent to the viewer.

## Claude Code

### Model streaming

`src/services/api/claude.ts` `queryModelWithStreaming()` calls the
Anthropic SDK with `stream: true`. The SDK emits
`message_start`, `content_block_start`,
`content_block_delta`, `content_block_stop`, `message_delta`,
`message_stop` events. The loop consumes them into assistant
messages as they arrive.

### Tool-use detection during stream

During `src/query.ts:560+` the loop peels `tool_use` blocks out
of the stream and, if streaming execution is enabled, pushes them
onto `StreamingToolExecutor`:

```ts
const useStreamingToolExecution = config.gates.streamingToolExecution
let streamingToolExecutor = useStreamingToolExecution
  ? new StreamingToolExecutor(
      toolUseContext.options.tools,
      canUseTool,
      toolUseContext,
    )
  : null
```

### Tool-result streaming

`src/services/tools/StreamingToolExecutor.ts:121+`
`getRemainingResults()` yields results in tool-call order (not
completion order) so the assistant's follow-up message aligns with
the original blocks. `discard()` on model fallback cancels pending
work and synthesizes error results for in-flight tools.

### Withheld messages

`src/query.ts:175-179`:

```ts
function isWithheldMaxOutputTokens(
  msg: Message | StreamEvent | undefined,
): msg is AssistantMessage {
  return msg?.type === 'assistant' && msg.apiError === 'max_output_tokens'
}
```

Intermediate max-output-token errors are held back from SDK callers
so the recovery loop can decide whether to escalate budget or
surface the error.

### UI

Claude Code renders with React-Ink in the terminal. Messages fan
out to a REPL component which turns them into text, tool-call cards,
and progress widgets. For SDK/API clients, the same message stream
is mapped into SDK message types.

## Cowork

### Server → client wire format

`packages/cowork-server/src/cowork_server/transport.py`
`event_to_payload` emits ADK's native wire format verbatim:

```python
def event_to_payload(event: Any) -> str:
    return event.model_dump_json(exclude_none=True, by_alias=True)
```

This matches ADK's own `adk_web_server.py` so any ADK-native client
could consume the stream without extra mapping.

### Event bus

`packages/cowork-server/src/cowork_server/queues.py:30-84`
`InMemoryEventBus` is a lock-guarded, bounded, fan-out pub/sub:

```python
class InMemoryEventBus:
    async def publish(self, session_id: str, payload: str) -> None:
        async with self._lock:
            queues = self._subscribers.get(session_id, [])
        for q in queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()     # drop oldest
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass
```

Full queues drop the oldest event (backpressure for slow
consumers). Multiple subscribers per session each get their own
queue — multiple windows on the same session all receive a copy.

### SSE endpoint

`packages/cowork-server/src/cowork_server/app.py:163-198`:

```python
@app.get("/v1/sessions/{session_id}/events/stream")
async def events_sse(session_id, user: UserIdentity = Depends(guard)):
    await limiter.acquire(user.user_id)
    async def gen() -> Any:
        try:
            async with bus.subscribe(session_id) as queue:
                while True:
                    try:
                        payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    yield f"data: {payload}\n\n"
                    try:
                        done = _json.loads(payload).get("turnComplete") is True
                    except (ValueError, AttributeError):
                        done = False
                    if done:
                        return
        finally:
            await limiter.release(user.user_id)
    return StreamingResponse(gen(), media_type="text/event-stream", ...)
```

15-second SSE keep-alive. Stream closes when an event's
`turnComplete` is `true`, which is how the client knows the turn is
finished.

### WebSocket (alternate)

`packages/cowork-server/src/cowork_server/app.py:200-224` exposes
the same event stream over WebSocket. The wire format is identical
JSON per frame. The browser uses SSE; WS is there for full-duplex
future use.

### Connection limiter

`packages/cowork-server/src/cowork_server/connections.py:30-60`
`InMemoryConnectionLimiter` is a per-user counter. Default max is
small; exceeding it returns 429. Prevents one user's runaway
streams from starving others.

### Client: folding events into React state

`packages/cowork-web/src/transport/client.ts:199-228`
`connectStream` attaches an `EventSource` and forwards each frame
to the handler.

`packages/cowork-web/src/hooks/useChat.ts:62-182` `handleEvent`
does the folding. It classifies each event:

```ts
const hasFunctionResponse = parts.some((p) => p.functionResponse)
const hasFunctionCall     = parts.some((p) => p.functionCall)
const hasText             = parts.some((p) => typeof p.text === "string" && p.text)
const isUserTurn = role === "user" && !hasFunctionResponse && hasText
```

And folds:

- **User turn** — append a `user` message.
- **functionResponse** — look up the `functionCall.id` in
  `toolMapRef`, update status to `ok` / `error` /
  `confirmation`, attach the result.
- **Text or functionCall on assistant** — accumulate into
  `pendingRef` and snapshot into the message list. Streaming text
  is stitched into `pending.text`; `part.thought` flag routes text
  into `pending.thought` instead.
- **turnComplete** — clear pending, flip sending off, optionally
  fire a desktop notification.

### The "sync ref" pattern

The hook uses `messagesRef`, `sendingRef`, and `pendingRef` that
mirror React state synchronously
(`packages/cowork-web/src/hooks/useChat.ts:36-47`):

```typescript
const setMessagesSync = useCallback((msgs) => {
  setMessages((prev) => {
    const next = typeof msgs === "function" ? msgs(prev) : msgs;
    messagesRef.current = next;
    return next;
  });
}, []);

const setSendingSync = useCallback((value: boolean) => {
  sendingRef.current = value;
  setSending(value);
}, []);
```

This lets `saveCurrentSession()` snapshot state at the exact moment
the user switches sessions without racing React's async setState.

### Per-session UI cache

See chapter 08 — `sessionCacheRef` keeps recent sessions resident
client-side so round-tripping between them doesn't always reload
history.

## Gap / takeaway

**Missing in Cowork:**

- *Streaming tool overlap.* Tools only start after the model
  yields — no `StreamingToolExecutor` analog. For read-only tools
  this is a latency loss on multi-tool turns.
- *Withheld-message protocol.* Errors are surfaced as error events
  immediately. There's no intermediate "this failed but we're
  recovering" state.
- *Per-tool progress render.* The client shows a generic status
  chip; there's no per-tool widget like Claude Code's file-diff
  render on Edit.

**Not missing, and arguably better for the scope:**

- A proper **pub/sub event bus** with multiple subscribers per
  session — Claude Code doesn't need this because there's only one
  terminal. Cowork supports opening the same session in multiple
  windows; the bus makes that correct.
- A **client-side session cache** so switching tabs is free.
- A **per-user connection limiter** — a real concern for a hosted
  server, a non-issue for a local TTY.
- **Identical SSE / WS wire format** matching ADK's own server, so
  any ADK-native client can consume the stream.

**Potentially worth adding:**

- A streaming tool executor in `_run_turn` that starts read-only
  tools (`fs_read`, `fs_glob`, `fs_stat`, `http_fetch`,
  `search_web`) in parallel as ADK yields their call events.
- A richer per-tool render in the web UI — at minimum, a diff view
  for `fs_edit` and a tabular view for `fs_list` / `fs_glob`.
