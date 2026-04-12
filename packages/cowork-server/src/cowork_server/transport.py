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
                frames.append({"type": "text", "text": piece, "author": author})

    if not frames:
        return {"type": "text", "text": "", "author": author}
    if len(frames) == 1:
        return frames[0]
    return {"type": "multi", "frames": frames, "author": author}


def _safe_dict(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj
    try:
        return dict(obj)
    except (TypeError, ValueError):
        return str(obj)
