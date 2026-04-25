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

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()


def _resolve_env(value: str) -> str:
    if value.startswith("env:"):
        return os.environ.get(value[4:], "")
    return value


class ModelConfig(BaseModel):
    base_url: str = "http://localhost:18000/v1"
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
    # Python snippets can read and write anywhere the host process can —
    # path confinement does NOT apply to `python_exec_run`. Default to
    # "confirm" so the agent can't silently exfiltrate files outside the
    # workdir (e.g. `open('/etc/passwd').read()`).
    python_exec: Literal["confirm", "allow", "deny"] = "confirm"


class RuntimeConfig(BaseModel):
    """Selects which session/bus/limiter implementations ``build_runtime`` wires.

    ``local`` (default) — single-process in-memory bus + SQLite session store.
    Suitable for desktop sidecar and small-team web.

    ``distributed`` — reserved for future Redis+Postgres backends. Not yet
    implemented; ``build_runtime`` will raise if selected today.
    """

    backend: Literal["local", "distributed"] = "local"


class McpServerConfig(BaseModel):
    """Configuration for a single MCP server.

    ``transport`` selects the wire protocol — ``stdio`` (default, runs
    a local subprocess), ``sse`` (Server-Sent Events), or ``http``
    (Streamable HTTP). ``command`` / ``args`` / ``env`` apply to
    stdio; ``url`` / ``headers`` apply to sse + http. ``tool_filter``
    optionally restricts which tools the server exposes to the agent
    (None = all tools). ``description`` is a free-form string
    surfaced in Settings.

    ``bundled`` distinguishes server entries shipped with the
    package (immutable, cannot be deleted via ``DELETE
    /v1/mcp/servers/{name}``) from user-added entries that live in
    ``<workspace>/global/mcp/servers.json``.
    """

    # stdio transport
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    # sse / http transport
    transport: Literal["stdio", "sse", "http"] = "stdio"
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    # cross-cutting
    tool_filter: list[str] | None = None
    description: str = ""
    bundled: bool = False


class EmailConfig(BaseModel):
    """SMTP settings for sending email via ``email_send``."""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = "env:COWORK_SMTP_PASSWORD"
    use_tls: bool = True
    default_from: str = ""

    @property
    def resolved_password(self) -> str:
        return _resolve_env(self.smtp_password)

    @property
    def configured(self) -> bool:
        return bool(self.smtp_host and self.default_from)


class SearchConfig(BaseModel):
    provider: Literal["duckduckgo", "brave", "tavily", "searxng"] = "duckduckgo"


class AuthConfig(BaseModel):
    """Authentication configuration.

    - ``token``: explicit token for sidecar mode (generated if empty).
    - ``keys``: dict of ``api_key → user_label`` for multi-user mode.
      When non-empty, each key identifies a distinct user.
    """

    token: str = ""
    keys: dict[str, str] = Field(default_factory=dict)


class CompactionConfig(BaseModel):
    """Knobs for ADK's native sliding-window + token-threshold compaction.

    ADK handles scheduling, summary generation (via ``LlmEventSummarizer``),
    and event bookkeeping; Cowork just supplies the thresholds and flips the
    feature on. See ``google.adk.apps.EventsCompactionConfig``.
    """

    enabled: bool = True
    compaction_interval: int = 6
    """Run sliding-window compaction every N new user-initiated invocations."""

    overlap_size: int = 1
    """Invocations to carry over from the tail of the last compaction."""

    token_threshold: int = 32000
    """When the latest prompt-token estimate crosses this, ADK triggers an
    inline mid-invocation compaction."""

    event_retention_size: int = 20
    """On token-threshold compaction, keep the last N raw events uncompacted
    so recent turns remain verbatim in the agent's context."""


class CoworkConfig(BaseModel):
    model: ModelConfig = Field(default_factory=ModelConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    compaction: CompactionConfig = Field(default_factory=CompactionConfig)
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)

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
        updates: dict[str, object] = {}

        # Model
        model = self.model
        base = os.environ.get("COWORK_MODEL_BASE_URL")
        name = os.environ.get("COWORK_MODEL_NAME")
        key = os.environ.get("COWORK_MODEL_API_KEY")
        if base or name or key:
            updates["model"] = ModelConfig(
                base_url=base or model.base_url,
                model=name or model.model,
                api_key=key or model.api_key,
            )

        # Workspace
        ws_root = os.environ.get("COWORK_WORKSPACE_ROOT")
        if ws_root:
            updates["workspace"] = WorkspaceConfig(root=Path(ws_root))

        # Email (SMTP)
        email = self.email
        smtp_host = os.environ.get("COWORK_SMTP_HOST")
        smtp_port = os.environ.get("COWORK_SMTP_PORT")
        smtp_user = os.environ.get("COWORK_SMTP_USER")
        smtp_pass = os.environ.get("COWORK_SMTP_PASSWORD")
        smtp_tls = os.environ.get("COWORK_SMTP_TLS")
        email_from = os.environ.get("COWORK_EMAIL_FROM")
        if any((smtp_host, smtp_port, smtp_user, smtp_pass, smtp_tls, email_from)):
            updates["email"] = EmailConfig(
                smtp_host=smtp_host or email.smtp_host,
                smtp_port=int(smtp_port) if smtp_port else email.smtp_port,
                smtp_user=smtp_user or email.smtp_user,
                smtp_password=smtp_pass or email.smtp_password,
                use_tls=smtp_tls.lower() not in ("0", "false", "no") if smtp_tls else email.use_tls,
                default_from=email_from or email.default_from,
            )

        return self.model_copy(update=updates)
