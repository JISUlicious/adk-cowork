"""Reusable tool-group tuples shared across the per-agent
``*_DEFAULT_ALLOWED_TOOLS`` declarations.

Composing each agent's allowlist from named tuples instead of
flat lists makes the role-flow principle grep-visible:

- ``WEB_FULL`` is referenced by exactly one agent (researcher) — the
  one whose job is consuming untrusted web content.
- ``MEMORY_AUDIT`` is referenced by reviewer + verifier — the
  audit-trail roles.
- ``MEMORY_PRODUCTIVE`` is referenced by researcher / writer /
  analyst — the long-form-output roles.

Slice W4. The groups themselves carry no enforcement; the static
gate (W1) still operates on the final flat tuple each module
exposes via ``*_DEFAULT_ALLOWED_TOOLS``.
"""

from __future__ import annotations


READ_ONLY_FS: tuple[str, ...] = (
    "fs_read", "fs_glob", "fs_list", "fs_stat",
)


WEB_LOOKUP: tuple[str, ...] = (
    # Cheap, safer fact-check — for roles that draft / compute and
    # occasionally need a single-fact verify mid-flight.
    "search_web",
)


WEB_FULL: tuple[str, ...] = (
    # Raw page fetch — only the researcher consumes untrusted HTML
    # (redirects, parse, etc.). Other roles delegate to researcher
    # if they need the full page.
    "search_web", "http_fetch",
)


MEMORY_PRODUCTIVE: tuple[str, ...] = (
    # Long-form output roles: read pages, write/overwrite named
    # pages, drop quick scratch notes for next-turn organisation.
    # No ``memory_log`` — that's the audit trail, separate role.
    "memory_read", "memory_write", "memory_remember",
)


MEMORY_AUDIT: tuple[str, ...] = (
    # Audit / check roles: read pages, append chronological log
    # entries. No ``write`` / ``remember`` — these roles aren't
    # producing pages; they're recording observations.
    "memory_read", "memory_log",
)


__all__ = [
    "READ_ONLY_FS",
    "WEB_LOOKUP",
    "WEB_FULL",
    "MEMORY_PRODUCTIVE",
    "MEMORY_AUDIT",
]
