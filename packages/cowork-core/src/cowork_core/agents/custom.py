"""W2 — custom agent loader.

Mirrors Claude Code's `.claude/agents/<name>.md` pattern: a Markdown
file whose YAML frontmatter declares the agent's name, description,
optional tool gates, and optional model override; whose body is the
system prompt the agent runs with.

```
---
name: legal-reviewer
description: Reviews contracts for compliance issues.
allowed_tools: [fs_read, search_web]
disallowed_tools: [shell_run]
model:
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini
  api_key: env:OPENAI_API_KEY
---

You are the Legal Reviewer...
```

Two scopes: ``user`` at ``~/.config/cowork/agents/`` (shared across
workspaces, XDG-style), and ``global`` at
``<workspace>/global/agents/`` (per-workspace, mirrors how skills are
laid out). Later scans shadow earlier ones on name collision so a
workspace can override a user-scoped default.

Built-in sub-agent names (``researcher``, ``writer``, ``analyst``,
``reviewer``) are reserved — a custom agent that tries to claim one
is rejected at parse time so the routing surface stays predictable.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]

from cowork_core.config import AgentConfig, ModelConfig

_FRONTMATTER_FENCE = "---"

# Names already claimed by ``SUB_AGENT_DEFAULTS`` (built-ins). A custom
# agent cannot use these — it would be ambiguous when the root routes
# via ``@<name>``.
_RESERVED_NAMES: frozenset[str] = frozenset({
    # The four original built-in specialists.
    "researcher", "writer", "analyst", "reviewer",
    # W3 — three new built-ins.
    "explorer", "planner", "verifier",
    # The root.
    "cowork_root",
})

# Cap on description length that ends up in the root prompt's sub-agent
# catalog. The full description is still stored on ``CustomAgent`` for
# the UI; only the prompt-injection version is truncated. Same defence
# as ``DESCRIPTION_PROMPT_CAP`` in the skill loader: a third-party agent
# can't smuggle long instructions in via its description line.
DESCRIPTION_PROMPT_CAP = 300

CustomAgentSource = Literal["user", "global"]


class CustomAgentLoadError(Exception):
    """Raised for malformed agent Markdown files."""


@dataclass(frozen=True)
class CustomAgent:
    """A user-defined sub-agent loaded from Markdown."""

    name: str
    description: str
    instruction: str  # Markdown body = system prompt content
    config: AgentConfig
    source: CustomAgentSource
    path: Path

    @property
    def description_prompt(self) -> str:
        """Truncated description for the root prompt's sub-agent catalog."""
        if len(self.description) <= DESCRIPTION_PROMPT_CAP:
            return self.description
        return self.description[:DESCRIPTION_PROMPT_CAP].rstrip() + "…"


def _split_frontmatter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    """Parse YAML frontmatter, return (frontmatter_dict, body_str)."""
    if not text.startswith(_FRONTMATTER_FENCE):
        raise CustomAgentLoadError(
            f"missing YAML frontmatter (file must start with '---'): {path}",
        )
    lines = text.splitlines()
    if len(lines) < 3:
        raise CustomAgentLoadError(f"truncated frontmatter in {path}")
    end = -1
    for idx in range(1, len(lines)):
        if lines[idx].rstrip() == _FRONTMATTER_FENCE:
            end = idx
            break
    if end == -1:
        raise CustomAgentLoadError(
            f"missing closing frontmatter fence in {path}",
        )
    fm_text = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1:]).lstrip("\n")
    try:
        fm = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as exc:
        raise CustomAgentLoadError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(fm, dict):
        raise CustomAgentLoadError(f"frontmatter must be a mapping in {path}")
    return fm, body


def _reject_non_printable(value: str, label: str, path: Path) -> None:
    """Mirror skill loader: disallow control chars in user-visible strings.

    Defence against an injection-via-frontmatter where the description
    embeds a newline + injected directives the root might honor when
    rendering the sub-agent catalog.
    """
    for ch in value:
        if ord(ch) < 0x20 and ch != "\t":
            raise CustomAgentLoadError(
                f"control character in {label!r} of {path}: "
                f"U+{ord(ch):04X} not permitted",
            )


