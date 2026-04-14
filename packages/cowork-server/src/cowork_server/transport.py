"""Translate ADK events into JSON frames sent over the WebSocket."""

from __future__ import annotations

from typing import Any


def event_to_frame(event: Any) -> dict[str, Any]:
    author = getattr(event, "author", None)
    content = getattr(event, "content", None)
    if content is None:
        return {"type": "text", "text": "", "author": author}

    parts = getattr(content, "parts", None) or []
    frames: list[dict[str, Any]] = []

    for part in parts:
        if getattr(part, "function_call", None) is not None:
            fc = part.function_call
            frames.append({
                "type": "tool_call",
                "name": getattr(fc, "name", None),
                "args": _safe_dict(getattr(fc, "args", None)),
                "id": getattr(fc, "id", None),
                "author": author,
            })
        elif getattr(part, "function_response", None) is not None:
            fr = part.function_response
            frames.append({
                "type": "tool_result",
                "name": getattr(fr, "name", None),
                "result": _safe_dict(getattr(fr, "response", None)),
                "id": getattr(fr, "id", None),
                "author": author,
            })
        else:
            piece = getattr(part, "text", None)
            if piece:
                frames.append({
                    "type": "text",
                    "text": piece,
                    "author": author,
                    "thought": bool(getattr(part, "thought", False)),
                })

    if not frames:
        return {"type": "text", "text": "", "author": author}
    if len(frames) == 1:
        return frames[0]
    return {"type": "multi", "frames": frames, "author": author}


def events_to_history(events: list[Any]) -> list[dict[str, Any]]:
    """Convert an ADK event list into ChatMessage-shaped history entries.

    Returned shape matches the web client's ``ChatMessage``:
    ``{role, text, thought, toolCalls: [{id, name, args, result, status}]}``.
    """
    messages: list[dict[str, Any]] = []
    tool_index: dict[str, tuple[int, int]] = {}

    def _new_assistant() -> dict[str, Any]:
        return {"role": "assistant", "text": "", "thought": "", "toolCalls": []}

    for ev in events:
        content = getattr(ev, "content", None)
        if content is None:
            continue
        role = getattr(content, "role", None) or ""
        parts = getattr(content, "parts", None) or []

        is_user = role == "user" and not any(
            getattr(p, "function_response", None) is not None for p in parts
        )

        if is_user:
            text = "".join(getattr(p, "text", "") or "" for p in parts)
            if text:
                messages.append({
                    "role": "user", "text": text, "thought": "", "toolCalls": [],
                })
            continue

        if not messages or messages[-1]["role"] != "assistant":
            messages.append(_new_assistant())
        msg = messages[-1]

        for part in parts:
            fc = getattr(part, "function_call", None)
            fr = getattr(part, "function_response", None)
            if fc is not None:
                tc_id = getattr(fc, "id", None) or f"tc-{len(msg['toolCalls'])}"
                msg["toolCalls"].append({
                    "id": tc_id,
                    "name": getattr(fc, "name", None),
                    "args": _safe_dict(getattr(fc, "args", None)) or {},
                    "status": "pending",
                })
                tool_index[tc_id] = (len(messages) - 1, len(msg["toolCalls"]) - 1)
            elif fr is not None:
                tc_id = getattr(fr, "id", None)
                result = _safe_dict(getattr(fr, "response", None)) or {}
                loc = tool_index.get(tc_id or "")
                if loc is not None:
                    mi, ti = loc
                    tc = messages[mi]["toolCalls"][ti]
                    tc["result"] = result
                    if isinstance(result, dict) and result.get("confirmation_required"):
                        tc["status"] = "confirmation"
                    elif isinstance(result, dict) and result.get("error"):
                        tc["status"] = "error"
                    else:
                        tc["status"] = "ok"
            else:
                piece = getattr(part, "text", None)
                if piece:
                    if getattr(part, "thought", False):
                        msg["thought"] += piece
                    else:
                        msg["text"] += piece

    return messages


def _safe_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    try:
        return dict(obj)
    except (TypeError, ValueError):
        return str(obj)
