"""Wire-format tests for cowork_server.transport.

Contract: payloads match Google ADK's own
``Event.model_dump_json(exclude_none=True, by_alias=True)`` and are a
round-trip through ``Event.model_validate_json``.
"""

from __future__ import annotations

import json

from cowork_server.transport import event_to_dict, event_to_payload, events_to_history
from google.adk.events.event import Event
from google.genai import types as genai_types


def _text_event(text: str, *, role: str = "model", thought: bool = False) -> Event:
    return Event(
        author="agent",
        invocation_id="inv-1",
        content=genai_types.Content(
            role=role,
            parts=[genai_types.Part(text=text, thought=thought)],
        ),
    )


def _tool_call_event() -> Event:
    fc = genai_types.FunctionCall(id="tc-1", name="fs_read", args={"path": "a.md"})
    return Event(
        author="agent",
        invocation_id="inv-1",
        content=genai_types.Content(role="model", parts=[genai_types.Part(function_call=fc)]),
    )


def _tool_response_event() -> Event:
    fr = genai_types.FunctionResponse(id="tc-1", name="fs_read", response={"ok": True})
    return Event(
        author="agent",
        invocation_id="inv-1",
        content=genai_types.Content(role="user", parts=[genai_types.Part(function_response=fr)]),
    )


def test_payload_is_camel_case_and_round_trips() -> None:
    ev = _text_event("hello")
    payload = event_to_payload(ev)
    data = json.loads(payload)
    assert "invocationId" in data
    assert "invocation_id" not in data
    # Round-trip: ADK must be able to parse it back.
    back = Event.model_validate_json(payload)
    assert back.author == "agent"
    assert back.content is not None
    assert back.content.parts is not None
    assert back.content.parts[0].text == "hello"


def test_exclude_none_drops_unset_fields() -> None:
    data = json.loads(event_to_payload(_text_event("hi")))
    # Fields that weren't set on this Event should not appear.
    assert "errorCode" not in data
    assert "errorMessage" not in data
    assert "groundingMetadata" not in data


def test_tool_call_and_response_preserve_parts() -> None:
    call = json.loads(event_to_payload(_tool_call_event()))
    resp = json.loads(event_to_payload(_tool_response_event()))
    assert call["content"]["parts"][0]["functionCall"]["name"] == "fs_read"
    assert call["content"]["parts"][0]["functionCall"]["id"] == "tc-1"
    assert resp["content"]["parts"][0]["functionResponse"]["response"] == {"ok": True}


def test_thought_flag_preserved() -> None:
    data = json.loads(event_to_payload(_text_event("pondering", thought=True)))
    assert data["content"]["parts"][0]["thought"] is True


def test_events_to_history_returns_wire_compatible_dicts() -> None:
    history = events_to_history([_text_event("one"), _tool_call_event()])
    assert len(history) == 2
    assert history[0] == event_to_dict(_text_event("one")) | {
        "id": history[0]["id"],
        "timestamp": history[0]["timestamp"],
    }
    # Every history entry must round-trip as an Event.
    for item in history:
        Event.model_validate_json(json.dumps(item))


def test_error_event_carries_error_fields() -> None:
    err = Event(
        author="cowork-server",
        invocation_id="inv-1",
        error_code="INTERNAL",
        error_message="boom",
        turn_complete=True,
    )
    data = json.loads(event_to_payload(err))
    assert data["errorCode"] == "INTERNAL"
    assert data["errorMessage"] == "boom"
    assert data["turnComplete"] is True
