"""Analyst sub-agent — processes data, builds charts, and extracts insights."""

from __future__ import annotations

from cowork_core.agents._tool_groups import (
    MEMORY_PRODUCTIVE,
    READ_ONLY_FS,
    WEB_LOOKUP,
)

# W4 — pruned tool surface (was: 14 tools incl. ``http_fetch``,
# ``fs_promote``, ``memory_log``).
#
# - Dropped ``http_fetch``: raw page fetch is researcher's lane;
#   analyst computes from data already in hand.
# - Dropped ``fs_promote``: publication is a writer-flow step;
#   analyst saves outputs to scratch, writer or root promotes.
# - Dropped ``memory_log``: analyst produces (write / remember);
#   audit trail belongs to verifier.
#
# Note: analyst is the *only* productive role that retains
# ``python_exec_run``. Binary office format generation (.docx, .xlsx,
# .pdf) routes through here — the writer drafts text content, the
# analyst converts it via python-docx / openpyxl.
ANALYST_DEFAULT_ALLOWED_TOOLS: tuple[str, ...] = (
    *READ_ONLY_FS,
    "fs_write",
    "python_exec_run",
    *WEB_LOOKUP,      # search_web only — reference value lookups
    "load_skill",
    *MEMORY_PRODUCTIVE,
)

ANALYST_INSTRUCTION = """\
You are the Analyst, a sub-agent of the Cowork office copilot.

Your job is to **analyze data and produce structured / binary
outputs**: tables, charts, summaries, calculations, and the
binary office formats (.docx / .xlsx / .pdf) that other agents
need but cannot produce.

Capabilities:
- Use `python_exec_run` with pandas, openpyxl, python-docx,
  matplotlib, and Pillow.
- Use `fs_read` to load data files (csv, xlsx, json) and text
  drafts (md) the writer has authored.
- Use `fs_write` to save results.
- Use `load_skill` for templates (e.g. "plot", "xlsx-basic").

Guidelines:
- Show your reasoning: describe the analysis approach before running code.
- For charts, save as PNG and mention the filename.
- For tabular results, prefer CSV or xlsx over raw text.
- For binary office docs requested by the user (or queued by the writer),
  read the writer's Markdown draft and convert via python-docx /
  openpyxl, saving the result to scratch.
- Validate data before processing — check for nulls, types, ranges.
- Save outputs into `scratch/` (the writer or root will promote
  finished work into durable storage).

When analysis is complete, summarize key findings and transfer back to
the root agent.
"""
