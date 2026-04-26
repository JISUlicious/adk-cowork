"""Tests for the U1 workspace-settings store + operator gate.

Slice U1 lifts model + compaction edits onto a new
``WorkspaceSettingsStore`` protocol with FS (SU) + SQLite (MU)
backings. Multi-user PUT routes lift T1's blanket 403 on caller
== ``cfg.auth.operator``. ``HealthResponse`` gains
``is_operator`` + ``operator_configured`` per-request.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from cowork_core import CoworkConfig
from cowork_core.config import (
    AuthConfig,
    CompactionConfig,
    ModelConfig,
    WorkspaceConfig,
)
from cowork_core.storage import (
    FSWorkspaceSettingsStore,
    SqliteWorkspaceSettingsStore,
    build_workspace_settings_store,
)
from cowork_core.storage.sqlite import _open_sqlite
from cowork_server.app import create_app
from cowork_server.auth import UserIdentity, is_operator
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Redirect HOME so single-user FS UserStore writes don't pollute
    the developer's real ``~/.config/cowork/``."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    return fake_home


# ──────────────── FSWorkspaceSettingsStore ────────────────


def test_fs_store_round_trip(tmp_path: Path) -> None:
    cfg_path = tmp_path / "cowork.toml"
    cfg_path.write_text(
        '[model]\nmodel = "old"\nbase_url = "http://old/v1"\n'
        '[compaction]\nenabled = true\ncompaction_interval = 6\n',
        encoding="utf-8",
    )
    store = FSWorkspaceSettingsStore(cfg_path)

    overrides = store.get_overrides()
    assert overrides["model"]["model"] == "old"
    assert overrides["compaction"]["compaction_interval"] == 6

    section = store.set_section("model", {"model": "new"})
    assert section["model"] == "new"
    # base_url untouched.
    assert section["base_url"] == "http://old/v1"
    # File on disk reflects the change.
    import tomllib
    on_disk = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    assert on_disk["model"]["model"] == "new"


# ──────────────── SqliteWorkspaceSettingsStore ────────────────


def test_sqlite_store_round_trip() -> None:
    conn = _open_sqlite(":memory:")
    store = SqliteWorkspaceSettingsStore(conn)

    # Empty on first build.
    assert store.get_overrides() == {}

    section = store.set_section("model", {
        "base_url": "http://x/v1",
        "model": "qwen-7b",
    })
    assert section["model"] == "qwen-7b"
    assert section["base_url"] == "http://x/v1"

    # get_overrides reads back grouped by section.
    overrides = store.get_overrides()
    assert overrides["model"]["model"] == "qwen-7b"
    assert overrides["model"]["base_url"] == "http://x/v1"

    # Upsert second time keeps prior keys.
    store.set_section("model", {"api_key": "env:KEY"})
    overrides = store.get_overrides()
    assert overrides["model"] == {
        "base_url": "http://x/v1",
        "model": "qwen-7b",
        "api_key": "env:KEY",
    }


def test_sqlite_store_none_in_patch_means_leave_alone() -> None:
    conn = _open_sqlite(":memory:")
    store = SqliteWorkspaceSettingsStore(conn)
    store.set_section("model", {"model": "keep-me", "base_url": "http://x/v1"})
    # None should NOT clobber.
    store.set_section("model", {"model": None, "base_url": "http://y/v1"})
    overrides = store.get_overrides()
    assert overrides["model"]["model"] == "keep-me"
    assert overrides["model"]["base_url"] == "http://y/v1"


def test_sqlite_store_persists_complex_values() -> None:
    """JSON-encoded values survive bool / int / str / nested types."""
    conn = _open_sqlite(":memory:")
    store = SqliteWorkspaceSettingsStore(conn)
    store.set_section("compaction", {
        "enabled": True,
        "compaction_interval": 12,
        "overlap_size": 0,
    })
    overrides = store.get_overrides()
    assert overrides["compaction"]["enabled"] is True
    assert overrides["compaction"]["compaction_interval"] == 12
    assert overrides["compaction"]["overlap_size"] == 0


# ──────────────── Factory ────────────────


def test_build_factory_returns_fs_in_su(tmp_path: Path) -> None:
    cfg_path = tmp_path / "cowork.toml"
    cfg_path.write_text("[model]\nmodel='x'\n", encoding="utf-8")
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    from cowork_core.workspace import Workspace
    store = build_workspace_settings_store(cfg, Workspace(root=tmp_path), cfg_path)
    assert isinstance(store, FSWorkspaceSettingsStore)


def test_build_factory_returns_sqlite_in_mu(tmp_path: Path) -> None:
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(keys={"k1": "alice"}),
    )
    from cowork_core.workspace import Workspace
    store = build_workspace_settings_store(
        cfg, Workspace(root=tmp_path), config_path=None,
    )
    assert isinstance(store, SqliteWorkspaceSettingsStore)


def test_build_factory_returns_none_in_env_only_su(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    from cowork_core.workspace import Workspace
    store = build_workspace_settings_store(
        cfg, Workspace(root=tmp_path), config_path=None,
    )
    assert store is None


# ──────────────── Boot-time merge ────────────────


def test_build_runtime_merges_db_overrides_in_mu(tmp_path: Path) -> None:
    """MU runtime boots with TOML defaults but a populated DB; the
    runtime's effective ``cfg.model.model`` reflects the DB override."""
    from cowork_core.runner import build_runtime

    # Pre-seed the DB.
    db_path = tmp_path / "multiuser.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = _open_sqlite(db_path)
    store = SqliteWorkspaceSettingsStore(conn)
    store.set_section("model", {"model": "claude-sonnet"})
    store.set_section("compaction", {"compaction_interval": 99})
    conn.close()

    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        model=ModelConfig(model="default-model"),
        compaction=CompactionConfig(compaction_interval=6),
        auth=AuthConfig(keys={"k1": "alice"}),
    )
    runtime = build_runtime(cfg)
    assert runtime.cfg.model.model == "claude-sonnet"
    assert runtime.cfg.compaction.compaction_interval == 99


