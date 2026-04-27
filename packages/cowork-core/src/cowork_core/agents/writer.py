"""Writer sub-agent — drafts and edits documents."""

from __future__ import annotations

from cowork_core.agents._tool_groups import (
    MEMORY_PRODUCTIVE,
    READ_ONLY_FS,
    WEB_LOOKUP,
)

# W4 — pruned tool surface (was: 16 tools incl. ``python_exec_run``,
# ``http_fetch``, ``memory_log``).
#
# - Dropped ``python_exec_run``: text formats (.md, .txt, .html, .csv,
#   .eml, .json, .xml) are all reachable via plain ``fs_write``. The
#   only thing it actually bought the writer was binary office formats
#   (.docx / .xlsx / .pdf), and those are analyst's lane (analyst has
#   ``python_exec_run`` legitimately, plus openpyxl / python-docx).
#   Keeping it on the writer too was a Turing-complete escape hatch on
#   what should be a text-producer role.
# - Dropped ``http_fetch``: raw page fetch is researcher's lane;
#   writer drafts from material the researcher already gathered.
# - Dropped ``memory_log``: writer produces (write / remember are the
#   right tools); audit trail is reviewer / verifier territory.
WRITER_DEFAULT_ALLOWED_TOOLS: tuple[str, ...] = (
    *READ_ONLY_FS,
    "fs_write", "fs_edit", "fs_promote",
    *WEB_LOOKUP,      # search_web only — single-fact verify mid-draft
    "load_skill",
    "email_draft",    # composing yes; sending is for the user via approval
    *MEMORY_PRODUCTIVE,
)

WRITER_INSTRUCTION = """\
You are the Writer, a sub-agent of the Cowork office copilot.

Your job is to **create and edit text-based documents**: memos,
reports, emails, markdown notes, HTML, CSV, and other text content.

Capabilities:
- Use `fs_write` to create files.
- Use `fs_read` + `fs_edit` to revise existing files.
- Use `load_skill` to fetch format-specific templates (e.g. "email-draft",
  "md", "docx-basic" — for the docx skill, you author the source text;
  the analyst converts it to .docx).
- Use `fs_promote` to move finished drafts into durable storage
  (managed-mode sessions only — returns an error in local-dir sessions,
  where files already live alongside the user's own).

Guidelines:
- Match the user's tone and formality level.
- Keep documents well-structured with clear headings.
- For binary office formats (.docx, .xlsx, .pdf), draft the content
  as Markdown and hand off to the Analyst — binary-format generation
  is the analyst's role (it has python-docx / openpyxl access).
- Follow the Working Context block above for where drafts should live.

When you have finished drafting, summarize what you wrote and transfer
back to the root agent.
"""
