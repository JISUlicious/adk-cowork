"""Tool registry — a tiny name-keyed collection of ADK ``BaseTool`` instances.

Each cowork tool module (``tools/fs/read.py``, ``tools/shell/run.py``, …)
exposes a ``register(registry)`` function that appends a ``FunctionTool`` built
from its plain async function. The runner assembles the registry and hands its
``.as_list()`` to the root ``LlmAgent``.

Kept intentionally minimal: no categories, no priorities, no filter DSL. If we
need any of that later, add it when we actually have two callers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from google.adk.tools.base_tool import BaseTool


@dataclass
class ToolRegistry:
    _tools: dict[str, BaseTool] = field(default_factory=dict)

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def as_list(self) -> list[BaseTool]:
        return [self._tools[name] for name in sorted(self._tools)]

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return name in self._tools
