"""Root Cowork agent with sub-agent delegation.

The root agent handles user requests directly for simple tasks and delegates
to specialist sub-agents for complex multi-step work:

- **Researcher**: web search, file scanning, information gathering
- **Writer**: document creation, editing, formatting
- **Analyst**: data processing, charts, calculations
- **Reviewer**: quality checks, fact-checking, proofreading
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.base_tool import BaseTool

from cowork_core.agents.custom import CustomAgent, CustomAgentRegistry
from cowork_core.agents.analyst import (
    ANALYST_DEFAULT_ALLOWED_TOOLS,
    ANALYST_DEFAULT_SHELL_ALLOWLIST,
    ANALYST_INSTRUCTION,
)
from cowork_core.agents.explorer import (
    EXPLORER_DEFAULT_ALLOWED_TOOLS,
    EXPLORER_INSTRUCTION,
)
from cowork_core.agents.planner import (
    PLANNER_DEFAULT_ALLOWED_TOOLS,
    PLANNER_INSTRUCTION,
)
from cowork_core.agents.researcher import (
    RESEARCHER_DEFAULT_ALLOWED_TOOLS,
    RESEARCHER_INSTRUCTION,
)
from cowork_core.agents.reviewer import (
    REVIEWER_DEFAULT_ALLOWED_TOOLS,
    REVIEWER_INSTRUCTION,
)
from cowork_core.agents.verifier import (
    VERIFIER_DEFAULT_ALLOWED_TOOLS,
    VERIFIER_DEFAULT_SHELL_ALLOWLIST,
    VERIFIER_INSTRUCTION,
)
from cowork_core.agents.writer import (
    WRITER_DEFAULT_ALLOWED_TOOLS,
    WRITER_INSTRUCTION,
)
from cowork_core.callbacks import make_model_callbacks
from cowork_core.config import AgentConfig, CoworkConfig, McpServerConfig
from cowork_core.model.openai_compat import build_model
from cowork_core.policy.hooks import make_audit_callbacks
from cowork_core.policy.permissions import (
    make_allowlist_callback,
    make_mcp_disable_callback,
    make_permission_callback,
    make_shell_allowlist_gate,
    make_static_agent_gate,
)
from cowork_core.tools.base import (
    COWORK_AUTO_ROUTE_KEY,
    COWORK_SKILLS_ENABLED_KEY,
    COWORK_CONTEXT_KEY,
    COWORK_POLICY_MODE_KEY,
)

ROOT_HEADER = """\
You are Cowork, an office-work copilot.

You help the user with documents, spreadsheets, PDFs, research, and drafting.
Be concise and practical. Ask for confirmation before any destructive action.
"""

# Fallback working-context paragraph — used when no ExecEnv is available
# (e.g. during agent construction before any session has started). At runtime
# the env's own ``describe_for_prompt()`` takes over.
ROOT_WORKING_CONTEXT_FALLBACK = """\
Working context:
- `scratch/` is the current session's draft directory — work here freely.
- `files/` is the project's durable storage — call `fs_promote` to move a
  draft from scratch into it.
"""

ROOT_TAIL = """\
Tool use:
- Use `fs_read` / `fs_write` / `fs_edit` for text files.
- Use `python_exec_run` for programmatic document work (docx, xlsx, pdf, …).
- Use `search_web` + `http_fetch` for research.
- Use `load_skill` to fetch the body of a named skill before doing
  format-specific work.

Sub-agent delegation:
You have seven specialist sub-agents. Delegate to them for complex tasks:
- **researcher**: Gather information from the web or project files. Use for
  research-heavy requests before drafting.
- **writer**: Draft or edit documents (memos, reports, emails, docx/xlsx).
- **analyst**: Analyze data, run calculations, produce charts and tables.
- **reviewer**: Review documents for style, tone, and completeness.
- **explorer**: Read-only fast file/keyword navigator. Use for "where is X"
  or "list every Y" queries — cheaper than running the main model.
- **planner**: Read-only plan author. Use when the user asks "what would
  you do" or in plan mode; planner writes a step-by-step plan to
  `scratch/plan.md` without executing.
