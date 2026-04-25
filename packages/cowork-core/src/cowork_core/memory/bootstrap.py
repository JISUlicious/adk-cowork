"""Memory store bootstrap + path helpers.

Lazy bootstrap on first ``memory_*`` call: if the scope's
``memory/schema.md`` is missing, copy the bundled default. Idempotent
on existing stores.

Key conventions: every memory artifact lives under the ``memory/``
prefix in its scope's store. Path-shaped string keys
(``"memory/pages/scratch.md"``) work identically against the FS and
SQLite backings — the FS resolver maps them to relative file paths,
SQLite tokenizes them as opaque keys.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from cowork_core.tools.base import CoworkToolContext

MemoryScope = Literal["user", "project"]

# Allowed write targets. Reject everything else so the agent can't
# clobber ``schema.md`` (user-only) or ``log.md`` (use ``memory_log``)
# or anything under ``raw/`` (user uploads, sacred).
_WRITE_TOP_LEVEL_ALLOWED = {"index.md"}
_WRITE_PREFIX_ALLOWED = "pages/"


def memory_key(name: str) -> str:
    """Wrap a relative path inside the memory store's namespace.
    All memory artifacts live under ``memory/<name>``."""
    if not name:
        raise ValueError("memory key name must be non-empty")
    if name.startswith("/") or "\\" in name or ".." in name.split("/"):
        raise ValueError(f"memory key name {name!r} is not a clean relative path")
    return f"memory/{name}"


def is_writable_target(name: str) -> bool:
    """``True`` for the paths the agent may overwrite via
    ``memory_write``. ``schema.md`` is user-only; ``log.md`` is
    ``memory_log``-only; ``raw/*`` is user-uploaded."""
    if name in _WRITE_TOP_LEVEL_ALLOWED:
        return True
    return name.startswith(_WRITE_PREFIX_ALLOWED) and name.endswith(".md")


def bundled_default_schema() -> str:
    """Return the bundled default schema.md as text. Lives next to
    this module under ``bundled/`` (same pattern as
    ``cowork_core/skills/bundled/<skill>/SKILL.md``)."""
    path = Path(__file__).parent / "bundled" / "default_schema.md"
    return path.read_text(encoding="utf-8")


def ensure_bootstrapped(ctx: "CoworkToolContext", scope: MemoryScope) -> None:
    """Copy the bundled default ``schema.md`` into the scope's
    memory store if it's missing. Cheap on the steady state — one
    ``store.read`` to check + one ``store.write`` only on the first
    call per scope, ever."""
    key = memory_key("schema.md")
    if scope == "user":
        existing = ctx.user_store.read(ctx.user_id, key)
        if existing is None:
            ctx.user_store.write(
                ctx.user_id, key, bundled_default_schema().encode("utf-8"),
            )
    else:  # project
        project_id = _project_id(ctx)
        existing = ctx.project_store.read(ctx.user_id, project_id, key)
        if existing is None:
            ctx.project_store.write(
                ctx.user_id, project_id, key,
                bundled_default_schema().encode("utf-8"),
            )


def _project_id(ctx: "CoworkToolContext") -> str:
    """Resolve the right ``project`` argument for ``ProjectStore``.

    Single-user mode (FS backing) — the resolver expects a workdir
    path string, so we pass ``str(ctx.project.root)``. Multi-user mode
    (SQLite backing) — the value is an opaque key; using the absolute
    path keeps SU and MU parallel and avoids a backing-detection
    branch in every memory tool. The path string is unique per
    (user, project) in both modes.
    """
    return str(ctx.project.root)
