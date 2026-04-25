"""Tests for the MCP integration surface (Slice III).

Cowork's ``build_mcp_toolset`` dispatches on transport, threads
``tool_filter`` through to ADK's ``MCPToolset``, and returns
``(toolset, last_error)`` so callers can populate
``CoworkRuntime.mcp_status``. ``/v1/health.mcp`` is the user-facing
surface for that status. These tests pin the behaviour without
spinning up a real MCP subprocess — we inspect the constructed
``MCPToolset`` and the runtime status dict directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cowork_core import CoworkConfig
from cowork_core.agents.root_agent import build_mcp_toolset
from cowork_core.config import McpServerConfig, WorkspaceConfig
from cowork_core.runner import build_runtime
from cowork_server.app import create_app
from fastapi.testclient import TestClient


def test_stdio_transport_builds_toolset() -> None:
    cfg = McpServerConfig(
        command="echo",
        args=["hello"],
        transport="stdio",
        tool_filter=["foo", "bar"],
    )
    toolset, error = build_mcp_toolset(cfg)
    assert error is None, error
    assert toolset is not None
    # ADK threads the filter through to MCPToolset; tool names land
    # under the toolset's ``_tool_filter`` private attribute. Match
    # against the public ``tool_filter`` if exposed; fall back to
    # private if needed (ADK's API has historically renamed this).
    filt = getattr(toolset, "tool_filter", None) or getattr(toolset, "_tool_filter", None)
    assert filt == ["foo", "bar"]


def test_stdio_missing_command_errors_cleanly() -> None:
    cfg = McpServerConfig(transport="stdio")  # no command
    toolset, error = build_mcp_toolset(cfg)
    assert toolset is None
    assert error is not None
    assert "command" in error


def test_sse_transport_builds_toolset() -> None:
    cfg = McpServerConfig(
        transport="sse",
        url="https://example.com/mcp",
        headers={"Authorization": "Bearer x"},
    )
    toolset, error = build_mcp_toolset(cfg)
    assert error is None, error
    assert toolset is not None


def test_sse_missing_url_errors_cleanly() -> None:
    cfg = McpServerConfig(transport="sse")
    toolset, error = build_mcp_toolset(cfg)
    assert toolset is None
    assert error is not None
    assert "url" in error


def test_http_transport_builds_toolset() -> None:
    cfg = McpServerConfig(
        transport="http",
        url="https://example.com/mcp",
    )
    toolset, error = build_mcp_toolset(cfg)
    assert error is None, error
    assert toolset is not None


def test_runtime_records_mcp_status_for_each_configured_server(
    tmp_path: Path,
) -> None:
    """``build_runtime`` populates ``CoworkRuntime.mcp_status`` with
    one entry per configured server. The previously-silent failure
    path now surfaces ``last_error`` so /v1/health can render it."""
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        mcp_servers={
            "good": McpServerConfig(transport="stdio", command="echo"),
            "broken": McpServerConfig(transport="stdio"),  # no command
        },
    )
    runtime = build_runtime(cfg)
    assert set(runtime.mcp_status.keys()) == {"good", "broken"}
    assert runtime.mcp_status["good"].status == "ok"
    assert runtime.mcp_status["good"].last_error is None
    assert runtime.mcp_status["broken"].status == "error"
    assert runtime.mcp_status["broken"].last_error is not None
    assert "command" in runtime.mcp_status["broken"].last_error


def test_health_payload_includes_mcp_status(tmp_path: Path) -> None:
    """The /v1/health route surfaces the same data Settings → System
    renders as the "MCP servers" row."""
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        mcp_servers={
            "fs": McpServerConfig(transport="stdio", command="echo"),
            "broken": McpServerConfig(transport="sse"),  # no url
        },
    )
    app = create_app(cfg, token="t")
    client = TestClient(app)
    r = client.get("/v1/health", headers={"x-cowork-token": "t"})
    assert r.status_code == 200
    payload = r.json()
    mcp = {entry["name"]: entry for entry in payload["mcp"]}
    assert mcp["fs"]["status"] == "ok"
    assert mcp["fs"]["transport"] == "stdio"
    assert mcp["broken"]["status"] == "error"
    assert mcp["broken"]["transport"] == "sse"
    assert "url" in (mcp["broken"]["last_error"] or "")
