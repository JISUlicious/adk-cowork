"""Local-dir session flow: user picks a folder, agent operates in it."""

from __future__ import annotations

from pathlib import Path

import pytest
from cowork_core import CoworkConfig
from cowork_core.config import WorkspaceConfig
from cowork_core.execenv import LocalDirExecEnv, ManagedExecEnv
from cowork_core.runner import build_runtime
from cowork_core.tools import COWORK_CONTEXT_KEY


@pytest.mark.asyncio
async def test_open_session_with_workdir_builds_localdir_env(tmp_path: Path) -> None:
    workdir = tmp_path / "user-project"
    workdir.mkdir()
    ws_root = tmp_path / "cowork-ws"

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=ws_root))
    runtime = build_runtime(cfg)

    project, session, adk_sid = await runtime.open_session(workdir=workdir)
    assert project.root == workdir.resolve()
    assert session.root.is_relative_to(workdir.resolve())

    # Session bookkeeping lives under <workdir>/.cowork/sessions/<id>/
    assert session.root.parent == workdir.resolve() / ".cowork" / "sessions"
    assert (session.root / "scratch").is_dir()
    assert (session.root / "transcript.jsonl").exists()

    # The injected context's env is LocalDirExecEnv.
    adk_session = await runtime.runner.session_service.get_session(
        app_name="cowork", user_id="local", session_id=adk_sid,
    )
    assert adk_session is not None
    ctx = adk_session.state[COWORK_CONTEXT_KEY]
    assert isinstance(ctx.env, LocalDirExecEnv)
    assert ctx.env.root() == workdir.resolve()


@pytest.mark.asyncio
async def test_open_session_without_workdir_uses_managed(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)

    project, session, adk_sid = await runtime.open_session(project_name="TestProj")
    adk_session = await runtime.runner.session_service.get_session(
        app_name="cowork", user_id="local", session_id=adk_sid,
    )
    assert adk_session is not None
    ctx = adk_session.state[COWORK_CONTEXT_KEY]
    assert isinstance(ctx.env, ManagedExecEnv)


