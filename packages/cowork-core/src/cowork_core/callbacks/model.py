"""ADK ``before_model_callback`` / ``after_model_callback`` factory.

Two responsibilities today:

1. **Turn-budget guard.** A cheap context-window guard: count how many times
   the model is called in a session and, once past ``max_turns``, short-circuit
   with a synthesized assistant message instead of blowing the API. Keeps
   runaway agents bounded without owning the full ADK loop.

2. **Model-call audit.** Append a ``model_call`` line to the session
   ``transcript.jsonl`` so operators can see LLM round-trips alongside
   tool calls. Silent on write failures — never kills a turn.

Both callbacks share the same ``(before, after)`` factory so callers register
them together.
"""

from __future__ import annotations

import json
import time
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from cowork_core.tools.base import COWORK_CONTEXT_KEY

# State keys
_TURN_COUNT_KEY = "cowork.turn_count"

# Defaults — conservative. Long sessions tend to thrash context anyway.
DEFAULT_MAX_TURNS = 50


def _transcript_path(state: Any) -> Any:
    """Fish the transcript path out of the live CoworkToolContext."""
    ctx = state.get(COWORK_CONTEXT_KEY)
    if ctx is None:
        return None
    try:
        return ctx.session.transcript_path
    except AttributeError:
        return None


def _append_line(path: Any, record: dict[str, Any]) -> None:
    if path is None:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    except OSError:
        pass


def make_model_callbacks(
    max_turns: int = DEFAULT_MAX_TURNS,
) -> tuple[Any, Any]:
    """Return ``(before_model_callback, after_model_callback)``.

    Args:
        max_turns: Hard ceiling on model calls per session. Past this the
            ``before_model_callback`` short-circuits with a synthesized
            assistant message.
    """

    def _before_model(
        callback_context: CallbackContext,
        llm_request: LlmRequest,
    ) -> LlmResponse | None:
        del llm_request  # we only inspect/mutate state, not the request

        state = callback_context.state
        turns = int(state.get(_TURN_COUNT_KEY, 0)) + 1
        state[_TURN_COUNT_KEY] = turns

        if turns > max_turns:
            msg = (
                f"Turn budget exceeded ({max_turns} model calls). "
                f"Start a new session or summarize progress and resume."
            )
            return LlmResponse(
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=msg)],
                ),
            )
        return None

    def _after_model(
        callback_context: CallbackContext,
        llm_response: LlmResponse,
    ) -> LlmResponse | None:
        # Token accounting + audit line. Never blocks the response.
        state = callback_context.state
        usage = getattr(llm_response, "usage_metadata", None)
        record: dict[str, Any] = {
            "event": "model_call",
            "ts": time.time(),
            "turn": int(state.get(_TURN_COUNT_KEY, 0)),
        }
        if usage is not None:
            for key in ("prompt_token_count", "candidates_token_count", "total_token_count"):
                val = getattr(usage, key, None)
                if val is not None:
                    record[key] = int(val)
        _append_line(_transcript_path(state), record)
        return None

    return _before_model, _after_model
