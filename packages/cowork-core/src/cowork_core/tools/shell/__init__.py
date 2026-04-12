"""Shell tool family — currently just ``shell.run``.

The *only* shell primitive is ``shell.run``. It takes an ``argv`` list, never
a single string, so there is no shell metacharacter surface. OS dispatch lives
in exactly one place (``run.py``) per constitution §3.5.
"""

from __future__ import annotations

from google.adk.tools.function_tool import FunctionTool

from cowork_core.tools.registry import ToolRegistry
from cowork_core.tools.shell.run import shell_run


def register_shell_tools(registry: ToolRegistry) -> None:
    registry.register(FunctionTool(shell_run))


__all__ = ["register_shell_tools", "shell_run"]