- **verifier**: Adversarial correctness checker. Use after a writer or
  analyst delivers — verifier opens the artifact, recomputes formulas,
  validates schemas, and returns PASS/FAIL/PARTIAL.

For simple requests (read a file, quick answer), handle them yourself.
For multi-step workflows (research → draft → verify), delegate to the
appropriate sub-agents in sequence.
"""

# Tier E.E2. Included in the root instruction when
# ``cowork.auto_route`` is ``True`` (default). The directive steers
# ADK's native ``sub_agents`` delegation — we don't add a manual
# ``transfer_to_agent`` tool; the root already has the hand-off
# mechanism and just needs to be told when to use it.
AT_MENTION_PROTOCOL = """\
User-directed routing:
If the user's message begins with ``@<agent_name>`` (e.g. ``@researcher``,
``@writer``, ``@analyst``, ``@reviewer``, ``@explorer``, ``@planner``,
``@verifier``), transfer to that sub-agent on the first move. Do not
answer yourself first. The mentioned sub-agent should strip the
``@<agent_name>`` prefix from the message and respond to the actual
request.

If the name doesn't match a known sub-agent, acknowledge the typo and
handle the request yourself.

Auto-routing triggers (delegate without waiting for ``@``-mention):
- "find / locate / where is / list every …" → ``explorer``
- "plan / what would you do / outline the steps / break this down" → ``planner``
- "verify / check correctness / does this actually work / run the
  formulas" → ``verifier``
- "research / gather / cite sources / summarize what's known" → ``researcher``
- "draft / write / compose / revise the document" → ``writer``
- "analyze / chart / table / compute / pivot the data" → ``analyst``
- "review / proofread / does this read well" → ``reviewer``

Pick the closest match; if uncertain, prefer the more specialized agent
(``planner`` over yourself for any planning, ``verifier`` over yourself
for any correctness check).
"""

# W1 — built-in sub-agent defaults. Keyed by agent name; each entry is
# (default-allowed-tools-tuple, instruction-string). The ``cfg.agents.<name>``
# config can override allowed_tools, add disallowed_tools, or swap the model.
SUB_AGENT_DEFAULTS: dict[str, tuple[tuple[str, ...], str]] = {
    "researcher": (RESEARCHER_DEFAULT_ALLOWED_TOOLS, RESEARCHER_INSTRUCTION),
    "writer": (WRITER_DEFAULT_ALLOWED_TOOLS, WRITER_INSTRUCTION),
    "analyst": (ANALYST_DEFAULT_ALLOWED_TOOLS, ANALYST_INSTRUCTION),
    "reviewer": (REVIEWER_DEFAULT_ALLOWED_TOOLS, REVIEWER_INSTRUCTION),
    # W3 — three new built-ins on top of W1+W2's primitives.
    "explorer": (EXPLORER_DEFAULT_ALLOWED_TOOLS, EXPLORER_INSTRUCTION),
    "planner": (PLANNER_DEFAULT_ALLOWED_TOOLS, PLANNER_INSTRUCTION),
    "verifier": (VERIFIER_DEFAULT_ALLOWED_TOOLS, VERIFIER_INSTRUCTION),
}


# W5 — per-agent default shell allowlist for sub-agents that have
# ``shell_run`` on their surface. Agents not in this map (or with an
# empty tuple) fall back to ``cfg.policy.shell_allowlist``; if the
# agent doesn't have ``shell_run`` in its ``allowed_tools``, the W1
# static gate blocks the call before the shell allowlist matters.
SUB_AGENT_SHELL_ALLOWLISTS: dict[str, tuple[str, ...]] = {
    "analyst": ANALYST_DEFAULT_SHELL_ALLOWLIST,
    "verifier": VERIFIER_DEFAULT_SHELL_ALLOWLIST,
}


PLAN_MODE_ADDENDUM = """\

## PLAN MODE — ACTIVE

You are in **plan mode**. You MUST NOT execute any actions that modify
files or run commands.

