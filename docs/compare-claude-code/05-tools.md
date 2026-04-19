# 05 — Tools

How tools are defined, registered, and executed.

## Claude Code

A uniform interface with heavy metadata, multiple orchestration
strategies, and MCP integration in the same pool.

### Contract

`src/Tool.ts` defines the tool interface. Every tool declares input
and output schemas (zod), read-only/destructive/concurrency
metadata, optional activity description, optional hook matcher, and
optional React render functions for progress + result widgets.

### Assembly

`src/tools.ts` is the composition root. It enumerates built-in
tools, applies feature gates and mode filtering (REPL / simple /
coordinator / agents), filters deny rules, and merges MCP tools into
the same pool so the model sees one flat list.

### Families

- **Local shell & files** — `BashTool`, `PowerShellTool`,
  `FileReadTool`, `FileEditTool`, `FileWriteTool`,
  `NotebookEditTool`, `GlobTool`, `GrepTool`, `LSPTool`.
- **Web / info** — `WebFetchTool`, `WebSearchTool`,
  `ListMcpResourcesTool`, `ReadMcpResourceTool`.
- **Orchestration** — `AgentTool`, `SendMessageTool`,
  `TaskCreate/Get/List/Update/Stop/Output`, `TeamCreateTool`,
  `TeamDeleteTool`, `TodoWriteTool`, `SkillTool`, plan/worktree
  entry and exit.
- **Automation** — `CronCreateTool`, `CronDeleteTool`,
  `CronListTool`, `RemoteTriggerTool`, `SleepTool`, `BriefTool`.
- **System** — `AskUserQuestionTool`, `SyntheticOutputTool`,
  `ToolSearchTool` (the tool that loads deferred tool schemas).

### Execution strategies

**Batch** — `src/services/tools/toolOrchestration.ts:19-82`
`runTools()` partitions tool calls into concurrency-safe parallel
groups and serial groups based on `tool.isConcurrencySafe(input)`.
Parallel groups are bounded by `MAX_TOOL_USE_CONCURRENCY`.

**Streaming** — `src/services/tools/StreamingToolExecutor.ts:40-62`.
Tools start executing while the model is still streaming, with
output ordering preserved via result buffering:

```ts
export class StreamingToolExecutor {
  addTool(block: ToolUseBlock, assistantMessage: AssistantMessage): void
  getRemainingResults(): Promise<Message[]>
  discard(): void
}
```

Cancellation behavior: sibling tools can be cancelled on error;
on model fallback, pending tools are discarded and in-progress
tools get a synthetic error result so the API contract is
preserved.

**Per-call** — `src/services/tools/toolExecution.ts:600+`
performs validation → pre-tool hooks → permission check → execute
→ post-tool hooks → result normalization.

### MCP

`src/services/mcp/client.ts` supports stdio, SSE, streamable HTTP,
WebSocket, and in-process SDK transports. MCP tools flow into the
same pool as built-ins; permission rules apply uniformly.

## Cowork

Plain async Python functions + ADK's `FunctionTool` auto-schema.

### Registry

`packages/cowork-core/src/cowork_core/tools/registry.py:19-42` is
intentionally minimal:

```python
@dataclass
class ToolRegistry:
    _tools: dict[str, BaseTool] = field(default_factory=dict)

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def as_list(self) -> list[BaseTool]:
        return [self._tools[name] for name in sorted(self._tools)]
```

The comment in the file (`registry.py:8-9`) makes the intent
explicit: "If we need any of that later, add it when we actually
have two callers."

### Registration

`packages/cowork-core/src/cowork_core/runner.py:249-256`:

```python
tool_registry = ToolRegistry()
register_fs_tools(tool_registry)
register_shell_tools(tool_registry)
register_python_exec_tools(tool_registry)
register_http_tools(tool_registry)
register_search_tools(tool_registry)
register_email_tools(tool_registry)
register_skill_tools(tool_registry)
```

Each `register_*` wraps a plain function with `FunctionTool(func)`.
ADK reads the Python type hints and docstring to auto-generate the
function-call schema the model sees — there is no hand-written zod
schema per tool.

### Tool-local context

Every tool gets a `tool_context: ToolContext` kwarg. Cowork stashes
a `CoworkToolContext` in the session state so tools can look it up
(`packages/cowork-core/src/cowork_core/tools/base.py:22-45`):

```python
COWORK_CONTEXT_KEY = "cowork.tool_context"
COWORK_READS_KEY = "cowork.session_reads"

@dataclass(frozen=True)
class CoworkToolContext:
    workspace: Workspace
    registry: ProjectRegistry
    project: Project
    session: Session
    config: CoworkConfig
    skills: SkillRegistry

def get_cowork_context(tool_context: ToolContext) -> CoworkToolContext:
    ctx = tool_context.state.get(COWORK_CONTEXT_KEY)
    if ctx is None:
        raise RuntimeError(...)
    return ctx
```

