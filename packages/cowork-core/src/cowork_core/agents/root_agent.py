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

from cowork_core.agents.analyst import ANALYST_INSTRUCTION
from cowork_core.agents.researcher import RESEARCHER_INSTRUCTION
from cowork_core.agents.reviewer import REVIEWER_INSTRUCTION
from cowork_core.agents.writer import WRITER_INSTRUCTION
from cowork_core.config import CoworkConfig, McpServerConfig
from cowork_core.model.openai_compat import build_model
from cowork_core.policy.hooks import make_audit_callbacks
from cowork_core.policy.permissions import make_permission_callback

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
You have four specialist sub-agents. Delegate to them for complex tasks:
- **researcher**: Gather information from the web or project files. Use for
  research-heavy requests before drafting.
- **writer**: Draft or edit documents (memos, reports, emails, docx/xlsx).
- **analyst**: Analyze data, run calculations, produce charts and tables.
- **reviewer**: Review documents for quality, accuracy, and completeness.

For simple requests (read a file, quick answer), handle them yourself.
For multi-step workflows (research → draft → review), delegate to the
appropriate sub-agents in sequence.
"""

PLAN_MODE_ADDENDUM = """\

## PLAN MODE — ACTIVE

You are in **plan mode**. You MUST NOT execute any actions that modify files
or run commands. Instead:

1. **Read** existing files and research as needed to understand the request.
2. **Write a plan** to `scratch/plan.md` describing exactly what you would do:
   - List every file you would create or modify, with a brief description.
   - List every shell command you would run.
   - List every sub-agent you would delegate to and why.
   - Note any risks, assumptions, or questions for the user.
3. **Stop** after writing the plan. Do not proceed to execution.

The user will review your plan, and may switch to work mode to execute it.
Use `fs_write` to save the plan to `scratch/plan.md` — this is the ONE write
operation allowed in plan mode.
"""


def _build_mcp_toolset(mcp_cfg: McpServerConfig) -> Any | None:
    """Create an MCPToolset from config, or None if misconfigured."""
    if not mcp_cfg.command:
        return None
    try:
        from google.adk.tools.mcp_tool import MCPToolset, StdioConnectionParams
        from mcp.client.stdio import StdioServerParameters

        return MCPToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=mcp_cfg.command,
                    args=mcp_cfg.args,
                    env=mcp_cfg.env or None,
                ),
            ),
        )
    except Exception:
        return None


def build_root_agent(
    cfg: CoworkConfig,
    tools: Sequence[BaseTool] | None = None,
    skills_snippet: str = "",
) -> LlmAgent:
    base_instruction = ROOT_INSTRUCTION_BASE
    if skills_snippet:
        base_instruction = f"{ROOT_INSTRUCTION_BASE}\n{skills_snippet}\n"

    # Dynamic instruction — resolves at each turn based on current policy mode
    def _dynamic_instruction(_ctx: ReadonlyContext) -> str:
        if cfg.policy.mode == "plan":
            return base_instruction + PLAN_MODE_ADDENDUM
        return base_instruction

    model = build_model(cfg.model)
    adk_tools: list[Any] = list(tools or [])

    # Mount MCP servers as toolsets
    for _name, mcp_cfg in cfg.mcp_servers.items():
        toolset = _build_mcp_toolset(mcp_cfg)
        if toolset:
            adk_tools.append(toolset)

    # Policy callbacks
    permission_cb = make_permission_callback(cfg.policy)
    audit_before, audit_after = make_audit_callbacks()
    before_tool_cbs = [permission_cb, audit_before]
    after_tool_cbs = [audit_after]

    # Sub-agents share the same model and tools
    researcher = LlmAgent(
        name="researcher",
        model=model,
        instruction=RESEARCHER_INSTRUCTION,
        tools=adk_tools,
    )
    writer = LlmAgent(
        name="writer",
        model=model,
        instruction=WRITER_INSTRUCTION,
        tools=adk_tools,
    )
    analyst = LlmAgent(
        name="analyst",
        model=model,
        instruction=ANALYST_INSTRUCTION,
        tools=adk_tools,
    )
    reviewer = LlmAgent(
        name="reviewer",
        model=model,
        instruction=REVIEWER_INSTRUCTION,
        tools=adk_tools,
    )

    return LlmAgent(
        name="cowork_root",
        model=model,
        instruction=_dynamic_instruction,
        tools=adk_tools,
        sub_agents=[researcher, writer, analyst, reviewer],
        before_tool_callback=before_tool_cbs,
        after_tool_callback=after_tool_cbs,
    )
