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
    COWORK_MCP_DISABLED_KEY,
    COWORK_POLICY_MODE_KEY,
    COWORK_PYTHON_EXEC_KEY,
    COWORK_TOOL_ALLOWLIST_KEY,
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
            # email_send: "deny" hard-blocks regardless of args; "confirm"
            # only enforces the approval token when the agent claims it is
            # already confirmed (``confirmed=True``). On the first call
            # (``confirmed=False``) the tool body itself returns a nicely
            # formatted ``confirmation_required`` dict — it has the .eml
            # file and can read the actual recipient / subject / body
            # preview, which the callback cannot. Layering the tool's own
            # prompt over the callback's gate avoids the previous "Send
            # email to None" bug while keeping ``confirmed=True`` from
            # bypassing user consent (the model could lie about the flag).
            if name == "email_send":
                if policy.email_send == "deny":
                    return {
                        "error": "Blocked by policy: email sending is disabled.",
                    }
                if policy.email_send == "confirm" and args.get("confirmed") is True:
                    if not _consume_approval(tool_context, name):
                        return {
                            "error": (
                                "email_send called with confirmed=True but "
                                "no user approval is on file. Re-call with "
                                "confirmed=False to request the user's "
                                "approval first."
                            ),
                        }

        # auto mode: no additional gates beyond tool-level checks
        return None

    return _check_permission