@pytest.mark.asyncio
async def test_resume_local_session_rehydrates_env(tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    workdir.mkdir()
    (workdir / "existing.txt").write_text("hi")
    ws_root = tmp_path / "ws"

    runtime = build_runtime(
        CoworkConfig(workspace=WorkspaceConfig(root=ws_root)),
    )
    _, session, sid = await runtime.open_session(workdir=workdir)

    # Rebuild runtime from scratch to simulate a process restart.
    runtime2 = build_runtime(
        CoworkConfig(workspace=WorkspaceConfig(root=ws_root)),
    )
    project, resumed, adk_sid = await runtime2.resume_session(
        session_id=session.id, workdir=workdir,
    )
    assert resumed.id == session.id
    assert project.root == workdir.resolve()


@pytest.mark.asyncio
async def test_fs_read_in_local_session_sees_user_files(tmp_path: Path) -> None:
    """End-to-end: put a file in workdir, fs_read sees it via LocalDirExecEnv."""
    workdir = tmp_path / "wd"
    workdir.mkdir()
    (workdir / "report.md").write_text("HELLO\n")
    ws_root = tmp_path / "ws"

    runtime = build_runtime(
        CoworkConfig(workspace=WorkspaceConfig(root=ws_root)),
    )
    _, _, adk_sid = await runtime.open_session(workdir=workdir)

    adk_session = await runtime.runner.session_service.get_session(
        app_name="cowork", user_id="local", session_id=adk_sid,
    )
    assert adk_session is not None
    env = adk_session.state[COWORK_CONTEXT_KEY].env
    resolved = env.resolve("report.md")
    assert resolved.read_text() == "HELLO\n"

    # Escape is rejected.
    err = env.try_resolve("../outside")
    assert isinstance(err, str)
    assert "escapes" in err


@pytest.mark.asyncio
async def test_list_and_delete_local_sessions(tmp_path: Path) -> None:
    workdir = tmp_path / "wd"
    workdir.mkdir()
    ws_root = tmp_path / "ws"

    runtime = build_runtime(
        CoworkConfig(workspace=WorkspaceConfig(root=ws_root)),
    )
    _, s1, _ = await runtime.open_session(workdir=workdir)
    _, s2, _ = await runtime.open_session(workdir=workdir)

    listed = runtime.list_local_sessions(workdir)
    ids = {s.id for s in listed}
    assert s1.id in ids and s2.id in ids

    await runtime.delete_local_session(workdir=workdir, session_id=s1.id)
    assert not (workdir / ".cowork" / "sessions" / s1.id).exists()

    remaining = {s.id for s in runtime.list_local_sessions(workdir)}
    assert remaining == {s2.id}


def test_server_accepts_workdir_body(tmp_path: Path) -> None:
    from cowork_server.app import create_app
    from fastapi.testclient import TestClient

    workdir = tmp_path / "wd"
    workdir.mkdir()
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path / "ws"))
    app = create_app(cfg, token="t")
    client = TestClient(app)

    r = client.post(
        "/v1/sessions",
        headers={"x-cowork-token": "t"},
        json={"workdir": str(workdir)},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["workdir"] == str(workdir)
    assert data["session_id"]

    # List endpoint returns the new session.
    r = client.get(
        "/v1/local-sessions",
        headers={"x-cowork-token": "t"},
        params={"workdir": str(workdir)},
    )
    assert r.status_code == 200
    sessions = r.json()
    assert len(sessions) == 1
    assert sessions[0]["id"] == data["cowork_session_id"]


@pytest.mark.asyncio
async def test_fs_tools_work_end_to_end_in_local_session(tmp_path: Path) -> None:
    """fs_read/write/edit against a LocalDirExecEnv session."""
    from unittest.mock import MagicMock

    from cowork_core.tools.fs import fs_edit, fs_read, fs_write

    workdir = tmp_path / "wd"
    workdir.mkdir()
    ws_root = tmp_path / "ws"

    runtime = build_runtime(
        CoworkConfig(workspace=WorkspaceConfig(root=ws_root)),
    )
    _, _, adk_sid = await runtime.open_session(workdir=workdir)

    adk_session = await runtime.runner.session_service.get_session(
        app_name="cowork", user_id="local", session_id=adk_sid,
    )
    ctx = adk_session.state[COWORK_CONTEXT_KEY]

    tctx = MagicMock()
    tctx.state = {COWORK_CONTEXT_KEY: ctx}

    # Write in plain relative form (no scratch/ prefix).
    w = fs_write("notes/first.md", "alpha beta\n", tctx)
    assert w["bytes"] == 11
    assert (workdir / "notes" / "first.md").read_text() == "alpha beta\n"

    r = fs_read("notes/first.md", tctx)
    assert r["content"] == "alpha beta\n"

    e = fs_edit("notes/first.md", "alpha", "ALPHA", tctx)
    assert "error" not in e
    assert (workdir / "notes" / "first.md").read_text() == "ALPHA beta\n"

    # Escape attempt surfaces as a tool-level error.
    bad = fs_read("../outside.md", tctx)
    assert "error" in bad


def test_server_rejects_both_project_and_workdir(tmp_path: Path) -> None:
    from cowork_server.app import create_app
    from fastapi.testclient import TestClient

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    app = create_app(cfg, token="t")
    client = TestClient(app)

    r = client.post(
        "/v1/sessions",
        headers={"x-cowork-token": "t"},
        json={"project": "x", "workdir": "/tmp/y"},
    )
    assert r.status_code == 400


def test_folder_picker_full_sequence(tmp_path: Path) -> None:
    """Simulates the full desktop picker flow against the HTTP surface.

    This is the streamlined end-to-end for Phase 2: the Tauri side returns
    a picked path (we provide it directly), then the UI flow is
    POST /v1/sessions → GET /v1/local-sessions → POST resume →
    DELETE /v1/local-sessions. No LLM round-trips, just the session
    bookkeeping the picker relies on.
    """
    from cowork_server.app import create_app
    from fastapi.testclient import TestClient

    # The "picker" returns this absolute path.
    workdir = tmp_path / "my-draft"
    workdir.mkdir()
    (workdir / "README.md").write_text("# existing\n")

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path / "ws"))
    app = create_app(cfg, token="t")
    client = TestClient(app)
    H = {"x-cowork-token": "t"}

    # 1. Create a session for the picked workdir (UI: handlePickWorkdir →
    #    createSession({workdir})).
    r = client.post("/v1/sessions", headers=H, json={"workdir": str(workdir)})
    assert r.status_code == 200, r.text
    info = r.json()
    sid = info["session_id"]
    assert info["workdir"] == str(workdir)
    assert info["cowork_session_id"] == sid

    # 2. The new session appears in local-sessions listing (sidebar refresh).
    r = client.get(
        "/v1/local-sessions", headers=H, params={"workdir": str(workdir)},
    )
    assert r.status_code == 200
    sessions = r.json()
    assert len(sessions) == 1
    assert sessions[0]["id"] == sid

    # 3. Session bookkeeping is on disk.
    session_root = workdir / ".cowork" / "sessions" / sid
    assert (session_root / "scratch").is_dir()
    assert (session_root / "transcript.jsonl").exists()

    # 4. A second session in the same workdir coexists.
    r = client.post("/v1/sessions", headers=H, json={"workdir": str(workdir)})
    assert r.status_code == 200
    sid2 = r.json()["session_id"]
    assert sid2 != sid

    r = client.get(
        "/v1/local-sessions", headers=H, params={"workdir": str(workdir)},
    )
    assert {s["id"] for s in r.json()} == {sid, sid2}

    # 5. Resume the first one (UI: clicking a session in the sidebar).
    r = client.post(
        f"/v1/sessions/{sid}/resume", headers=H, json={"workdir": str(workdir)},
    )
    assert r.status_code == 200, r.text
    assert r.json()["session_id"] == sid

    # 6. Delete the second one.
    r = client.delete(
        f"/v1/local-sessions/{sid2}",
        headers=H,
        params={"workdir": str(workdir)},
    )
    assert r.status_code == 200

    r = client.get(
        "/v1/local-sessions", headers=H, params={"workdir": str(workdir)},
    )
    assert [s["id"] for s in r.json()] == [sid]
    assert not (workdir / ".cowork" / "sessions" / sid2).exists()

    # 7. Picking a *different* workdir gets a different session pool.
    workdir2 = tmp_path / "other"
    workdir2.mkdir()
    r = client.post("/v1/sessions", headers=H, json={"workdir": str(workdir2)})
    assert r.status_code == 200

    r = client.get(
        "/v1/local-sessions", headers=H, params={"workdir": str(workdir2)},
    )
    assert len(r.json()) == 1

    r = client.get(
        "/v1/local-sessions", headers=H, params={"workdir": str(workdir)},
    )
    assert len(r.json()) == 1  # still just sid from the original workdir


