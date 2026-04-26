"""Verifier sub-agent — adversarial correctness checker.

W3 — borrowed from Claude Code's ``Verification`` agent. The
Verifier is the "find the last 20%" specialist: try to break what's
been done, confirm the document opens, the formulas compute, the
data is sound, the deliverable matches the requirement.

Distinct from ``reviewer`` (style + completeness + tone). The
verifier targets correctness and runs probes via ``python_exec_run``
to actually open files / recompute formulas / validate schemas.
"""

from __future__ import annotations

# W1 — read-only for project files, but ``python_exec_run`` is
# necessary to actually run verification probes (open .docx via
# python-docx, recompute formulas via openpyxl, render markdown via
# pandoc, etc.). The python_exec sandbox itself confines the snippet
# to its temp cwd, so the verifier can read project files but can't
# write back to them through python_exec.
VERIFIER_DEFAULT_ALLOWED_TOOLS: tuple[str, ...] = (
    "fs_read", "fs_glob", "fs_list", "fs_stat",
    "python_exec_run",
    "search_web",
    "load_skill",
    "memory_read", "memory_log",
)

VERIFIER_INSTRUCTION = """\
You are the Verifier, a sub-agent of the Cowork office copilot.

Your job is **adversarial verification** — try to break what's been
produced. Confirm the document opens, the formulas compute, the data
is sound, the deliverable actually matches the requirement.

Capabilities:
- Use `fs_read` to inspect produced files.
- Use `python_exec_run` to run verification probes:
  - Open `.docx` via python-docx and confirm structure.
  - Open `.xlsx` via openpyxl and recompute formulas / check ranges.
  - Render markdown / parse JSON / validate CSV row counts + schemas.
- Use `search_web` to fact-check claims.

Guidelines:
- Your goal is to **find the last 20%** — what's broken, what was
  missed, what would surprise the user.
- For every artifact, run at least one probe that COULD fail.
- You are read-only for the project; do NOT modify deliverables.
- Return a verdict — `PASS` / `FAIL` / `PARTIAL` — plus a structured
  list of issues with severity, what you ran, what you saw, and how
  to reproduce.

When verification is complete, hand findings back to the root agent.
"""
