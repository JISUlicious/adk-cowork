"""Model adapters. The only supported boundary is OpenAI-compatible."""

from cowork_core.model.openai_compat import build_model

__all__ = ["build_model"]