**Default behaviour: delegate to the ``planner`` sub-agent on the
first turn.** The planner is read-only by design (config-time gate)
and writes the final plan to `scratch/plan.md`. Transferring to it is
strictly safer than handling the planning yourself.

Skip the delegation and write the plan yourself only when:
- the planner has already returned a plan this turn and the user
  asked you to refine it inline; or
- the planner sub-agent is somehow unavailable (e.g. an edge-case
  test harness with no sub-agents wired).

When you do write the plan yourself, follow the same shape: list every
file you would create or modify, every shell command you would run,
every sub-agent you would delegate to and why, plus risks /
assumptions / questions. Save it via `fs_write` to `scratch/plan.md`
— that is the ONE write operation allowed in plan mode.

Stop after the plan is saved. The user will review it and may switch
to work mode to execute.
"""


def build_mcp_toolset(mcp_cfg: McpServerConfig) -> tuple[Any | None, str | None]:
    """Construct an ADK ``MCPToolset`` for ``mcp_cfg`` and return
    ``(toolset, last_error)``. Either field may be ``None``: a
    successful build returns ``(toolset, None)``, a misconfigured
    or exception-throwing build returns ``(None, "<error>")``.

    Slice III replaces the older silent-failure ``_build_mcp_toolset``
    so callers can populate ``CoworkRuntime.mcp_status`` and surface
    the error to Settings → System.

    Dispatches on ``transport``:
    - ``stdio`` (default): subprocess launched from ``command`` +
      ``args`` + ``env``.
    - ``sse``: Server-Sent Events to ``url`` with ``headers``.
    - ``http``: Streamable HTTP to ``url`` with ``headers``.

    ``tool_filter`` is passed through to ``MCPToolset`` so the agent
    only sees the whitelisted tools when the user has narrowed the
    surface.
    """
    try:
        # ``McpToolset`` (lowercase ``Mcp``) is the current ADK class
        # name; ``MCPToolset`` is a deprecated alias retained for
        # backwards compatibility. Use the fresh name to silence the
        # deprecation warning.
        from google.adk.tools.mcp_tool import (
            McpToolset,
            SseConnectionParams,
            StdioConnectionParams,
            StreamableHTTPConnectionParams,
        )
    except ImportError as exc:  # pragma: no cover — adk extra missing
        return None, f"google-adk MCP support unavailable: {exc}"

    try:
        if mcp_cfg.transport == "stdio":
            if not mcp_cfg.command:
                return None, "stdio transport requires 'command'"
            from mcp.client.stdio import StdioServerParameters

            params: Any = StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=mcp_cfg.command,
                    args=mcp_cfg.args,
                    env=mcp_cfg.env or None,
                ),
            )
        elif mcp_cfg.transport == "sse":
            if not mcp_cfg.url:
                return None, "sse transport requires 'url'"
            params = SseConnectionParams(
                url=mcp_cfg.url,
                headers=mcp_cfg.headers or None,
            )
        elif mcp_cfg.transport == "http":
            if not mcp_cfg.url:
                return None, "http transport requires 'url'"
            params = StreamableHTTPConnectionParams(
                url=mcp_cfg.url,
                headers=mcp_cfg.headers or None,
            )
        else:  # pragma: no cover — Pydantic Literal blocks this
            return None, f"unknown transport: {mcp_cfg.transport!r}"

        toolset = McpToolset(
            connection_params=params,
            tool_filter=mcp_cfg.tool_filter,
        )
        return toolset, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _compose_instruction(
    working_context: str,
    skills_snippet: str,
    policy_mode: str,
    auto_route: bool = True,
    memory_snippet: str = "",
) -> str:
    """Assemble the root system prompt for a single turn.

    Header → env-specific working-context paragraph → tool-use guidance →
    sub-agent guidance → optional ``@``-mention protocol → optional skill
    catalog → optional memory registry line → optional plan-mode addendum.

    ``auto_route`` gates the ``@``-mention paragraph. When off, the
    root sees an unannotated user message and decides delegation
    normally — escape hatch for sessions where the routing directive
    misbehaves.

    ``memory_snippet`` (Slice S2) is a single line per active scope
    pointing at ``memory_read(scope, "schema.md")`` so the agent can
    discover the conventions on demand. Empty string = no memory yet,
    omit entirely.
    """
    parts = [ROOT_HEADER.rstrip(), working_context.rstrip(), ROOT_TAIL.rstrip()]
    if auto_route:
        parts.append(AT_MENTION_PROTOCOL.rstrip())
    if skills_snippet:
        parts.append(skills_snippet.rstrip())
    if memory_snippet:
        parts.append(memory_snippet.rstrip())
    prompt = "\n\n".join(parts) + "\n"
    if policy_mode == "plan":
        prompt = prompt + PLAN_MODE_ADDENDUM
    return prompt


def _env_description(ctx: ReadonlyContext) -> str:
    """Pull the session's env description paragraph out of state.

    Falls back to the managed-mode paragraph when no ``CoworkToolContext``
    is stashed yet (e.g. during static agent construction before any
    session has opened).
    """
    cowork_ctx = ctx.state.get(COWORK_CONTEXT_KEY)
    env = getattr(cowork_ctx, "env", None)
    if env is not None:
        return env.describe_for_prompt()
    return ROOT_WORKING_CONTEXT_FALLBACK


def _sub_agent_instruction(base: str):
    """Wrap a static sub-agent instruction string so it gets the same
    env-specific Working Context paragraph that the root prompt uses.

    Sub-agents delegate-to-and-from the root and share its session state,
    so they need the same path vocabulary. Without this, a desktop
    (local-dir) session handing work to ``writer`` would tell it to
    ``fs_write`` into ``scratch/`` — a namespace that doesn't exist.
    """

    def _instruction(ctx: ReadonlyContext) -> str:
        working_context = _env_description(ctx)
        return f"{working_context.rstrip()}\n\n{base.rstrip()}\n"

    return _instruction


def build_root_agent(
    cfg: CoworkConfig,
    tools: Sequence[BaseTool] | None = None,
    skills_snippet: str = "",
    skills: Any = None,
    mcp_tool_owner: dict[str, str] | None = None,
    memory: Any = None,
    custom_agents: CustomAgentRegistry | None = None,
) -> LlmAgent:
    # Dynamic instruction — resolved per turn so the working-context paragraph
    # reflects the session's ExecEnv and the policy-mode addendum reflects
    # whatever mode the session is currently in.
    #
    # ``skills``, when supplied, is the live ``SkillRegistry`` from the
    # runtime. We re-query its ``injection_snippet()`` on every turn so
    # skills installed mid-process (via POST /v1/skills) show up in
    # existing sessions' root prompt on the next model call without a
    # restart. Callers that don't pass it (tests, light harnesses)
    # fall back to the static ``skills_snippet`` string.
    def _dynamic_instruction(ctx: ReadonlyContext) -> str:
        working_context = _env_description(ctx)
        mode = ctx.state.get(COWORK_POLICY_MODE_KEY, cfg.policy.mode)
        # Auto-route defaults to True; any non-bool stored value is
        # ignored so a malformed state write can't silently turn the
        # feature off for the session.
        raw_auto_route = ctx.state.get(COWORK_AUTO_ROUTE_KEY, True)
        auto_route = raw_auto_route if isinstance(raw_auto_route, bool) else True
        # Per-session skill enable map — absent skill = enabled. Slice II.
        raw_enabled = ctx.state.get(COWORK_SKILLS_ENABLED_KEY, {})
        enabled_map: dict[str, bool] = (
            {k: bool(v) for k, v in raw_enabled.items() if isinstance(k, str)}
            if isinstance(raw_enabled, dict)
            else {}
        )
        if skills is not None:
            snippet = skills.injection_snippet(
                enabled=lambda name: enabled_map.get(name, True),
            )
        else:
            snippet = skills_snippet
        # Slice S2 — memory registry snippet. Single line per active
        # scope; empty string when both scopes have no pages (the
        # registry's own decision). Cheap: one ``store.list`` per
        # scope.
        memory_snippet = ""
        if memory is not None:
            cowork_ctx = ctx.state.get(COWORK_CONTEXT_KEY)
            if cowork_ctx is not None:
                try:
                    memory_snippet = memory.injection_snippet(cowork_ctx)
                except Exception:
                    memory_snippet = ""
        return _compose_instruction(
            working_context,
            snippet,
            mode,
            auto_route=auto_route,
            memory_snippet=memory_snippet,
        )

    root_model = build_model(cfg.model)
    # MCP toolsets are appended to ``tools`` by ``build_runtime``
    # before this function is called, so per-server status can live on
    # ``CoworkRuntime.mcp_status``. ``build_root_agent`` itself stays
    # MCP-config-agnostic.
    adk_tools: list[Any] = list(tools or [])

    def _resolve_agent(name: str, default_allowed: tuple[str, ...]) -> tuple[
        Any,  # model (LiteLlm)
        frozenset[str] | None,  # allowed_tools (None = no allowlist)
        frozenset[str],  # disallowed_tools
        tuple[str, ...],  # shell_allowlist (per-agent, W5)
    ]:
        """Layer cfg.agents[name] over the built-in defaults."""
        agent_cfg: AgentConfig | None = cfg.agents.get(name)
        # Model: explicit override beats inherited cfg.model.
        if agent_cfg is not None and agent_cfg.model is not None:
            agent_model = build_model(agent_cfg.model)
        else:
            agent_model = root_model
        # Allowed tools: cfg override beats per-agent default. ``[]``
        # is a valid override that silences the agent (no allowlisted
        # tools); only ``None`` falls back to defaults.
        if agent_cfg is not None and agent_cfg.allowed_tools is not None:
            allowed = frozenset(agent_cfg.allowed_tools)
        else:
            allowed = frozenset(default_allowed)
        # Disallowed tools: cfg additions only (defaults don't carry a
        # disallow list — the allowlist already encodes the surface).
        disallowed = (
            frozenset(agent_cfg.disallowed_tools)
            if agent_cfg is not None
            else frozenset()
        )
        # W5 — shell allowlist resolution: cfg override > per-agent
        # default > policy fallback. Only matters when the agent has
        # ``shell_run`` in its allowed tools; agents without it won't
        # exercise the shell gate at all.
        if agent_cfg is not None and agent_cfg.shell_allowlist is not None:
            shell_allow = tuple(agent_cfg.shell_allowlist)
        elif name in SUB_AGENT_SHELL_ALLOWLISTS:
            shell_allow = SUB_AGENT_SHELL_ALLOWLISTS[name]
        else:
            shell_allow = tuple(cfg.policy.shell_allowlist)
        return agent_model, allowed, disallowed, shell_allow

    # Policy + audit + model callbacks — applied to every agent (root +
    # sub-agents) so plan-mode enforcement, audit logging, and turn-budget
    # guards are uniform.
    permission_cb = make_permission_callback(cfg.policy)
    audit_before, audit_after = make_audit_callbacks()
    before_model_cb, after_model_cb = make_model_callbacks()
    # Slice VI — single MCP-disable callback closes over the runtime's
    # ``mcp_tool_owner`` map (populated at boot + restart). Mounted on
    # every agent so a disabled server's tools are blocked uniformly.
    # When ``mcp_tool_owner`` is None (light test harnesses) we skip
    # the callback entirely.
    mcp_disable_cb = (
        make_mcp_disable_callback(mcp_tool_owner)
        if mcp_tool_owner is not None
        else None
    )

    def _with_mcp(callbacks: list[Any]) -> list[Any]:
        return [mcp_disable_cb, *callbacks] if mcp_disable_cb is not None else callbacks

    # Root is unrestricted by the allowlist by design — the feature
    # scopes specialist sub-agents, not the primary interlocutor. Each
    # sub-agent gets its own allowlist closure so the callback can
    # know "which agent am I guarding" without reaching into ADK's
    # private ``InvocationContext``.
    # W5 — root's shell gate uses ``cfg.policy.shell_allowlist`` (the
    # historical global default). Sub-agents get per-agent allowlists
    # via ``_resolve_agent`` below.
    root_shell_allowlist = tuple(cfg.policy.shell_allowlist)
    root_before_tool_cbs = _with_mcp([
        make_shell_allowlist_gate("cowork_root", root_shell_allowlist),
        permission_cb,
        audit_before,
    ])
    after_tool_cbs = [audit_after]

    def _sub_before_tool(
        name: str,
        allowed: frozenset[str] | None,
        disallowed: frozenset[str],
        shell_allow: tuple[str, ...],
    ) -> list[Any]:
        # W1 — static gate runs FIRST so config-time allow/deny holds
        # even if an injected message flips the runtime allowlist.
        # W5 — shell allowlist gate runs after the static gate but
        # before the runtime allowlist so even a session-state
        # widening of shell_run can't bypass the per-agent shell
        # surface.
        return _with_mcp([
            make_static_agent_gate(name, allowed, disallowed),
            make_shell_allowlist_gate(name, shell_allow),
            make_allowlist_callback(name),
            permission_cb,
            audit_before,
        ])

    # Sub-agents share the tool list; per-agent model + allow/disallow
    # + shell allowlist are layered from ``cfg.agents.<name>`` on top
    # of built-in defaults.
    sub_agents: list[LlmAgent] = []
    for sub_name, (default_allowed, instruction) in SUB_AGENT_DEFAULTS.items():
        sub_model, allowed_set, disallowed_set, shell_allow = _resolve_agent(
            sub_name, default_allowed,
        )
        sub_agents.append(
            LlmAgent(
                name=sub_name,
                model=sub_model,
                instruction=_sub_agent_instruction(instruction),
                tools=adk_tools,
                before_tool_callback=_sub_before_tool(
                    sub_name, allowed_set, disallowed_set, shell_allow,
                ),
                after_tool_callback=after_tool_cbs,
                before_model_callback=before_model_cb,
                after_model_callback=after_model_cb,
            )
        )

    # W2 — register user-defined sub-agents loaded from Markdown.
    # Each custom agent comes with its own AgentConfig (tools + model
    # gates parsed from the frontmatter). When ``allowed_tools`` is
    # ``None`` in the frontmatter, the static gate runs with ``None``
    # too — meaning no allowlist (only the explicit ``disallowed_tools``
    # apply). This is intentional: built-in defaults exist for the four
    # known specialists; user-defined agents declare their own surface.
    if custom_agents is not None:
        for custom in custom_agents:
            custom_cfg = custom.config
            agent_model = (
                build_model(custom_cfg.model)
                if custom_cfg.model is not None
                else root_model
            )
            allowed_set: frozenset[str] | None = (
                frozenset(custom_cfg.allowed_tools)
                if custom_cfg.allowed_tools is not None
                else None
            )
            disallowed_set = frozenset(custom_cfg.disallowed_tools)
            # W5 — custom agents inherit the policy-level shell
            # allowlist unless their frontmatter declares one. Custom
            # agents that don't list shell_run in allowed_tools never
            # exercise the gate anyway.
            custom_shell_allow = (
                tuple(custom_cfg.shell_allowlist)
                if custom_cfg.shell_allowlist is not None
                else tuple(cfg.policy.shell_allowlist)
            )
            sub_agents.append(
                LlmAgent(
                    name=custom.name,
                    description=custom.description_prompt,
                    model=agent_model,
                    instruction=_sub_agent_instruction(custom.instruction),
                    tools=adk_tools,
                    before_tool_callback=_sub_before_tool(
                        custom.name, allowed_set, disallowed_set,
                        custom_shell_allow,
                    ),
                    after_tool_callback=after_tool_cbs,
                    before_model_callback=before_model_cb,
                    after_model_callback=after_model_cb,
                )
            )

    return LlmAgent(
        name="cowork_root",
        model=root_model,
        instruction=_dynamic_instruction,
        tools=adk_tools,
        sub_agents=sub_agents,
        before_tool_callback=root_before_tool_cbs,
        after_tool_callback=after_tool_cbs,
        before_model_callback=before_model_cb,
        after_model_callback=after_model_cb,
    )
