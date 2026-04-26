"""Tests for V2 — live runtime reload.

POST /v1/runtime/reload re-fetches workspace-settings overrides,
merges into cfg, rebuilds the agent + model + Runner in place.
Operator-gated in MU; open in SU.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cowork_core import CoworkConfig
from cowork_core.config import (
    AuthConfig,
    CompactionConfig,
    ModelConfig,
    WorkspaceConfig,
)
from cowork_core.runner import build_runtime
from cowork_core.storage import SqliteWorkspaceSettingsStore
from cowork_core.storage.sqlite import _open_sqlite
from cowork_server.app import create_app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Path:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    return fake_home


# ──────────────── runtime.reload() ────────────────


@pytest.mark.asyncio
async def test_reload_picks_up_db_overrides_in_mu(tmp_path: Path) -> None:
    """Operator's PUT to workspace_settings_store updates the DB; the
    next reload merges those values into runtime.cfg."""
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        model=ModelConfig(model="default-model"),
        auth=AuthConfig(keys={"k1": "alice"}),
    )
    runtime = build_runtime(cfg)
    assert runtime.cfg.model.model == "default-model"

    # Simulate an operator save (writes to the DB store directly).
    assert runtime.workspace_settings_store is not None
    runtime.workspace_settings_store.set_section(
        "model", {"model": "claude-sonnet"},
    )

    await runtime.reload()
    assert runtime.cfg.model.model == "claude-sonnet"


@pytest.mark.asyncio
async def test_reload_picks_up_compaction_changes(tmp_path: Path) -> None:
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        compaction=CompactionConfig(compaction_interval=6),
        auth=AuthConfig(keys={"k1": "alice"}),
    )
    runtime = build_runtime(cfg)
    assert runtime.cfg.compaction.compaction_interval == 6

    assert runtime.workspace_settings_store is not None
    runtime.workspace_settings_store.set_section(
        "compaction", {"compaction_interval": 12},
    )

    await runtime.reload()
    assert runtime.cfg.compaction.compaction_interval == 12


@pytest.mark.asyncio
async def test_reload_preserves_session_service(tmp_path: Path) -> None:
    """Existing sessions stay reachable across a reload — the
    session_service is the seam that's preserved."""
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    original_session_service = runtime.session_service

    await runtime.reload()
    # Same instance (preserved, not rebuilt).
    assert runtime.runner.session_service is original_session_service


@pytest.mark.asyncio
async def test_reload_no_overrides_is_a_noop_for_cfg(tmp_path: Path) -> None:
    """Reload without any DB overrides leaves cfg unchanged."""
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        model=ModelConfig(model="x"),
        auth=AuthConfig(keys={"k1": "alice"}),
    )
    runtime = build_runtime(cfg)
    snapshot = runtime.cfg.model.model
    await runtime.reload()
    assert runtime.cfg.model.model == snapshot


# ──────────────── /v1/runtime/reload route ────────────────


def test_reload_route_open_in_su(tmp_path: Path) -> None:
    cfg_path = tmp_path / "cowork.toml"
    cfg_path.write_text("[model]\nmodel = 'x'\n", encoding="utf-8")
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    client = TestClient(create_app(cfg, token="t", config_path=cfg_path))
    r = client.post("/v1/runtime/reload", headers={"x-cowork-token": "t"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "reloaded"


def test_reload_route_403s_non_operator_in_mu(tmp_path: Path) -> None:
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(
            keys={"alice-k": "alice", "bob-k": "bob"},
            operator="alice",
        ),
    )
    client = TestClient(create_app(cfg, token="t"))

    # Bob is not the operator → 403.
    r = client.post("/v1/runtime/reload", headers={"x-cowork-token": "bob-k"})
    assert r.status_code == 403

    # Alice is the operator → 200.
    r = client.post("/v1/runtime/reload", headers={"x-cowork-token": "alice-k"})
    assert r.status_code == 200


def test_reload_route_propagates_db_changes_through_cfg(tmp_path: Path) -> None:
    """End-to-end: operator PUTs a config change, reloads, then
    /v1/health.model reflects the new value (because cfg got
    rebound in the create_app closure via nonlocal cfg in the
    reload route)."""
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        model=ModelConfig(model="orig"),
        auth=AuthConfig(
            keys={"alice-k": "alice"},
            operator="alice",
        ),
    )
    client = TestClient(create_app(cfg, token="t"))

    r = client.get("/v1/health", headers={"x-cowork-token": "alice-k"})
    assert r.json()["model"] == "orig"

    client.put(
        "/v1/config/model",
        headers={"x-cowork-token": "alice-k"},
        json={"model": "claude-sonnet"},
    )
    # Before reload: health still shows the merged value because
    # the PUT updated the DB AND the response echoed the new value,
    # but the runtime.cfg snapshot at app build hasn't picked it up
    # yet. Actually, the health route reads cfg directly, and
    # cfg was set to runtime.cfg at create_app time which reflects
    # the boot-merged value. After the PUT, runtime.cfg hasn't
    # changed (no reload). So health should still say "orig".
    r = client.get("/v1/health", headers={"x-cowork-token": "alice-k"})
    assert r.json()["model"] == "orig"

    r = client.post(
        "/v1/runtime/reload",
        headers={"x-cowork-token": "alice-k"},
    )
    assert r.status_code == 200
    assert r.json()["model"] == "claude-sonnet"

    # After reload: health now shows the new model — the closure's
    # cfg got rebound via ``nonlocal``.
    r = client.get("/v1/health", headers={"x-cowork-token": "alice-k"})
    assert r.json()["model"] == "claude-sonnet"
