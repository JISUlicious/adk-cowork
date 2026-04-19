# Cowork vs Claude Code — architecture comparison

A side-by-side walk through two coding-agent codebases, focused on the
agent loop, prompts, hooks, policies, tools, skills, subagents,
memory, and streaming.

**Claude Code** (`/Users/jisu/data/workspace/ref/claude-code-leak/`)
is the reverse-engineered source of Anthropic's CLI. It is a
self-contained TypeScript app that ships a REPL, SDK, hooks,
skills, plugins, MCP, sandbox, remote sessions, and a memory system.

**Cowork** (this repo) is a Google-ADK-based office copilot. A Python
`cowork-core` package defines the agent, a FastAPI `cowork-server`
exposes `/v1/` over HTTP + SSE, and a Tauri + React `cowork-web`
client renders the conversation. ADK owns the turn loop, session
persistence, and event streaming; Cowork layers tools, skills,
policies, and a UI on top.

The two projects cover the same conceptual territory with very
different ambitions. Claude Code treats the loop as a product
surface; Cowork lets ADK handle the loop and focuses on the
surrounding workflow.

## TL;DR mapping

| Concept | Claude Code | Cowork |
| --- | --- | --- |
| Turn loop | `query()` generator, 3 layers, reactive compact ([01](01-agent-loop.md)) | `Runner.run_async` wrapped by `_run_turn` ([01](01-agent-loop.md)) |
| System prompt | `fetchSystemPromptParts` + cache boundary ([02](02-system-prompt.md)) | Static `ROOT_INSTRUCTION_BASE` + plan-mode addendum ([02](02-system-prompt.md)) |
| Lifecycle hooks | 28 events, external runners, JSON decisions ([03](03-hooks-callbacks.md)) | 4 ADK callbacks: permission + audit + before/after model (w/ turn guard) ([03](03-hooks-callbacks.md)) |
| Policies | Rule engine + sandbox adapter ([04](04-policies.md)) | Mode switch + shell allowlist ([04](04-policies.md)) |
| Tools | `Tool<I,O>` interface, zod, MCP, streaming exec ([05](05-tools.md)) | ADK `FunctionTool` auto-schema, 13 tools ([05](05-tools.md)) |
| Skills | 6 sources, frontmatter with tool/hook/agent bindings ([06](06-skills.md)) | 3 sources, minimal frontmatter, `load_skill` tool ([06](06-skills.md)) |
| Subagents | `AgentTool`, forked context, task objects, worktree ([07](07-subagents.md)) | ADK `sub_agents`, shared model + tools, env-aware prompts, uniform policy/audit/model callbacks ([07](07-subagents.md)) |
| Memory | MEMORY.md + autoDream + 5-stage compaction ([08](08-memory-context.md)) | Session event history + transcript.jsonl ([08](08-memory-context.md)) |
| Streaming | Model stream + streaming tool overlap ([09](09-streaming-ui.md)) | ADK events → `InMemoryEventBus` → SSE ([09](09-streaming-ui.md)) |

## How to read

Each chapter has the same three-part shape:

1. **Claude Code** — what the mechanism looks like, with
   `file:line` pointers into `ref/claude-code-leak/src/`.
2. **Cowork** — the corresponding mechanism in this repo, with
   pointers into `packages/cowork-{core,server,web}/`.
3. **Gap / takeaway** — which concerns are present in Claude Code but
   absent in Cowork (and vice versa), plus whether the gap matters
   for Cowork's scope.

Every claim anchors to a `file:line` so the reader can open either
tree and verify without guessing.

## Quick inventory

Claude Code's own notes live at
`/Users/jisu/data/workspace/ref/claude-code-leak/analysis/`:

- `01-directory-structure.md`
- `02-software-architecture.md`
- `03-agent-loop-architecture.md`
- `04-ecosystem-tools-sandboxes-skills.md`

Cowork's top-level docs:

- `SPEC.md` — product spec
- `CONSTITUTION.md` — repo invariants
- `PLAN.md` — roadmap
- `INDEX.md` — repo tour
