"""Multi-user auth + per-user workspace isolation."""

from __future__ import annotations

from pathlib import Path

import pytest
from cowork_core import CoworkConfig
from cowork_core.config import AuthConfig, WorkspaceConfig
from cowork_core.runner import build_runtime
from cowork_server.app import create_app
from fastapi.testclient import TestClient


def _multi_user_app(tmp_path: Path) -> tuple[TestClient, dict[str, str]]:
    keys = {"key-alice": "Alice", "key-bob": "Bob"}
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(keys=keys),
    )
    app = create_app(cfg, token="")
    return TestClient(app), keys


def test_projects_are_isolated_per_user(tmp_path: Path) -> None:
    client, _ = _multi_user_app(tmp_path)

    # Alice creates a project.
    r = client.post(
        "/v1/projects",
        headers={"x-cowork-token": "key-alice"},
        json={"name": "Alice Report"},
    )
    assert r.status_code == 200, r.text
    alice_slug = r.json()["slug"]

    # Bob creates one too.
    r = client.post(
        "/v1/projects",
        headers={"x-cowork-token": "key-bob"},
        json={"name": "Bob Report"},
    )
    bob_slug = r.json()["slug"]

    # Alice's list shows only her project.
    r = client.get("/v1/projects", headers={"x-cowork-token": "key-alice"})
    assert r.status_code == 200
    slugs = {p["slug"] for p in r.json()}
    assert alice_slug in slugs
    assert bob_slug not in slugs

    # Bob's list shows only his.
    r = client.get("/v1/projects", headers={"x-cowork-token": "key-bob"})
    slugs = {p["slug"] for p in r.json()}
    assert bob_slug in slugs
    assert alice_slug not in slugs


def test_user_workspaces_land_under_users_subtree(tmp_path: Path) -> None:
    """Multi-user mode routes each user's projects to <root>/users/<uid>/."""
    client, keys = _multi_user_app(tmp_path)

    r = client.post(
        "/v1/projects",
        headers={"x-cowork-token": "key-alice"},
        json={"name": "Alice Proj"},
    )
    slug = r.json()["slug"]

    # Files for Alice live somewhere under users/.
    users_dir = tmp_path / "users"
    assert users_dir.is_dir()
    found = list(users_dir.rglob(f"projects/{slug}/project.toml"))
    assert found, f"expected Alice's project under users/: {list(users_dir.rglob('*'))}"


def test_invalid_key_returns_401(tmp_path: Path) -> None:
    client, _ = _multi_user_app(tmp_path)
    r = client.get("/v1/projects", headers={"x-cowork-token": "nope"})
    assert r.status_code == 401


def test_missing_token_returns_401(tmp_path: Path) -> None:
    """No x-cowork-token header and no ?token query param → 401."""
    client, _ = _multi_user_app(tmp_path)
    r = client.get("/v1/projects")
    assert r.status_code == 401


def test_alice_cannot_read_bobs_session_history(tmp_path: Path) -> None:
    """Cross-tenant access is denied: Bob's session is invisible to Alice.

    The stronger property — Alice gets 404, *not* 403 — means the server
    doesn't even acknowledge the session exists. No side-channel leak of
    "Bob has a session with id X."
    """
    client, _ = _multi_user_app(tmp_path)

    # Bob creates a project + session.
    r = client.post(
        "/v1/projects",
        headers={"x-cowork-token": "key-bob"},
        json={"name": "Bob Secret"},
    )
    assert r.status_code == 200
    bob_slug = r.json()["slug"]

    r = client.post(
        "/v1/sessions",
        headers={"x-cowork-token": "key-bob"},
        json={"project": bob_slug},
    )
    assert r.status_code == 200, r.text
    bob_sid = r.json()["session_id"]

    # Bob can read his own session history fine.
    r = client.get(
        f"/v1/sessions/{bob_sid}/history",
        headers={"x-cowork-token": "key-bob"},
    )
    assert r.status_code == 200

    # Alice asks for Bob's session history — must be 404 (not 403, not 200).
    r = client.get(
        f"/v1/sessions/{bob_sid}/history",
        headers={"x-cowork-token": "key-alice"},
    )
    assert r.status_code == 404


