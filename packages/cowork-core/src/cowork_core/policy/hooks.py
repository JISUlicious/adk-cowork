"""Audit hooks — log tool calls and results.

Two outputs in parallel:

1. **Per-session transcript JSONL** (pre-V1 behaviour, retained) —
   ``sessions/<id>/transcript.jsonl``. Useful for replaying or
   debugging a single session; full args + result kept verbatim.

2. **Structured audit sink** (Slice V1) — every call lands as a row
   in the audit DB (``<workspace>/audit.db`` in SU,
   ``audit_log`` table inside ``multiuser.db`` in MU). Capture is
   filtered through ``cowork_core.audit_policy`` so file content,
   email bodies, memory pages etc. don't leak unless the operator
   has explicitly opted a tool in.

Wired via ADK's ``before_tool_callback`` / ``after_tool_callback``
on every agent. The sink + transcript paths are taken from the
``CoworkToolContext`` stashed in ``tool_context.state``.
"""

from __future__ import annotations

import json
import time
from typing import Any

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

from cowork_core.audit import AuditEntry, serialize_args, serialize_result
from cowork_core.audit_policy import policy_for
from cowork_core.tools.base import COWORK_CONTEXT_KEY, CoworkToolContext


def _get_transcript_path(tool_context: ToolContext) -> Any:
    """Extract transcript path from the CoworkToolContext in session state."""
    ctx = tool_context.state.get(COWORK_CONTEXT_KEY)
    if isinstance(ctx, CoworkToolContext):
        return ctx.session.transcript_path
    return None


def _append_line(path: Any, record: dict[str, Any]) -> None:
    """Append a JSON line to the transcript file."""
    if path is None:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError:
        pass  # Don't crash the agent if transcript write fails


def _get_cowork_ctx(tool_context: ToolContext) -> CoworkToolContext | None:
    ctx = tool_context.state.get(COWORK_CONTEXT_KEY)
    return ctx if isinstance(ctx, CoworkToolContext) else None


def _now_iso() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()


def _audit_session_id(ctx: CoworkToolContext | None) -> str | None:
    if ctx is None:
        return None
    return getattr(ctx.session, "id", None)


def _audit_project_id(ctx: CoworkToolContext | None) -> str | None:
    if ctx is None:
        return None
    proj = getattr(ctx, "project", None)
    if proj is None:
        return None
    return str(getattr(proj, "root", "")) or None


def make_audit_callbacks() -> tuple[Any, Any]:
    """Return (before_tool_callback, after_tool_callback) for audit
    logging. The sink is read off the runtime via the cowork context
    so callbacks don't need to be rebuilt when the runtime changes."""

    def _before_tool(
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict[str, Any] | None:
        # Stash the start time so after_tool can compute duration
        tool_context.state["_audit_tool_start"] = time.time()

        # ── Pre-V1 transcript line (full args, retained) ──
        path = _get_transcript_path(tool_context)
        _append_line(path, {
            "event": "tool_call",
            "ts": time.time(),
            "tool": tool.name,
            "args": args,
        })

        # ── V1 structured audit row ──
        ctx = _get_cowork_ctx(tool_context)
        if ctx is None:
            return None
        sink = getattr(ctx, "audit_sink", None)
        if sink is None:
            return None
        policy = policy_for(tool.name)
        sink.record(AuditEntry(
            ts=_now_iso(),
            user_id=ctx.user_id,
            kind="tool_call",
            tool_name=tool.name,
            session_id=_audit_session_id(ctx),
            project_id=_audit_project_id(ctx),
            args_json=serialize_args(args, policy),
        ))
        return None  # Don't intercept

    def _after_tool(
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: ToolContext,
        tool_response: dict[str, Any],
    ) -> dict[str, Any] | None:
        del args  # unused at the after-tool boundary
        start = tool_context.state.get("_audit_tool_start")
        tool_context.state["_audit_tool_start"] = None
        duration_ms = int((time.time() - start) * 1000) if start else None

        # ── Pre-V1 transcript line ──
        path = _get_transcript_path(tool_context)
        record: dict[str, Any] = {
            "event": "tool_result",
            "ts": time.time(),
            "tool": tool.name,
        }
        if duration_ms is not None:
            record["duration_ms"] = duration_ms

        if tool_response.get("error"):
            record["error"] = str(tool_response["error"])
        elif tool_response.get("confirmation_required"):
            record["confirmation_required"] = True
            record["summary"] = tool_response.get("summary", "")
        else:
            for key in ("exit_code", "path", "count", "status"):
                if key in tool_response:
                    record[key] = tool_response[key]
        _append_line(path, record)

        # ── V1 structured audit row ──
        ctx = _get_cowork_ctx(tool_context)
        if ctx is None:
            return None
        sink = getattr(ctx, "audit_sink", None)
        if sink is None:
            return None
        policy = policy_for(tool.name)
        result_json, error_text = serialize_result(tool_response, policy)
        sink.record(AuditEntry(
            ts=_now_iso(),
            user_id=ctx.user_id,
            kind="tool_result",
            tool_name=tool.name,
            session_id=_audit_session_id(ctx),
            project_id=_audit_project_id(ctx),
            result_json=result_json,
            error_text=error_text,
            duration_ms=duration_ms,
        ))
        return None  # Don't modify the result

    return _before_tool, _after_tool
