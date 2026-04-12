"""Web search tool family — currently just ``search.web`` (DuckDuckGo)."""

from __future__ import annotations

from google.adk.tools.function_tool import FunctionTool

from cowork_core.tools.registry import ToolRegistry
from cowork_core.tools.search.web import search_web


def register_search_tools(registry: ToolRegistry) -> None:
    registry.register(FunctionTool(search_web))


__all__ = ["register_search_tools", "search_web"]