`record_read(tool_context, path)` tracks which project-relative
paths have been read in this session (stored under
`COWORK_READS_KEY`, a plain `list[str]` — must be JSON-serializable
because ADK persists the session state).

### Tools

| Name               | File                                   | Summary                                                      |
| ------------------ | -------------------------------------- | ------------------------------------------------------------ |
| `fs_read`          | `tools/fs/read.py`                     | Read a UTF-8 file up to ~2MB; records the read.              |
| `fs_write`         | `tools/fs/write.py`                    | Write text to `scratch/` or `files/`.                        |
| `fs_list`          | `tools/fs/list.py`                     | List a directory.                                            |
| `fs_glob`          | `tools/fs/glob.py`                     | Glob; bare patterns search both `scratch/` and `files/`.     |
| `fs_stat`          | `tools/fs/stat.py`                     | File/dir metadata.                                           |
| `fs_edit`          | `tools/fs/edit.py`                     | Line-replace / insert / delete edit.                         |
| `fs_promote`       | `tools/fs/promote.py`                  | Move a file from `scratch/` into `files/`.                   |
| `shell_run`        | `tools/shell/run.py`                   | Run an argv list; confirms if `argv[0]` not in allowlist.    |
| `python_exec_run`  | `tools/python_exec/run.py`             | Run a Python snippet in a locked-down subprocess.            |
| `http_fetch`       | `tools/http/fetch.py`                  | Safe HTTP GET (no `file://`, 2MB cap, 5 redirects).          |
| `search_web`       | `tools/search/web.py`                  | Web search (DuckDuckGo default; Brave/Tavily/SearXNG).       |
| `email_draft`      | `tools/email/draft.py`                 | Write a `.eml` file to scratch.                              |
| `email_send`       | `tools/email/send.py`                  | Send via SMTP; confirm or deny per policy.                   |
| `load_skill`       | `skills/load_skill_tool.py`            | Fetch a skill body + manifest.                               |

### Path resolution

`packages/cowork-core/src/cowork_core/tools/fs/_paths.py` enforces
the two-namespace view the prompt documents:

```python
def resolve_project_path(ctx: CoworkToolContext, rel: str) -> Path:
    parts = Path(rel).parts
    head, tail = parts[0], Path(*parts[1:]) if len(parts) > 1 else Path()
    if head == "scratch":
        base = ctx.session.scratch_dir.resolve()
    elif head == "files":
        base = ctx.project.files_dir.resolve()
    else:
        raise WorkspaceError(f"path must start with 'scratch/' or 'files/': {rel}")
    candidate = (base / tail).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as e:
        raise WorkspaceError(f"path escapes {head}/: {rel}") from e
    return candidate
```

`try_resolve_project_path` is the non-raising variant — returns the
error message as a string so tools can return `{"error": ...}` and
let the agent self-correct instead of killing the turn.

### Hardening notes

- `shell_run` refuses string `argv` (no shell expansion), checks
  `argv[0]` against `config.policy.shell_allowlist`, caps output at
  ~200KB and timeout at 600s. Working dir defaults to the session's
  scratch.
- `python_exec_run` writes the snippet to a temp `.py` under
  scratch, sets `PYTHONNOUSERSITE=1`, clears `PYTHONPATH`, and
  disables network via a bad proxy (`127.0.0.1:1`) unless the call
  explicitly opts in.

### MCP

`packages/cowork-core/src/cowork_core/agents/root_agent.py:82-100`
`_build_mcp_toolset` loads any configured MCP servers (stdio only
today) and appends them to the agent's tool list. Configured via
`cfg.mcp_servers` in `config.py:53-57`. The try/except silently
drops a server if the import fails, so MCP is truly optional.

## Gap / takeaway

**Missing in Cowork:**

- *Concurrency metadata.* No `isConcurrencySafe` equivalent; ADK
  decides call order internally.
- *Progress rendering.* No per-tool UI widget. The web client shows
  a generic "pending / ok / error / confirmation" chip and the args
  JSON.
- *Deferred tool loading.* Claude Code has `ToolSearch` for lazily
  fetching tool schemas; all Cowork tools are resident from the
  first turn.
- *Streaming execution overlap.* Tools run after the model decides,
  not during.
- *MCP transports.* Only stdio. SSE / HTTP / WS MCP servers are not
  wired (though ADK's `MCPToolset` has variants — would need config
  schema extension).

**Not missing, because the scope is different:**

- The tool count is small and stable; the ceremony of a `Tool<I, O>`
  interface with zod schemas would add friction for no gain at 13
  tools.
- ADK's auto-schema derivation from type hints means a new tool is
  just one function + one `registry.register(FunctionTool(func))`.

**Potentially worth adding:**

- Declaring per-tool concurrency metadata so the permission callback
  (or a future orchestration layer) can run read-only tools in
  parallel.
- A per-tool result size cap consistent with
  `maxResultSizeChars` — today each tool enforces its own ad-hoc
  limit (shell 200KB, fs_read 2MB, http 2MB).
