"""Filesystem tool family (read/write/list/glob/stat/edit/promote).

All paths are interpreted relative to the active project root and resolved
through the workspace sandbox — anything that escapes the project root is
rejected. This is the single place where file I/O policy is enforced.
"""

from __future__ import annotations

from google.adk.tools.function_tool import FunctionTool

from cowork_core.tools.fs.edit import fs_edit
from cowork_core.tools.fs.glob import fs_glob
from cowork_core.tools.fs.list import fs_list
from cowork_core.tools.fs.promote import fs_promote
from cowork_core.tools.fs.read import fs_read
from cowork_core.tools.fs.stat import fs_stat
from cowork_core.tools.fs.write import fs_write
from cowork_core.tools.registry import ToolRegistry


def register_fs_tools(registry: ToolRegistry) -> None:
    for func in (fs_read, fs_write, fs_list, fs_glob, fs_stat, fs_edit, fs_promote):
        registry.register(FunctionTool(func))


__all__ = [
    "fs_edit",
    "fs_glob",
    "fs_list",
    "fs_promote",
    "fs_read",
    "fs_stat",
    "fs_write",
    "register_fs_tools",
]
