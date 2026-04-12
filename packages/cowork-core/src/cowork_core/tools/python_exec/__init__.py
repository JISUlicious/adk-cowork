"""python_exec — run a Python snippet in the session scratch dir.

This is the execution surface for office skills: a skill like ``docx-basic``
hands the agent a snippet that uses ``python-docx`` to read/write files.
Everything runs in a subprocess with a stripped environment so user-site
packages and ambient ``PYTHONPATH`` cannot leak in.
"""

from __future__ import annotations

from google.adk.tools.function_tool import FunctionTool

from cowork_core.tools.python_exec.run import python_exec_run
from cowork_core.tools.registry import ToolRegistry


def register_python_exec_tools(registry: ToolRegistry) -> None:
    registry.register(FunctionTool(python_exec_run))


__all__ = ["python_exec_run", "register_python_exec_tools"]