def test_picker_rejects_nonexistent_workdir(tmp_path: Path) -> None:
    from cowork_server.app import create_app
    from fastapi.testclient import TestClient

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path / "ws"))
    app = create_app(cfg, token="t")
    client = TestClient(app)

    r = client.post(
        "/v1/sessions",
        headers={"x-cowork-token": "t"},
        json={"workdir": str(tmp_path / "does-not-exist")},
    )
    # The runtime raises ValueError on a bad workdir; the server surfaces it
    # as 400 so the UI can show a "pick a valid folder" message.
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_fs_promote_returns_error_in_local_dir_mode(tmp_path: Path) -> None:
    """In local-dir (desktop) mode the scratch/files distinction doesn't
    exist; fs_promote should fail cleanly rather than silently write to
    `<workdir>/files/` or similar."""
    from unittest.mock import MagicMock

    from cowork_core.tools.fs import fs_promote

    workdir = tmp_path / "wd"
    workdir.mkdir()
    ws_root = tmp_path / "ws"

    runtime = build_runtime(
        CoworkConfig(workspace=WorkspaceConfig(root=ws_root)),
    )
    _, _, adk_sid = await runtime.open_session(workdir=workdir)
    adk_session = await runtime.runner.session_service.get_session(
        app_name="cowork", user_id="local", session_id=adk_sid,
    )
    ctx = adk_session.state[COWORK_CONTEXT_KEY]

    tctx = MagicMock()
    tctx.state = {COWORK_CONTEXT_KEY: ctx}

    result = fs_promote("draft.md", tctx)
    assert "error" in result
    assert "local-dir mode" in result["error"]
    assert "fs_write" in result["error"]  # hint points at the right tool


def test_local_files_list_and_read(tmp_path: Path) -> None:
    """Desktop file browser endpoints respect LocalDirExecEnv confinement."""
    from cowork_server.app import create_app
    from fastapi.testclient import TestClient

    workdir = tmp_path / "wd"
    workdir.mkdir()
    (workdir / "hello.md").write_text("# hi\n")
    (workdir / "sub").mkdir()
    (workdir / "sub" / "nested.txt").write_text("deep\n")
    (workdir / ".cowork").mkdir()  # bookkeeping — should be hidden

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path / "ws"))
    app = create_app(cfg, token="t")
    client = TestClient(app)
    H = {"x-cowork-token": "t"}

    # List root: no .cowork entry.
    r = client.get("/v1/local-files", headers=H, params={"workdir": str(workdir)})
    assert r.status_code == 200
    names = {e["name"] for e in r.json()["entries"]}
    assert names == {"hello.md", "sub"}
    assert ".cowork" not in names

    # List subdir.
    r = client.get(
        "/v1/local-files",
        headers=H,
        params={"workdir": str(workdir), "path": "sub"},
    )
    assert r.status_code == 200
    assert [e["name"] for e in r.json()["entries"]] == ["nested.txt"]

    # Read file content.
    r = client.get(
        "/v1/local-files/content",
        headers=H,
        params={"workdir": str(workdir), "path": "hello.md"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["content"] == "# hi\n"
    assert data["truncated"] is False

    # Path escape attempt → 400 (LocalDirExecEnv rejects before fs touch).
    r = client.get(
        "/v1/local-files",
        headers=H,
        params={"workdir": str(workdir), "path": "../outside"},
    )
    assert r.status_code == 400


def test_picker_resume_missing_session_404(tmp_path: Path) -> None:
    from cowork_server.app import create_app
    from fastapi.testclient import TestClient

    workdir = tmp_path / "wd"
    workdir.mkdir()
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path / "ws"))
    app = create_app(cfg, token="t")
    client = TestClient(app)

    r = client.post(
        "/v1/sessions/ghost-session/resume",
        headers={"x-cowork-token": "t"},
        json={"workdir": str(workdir)},
    )
    assert r.status_code == 404
