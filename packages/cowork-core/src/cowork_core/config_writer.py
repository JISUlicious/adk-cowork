"""Atomic TOML rewriter for ``cowork.toml`` (Slice T1).

Reads the full file, applies a patch dict to a named section, writes
via temp+rename. Used by the Settings UI's PUT routes for
``[model]`` and ``[compaction]``. Comments and custom whitespace
from the pre-write TOML are NOT preserved — ``tomli_w`` is a
straightforward writer, not a round-tripper.

The writer is deliberately section-scoped so a UI editing only
``[model]`` can't accidentally clobber ``[mcp_servers.foo]`` or
similar table-of-tables data the user maintains by hand.
"""

from __future__ import annotations

import os
import secrets
import threading
import tomllib
from pathlib import Path
from typing import Any

import tomli_w


class ConfigWriteError(Exception):
    """Raised when the TOML can't be loaded, validated, or written."""


def update_toml_section(
    path: Path,
    section: str,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """Read TOML at ``path``, merge ``patch`` into the top-level
    ``[section]`` table, write back atomically. Returns the merged
    full config dict so the caller can echo just the touched section
    back to the client.

    ``patch`` keys with ``None`` values are dropped (client signals
    "leave alone"). All other keys overwrite. Nested tables are not
    handled — this is deliberately section-scoped.
    """
    if not path.is_file():
        raise ConfigWriteError(f"config file not found: {path}")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigWriteError(f"invalid TOML at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigWriteError(f"TOML root at {path} is not a table")

    current = data.get(section)
    if current is None:
        current = {}
    elif not isinstance(current, dict):
        raise ConfigWriteError(
            f"section [{section}] in {path} is not a table",
        )

    merged = dict(current)
    for key, value in patch.items():
        if value is None:
            continue
        merged[key] = value
    data[section] = merged

    try:
        rendered = tomli_w.dumps(data)
    except Exception as exc:
        raise ConfigWriteError(f"failed to serialise TOML: {exc}") from exc

    _atomic_write_text(path, rendered)
    return data


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
