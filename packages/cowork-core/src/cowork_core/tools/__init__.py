"""Cowork tool base types and registry.

Cowork tools are plain async Python functions wrapped by ADK's ``FunctionTool``.
ADK already auto-derives the function declaration (name, description, JSON
schema) from type hints + docstring and injects the ``tool_context``. This
subpackage adds two things on top:

* ``CoworkToolContext`` — the per-invocation cowork state (workspace, project,
  session, config) that individual tools need. Stored in and read from ADK's
  ``tool_context.state`` under a single key so no global is required.
* ``ToolRegistry`` — a tiny name → tool map used by the runner to assemble the
  final tool list handed to the ``LlmAgent``.
"""

from __future__ import annotations

from cowork_core.tools.base import (
    COWORK_AUTO_ROUTE_KEY,
    COWORK_CONTEXT_KEY,
    COWORK_POLICY_MODE_KEY,
    COWORK_PYTHON_EXEC_KEY,
    COWORK_READS_KEY,
    COWORK_TOOL_ALLOWLIST_KEY,
    CoworkToolContext,
    get_cowork_context,
)
from cowork_core.tools.registry import ToolRegistry

__all__ = [
    "COWORK_AUTO_ROUTE_KEY",
    "COWORK_CONTEXT_KEY",
    "COWORK_POLICY_MODE_KEY",
    "COWORK_PYTHON_EXEC_KEY",
    "COWORK_READS_KEY",
    "COWORK_TOOL_ALLOWLIST_KEY",
    "CoworkToolContext",
    "ToolRegistry",
    "get_cowork_context",
]
