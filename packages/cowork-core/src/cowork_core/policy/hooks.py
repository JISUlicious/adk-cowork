"""Audit hooks — log tool calls and results to the session transcript.

Wired via ADK's ``before_tool_callback`` and ``after_tool_callback`` on the
root agent. Each invocation appends a JSON line to
``sessions/<id>/transcript.jsonl``.
"""

from __future__ import annotations

import json
import time
from typing import Any

from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext

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


def make_audit_callbacks() -> tuple[Any, Any]:
    """Return (before_tool_callback, after_tool_callback) for audit logging."""

    def _before_tool(
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: ToolContext,
    ) -> dict[str, Any] | None:
        # Stash the start time so after_tool can compute duration
        tool_context.state["_audit_tool_start"] = time.time()

        path = _get_transcript_path(tool_context)
        _append_line(path, {
            "event": "tool_call",
            "ts": time.time(),
            "tool": tool.name,
            "args": args,
        })
        return None  # Don't intercept

    def _after_tool(
        tool: BaseTool,
        args: dict[str, Any],
        tool_context: ToolContext,
        tool_response: dict[str, Any],
    ) -> dict[str, Any] | None:
        del args  # unused
        start = tool_context.state.get("_audit_tool_start")
        tool_context.state["_audit_tool_start"] = None
        duration_ms = int((time.time() - start) * 1000) if start else None

        path = _get_transcript_path(tool_context)
        record: dict[str, Any] = {
            "event": "tool_result",
            "ts": time.time(),
            "tool": tool.name,
        }
        if duration_ms is not None:
            record["duration_ms"] = duration_ms

        # Log a summary, not the full result (could be huge)
        if tool_response.get("error"):
            record["error"] = str(tool_response["error"])
        elif tool_response.get("confirmation_required"):
            record["confirmation_required"] = True
            record["summary"] = tool_response.get("summary", "")
        else:
            # Include key indicators without full content
            for key in ("exit_code", "path", "count", "status"):
                if key in tool_response:
                    record[key] = tool_response[key]

        _append_line(path, record)
        return None  # Don't modify the result

    return _before_tool, _after_tool
