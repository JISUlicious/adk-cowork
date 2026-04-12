"""OpenAI-compatible model adapter.

The sole model boundary in Cowork. ADK's ``LiteLlm`` wrapper forwards kwargs
to LiteLLM's ``completion``; LiteLLM accepts ``api_base`` and ``api_key`` for
custom OpenAI-compatible endpoints (OpenRouter, vLLM, LM Studio, Ollama at
``http://localhost:11434/v1``, LiteLLM proxy, etc.).
"""

from __future__ import annotations

import os

from google.adk.models.lite_llm import LiteLlm

from cowork_core.config import ModelConfig

_DUMMY_KEY = "cowork-local"


def build_model(cfg: ModelConfig) -> LiteLlm:
    key = cfg.resolved_api_key or _DUMMY_KEY
    # LiteLLM validates OPENAI_API_KEY from the environment regardless of the
    # api_key kwarg. Always ensure it's set so local endpoints (LM Studio,
    # Ollama) that don't need a real key work out of the box.
    os.environ.setdefault("OPENAI_API_KEY", key)
    return LiteLlm(
        model=f"openai/{cfg.model}",
        api_base=cfg.base_url,
        api_key=key,
    )
