"""Translate ADK events into JSON frames sent over the WebSocket.

M0 only serializes text content; tool-call / tool-result / confirmation frames
are added in later milestones when the tool layer lands.
"""

from __future__ import annotations

from typing import Any


def event_to_frame(event: Any) -> dict[str, Any]:
    text = ""
    content = getattr(event, "content", None)
    if content is not None:
        parts = getattr(content, "parts", None) or []
        for part in parts:
            piece = getattr(part, "text", None)
            if piece:
                text += piece
    return {
        "type": "text",
        "text": text,
        "author": getattr(event, "author", None),
    }
