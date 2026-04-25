"""Four agent-callable memory tools (Slice S2).

File-I/O primitives over the S1 stores; the LLM does the actual
synthesis driven by ``schema.md``. Same shape, same call sites in
single-user (FS) and multi-user (SQLite) mode — the storage
abstraction routes appropriately.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Literal

from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from cowork_core.memory.bootstrap import (
    MemoryScope,
    _project_id,
    ensure_bootstrapped,
    is_writable_target,
    memory_key,
)
from cowork_core.tools.base import get_cowork_context
from cowork_core.tools.registry import ToolRegistry

# Log entry kinds — alphanumeric + underscore only, so a malicious
# input can't smuggle markdown into the log.
_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def memory_read(
    scope: Literal["user", "project"],
    name: str,
    tool_context: ToolContext,
) -> dict[str, object]:
    """Read a file from the memory store for ``scope``.

    Args:
        scope: ``"user"`` (cross-project, ``~/.config/cowork/`` in
            single-user mode) or ``"project"`` (per-project,
            ``<workdir>/.cowork/`` in single-user mode).
        name: Path within the memory store. Examples:
            ``"schema.md"``, ``"index.md"``, ``"log.md"``,
            ``"pages/scratch.md"``.

    Returns:
        ``{"name": ..., "content": ..., "scope": ...}`` on success,
        ``{"error": ...}`` if the path is missing or invalid.
    """
    ctx = get_cowork_context(tool_context)
    try:
        ensure_bootstrapped(ctx, scope)  # type: ignore[arg-type]
        key = memory_key(name)
    except ValueError as exc:
        return {"error": str(exc)}

    if scope == "user":
        body = ctx.user_store.read(ctx.user_id, key)
    else:
        body = ctx.project_store.read(
            ctx.user_id, _project_id(ctx), key,
        )
    if body is None:
        return {"error": f"memory not found: {scope}:{name}"}
    return {
        "scope": scope,
        "name": name,
        "content": body.decode("utf-8", errors="replace"),
    }


def memory_write(
    scope: Literal["user", "project"],
    name: str,
    content: str,
    tool_context: ToolContext,
) -> dict[str, object]:
    """Create or overwrite a memory page (or the index).

    Allowed targets: ``index.md`` and ``pages/*.md``. ``schema.md``
    is user-editable only (the schema governs the agent; the agent
    shouldn't rewrite its own conventions). ``log.md`` is
    ``memory_log``-only (atomic append). ``raw/*`` is sacred —
    user-uploaded sources only.

    Args:
        scope: ``"user"`` or ``"project"``.
        name: Path within the memory store.
        content: UTF-8 markdown text. Always overwrites; use
            ``memory_log`` to append.

    Returns:
        ``{"scope": ..., "name": ..., "bytes": <int>}`` on success,
        ``{"error": ...}`` on rejection.
    """
    ctx = get_cowork_context(tool_context)
    if not is_writable_target(name):
        return {
            "error": (
                f"memory_write target {name!r} not allowed; "
                f"valid targets are 'index.md' and 'pages/*.md'. "
                f"Use memory_log() to append to log.md, and don't "
                f"write to schema.md (user-edited) or raw/ (uploads)."
            ),
        }
    try:
        ensure_bootstrapped(ctx, scope)  # type: ignore[arg-type]
        key = memory_key(name)
    except ValueError as exc:
        return {"error": str(exc)}

    body = content.encode("utf-8")
    if scope == "user":
        ctx.user_store.write(ctx.user_id, key, body)
    else:
        ctx.project_store.write(
            ctx.user_id, _project_id(ctx), key, body,
        )
    return {"scope": scope, "name": name, "bytes": len(body)}


def memory_log(
    scope: Literal["user", "project"],
    kind: str,
    title: str,
    body: str = "",
    tool_context: ToolContext = None,  # type: ignore[assignment]
) -> dict[str, object]:
    """Append a chronological entry to the scope's ``log.md``.

    The server stamps the date so the format stays consistent
    across agents and turns.

    Args:
        scope: ``"user"`` or ``"project"``.
        kind: Short event kind, lowercase + underscore + digits only
            (e.g. ``"ingest"``, ``"query"``, ``"lint"``,
            ``"remember"``). Constrained so a malicious value can't
            inject markdown into the log.
        title: One-line title shown in the entry header.
        body: Optional longer body. Empty = header line only.

    Resulting entry:

        ## [YYYY-MM-DD] <kind> | <title>

        <body>
    """
    if tool_context is None:
        return {"error": "tool_context is required"}
    ctx = get_cowork_context(tool_context)
    if not _KIND_PATTERN.match(kind):
        return {
            "error": (
                f"memory_log kind {kind!r} invalid; must match "
                f"^[a-z][a-z0-9_]{{0,31}}$"
            ),
        }
    if not title.strip():
        return {"error": "memory_log title must be non-empty"}
    if "\n" in title:
        return {"error": "memory_log title must be a single line"}

    try:
        ensure_bootstrapped(ctx, scope)  # type: ignore[arg-type]
    except ValueError as exc:
        return {"error": str(exc)}

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    entry = f"\n## [{today}] {kind} | {title.strip()}\n"
    if body.strip():
        entry += f"\n{body.rstrip()}\n"

    log_key = memory_key("log.md")
    if scope == "user":
        existing = ctx.user_store.read(ctx.user_id, log_key) or b""
        ctx.user_store.write(
            ctx.user_id, log_key, existing + entry.encode("utf-8"),
        )
    else:
        project = _project_id(ctx)
        existing = ctx.project_store.read(ctx.user_id, project, log_key) or b""
        ctx.project_store.write(
            ctx.user_id, project, log_key, existing + entry.encode("utf-8"),
        )
    return {"scope": scope, "kind": kind, "title": title}


def memory_remember(
    content: str,
    scope: Literal["user", "project"] = "project",
    tool_context: ToolContext = None,  # type: ignore[assignment]
) -> dict[str, object]:
    """Append a timestamped scratch note to ``pages/scratch.md``.

    Stays dumb on purpose — the agent's *next* turn (per the
    schema's "Remember" workflow) decides whether the note belongs
    in an existing page or a new one and moves it accordingly.

    Default scope is ``"project"`` since most "remember X" requests
    are project-bound. Pass ``scope="user"`` for cross-project
    facts.
    """
    if tool_context is None:
        return {"error": "tool_context is required"}
    ctx = get_cowork_context(tool_context)
    if not content.strip():
        return {"error": "memory_remember content must be non-empty"}

    try:
        ensure_bootstrapped(ctx, scope)  # type: ignore[arg-type]
    except ValueError as exc:
        return {"error": str(exc)}

    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n## [{timestamp}] note\n\n{content.rstrip()}\n"

    scratch_key = memory_key("pages/scratch.md")
    if scope == "user":
        existing = ctx.user_store.read(ctx.user_id, scratch_key) or b""
        ctx.user_store.write(
            ctx.user_id, scratch_key, existing + entry.encode("utf-8"),
        )
    else:
        project = _project_id(ctx)
        existing = ctx.project_store.read(
            ctx.user_id, project, scratch_key,
        ) or b""
        ctx.project_store.write(
            ctx.user_id, project, scratch_key,
            existing + entry.encode("utf-8"),
        )
    return {
        "scope": scope,
        "name": "pages/scratch.md",
        "appended_bytes": len(entry.encode("utf-8")),
    }


def register_memory_tools(registry: ToolRegistry) -> None:
    """Register the four memory tools."""
    registry.register(FunctionTool(memory_read))
    registry.register(FunctionTool(memory_write))
    registry.register(FunctionTool(memory_log))
    registry.register(FunctionTool(memory_remember))
