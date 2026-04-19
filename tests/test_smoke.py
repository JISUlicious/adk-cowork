"""Import + structural smoke tests that run without any LLM credentials."""

from __future__ import annotations

from pathlib import Path

import pytest


def test_core_imports() -> None:
    import cowork_core  # noqa: F401
    from cowork_core import CoworkConfig

    cfg = CoworkConfig()
    assert cfg.model.model
    assert cfg.policy.mode == "work"
    assert cfg.search.provider == "duckduckgo"


def test_workspace_rejects_traversal(tmp_path: Path) -> None:
    from cowork_core import Workspace, WorkspaceError

    ws = Workspace(root=tmp_path)
    with pytest.raises(WorkspaceError):
        ws.resolve("../outside.txt")


def test_workspace_scratch_dir(tmp_path: Path) -> None:
    from cowork_core import Workspace

    ws = Workspace(root=tmp_path)
    scratch = ws.scratch_dir("default", "s1")
    assert scratch.exists()
    assert scratch.is_relative_to(tmp_path)


def test_server_app_factory() -> None:
    from cowork_server.app import create_app

    app = create_app()
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/v1/health" in paths
    assert "/v1/sessions" in paths
    assert "/v1/projects/{project}/upload" in paths


def test_upload_endpoint_writes_file(tmp_path: Path) -> None:
    from cowork_core import CoworkConfig
    from cowork_core.config import WorkspaceConfig
    from cowork_server.app import create_app
    from fastapi.testclient import TestClient

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    app = create_app(cfg, token="t")
    client = TestClient(app)

    # Project must exist before upload.
    r = client.post(
        "/v1/projects", headers={"x-cowork-token": "t"}, json={"name": "Drop Test"}
    )
    slug = r.json()["slug"]

    r = client.post(
        f"/v1/projects/{slug}/upload",
        headers={"x-cowork-token": "t"},
        files={"file": ("hello.txt", b"hi there", "text/plain")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["size"] == len(b"hi there")
    written = tmp_path / "projects" / slug / "files" / "hello.txt"
    assert written.read_bytes() == b"hi there"


def test_cli_importable() -> None:
    import cowork_cli.main  # noqa: F401


def test_runtime_config_defaults_to_local() -> None:
    from cowork_core import CoworkConfig

    cfg = CoworkConfig()
    assert cfg.runtime.backend == "local"


def test_build_runtime_rejects_unimplemented_backend(tmp_path: Path) -> None:
    from cowork_core import CoworkConfig
    from cowork_core.config import RuntimeConfig, WorkspaceConfig
    from cowork_core.runner import build_runtime

    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        runtime=RuntimeConfig(backend="distributed"),
    )
    with pytest.raises(NotImplementedError, match="not implemented"):
        build_runtime(cfg)
