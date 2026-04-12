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


def build_model(cfg: ModelConfig) -> LiteLlm:
    key = cfg.resolved_api_key
    # LiteLLM reads OPENAI_API_KEY from the environment even when api_key is
    # passed explicitly. Set it so local endpoints that don't need a real key
    # (LM Studio, Ollama) don't trigger an "OPENAI_API_KEY required" error.
    if key and not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = key
    return LiteLlm(
        model=f"openai/{cfg.model}",
        api_base=cfg.base_url,
        api_key=key,
    )
