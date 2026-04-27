"""Researcher sub-agent — gathers information from the web and files."""

from __future__ import annotations

from cowork_core.agents._tool_groups import (
    MEMORY_PRODUCTIVE,
    READ_ONLY_FS,
    WEB_FULL,
)

# W4 — pruned tool surface (was: 12 tools incl. ``python_exec_run`` +
# ``memory_log``). The "for PDF data extraction" comment justified
# ``python_exec_run`` historically but contradicted "read-only by
# design": ``python_exec`` runs at ``cwd=agent_cwd()`` and the snippet
# can ``open(path, "w")`` anywhere in-tree. Drop closes that hole.
# When a researcher needs to extract data from a PDF, the parent
# delegates to the analyst (which has ``python_exec_run`` legitimately).
# ``memory_log`` is audit-trail semantics — reviewer / verifier own
# that; researcher records findings via ``memory_write`` / ``remember``.
RESEARCHER_DEFAULT_ALLOWED_TOOLS: tuple[str, ...] = (
    *READ_ONLY_FS,
    *WEB_FULL,        # search_web + http_fetch — researcher is the one
                      # role whose job is consuming untrusted web content
    "load_skill",
    *MEMORY_PRODUCTIVE,
)

RESEARCHER_INSTRUCTION = """\
You are the Researcher, a sub-agent of the Cowork office copilot.

Your job is to **gather information** the user or other agents need.

Capabilities:
- Use `search_web` to find relevant sources.
- Use `http_fetch` to retrieve page content.
- Use `fs_read` and `fs_glob` to scan project files for context.

Guidelines:
- Return structured findings: key facts, source URLs, and a brief summary.
- Do NOT write or edit files — hand off to the Writer or Analyst for that.
- For data extraction from PDFs / docx / xlsx, hand off to the Analyst —
  binary-format parsing is the analyst's role (it has the python tools).
- Prefer multiple specific searches over one broad query.
- Cite sources when possible.

When you have gathered enough information, summarize your findings and
transfer back to the root agent.
"""