def test_alice_cannot_delete_bobs_project(tmp_path: Path) -> None:
    """Cross-tenant project delete: Alice's DELETE against Bob's slug
    resolves in Alice's own (empty) registry and returns 404."""
    client, _ = _multi_user_app(tmp_path)

    r = client.post(
        "/v1/projects",
        headers={"x-cowork-token": "key-bob"},
        json={"name": "Bob Keep This"},
    )
    bob_slug = r.json()["slug"]

    r = client.delete(
        f"/v1/projects/{bob_slug}",
        headers={"x-cowork-token": "key-alice"},
    )
    assert r.status_code == 404

    # Bob's project still there.
    r = client.get("/v1/projects", headers={"x-cowork-token": "key-bob"})
    assert any(p["slug"] == bob_slug for p in r.json())


def test_load_config_from_toml_enables_multi_user(tmp_path: Path) -> None:
    """The COWORK_CONFIG_PATH path loads [auth].keys from a TOML file,
    which is the only practical way to configure multi-user mode today
    (env vars can't carry a dict)."""
    import os
    from cowork_server.__main__ import _load_config

    cfg_path = tmp_path / "cowork.toml"
    cfg_path.write_text(
        '[workspace]\n'
        f'root = "{tmp_path / "ws"}"\n'
        '\n'
        '[auth]\n'
        'keys = { "alice-key" = "Alice", "bob-key" = "Bob" }\n'
    )
    old = os.environ.get("COWORK_CONFIG_PATH")
    try:
        os.environ["COWORK_CONFIG_PATH"] = str(cfg_path)
        cfg = _load_config()
        assert cfg.auth.keys == {"alice-key": "Alice", "bob-key": "Bob"}
    finally:
        if old is None:
            os.environ.pop("COWORK_CONFIG_PATH", None)
        else:
            os.environ["COWORK_CONFIG_PATH"] = old


def test_load_config_raises_on_missing_path(tmp_path: Path) -> None:
    """A typo in COWORK_CONFIG_PATH must fail loud. Silently falling
    back to env-only is what hid earlier QA confusion (health showed
    ``auth: sidecar`` while the operator had clearly set the path)."""
    import os
    from cowork_server.__main__ import _load_config

    old = os.environ.get("COWORK_CONFIG_PATH")
    try:
        os.environ["COWORK_CONFIG_PATH"] = str(tmp_path / "no-such-file.toml")
        with pytest.raises(SystemExit) as exc:
            _load_config()
        assert "does not exist" in str(exc.value)
    finally:
        if old is None:
            os.environ.pop("COWORK_CONFIG_PATH", None)
        else:
            os.environ["COWORK_CONFIG_PATH"] = old


def test_sidecar_mode_keeps_single_user_behavior(tmp_path: Path) -> None:
    """With no keys configured, everything runs as user_id="local"."""
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    assert not runtime.multi_user
    assert runtime.workspace_for("local") is runtime.workspace
    assert runtime.registry_for("local") is runtime.projects


def test_health_reports_backend_and_auth_mode(tmp_path: Path) -> None:
    client, _ = _multi_user_app(tmp_path)
    r = client.get("/v1/health", headers={"x-cowork-token": "key-alice"})
    assert r.status_code == 200
    data = r.json()
    assert data["backend"] == "local"
    assert data["auth"] == "multi-user"
    assert data["components"] == {
        "eventbus": "ok",
        "limiter": "ok",
        "sessions": "ok",
    }


def test_health_reports_sidecar_when_single_token(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    app = create_app(cfg, token="t")
    client = TestClient(app)
    r = client.get("/v1/health", headers={"x-cowork-token": "t"})
    assert r.status_code == 200
    assert r.json()["auth"] == "sidecar"


@pytest.mark.asyncio
async def test_open_session_uses_user_registry(tmp_path: Path) -> None:
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(keys={"k": "Kate"}),
    )
    runtime = build_runtime(cfg)
    project, session, _ = await runtime.open_session(
        user_id="kate-uid", project_name="MyDoc",
    )
    # The project lives under the user subtree.
    assert project.root.is_relative_to(tmp_path / "users" / "kate-uid")
    assert session.root.is_relative_to(project.root)
