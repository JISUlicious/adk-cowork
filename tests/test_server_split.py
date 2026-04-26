"""Tests for the U0 server split invariants.

cowork-server-app and cowork-server-web are thin wrappers around the
shared cowork-server.app.create_app, with mode-based route filtering
that hides MU-only routes from the SU sidecar and vice versa.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cowork_core import CoworkConfig
from cowork_core.config import AuthConfig, WorkspaceConfig
from cowork_server.app import create_app as shared_create_app
from cowork_server_app import create_app as app_create_app
from cowork_server_web import create_app as web_create_app


def _route_paths(app) -> set[str]:
    return {r.path for r in app.router.routes if hasattr(r, "path")}


def test_app_backend_filters_managed_project_routes(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    paths = _route_paths(app_create_app(cfg, token="t"))
    # Common routes still present.
    assert "/v1/health" in paths
    assert "/v1/sessions" in paths
    assert "/v1/memory/{scope}/pages" in paths
    # Local-dir routes still present.
    assert "/v1/local-files" in paths
    assert "/v1/local-sessions" in paths
    # Managed projects + files filtered out.
    assert "/v1/projects" not in paths
    assert "/v1/projects/{project}/files/{path:path}" not in paths


def test_web_backend_filters_local_dir_routes(tmp_path: Path) -> None:
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(keys={"k1": "alice"}),
    )
    paths = _route_paths(web_create_app(cfg, token="t"))
    # Common routes still present.
    assert "/v1/health" in paths
    assert "/v1/memory/{scope}/pages" in paths
    # Managed projects + files present.
    assert "/v1/projects" in paths
    assert "/v1/projects/{project}/files/{path:path}" in paths
    # Local-dir routes filtered out.
    assert "/v1/local-files" not in paths
    assert "/v1/local-sessions" not in paths


def test_app_backend_refuses_multi_user_config(tmp_path: Path) -> None:
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(keys={"k1": "alice"}),
    )
    with pytest.raises(ValueError, match="single-user"):
        app_create_app(cfg, token="t")


def test_web_backend_refuses_empty_keys(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    with pytest.raises(ValueError, match="multi-user"):
        web_create_app(cfg, token="t")


def test_shared_create_app_mode_all_keeps_all_routes(tmp_path: Path) -> None:
    """Back-compat: ``mode='all'`` (default) registers every route, so
    existing tests using ``cowork_server.app.create_app`` directly
    keep working without changes."""
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    paths = _route_paths(shared_create_app(cfg, token="t"))
    # All three groups present together — that's the back-compat contract.
    assert "/v1/local-files" in paths
    assert "/v1/projects" in paths
    assert "/v1/health" in paths


def test_shared_create_app_mode_web_requires_keys(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    with pytest.raises(ValueError, match="auth.keys"):
        shared_create_app(cfg, token="t", mode="web")