def parse_agent_md(path: Path, source: CustomAgentSource) -> CustomAgent:
    """Parse one ``<name>.md`` agent definition.

    Required frontmatter: ``name``, ``description``. The Markdown body
    after the closing fence becomes the instruction string. Optional:
    ``allowed_tools``, ``disallowed_tools`` (lists of strings),
    ``model`` (mapping with ``base_url`` / ``model`` / ``api_key``).
    """
    if not path.is_file():
        raise CustomAgentLoadError(f"not a file: {path}")
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="strict")
    fm, body = _split_frontmatter(text, path)

    name = fm.get("name")
    if not isinstance(name, str) or not name:
        raise CustomAgentLoadError(f"missing 'name' in {path}")
    if name in _RESERVED_NAMES:
        raise CustomAgentLoadError(
            f"name {name!r} is reserved for a built-in sub-agent ({path})",
        )
    # ADK's ``LlmAgent`` rejects non-identifier names. We validate here
    # so the agent author gets the error pointed at their .md file rather
    # than an opaque Pydantic stack trace at ``build_root_agent`` time.
    if not name.isidentifier():
        raise CustomAgentLoadError(
            f"name {name!r} must be a valid Python identifier "
            f"(letters/digits/underscore, no hyphens) in {path}",
        )

    description = fm.get("description")
    if not isinstance(description, str) or not description:
        raise CustomAgentLoadError(f"missing 'description' in {path}")

    instruction_body = body.strip()
    if not instruction_body:
        raise CustomAgentLoadError(
            f"empty instruction body (Markdown after the frontmatter "
            f"fence): {path}",
        )

    _reject_non_printable(name, "name", path)
    _reject_non_printable(description, "description", path)

    # Optional tool gates.
    allowed_raw = fm.get("allowed_tools")
    if allowed_raw is None:
        allowed_tools: list[str] | None = None
    else:
        if not isinstance(allowed_raw, list) or not all(
            isinstance(t, str) for t in allowed_raw
        ):
            raise CustomAgentLoadError(
                f"'allowed_tools' must be a list of strings in {path}",
            )
        allowed_tools = list(allowed_raw)

    disallowed_raw = fm.get("disallowed_tools", [])
    if not isinstance(disallowed_raw, list) or not all(
        isinstance(t, str) for t in disallowed_raw
    ):
        raise CustomAgentLoadError(
            f"'disallowed_tools' must be a list of strings in {path}",
        )

    # Optional model override.
    model_raw = fm.get("model")
    if model_raw is None:
        model: ModelConfig | None = None
    else:
        if not isinstance(model_raw, dict):
            raise CustomAgentLoadError(
                f"'model' must be a mapping in {path}",
            )
        try:
            model = ModelConfig.model_validate(model_raw)
        except Exception as exc:
            raise CustomAgentLoadError(
                f"invalid model override in {path}: {exc}",
            ) from exc

    config = AgentConfig(
        allowed_tools=allowed_tools,
        disallowed_tools=list(disallowed_raw),
        model=model,
    )

    return CustomAgent(
        name=name,
        description=description,
        instruction=instruction_body,
        config=config,
        source=source,
        path=path,
    )


@dataclass
class CustomAgentRegistry:
    """In-memory index of custom agents discovered under one or more roots."""

    _agents: dict[str, CustomAgent] = field(default_factory=dict)

    def scan(self, root: Path, source: CustomAgentSource) -> int:
        """Scan ``root`` for ``<name>.md`` entries (top-level only —
        no recursion). Returns count added. Later scans overwrite
        earlier ones with the same agent name.
        """
        if not root.is_dir():
            return 0
        added = 0
        for entry in sorted(root.iterdir()):
            if not entry.is_file() or entry.suffix.lower() != ".md":
                continue
            agent = parse_agent_md(entry, source=source)
            self._agents[agent.name] = agent
            added += 1
        return added

    def get(self, name: str) -> CustomAgent | None:
        return self._agents.get(name)

    def list(self) -> list[CustomAgent]:
        return list(self._agents.values())

    def __iter__(self) -> Iterator[CustomAgent]:
        return iter(self._agents.values())

    def __len__(self) -> int:
        return len(self._agents)


__all__ = [
    "CustomAgent",
    "CustomAgentLoadError",
    "CustomAgentRegistry",
    "CustomAgentSource",
    "DESCRIPTION_PROMPT_CAP",
    "parse_agent_md",
]
