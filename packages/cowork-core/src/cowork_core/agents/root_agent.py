"""Root Cowork agent.

M0 was a tool-less orchestrator. M1 wires the execution-surface tools
(`fs.*`, `shell.run`, `python_exec`, `http.fetch`, `search.web`, `load_skill`)
and a skill-registry injection snippet so the agent can actually *do* office
work. M3 will add sub-agents via ADK's ``sub_agents`` parameter.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools.base_tool import BaseTool

from cowork_core.config import CoworkConfig
from cowork_core.model.openai_compat import build_model

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
"""


def build_root_agent(
    cfg: CoworkConfig,
    tools: Sequence[BaseTool] | None = None,
    skills_snippet: str = "",
) -> LlmAgent:
    instruction = ROOT_INSTRUCTION_BASE
    if skills_snippet:
        instruction = f"{ROOT_INSTRUCTION_BASE}\n{skills_snippet}\n"
    adk_tools: list[Any] = list(tools or [])
    return LlmAgent(
        name="cowork_root",
        model=build_model(cfg.model),
        instruction=instruction,
        tools=adk_tools,
    )
