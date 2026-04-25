"""Memory subsystem (Slice S2) — Karpathy's "LLM Wiki" pattern on
top of the S1 storage protocols.

Two scopes (``user`` + ``project``), each with the same on-disk shape:

    schema.md     # conventions; bundled default copied on bootstrap
    index.md      # catalog of pages, agent-maintained
    log.md        # append-only ``[YYYY-MM-DD] kind | title`` entries
    pages/        # agent-authored markdown
    raw/          # user-uploaded sources (agent treats as read-only)

Four agent-callable tools — file-I/O primitives; the LLM does the
synthesis driven by the schema:

* ``memory_read(scope, name)``      — read schema/index/log/page
* ``memory_write(scope, name, ...)`` — create or overwrite (allowed
                                       targets: ``index.md``,
                                       ``pages/*.md``)
* ``memory_log(scope, kind, title)`` — append a dated log entry
* ``memory_remember(content, scope)`` — append a timestamped scratch
                                        note; agent's next turn does
                                        proper filing per the schema

Bootstrap is lazy: every memory tool calls ``_ensure_bootstrapped``
which copies the bundled default schema if the scope's
``schema.md`` is missing. Idempotent on existing stores.

Per-turn prompt injection is one line per active scope (page count
+ pointer to ``memory_read(scope, "schema.md")``) — full schemas
load on demand, mirroring how skills inject name + description and
load the body via ``load_skill``.
"""

from __future__ import annotations

from cowork_core.memory.registry import MemoryRegistry
from cowork_core.memory.tools import register_memory_tools

__all__ = [
    "MemoryRegistry",
    "register_memory_tools",
]
