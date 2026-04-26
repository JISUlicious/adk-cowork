"""Planner sub-agent — architectural plan writer.

W3 — borrowed from Claude Code's ``Plan`` agent. The Planner reads
the project, gathers references, and emits a step-by-step plan
(files to create/modify, commands to run, sub-agent delegations,
risks). It does NOT execute.

Strong fit with Cowork's Plan/Work policy mode: when the session is
in plan mode, the root prefers delegating the planning work here so
the plan is authored by a specialist whose surface guarantees
read-only behaviour at the gate level.
"""

from __future__ import annotations

# W1 — read-only by design (mirrors how plan mode is enforced at the
# policy layer; the static gate adds defence-in-depth).
PLANNER_DEFAULT_ALLOWED_TOOLS: tuple[str, ...] = (
    "fs_read", "fs_glob", "fs_list", "fs_stat",
    # Plan mode allows fs_write only to scratch/plan.md — that's
    # enforced by the policy callback, not the static gate. Without
    # fs_write here the planner literally can't even write the plan.
    "fs_write",
    "search_web",
    "load_skill",
    "memory_read",
)

PLANNER_INSTRUCTION = """\
You are the Planner, a sub-agent of the Cowork office copilot.

Your job is to **design plans before action** — read the project,
research the requirement, and emit a detailed step-by-step plan.

Capabilities:
- Use `fs_read` / `fs_glob` / `fs_list` / `fs_stat` to understand the
  existing materials.
- Use `search_web` for fact-checking + reference gathering.
- Use `load_skill` to surface format-specific templates.
- Use `fs_write` only to save the final plan to `scratch/plan.md`.

Guidelines:
- Read first; only then plan.
- Plans should be concrete: list every file you would create / modify
  / delete, every shell command you would run, every sub-agent you
  would delegate to (and why), and every source you would cite.
- You are read-only **except for `scratch/plan.md`**; do NOT modify
  anything else.
- Surface risks, assumptions, and questions for the user explicitly.

When the plan is written to `scratch/plan.md`, summarise the headline
sections and transfer back. The user (or another agent in work mode)
will execute it.
"""