def test_build_runtime_warns_on_su_with_populated_db(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """R4 — startup warning when SU mode boots over a DB with rows
    in ``workspace_settings`` (mode-flip residue)."""
    from cowork_core.runner import build_runtime

    db_path = tmp_path / "multiuser.db"
    conn = _open_sqlite(db_path)
    SqliteWorkspaceSettingsStore(conn).set_section("model", {"model": "x"})
    conn.close()

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    build_runtime(cfg)
    captured = capsys.readouterr()
    assert "[storage] SU mode but workspace_settings table has 1 rows" in captured.out


# ──────────────── R3 — duplicate label validator ────────────────


def test_auth_config_rejects_duplicate_labels() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="duplicate label"):
        AuthConfig(keys={"k1": "alice", "k2": "alice"})


def test_auth_config_accepts_unique_labels() -> None:
    cfg = AuthConfig(keys={"k1": "alice", "k2": "bob"})
    assert cfg.keys == {"k1": "alice", "k2": "bob"}


# ──────────────── is_operator helper ────────────────


def test_is_operator_su_always_true() -> None:
    cfg = CoworkConfig()  # empty auth.keys → SU
    assert is_operator(cfg, UserIdentity(user_id="local", label="local")) is True


def test_is_operator_mu_no_operator_set() -> None:
    cfg = CoworkConfig(auth=AuthConfig(keys={"k1": "alice"}))
    assert is_operator(cfg, UserIdentity(user_id="hash1", label="alice")) is False


def test_is_operator_mu_caller_is_operator() -> None:
    cfg = CoworkConfig(
        auth=AuthConfig(keys={"k1": "alice"}, operator="alice"),
    )
    assert is_operator(cfg, UserIdentity(user_id="hash1", label="alice")) is True


def test_is_operator_mu_caller_is_not_operator() -> None:
    cfg = CoworkConfig(
        auth=AuthConfig(keys={"k1": "alice", "k2": "bob"}, operator="alice"),
    )
    assert is_operator(cfg, UserIdentity(user_id="hash2", label="bob")) is False


# ──────────────── PUT routes ────────────────


def _su_client(tmp_path: Path) -> tuple[TestClient, Path]:
    cfg_path = tmp_path / "cowork.toml"
    cfg_path.write_text(
        '[model]\nmodel = "default"\nbase_url = "http://localhost:18000/v1"\n'
        'api_key = "env:OPENAI_API_KEY"\n'
        '[compaction]\nenabled = true\ncompaction_interval = 6\n'
        'overlap_size = 1\ntoken_threshold = 32000\n'
        'event_retention_size = 20\n',
        encoding="utf-8",
    )
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    return TestClient(create_app(cfg, token="t", config_path=cfg_path)), cfg_path


