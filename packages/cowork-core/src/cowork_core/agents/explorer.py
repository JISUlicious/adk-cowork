"""Explorer sub-agent — fast read-only file/keyword navigator.

W3 — borrowed from Claude Code's ``Explore`` agent (which runs on
Haiku for speed). Cowork's Explorer is the same idea: a read-only
specialist for "find me X across the workspace" queries that the
root would otherwise burn its main-model context on.

Operators who want the speed/cost benefit can set
``cfg.agents.explorer.model`` (W1) to a cheaper OpenAI-compatible
endpoint without changing the writer/analyst's model.
"""

from __future__ import annotations

# W1 — strict read-only. No python_exec, no http_fetch (search is
# enough for online refs without arbitrary URL fetches), no email,
# no fs mutation.
EXPLORER_DEFAULT_ALLOWED_TOOLS: tuple[str, ...] = (
    "fs_read", "fs_glob", "fs_list", "fs_stat",
    "search_web",
    "memory_read",
)

EXPLORER_INSTRUCTION = """\
You are the Explorer, a sub-agent of the Cowork office copilot.

Your job is to **find information fast** — locate files, scan
directories, identify references the user or other agents need.

Capabilities:
- Use `fs_glob` + `fs_list` + `fs_stat` to navigate directory structure.
- Use `fs_read` to peek at specific files.
- Use `search_web` for online references.

Guidelines:
- Be fast and lean. Return paths, line numbers, or URLs — not full
  content dumps unless asked.
- Prefer multiple specific globs over one wide read.
- You are **read-only**; do NOT write, edit, or run anything.
- Output a concise structured listing (paths + 1-line summary each).

When you have enough findings, transfer back to the root agent.
"""
