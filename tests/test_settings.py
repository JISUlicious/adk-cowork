"""Tests for the Settings UI backend (Slice T1).

Atomic TOML writer + config / profile / memory routes.

The autouse ``_isolate_home`` fixture redirects ``HOME`` (and the
Windows equivalent ``USERPROFILE``) to a per-test temp directory so
``FSUserStore``'s default root (``~/.config/cowork/``) lands in the
sandbox instead of the developer's real home — single-user mode
tests would otherwise pollute the dev's actual config dir.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cowork_core import CoworkConfig
from cowork_core.config import AuthConfig, WorkspaceConfig
from cowork_core.config_writer import ConfigWriteError, update_toml_section
from cowork_server.app import create_app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Redirect ``$HOME`` (and ``$USERPROFILE``) to a per-test temp
    dir so ``Path("~/.config/cowork").expanduser()`` lands inside
    ``tmp_path`` instead of the real home dir."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    return fake_home


# ───────────────────────── update_toml_section ─────────────────────────


def test_update_toml_section_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "cowork.toml"
    p.write_text(
        "[model]\n"
        'base_url = "http://old.example/v1"\n'
        'model = "old-model"\n'
        'api_key = "env:OLD_KEY"\n'
        "\n"
        "[workspace]\n"
        'root = "/tmp/ws"\n',
        encoding="utf-8",
    )
    data = update_toml_section(
        p, "model",
        {"base_url": "http://new.example/v1", "model": "new-model"},
    )
    assert data["model"]["base_url"] == "http://new.example/v1"
    assert data["model"]["model"] == "new-model"
    # api_key untouched.
    assert data["model"]["api_key"] == "env:OLD_KEY"
    # Other sections survive verbatim.
    assert data["workspace"]["root"] == "/tmp/ws"
    # File on disk reparses to the same shape.
    import tomllib
    reparsed = tomllib.loads(p.read_text(encoding="utf-8"))
    assert reparsed == data


def test_update_toml_section_creates_section_when_missing(tmp_path: Path) -> None:
    p = tmp_path / "cowork.toml"
    p.write_text("[workspace]\nroot = '/tmp/ws'\n", encoding="utf-8")
    data = update_toml_section(p, "model", {"model": "fresh"})
    assert data["model"]["model"] == "fresh"
    assert data["workspace"]["root"] == "/tmp/ws"


def test_update_toml_section_drops_none_keys(tmp_path: Path) -> None:
    """``None`` in the patch means 'leave alone' — clients send full
    Pydantic dumps with optional fields, and we must not blow them
    away when they were left empty."""
    p = tmp_path / "cowork.toml"
    p.write_text(
        "[model]\nmodel = 'keep-me'\nbase_url = 'old'\n",
        encoding="utf-8",
    )
    data = update_toml_section(
        p, "model", {"base_url": "new", "model": None, "api_key": None},
    )
    assert data["model"]["model"] == "keep-me"
    assert data["model"]["base_url"] == "new"


def test_update_toml_section_raises_on_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigWriteError, match="not found"):
        update_toml_section(tmp_path / "nope.toml", "model", {})


def test_update_toml_section_raises_on_invalid_toml(tmp_path: Path) -> None:
    p = tmp_path / "cowork.toml"
    p.write_text("not = a = valid = toml\n", encoding="utf-8")
    with pytest.raises(ConfigWriteError, match="invalid"):
        update_toml_section(p, "model", {})


def test_update_toml_section_preserves_comments(tmp_path: Path) -> None:
    """V4a — comments + whitespace round-trip across the writer.
    Pre-V4a (under tomli_w) this would lose every comment."""
    p = tmp_path / "cowork.toml"
    p.write_text(
        "# Top-of-file note from the operator\n"
        "\n"
        "[model]\n"
        "# pin to the same model in dev as in prod\n"
        'model = "old"\n'
        'base_url = "http://old/v1"  # internal proxy\n'
        "\n"
        "[workspace]\n"
        "# Default workspace for the team.\n"
        "root = '/tmp/ws'\n",
        encoding="utf-8",
    )
    update_toml_section(p, "model", {"model": "new"})
    after = p.read_text(encoding="utf-8")
    assert "# Top-of-file note from the operator" in after
    assert "# pin to the same model in dev as in prod" in after
    assert "# internal proxy" in after
    assert "# Default workspace for the team." in after
    # And the edit landed.
    assert 'model = "new"' in after


# ───────────────────────── PUT /v1/config/model ─────────────────────────


def _make_su_client(tmp_path: Path) -> tuple[TestClient, Path]:
    """Helper — single-user mode with an on-disk cowork.toml."""
    cfg_path = tmp_path / "cowork.toml"
    cfg_path.write_text(
        "[model]\n"
        'base_url = "http://localhost:18000/v1"\n'
        'model = "default"\n'
        'api_key = "env:OPENAI_API_KEY"\n'
        "\n"
        "[compaction]\n"
        "enabled = true\n"
        "compaction_interval = 6\n"
        "overlap_size = 1\n"
        "token_threshold = 32000\n"
        "event_retention_size = 20\n",
        encoding="utf-8",
    )
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    app = create_app(cfg, token="t", config_path=cfg_path)
    return TestClient(app), cfg_path


def test_put_config_model_updates_file_and_returns_view(tmp_path: Path) -> None:
    client, cfg_path = _make_su_client(tmp_path)
    r = client.put(
        "/v1/config/model",
        headers={"x-cowork-token": "t"},
        json={"base_url": "http://new.example/v1", "model": "qwen-7b"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["base_url"] == "http://new.example/v1"
    assert body["model"] == "qwen-7b"
    # File on disk reflects the edit.
    import tomllib
    on_disk = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    assert on_disk["model"]["base_url"] == "http://new.example/v1"
    assert on_disk["model"]["model"] == "qwen-7b"
    # api_key untouched.
    assert on_disk["model"]["api_key"] == "env:OPENAI_API_KEY"


def test_put_config_model_returns_403_in_multi_user(tmp_path: Path) -> None:
    cfg_path = tmp_path / "cowork.toml"
    cfg_path.write_text("[model]\nmodel='x'\n", encoding="utf-8")
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(keys={"key1": "alice"}),
    )
    app = create_app(cfg, token="t", config_path=cfg_path)
    client = TestClient(app)
    r = client.put(
        "/v1/config/model",
        headers={"x-cowork-token": "alice-key1"},  # bogus, doesn't matter
        json={"model": "evil"},
    )
    # Multi-user routes go through the auth surface; the request might
    # 401 first if the token's wrong. Use a real key.
    r = client.put(
        "/v1/config/model",
        headers={"x-cowork-token": "key1"},
        json={"model": "evil"},
    )
    assert r.status_code == 403
    assert "operator" in r.json()["detail"]


def test_put_config_model_returns_503_in_env_only_mode(tmp_path: Path) -> None:
    """No COWORK_CONFIG_PATH → no on-disk TOML → no edit possible."""
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    app = create_app(cfg, token="t")  # no config_path
    client = TestClient(app)
    r = client.put(
        "/v1/config/model",
        headers={"x-cowork-token": "t"},
        json={"model": "x"},
    )
    assert r.status_code == 503
    assert "env-only" in r.json()["detail"]


# ───────────────────────── PUT /v1/config/compaction ────────────────


def test_put_config_compaction_updates_and_validates(tmp_path: Path) -> None:
    client, cfg_path = _make_su_client(tmp_path)
    r = client.put(
        "/v1/config/compaction",
        headers={"x-cowork-token": "t"},
        json={"compaction_interval": 12, "enabled": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["compaction_interval"] == 12
    assert body["enabled"] is False
    # Out-of-range fails validation (Pydantic 422).
    r2 = client.put(
        "/v1/config/compaction",
        headers={"x-cowork-token": "t"},
        json={"compaction_interval": 0},
    )
    assert r2.status_code == 422


# ───────────────────────── /v1/profile ──────────────────────────────


def test_profile_get_default_is_empty(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    client = TestClient(create_app(cfg, token="t"))
    r = client.get("/v1/profile", headers={"x-cowork-token": "t"})
    assert r.status_code == 200
    body = r.json()
    assert body["display_name"] == ""
    assert body["email"] == ""
    assert body["user_id"]


def test_profile_put_round_trip(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    client = TestClient(create_app(cfg, token="t"))
    r = client.put(
        "/v1/profile",
        headers={"x-cowork-token": "t"},
        json={"display_name": "Alice", "email": "alice@example.com"},
    )
    assert r.status_code == 200
    assert r.json()["display_name"] == "Alice"
    # GET reads it back.
    r2 = client.get("/v1/profile", headers={"x-cowork-token": "t"})
    assert r2.json()["display_name"] == "Alice"
    assert r2.json()["email"] == "alice@example.com"


def test_profile_put_rejects_email_without_at(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    client = TestClient(create_app(cfg, token="t"))
    r = client.put(
        "/v1/profile",
        headers={"x-cowork-token": "t"},
        json={"email": "not-an-email"},
    )
    assert r.status_code == 422
    assert "@" in r.json()["detail"]


def test_profile_isolation_between_users_in_mu(tmp_path: Path) -> None:
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(keys={"alice-k": "alice", "bob-k": "bob"}),
    )
    client = TestClient(create_app(cfg, token="t"))
    # Alice sets her name.
    r = client.put(
        "/v1/profile",
        headers={"x-cowork-token": "alice-k"},
        json={"display_name": "Alice A."},
    )
    assert r.status_code == 200
    # Bob's GET sees the default (empty), not Alice's.
    r2 = client.get("/v1/profile", headers={"x-cowork-token": "bob-k"})
    assert r2.status_code == 200
    assert r2.json()["display_name"] == ""
    # Alice's GET still shows her own.
    r3 = client.get("/v1/profile", headers={"x-cowork-token": "alice-k"})
    assert r3.json()["display_name"] == "Alice A."


# ───────────────────────── /v1/memory ───────────────────────────────


def test_memory_user_pages_list_read_delete(
    tmp_path: Path, _isolate_home: Path,
) -> None:
    """Single-user user-scope memory routes — list, read, delete."""
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    app = create_app(cfg, token="t")
    client = TestClient(app)

    # Pre-seed two pages on disk — ``FSUserStore`` writes
    # ``<root>/<key>`` and ``_isolate_home`` has redirected the FS
    # root to ``<tmp>/home/.config/cowork/``.
    pages_dir = _isolate_home / ".config" / "cowork" / "memory" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    (pages_dir / "note-a.md").write_text("first note body", encoding="utf-8")
    (pages_dir / "note-b.md").write_text("second note body", encoding="utf-8")

    r = client.get("/v1/memory/user/pages", headers={"x-cowork-token": "t"})
    assert r.status_code == 200
    body = r.json()
    assert body["scope"] == "user"
    names = sorted(p["name"] for p in body["pages"])
    assert names == ["note-a.md", "note-b.md"]
    # Preview field is non-empty.
    assert all(p["preview"] for p in body["pages"])

    r2 = client.get(
        "/v1/memory/user/pages/note-a.md",
        headers={"x-cowork-token": "t"},
    )
    assert r2.status_code == 200
    assert r2.json()["content"] == "first note body"

    r3 = client.delete(
        "/v1/memory/user/pages/note-a.md",
        headers={"x-cowork-token": "t"},
    )
    assert r3.status_code == 200
    r4 = client.get(
        "/v1/memory/user/pages/note-a.md",
        headers={"x-cowork-token": "t"},
    )
    assert r4.status_code == 404


def test_memory_project_pages_requires_session_id(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    client = TestClient(create_app(cfg, token="t"))
    r = client.get("/v1/memory/project/pages", headers={"x-cowork-token": "t"})
    assert r.status_code == 400
    assert "session_id" in r.json()["detail"]


def test_memory_invalid_scope_400(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    client = TestClient(create_app(cfg, token="t"))
    r = client.get("/v1/memory/bogus/pages", headers={"x-cowork-token": "t"})
    assert r.status_code == 400


def test_memory_read_404_on_missing(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    client = TestClient(create_app(cfg, token="t"))
    r = client.get(
        "/v1/memory/user/pages/missing.md",
        headers={"x-cowork-token": "t"},
    )
    assert r.status_code == 404


# ───────────────────────── HealthResponse new fields ──────────────────


def test_health_is_multi_user_false_in_su(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    client = TestClient(create_app(cfg, token="t"))
    r = client.get("/v1/health", headers={"x-cowork-token": "t"})
    assert r.status_code == 200
    body = r.json()
    assert body["is_multi_user"] is False
    assert body["has_config_file"] is False


def test_health_is_multi_user_true_in_mu(tmp_path: Path) -> None:
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(keys={"k": "alice"}),
    )
    cfg_path = tmp_path / "cowork.toml"
    cfg_path.write_text("[model]\n", encoding="utf-8")
    client = TestClient(create_app(cfg, token="t", config_path=cfg_path))
    r = client.get("/v1/health", headers={"x-cowork-token": "k"})
    assert r.status_code == 200
    body = r.json()
    assert body["is_multi_user"] is True
    assert body["has_config_file"] is True
