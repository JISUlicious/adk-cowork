"""Permission enforcement for Cowork's three policy modes.

Modes:
- ``plan``: Planning only. Reads + research allowed. The only write permitted
  is ``fs_write`` to ``scratch/plan.md``. All other writes blocked.
- ``work``: Normal mode. Writes allowed; ``python_exec_run`` and
  ``email_send`` require confirmation by default (see ``PolicyConfig``);
  ``shell_run`` gates itself via the command allowlist.
- ``auto``: Autonomous. Only the shell allowlist gates execution.

Mode resolution: each session stores its own ``cowork.policy_mode`` on ADK
session state; the callback reads from there with ``policy.mode`` as the
fallback for fresh sessions.

Approval: tools gated with ``confirmation_required`` consume one token from
the session's approval counter when the user hits Approve in the UI. The
endpoint ``POST /v1/sessions/{id}/approvals`` adds a token; the callback
decrements. Without an approval token the callback returns
``confirmation_required`` and the tool does not execute.

Enforced via ADK's ``before_tool_callback`` on the root agent. Returning a
dict from the callback short-circuits the tool call with that result.
"""

from __future__ import annotations

from typing import Any

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from cowork_core.config import PolicyConfig
from cowork_core.tools.base import (
    COWORK_CONTEXT_KEY,
    COWORK_POLICY_MODE_KEY,
    COWORK_PYTHON_EXEC_KEY,
)

# Tools that mutate project state
_WRITE_TOOLS = frozenset({
    "fs_write", "fs_edit", "fs_promote",
    "shell_run", "python_exec_run",
})


def _consume_approval(tool_context: ToolContext, tool_name: str) -> bool:
    """If the session has a pending approval for this tool, spend it.

    Duck-types ``tool_context.state[COWORK_CONTEXT_KEY]`` rather than
    going through ``get_cowork_context``'s isinstance check — the callback
    only needs ``.session.id`` and ``.approvals``, and duck-typing keeps
    unit tests that inject a stub light.

    The store is a process-local singleton, not ADK session state. Using
    ADK state_delta for this counter raced with ``runner.run_async`` —
    see ``cowork_core.approvals`` for the full story.
    """
    ctx = tool_context.state.get(COWORK_CONTEXT_KEY)
    if ctx is None:
        return False
    try:
        session_id = ctx.session.id
        store = ctx.approvals
    except AttributeError:
        return False
    return store.consume(session_id, tool_name)


def _confirmation(tool_name: str, summary: str, **details: Any) -> dict[str, Any]:
    """Build the confirmation envelope the React client recognizes."""
    return {
        "confirmation_required": True,
        "tool": tool_name,
        "summary": summary,
        **details,
    }


def make_permission_callback(
    policy: PolicyConfig,
) -> Any:
    """Return an ADK before_tool_callback that enforces the policy mode."""

    def _check_permission(
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict[str, Any] | None:
        name = tool.name
        # Per-session mode overrides the server default.
        mode = tool_context.state.get(COWORK_POLICY_MODE_KEY, policy.mode)

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

        if mode == "work":
            # python_exec_run: not path-confined, so gate by default.
            if name == "python_exec_run":
                # Per-session override (settable via PUT
                # /v1/sessions/{id}/policy/python_exec) beats cfg default.
                python_exec = tool_context.state.get(
                    COWORK_PYTHON_EXEC_KEY, policy.python_exec,
                )
                if python_exec == "deny":
                    return {
                        "error": (
                            "Blocked by policy: Python execution is disabled. "
                            "Set [policy] python_exec = \"confirm\" or \"allow\" "
                            "in cowork.toml to change this."
                        ),
                    }
                if python_exec == "confirm":
                    if _consume_approval(tool_context, name):
                        return None
                    code_preview = str(args.get("code", ""))
                    if len(code_preview) > 300:
                        code_preview = code_preview[:300] + "…"
                    return _confirmation(
                        name,
                        summary="Run Python snippet (not path-confined; "
                                "can read/write outside the workdir).",
                        code_preview=code_preview,
                    )
                # python_exec == "allow" → pass through
            # email_send: "confirm" surfaces a UI prompt; "deny" hard-blocks.
            if name == "email_send":
                if policy.email_send == "deny":
                    return {
                        "error": "Blocked by policy: email sending is disabled.",
                    }
                if policy.email_send == "confirm":
                    if _consume_approval(tool_context, name):
                        return None
                    to = args.get("to")
                    subject = args.get("subject")
                    body = args.get("body") or ""
                    body_preview = body if len(body) <= 400 else body[:400] + "…"
                    return _confirmation(
                        name,
                        summary=f"Send email to {to} — subject: {subject!r}",
                        to=to,
                        cc=args.get("cc"),
                        subject=subject,
                        body_preview=body_preview,
                    )

        # auto mode: no additional gates beyond tool-level checks
        return None

    return _check_permission