def _mu_client(
    tmp_path: Path,
    operator: str = "",
) -> TestClient:
    auth_kwargs: dict[str, Any] = {"keys": {"alice-k": "alice", "bob-k": "bob"}}
    if operator:
        auth_kwargs["operator"] = operator
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(**auth_kwargs),
    )
    return TestClient(create_app(cfg, token="t"))


def test_put_model_in_su_writes_toml(tmp_path: Path) -> None:
    client, cfg_path = _su_client(tmp_path)
    r = client.put(
        "/v1/config/model",
        headers={"x-cowork-token": "t"},
        json={"model": "qwen-3"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"] == "qwen-3"
    import tomllib
    on_disk = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    assert on_disk["model"]["model"] == "qwen-3"


def test_put_model_in_mu_no_operator_403s(tmp_path: Path) -> None:
    client = _mu_client(tmp_path, operator="")
    r = client.put(
        "/v1/config/model",
        headers={"x-cowork-token": "alice-k"},
        json={"model": "evil"},
    )
    assert r.status_code == 403
    assert "no operator is configured" in r.json()["detail"]


def test_put_model_in_mu_non_operator_403s(tmp_path: Path) -> None:
    client = _mu_client(tmp_path, operator="alice")
    r = client.put(
        "/v1/config/model",
        headers={"x-cowork-token": "bob-k"},
        json={"model": "evil"},
    )
    assert r.status_code == 403
    assert "operator-only" in r.json()["detail"]


def test_put_model_in_mu_operator_writes_db(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    client = _mu_client(tmp_path, operator="alice")
    r = client.put(
        "/v1/config/model",
        headers={"x-cowork-token": "alice-k"},
        json={"model": "claude-sonnet"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"] == "claude-sonnet"
    # DB row exists.
    db_path = tmp_path / "multiuser.db"
    assert db_path.is_file()
    import sqlite3
    rows = sqlite3.connect(str(db_path)).execute(
        "SELECT key, value FROM workspace_settings",
    ).fetchall()
    keys = {r[0] for r in rows}
    assert "model.model" in keys
    # R5 — log line emitted on save.
    captured = capsys.readouterr()
    assert "[settings] model.model updated → multiuser.db" in captured.out
    assert "operator=alice" in captured.out


def test_put_compaction_in_mu_validates_ranges(tmp_path: Path) -> None:
    client = _mu_client(tmp_path, operator="alice")
    r = client.put(
        "/v1/config/compaction",
        headers={"x-cowork-token": "alice-k"},
        json={"compaction_interval": 0},
    )
    assert r.status_code == 422


# ──────────────── /v1/config/effective ────────────────


def test_effective_returns_merged_with_source_map_su(tmp_path: Path) -> None:
    client, cfg_path = _su_client(tmp_path)
    r = client.get(
        "/v1/config/effective",
        headers={"x-cowork-token": "t"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["model"]["model"] == "default"
    # In SU the FS backing reads cowork.toml; values are flagged as toml.
    assert body["source"]["model.model"] == "toml"
    assert body["source"]["compaction.enabled"] == "toml"


def test_effective_marks_db_overridden_keys_in_mu(tmp_path: Path) -> None:
    client = _mu_client(tmp_path, operator="alice")
    # Operator saves a model override.
    client.put(
        "/v1/config/model",
        headers={"x-cowork-token": "alice-k"},
        json={"model": "claude-sonnet"},
    )
    # Get effective from any user (read-only, no operator gate).
    r = client.get(
        "/v1/config/effective",
        headers={"x-cowork-token": "bob-k"},
    )
    assert r.status_code == 200
    body = r.json()
    # The DB-saved key is flagged "db"; un-overridden keys stay "toml".
    assert body["source"]["model.model"] == "db"
    assert body["source"]["model.base_url"] == "toml"


# ──────────────── Health surface ────────────────


def test_health_is_operator_su(tmp_path: Path) -> None:
    client, _ = _su_client(tmp_path)
    r = client.get("/v1/health", headers={"x-cowork-token": "t"})
    body = r.json()
    assert body["is_operator"] is True
    assert body["operator_configured"] is False  # SU doesn't need an operator


def test_health_is_operator_mu_per_caller(tmp_path: Path) -> None:
    client = _mu_client(tmp_path, operator="alice")
    alice = client.get("/v1/health", headers={"x-cowork-token": "alice-k"}).json()
    assert alice["is_operator"] is True
    assert alice["operator_configured"] is True
    bob = client.get("/v1/health", headers={"x-cowork-token": "bob-k"}).json()
    assert bob["is_operator"] is False
    assert bob["operator_configured"] is True
