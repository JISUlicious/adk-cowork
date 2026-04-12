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


def test_cli_importable() -> None:
    import cowork_cli.main  # noqa: F401
