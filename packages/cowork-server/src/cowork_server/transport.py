"""Translate ADK events to the wire format.

The wire format is identical to the one Google ADK's own FastAPI server
uses at ``/run_sse`` and ``/run_live`` (see
``google/adk/cli/adk_web_server.py``): ``Event.model_dump_json(
exclude_none=True, by_alias=True)``. Every ADK field — ``id``,
``invocationId``, ``author``, ``content`` (with raw ``parts``),
``actions``, ``partial``, ``turnComplete``, ``errorCode``,
``errorMessage``, ``usageMetadata``, ``groundingMetadata``,
``longRunningToolIds``, ``branch``, ``timestamp``, ``customMetadata``,
etc. — flows through unchanged. No custom envelope, no flattening.
"""

from __future__ import annotations

from typing import Any


def event_to_payload(event: Any) -> str:
    """Serialize an ADK ``Event`` to the wire JSON string.

    Matches ``adk_web_server.py``'s ``event_to_stream.model_dump_json(
    exclude_none=True, by_alias=True)`` verbatim so any ADK-native
    client can parse cowork-server streams.
    """
    return event.model_dump_json(exclude_none=True, by_alias=True)


def event_to_dict(event: Any) -> dict[str, Any]:
    """Same as :func:`event_to_payload` but returns a dict (for history)."""
    return event.model_dump(mode="json", exclude_none=True, by_alias=True)


def events_to_history(events: list[Any]) -> list[dict[str, Any]]:
    """Return the persisted ADK events in wire-compatible form.

    The client uses the same parsing logic for live and replayed streams,
    so history is just a list of the same dicts it would receive over
    SSE/WS.
    """
    return [event_to_dict(ev) for ev in events]
