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


def test_user_servers_persist_to_json(tmp_path: Path) -> None:
    """Saving a user MCP server writes
    ``<workspace>/global/mcp/servers.json``; reloading the runtime
    picks it up. TOML-declared bundled servers stay distinct."""
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        mcp_servers={
            "from_toml": McpServerConfig(transport="stdio", command="echo"),
        },
    )
    runtime = build_runtime(cfg)
    assert runtime.mcp_status["from_toml"].status == "ok"

    runtime.save_mcp_server(
        "from_user",
        McpServerConfig(transport="stdio", command="echo", args=["user"]),
    )
    servers_path = tmp_path / "global" / "mcp" / "servers.json"
    assert servers_path.is_file()

    # Fresh runtime over the same workspace picks up the user server.
    fresh = build_runtime(cfg)
    listing = fresh.list_mcp_servers()
    assert "from_toml" in listing
    assert "from_user" in listing
    assert listing["from_toml"][0].bundled is True
    assert listing["from_user"][0].bundled is False


def test_delete_user_server(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    runtime.save_mcp_server(
        "tmp", McpServerConfig(transport="stdio", command="echo"),
    )
    assert "tmp" in runtime.list_mcp_servers()

    runtime.delete_mcp_server("tmp")
    assert "tmp" not in _read_servers_json(tmp_path)


def test_delete_bundled_refused(tmp_path: Path) -> None:
    from cowork_core.runner import MCPInstallError

    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        mcp_servers={
            "shipped": McpServerConfig(transport="stdio", command="echo"),
        },
    )
    runtime = build_runtime(cfg)
    with pytest.raises(MCPInstallError, match="bundled"):
        runtime.delete_mcp_server("shipped")


def test_delete_unknown_returns_404_via_route(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    app = create_app(cfg, token="t")
    client = TestClient(app)
    r = client.delete(
        "/v1/mcp/servers/nope", headers={"x-cowork-token": "t"},
    )
    assert r.status_code == 404


def test_restart_rebuilds_status(tmp_path: Path) -> None:
    """``restart_mcp`` re-mounts toolsets from the *current*
    effective config, so a server saved after boot shows up in the
    status dict after restart."""
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    assert runtime.mcp_status == {}

    runtime.save_mcp_server(
        "added", McpServerConfig(transport="stdio", command="echo"),
    )
    # Save alone doesn't update mcp_status — restart does.
    assert "added" not in runtime.mcp_status

    runtime.restart_mcp()
    assert "added" in runtime.mcp_status
    assert runtime.mcp_status["added"].status == "ok"


def _read_servers_json(workspace_root: Path) -> dict[str, dict]:
    import json

    p = workspace_root / "global" / "mcp" / "servers.json"
    if not p.is_file():
        return {}
    return json.loads(p.read_text())


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
