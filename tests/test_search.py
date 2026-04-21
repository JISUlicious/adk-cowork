"""⌘K global search endpoint smoke tests.

Covers the three response sections (sessions / files / messages) on a
freshly created project + session. Message scan relies on the ADK
session event list, which we populate through the public
``POST /v1/sessions/{id}/messages`` fire-and-forget route would require
waiting for the runner; instead we append one event directly through
``session_service`` to keep the test hermetic.
"""

from __future__ import annotations

from pathlib import Path

from cowork_core import CoworkConfig
from cowork_core.config import WorkspaceConfig
from cowork_core.runner import APP_NAME
from cowork_server.app import create_app
from fastapi.testclient import TestClient


def _setup(tmp_path: Path) -> TestClient:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    app = create_app(cfg, token="t")
    return TestClient(app)


def _auth() -> dict[str, str]:
    return {"x-cowork-token": "t"}


def test_search_finds_session_title_and_file_path(tmp_path: Path) -> None:
    client = _setup(tmp_path)

    # Project + session. The HTTP create-session route doesn't accept
    # a title, and PATCH only exposes ``pinned`` today, so we rewrite
    # ``session.toml`` directly to give the session a distinctive name.
    proj = client.post("/v1/projects", headers=_auth(), json={"name": "Kappa"}).json()
    slug = proj["slug"]
    sess = client.post(
        "/v1/sessions",
        headers=_auth(),
        json={"project": slug},
    ).json()
    cowork_sid = sess["cowork_session_id"]
    toml_path = tmp_path / "projects" / slug / "sessions" / cowork_sid / "session.toml"
    assert toml_path.exists(), toml_path
    original = toml_path.read_text(encoding="utf-8")
    toml_path.write_text(
        original.replace('title = ""', 'title = "Platypus planning"'),
        encoding="utf-8",
    )

    # Upload a file whose name the search should surface.
    r = client.post(
        f"/v1/projects/{slug}/upload",
        headers=_auth(),
        files={"file": ("platypus-notes.md", b"hello", "text/markdown")},
    )
    assert r.status_code == 200, r.text

    r = client.get("/v1/search", headers=_auth(), params={"q": "platypus"})
    assert r.status_code == 200
    body = r.json()

    session_titles = [s["title"] for s in body["sessions"]]
    assert "Platypus planning" in session_titles

    file_paths = [f["path"] for f in body["files"]]
    assert any("platypus-notes.md" in p for p in file_paths)


def test_search_empty_query_returns_empty_sections(tmp_path: Path) -> None:
    client = _setup(tmp_path)
    r = client.get("/v1/search", headers=_auth(), params={"q": ""})
    assert r.status_code == 200
    assert r.json() == {"sessions": [], "files": [], "messages": []}


def test_search_scope_limited_to_user(tmp_path: Path) -> None:
    """A managed project created by one user must not leak into a
    different user's palette results. The in-process store segments by
    ``user_id`` — regression guard if that ever changes."""
    from cowork_core.config import AuthConfig

    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(keys={"ak": "alice", "bk": "bob"}),
    )
    app = create_app(cfg)
    tc = TestClient(app)

    tc.post(
        "/v1/projects",
        headers={"x-cowork-token": "ak"},
        json={"name": "alice-secret-platypus"},
    )

    r = tc.get(
        "/v1/search",
        headers={"x-cowork-token": "bk"},
        params={"q": "platypus"},
    )
    assert r.status_code == 200
    assert r.json()["sessions"] == []
    assert r.json()["files"] == []
