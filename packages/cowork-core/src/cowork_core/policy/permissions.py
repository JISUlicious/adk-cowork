"""Permission enforcement for Cowork's three policy modes.

Modes:
- ``plan``: Planning only. Reads + research allowed. The only write permitted
  is ``fs_write`` to ``scratch/plan.md``. All other writes blocked.
- ``work``: Normal mode. Writes allowed; shell and email require confirmation
  for commands outside the allowlist.
- ``auto``: Autonomous. Only the shell allowlist gates execution.

Enforced via ADK's ``before_tool_callback`` on the root agent. Returning a
dict from the callback short-circuits the tool call with that result.
"""

from __future__ import annotations

from typing import Any

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from cowork_core.config import PolicyConfig

# Tools that mutate project state
_WRITE_TOOLS = frozenset({
    "fs_write", "fs_edit", "fs_promote",
    "shell_run", "python_exec_run",
})


def make_permission_callback(
    policy: PolicyConfig,
) -> Any:
    """Return an ADK before_tool_callback that enforces the policy mode."""

    def _check_permission(
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict[str, Any] | None:
        del tool_context  # unused; required by ADK callback signature
        name = tool.name
        mode = policy.mode

        if mode == "plan":
            # Allow fs_write only to scratch/plan.md
            if name == "fs_write":
                path = str(args.get("path", ""))
                if path == "scratch/plan.md" or path.endswith("/plan.md"):
                    return None  # Allowed — this is the plan file
                return {
                    "error": (
                        "Blocked by policy: in plan mode, `fs_write` "
                        "is only allowed to `scratch/plan.md`. "
                        "Write your plan there instead."
                    ),
                }
            if name in _WRITE_TOOLS:
                return {
                    "error": f"Blocked by policy: `{name}` is not allowed in "
                    f"plan mode. Write a plan to `scratch/plan.md` instead, "
                    f"then the user can switch to work mode to execute it.",
                }

        if mode == "work" and name == "email_send" and policy.email_send == "deny":
            return {
                "error": "Blocked by policy: email sending is disabled.",
            }

        # auto mode: no additional gates beyond tool-level checks
        return None

    return _check_permission