def make_shell_allowlist_gate(
    agent_name: str,
    allowlist: tuple[str, ...],
) -> Any:
    """W5 — per-agent gate for ``shell_run``.

    Captures the agent's effective shell allowlist at agent-build time
    (closure pattern, mirrors ``make_static_agent_gate`` and
    ``make_allowlist_callback``). Other tools pass through; only
    ``shell_run`` calls are inspected.

    Order of operations:
    1. Hardcoded global deny via ``check_shell_deny`` — no override.
    2. ``argv[0]`` basename in ``allowlist`` → pass through, no
       confirm prompt.
    3. Otherwise: try to consume one approval token (granted by the
       UI's ``POST /v1/sessions/{id}/approvals``). If consumed → pass
       through. If not → return ``confirmation_required`` so the UI
       can prompt the user with the agent-supplied ``description``.

    Per-tool-name approval semantics (one token grants the next call
    of the same tool, regardless of args) are inherited from the
    existing approvals layer. Argv-hash-keyed approvals are out of
    scope for W5; the per-agent allowlist already narrows the surface.
    """
    from cowork_core.tools.shell.deny import check_shell_deny

    allowed_set = frozenset(allowlist)

    def _check(
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict[str, Any] | None:
        if tool.name != "shell_run":
            return None

        argv = args.get("argv")
        if not isinstance(argv, list) or not argv or not all(
            isinstance(a, str) for a in argv
        ):
            # Let shell_run's own input validation produce the error
            # message — nothing for the gate to do here.
            return None

        deny_reason = check_shell_deny(argv)
        if deny_reason is not None:
            return {
                "error": (
                    f"Blocked by global deny rule for agent "
                    f"{agent_name!r}: {deny_reason}"
                ),
            }

        # ``argv[0]`` may be a path (e.g. ``/usr/local/bin/pandoc``);
        # the allowlist is keyed by program basename so absolute and
        # bare names match equivalently.
        program = argv[0].rsplit("/", 1)[-1]
        if program in allowed_set:
            return None

        if _consume_approval(tool_context, "shell_run"):
            return None

        description = args.get("description")
        if not isinstance(description, str) or not description:
            description = f"Run `{' '.join(argv)}`"
        return _confirmation(
            "shell_run",
            summary=description,
            argv=argv,
            agent=agent_name,
            allowlist=sorted(allowed_set),
        )

    return _check


def make_static_agent_gate(
    agent_name: str,
    allowed_tools: frozenset[str] | None,
    disallowed_tools: frozenset[str],
) -> Any:
    """W1 — config-time hard gate enforced before any session-state
    allowlist. Captures the allow/disallow sets at agent-build time so
    a prompt-injected sub-agent that mutates its own session state
    cannot escape them.

    Semantics:
    - ``tool.name in disallowed_tools`` → block (denylist wins).
    - ``allowed_tools is None`` → no allowlist; pass everything not in
      the denylist (full surface, useful when only blacklisting a few).
    - ``tool.name not in allowed_tools`` (when ``allowed_tools`` is a
      set) → block.

    MCP tools are never gated here — the gate is mounted FIRST in the
    chain, but it inspects ``tool.name`` only, and MCP tools live under
    arbitrary names that the static config can't enumerate. The
    ``mcp_disable`` callback already handles MCP-specific disablement.
    Tool-name collisions between MCP and built-ins are extremely
    unlikely; if they happen, that's an MCP-server design bug.
    """

    def _check(
        tool: BaseTool,
        _args: dict[str, Any],
        _ctx: ToolContext,
    ) -> dict[str, Any] | None:
        name = tool.name
        if name in disallowed_tools:
            return {
                "error": (
                    f"Tool '{name}' is denied for agent '{agent_name}' "
                    f"by configuration (cfg.agents.{agent_name}."
                    f"disallowed_tools)."
                ),
            }
        if allowed_tools is not None and name not in allowed_tools:
            return {
                "error": (
                    f"Tool '{name}' is not in the allowlist for agent "
                    f"'{agent_name}' (cfg.agents.{agent_name}."
                    f"allowed_tools or per-agent default)."
                ),
            }
        return None

    return _check


def make_allowlist_callback(agent_name: str) -> Any:
    """Return a ``before_tool_callback`` that enforces a per-agent
    tool allowlist from session state.

    Tier E.E1. The allowlist lives in
    ``tool_context.state[COWORK_TOOL_ALLOWLIST_KEY]`` as
    ``dict[str, list[str]]`` (agent name → allowed tool names). An
    agent absent from the dict runs unrestricted (default behaviour,
    pre-E1 compatible); an agent with an empty list is effectively
    silenced because every tool call is blocked.

    The closure captures ``agent_name`` at callback-creation time
    rather than reaching into ADK's private ``InvocationContext`` for
    the current agent. We register one callback per sub-agent in
    ``build_root_agent``; the root agent is unrestricted by design —
    the feature scopes specialist sub-agents, not the primary
    interlocutor. A user who wants to block a tool entirely should
    use the existing policy layer (e.g. ``python_exec = "deny"``).
    """

    def _check(
        tool: BaseTool,
        _args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict[str, Any] | None:
        allowlist = tool_context.state.get(COWORK_TOOL_ALLOWLIST_KEY)
        if not isinstance(allowlist, dict):
            return None
        allowed = allowlist.get(agent_name)
        if allowed is None:
            return None
        if tool.name in allowed:
            return None
        return {
            "error": (
                f"Tool '{tool.name}' not allowed for agent "
                f"'{agent_name}' this session."
            ),
        }

    return _check


def make_mcp_disable_callback(tool_owner: dict[str, str]) -> Any:
    """Return a ``before_tool_callback`` that blocks tools owned by
    MCP servers disabled for the current session.

    Slice VI. ``tool_owner`` is a mapping from MCP tool name to the
    server name that owns it, captured during ``build_runtime`` /
    ``restart_mcp`` by listing each toolset's tools. The session's
    disable list lives on
    ``tool_context.state[COWORK_MCP_DISABLED_KEY]`` as ``list[str]``;
    absent / empty = all servers enabled (the default). Tools whose
    ``name`` is not in ``tool_owner`` are not MCP tools and pass
    through untouched, so this callback is safe to mount on every
    agent.

    The closure captures the same dict object the runtime updates,
    so a ``restart_mcp`` that adds/removes servers re-keys the gate
    without rebuilding the callback. We never copy the dict in.
    """

    def _check(
        tool: BaseTool,
        _args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict[str, Any] | None:
        owner = tool_owner.get(tool.name)
        if owner is None:
            return None
        disabled = tool_context.state.get(COWORK_MCP_DISABLED_KEY, [])
        if not isinstance(disabled, list):
            return None
        if owner not in disabled:
            return None
        return {
            "error": (
                f"MCP server '{owner}' is disabled for this session. "
                f"Re-enable it in Settings → MCP servers to call "
                f"'{tool.name}'."
            ),
        }

    return _check
