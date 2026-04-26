"""Atomic TOML rewriter for ``cowork.toml`` (Slice T1, V4a).

Reads the full file, applies a patch dict to a named section, writes
via temp+rename. Used by the Settings UI's PUT routes for
``[model]`` and ``[compaction]``.

V4a — migrated from ``tomli_w`` to ``tomlkit`` so comments + custom
whitespace from the pre-write TOML are preserved across edits.
``tomlkit`` round-trips a ``TOMLDocument`` that's dict-like enough
for our patch + assign API while keeping format fidelity. The reader
returns a plain ``dict`` so callers don't need to know about
tomlkit's container types.

The writer is deliberately section-scoped so a UI editing only
``[model]`` can't accidentally clobber ``[mcp_servers.foo]`` or
similar table-of-tables data the user maintains by hand.
"""

from __future__ import annotations

import os
import secrets
import threading
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.exceptions import TOMLKitError


class ConfigWriteError(Exception):
    """Raised when the TOML can't be loaded, validated, or written."""


def update_toml_section(
    path: Path,
    section: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Read TOML at ``path``, merge ``patch`` into the top-level
    ``[section]`` table, write back atomically. Returns the merged
    full config as a plain ``dict`` so the caller can echo just the
    touched section back to the client.

    ``patch`` keys with ``None`` values are dropped (client signals
    "leave alone"). All other keys overwrite. Nested tables are not
    handled — this is deliberately section-scoped.

    Comments + whitespace from the original TOML are preserved
    across the round-trip (V4a — was lost under ``tomli_w``).
    """
    if not path.is_file():
        raise ConfigWriteError(f"config file not found: {path}")
    try:
        doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    except TOMLKitError as exc:
        raise ConfigWriteError(f"invalid TOML at {path}: {exc}") from exc

    current = doc.get(section)
    # Treat missing or non-table sections specially. tomlkit returns
    # ``Table`` objects for ``[section]`` blocks; anything else is a
    # shape error.
    if current is None:
        # Create a fresh table at the bottom of the document.
        current = tomlkit.table()
        doc[section] = current
    elif not _is_table(current):
        raise ConfigWriteError(
            f"section [{section}] in {path} is not a table",
        )

    for key, value in patch.items():
        if value is None:
            continue
        current[key] = value

    try:
        rendered = tomlkit.dumps(doc)
    except Exception as exc:
        raise ConfigWriteError(f"failed to serialise TOML: {exc}") from exc

    _atomic_write_text(path, rendered)
    # Convert to plain dict for callers — tomlkit Tables behave
    # dict-ish but aren't ``isinstance(_, dict)``-true under all
    # checks downstream.
    return _doc_to_dict(doc)


def _is_table(value: Any) -> bool:
    """tomlkit returns ``Table`` (or ``InlineTable``) for ``[x]``
    blocks; both behave like dicts. We accept either."""
    return hasattr(value, "items") and hasattr(value, "__getitem__")


def _doc_to_dict(doc: Any) -> dict[str, Any]:
    """Coerce a tomlkit document/table into nested plain dicts so
    callers can use ``isinstance(value, dict)`` without surprises."""
    if hasattr(doc, "unwrap"):
        return doc.unwrap()
    return dict(doc)


def _atomic_write_text(path: Path, text: str) -> None:
    """Atomic temp+rename write. Mixes pid/tid/nonce into the temp
    suffix so concurrent writers (two browsers saving model +
    compaction at the same time) don't collide on the same temp
    path. Same pattern the Slice S1 ``_atomic_write`` uses for the
    storage layer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = (
        f".{os.getpid()}.{threading.get_ident()}."
        f"{secrets.token_hex(4)}.tmp"
    )
    tmp = path.with_suffix(path.suffix + suffix)
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
