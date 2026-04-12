"""HTTP tool family — currently just ``http.fetch``."""

from __future__ import annotations

from google.adk.tools.function_tool import FunctionTool

from cowork_core.tools.http.fetch import http_fetch
from cowork_core.tools.registry import ToolRegistry


def register_http_tools(registry: ToolRegistry) -> None:
    registry.register(FunctionTool(http_fetch))


__all__ = ["http_fetch", "register_http_tools"]
