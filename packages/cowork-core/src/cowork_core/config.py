"""Cowork configuration models loaded from ``cowork.toml``.

The only model boundary is ``ModelConfig`` — any OpenAI-compatible endpoint
(OpenAI, OpenRouter, vLLM, LM Studio, Ollama, LiteLLM proxy) works by setting
``base_url`` and ``api_key``. Values prefixed with ``env:`` are read from the
process environment at resolution time.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


def _resolve_env(value: str) -> str:
    if value.startswith("env:"):
        return os.environ.get(value[4:], "")
    return value


class ModelConfig(BaseModel):
    base_url: str = "http://localhost:8000/v1"
    api_key: str = "env:OPENAI_API_KEY"
    model: str = "Huihui-Qwen3.5-35B-A3B-Claude-4.6-Opus-abliterated-4bit"

    @property
    def resolved_api_key(self) -> str:
        return _resolve_env(self.api_key)


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 0


class WorkspaceConfig(BaseModel):
    root: Path = Field(default_factory=lambda: Path.home() / "CoworkWorkspaces")


class PolicyConfig(BaseModel):
    mode: Literal["plan", "work", "auto"] = "work"
    shell_allowlist: list[str] = Field(default_factory=lambda: ["git", "python"])
    email_send: Literal["confirm", "deny"] = "confirm"


class SearchConfig(BaseModel):
    provider: Literal["duckduckgo", "brave", "tavily", "searxng"] = "duckduckgo"


class CoworkConfig(BaseModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)

    @classmethod
    def load(cls, path: Path | None = None) -> CoworkConfig:
        if path is None or not path.exists():
            return cls.from_env()
        with path.open("rb") as f:
            data = tomllib.load(f)
        cfg = cls.model_validate(data)
        return cfg.apply_env_overrides()

    @classmethod
    def from_env(cls) -> CoworkConfig:
        return cls().apply_env_overrides()

    def apply_env_overrides(self) -> CoworkConfig:
        model = self.model
        base = os.environ.get("COWORK_MODEL_BASE_URL")
        name = os.environ.get("COWORK_MODEL_NAME")
        key = os.environ.get("COWORK_MODEL_API_KEY")
        if base or name or key:
            model = ModelConfig(
                base_url=base or model.base_url,
                model=name or model.model,
                api_key=key or model.api_key,
            )
        workspace = self.workspace
        ws_root = os.environ.get("COWORK_WORKSPACE_ROOT")
        if ws_root:
            workspace = WorkspaceConfig(root=Path(ws_root))
        return self.model_copy(update={"model": model, "workspace": workspace})
