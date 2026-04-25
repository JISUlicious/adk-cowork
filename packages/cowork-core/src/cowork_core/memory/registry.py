"""``MemoryRegistry`` — per-turn prompt injection snippet.

Cheap: one ``store.list`` per scope to count pages. Mirrors how
skills inject ``injection_snippet`` per turn from a live registry.
The agent loads the actual schema on demand via
``memory_read(scope, "schema.md")`` — full schemas are NOT eagerly
injected into the prompt (would violate the existing budget
convention skills established with ``DESCRIPTION_PROMPT_CAP``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cowork_core.tools.base import CoworkToolContext


class MemoryRegistry:
    """Computes the per-turn prompt snippet for memory stores.

    Stateless — instantiate once per runtime, call
    ``injection_snippet(ctx)`` per turn. The page count comes from
    ``store.list(prefix="memory/pages/")`` so it reflects whatever
    the agent has filed by the time the next turn starts.
    """

    def injection_snippet(self, ctx: "CoworkToolContext") -> str:
        """Return a one-line registry snippet, or ``""`` when both
        scopes are empty (no memory yet → no point cluttering the
        prompt with a 'no memory' line)."""
        user_pages = self._page_count_user(ctx)
        project_pages = self._page_count_project(ctx)
        if user_pages == 0 and project_pages == 0:
            return ""
        return (
            f"Memory: 'user' ({user_pages} pages) · "
            f"'project' ({project_pages} pages). "
            f"Read `memory_read(scope, \"schema.md\")` for conventions."
        )

    def _page_count_user(self, ctx: "CoworkToolContext") -> int:
        try:
            keys = ctx.user_store.list(ctx.user_id, "memory/pages/")
        except Exception:
            return 0
        return sum(1 for k in keys if k.endswith(".md"))

    def _page_count_project(self, ctx: "CoworkToolContext") -> int:
        from cowork_core.memory.bootstrap import _project_id

        try:
            keys = ctx.project_store.list(
                ctx.user_id, _project_id(ctx), "memory/pages/",
            )
        except Exception:
            return 0
        return sum(1 for k in keys if k.endswith(".md"))
