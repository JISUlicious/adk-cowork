"""Tests for the storage hierarchy (Slice S1).

UserStore / ProjectStore protocols + FS + SQLite backings + the
build_stores factory + the backend registry.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from cowork_core.config import (
    AuthConfig,
    CoworkConfig,
    StorageConfig,
    WorkspaceConfig,
)
from cowork_core.storage import (
    FSProjectStore,
    FSUserStore,
    InMemoryProjectStore,
    InMemoryUserStore,
    ProjectStore,
    SqliteProjectStore,
    SqliteUserStore,
    UserStore,
    build_stores,
    register_backend,
)
from cowork_core.storage.factory import StorageBackendError
from cowork_core.storage.fs import StorageError
from cowork_core.storage.sqlite import _open_sqlite
from cowork_core.workspace import Workspace


# ───────────────────────── FS user store ─────────────────────────


def test_fs_user_store_round_trip(tmp_path: Path) -> None:
    store = FSUserStore(tmp_path)
    assert store.read("local", "memory/pages/x.md") is None
    store.write("local", "memory/pages/x.md", b"hello")
    assert store.read("local", "memory/pages/x.md") == b"hello"
    # Filesystem layout matches: file lives at <root>/memory/pages/x.md
    assert (tmp_path / "memory" / "pages" / "x.md").read_bytes() == b"hello"


def test_fs_user_store_list_by_prefix(tmp_path: Path) -> None:
    store = FSUserStore(tmp_path)
    store.write("local", "memory/pages/a.md", b"A")
    store.write("local", "memory/pages/b.md", b"B")
    store.write("local", "skills/foo.md", b"S")

    assert store.list("local", "memory/") == [
        "memory/pages/a.md",
        "memory/pages/b.md",
    ]
    assert store.list("local", "") == sorted([
        "memory/pages/a.md",
        "memory/pages/b.md",
        "skills/foo.md",
    ])
    assert store.list("local", "skills/") == ["skills/foo.md"]


def test_fs_user_store_delete_idempotent(tmp_path: Path) -> None:
    store = FSUserStore(tmp_path)
    store.write("local", "memory/pages/x.md", b"hello")
    store.delete("local", "memory/pages/x.md")
    assert store.read("local", "memory/pages/x.md") is None
    # Deleting a missing key is a no-op.
    store.delete("local", "memory/pages/x.md")


def test_fs_user_store_rejects_path_traversal(tmp_path: Path) -> None:
    store = FSUserStore(tmp_path)
    with pytest.raises(StorageError):
        store.write("local", "../escape.md", b"nope")
    with pytest.raises(StorageError):
        store.write("local", "/abs/escape.md", b"nope")
    with pytest.raises(StorageError):
        store.write("local", "", b"nope")


def test_fs_user_store_atomic_writes(tmp_path: Path) -> None:
    """Concurrent writers converge to one of the values, never half-
    written. We test atomicity by looking for ``.tmp`` artifacts AND
    by reading back legible content."""
    store = FSUserStore(tmp_path)
    body_a = b"A" * 4096
    body_b = b"B" * 4096

    def write_a() -> None:
        for _ in range(100):
            store.write("local", "k.md", body_a)

    def write_b() -> None:
        for _ in range(100):
            store.write("local", "k.md", body_b)

    t1 = threading.Thread(target=write_a)
    t2 = threading.Thread(target=write_b)
    t1.start(); t2.start()
    t1.join(); t2.join()

    final = store.read("local", "k.md")
    assert final in (body_a, body_b), "atomic write produced corrupted content"
    # No temp file is left behind on success (unique suffixes per
    # writer prevent the cross-thread collision that the previous
    # fixed-".tmp" implementation suffered from).
    leftovers = list(tmp_path.glob("k.md*.tmp"))
    assert leftovers == [], f"temp files leaked: {leftovers}"


# ───────────────────────── FS project store ─────────────────────────


def test_fs_project_store_round_trip_and_isolation(tmp_path: Path) -> None:
    """In single-user mode the project slug IS a workdir path. The
    store routes writes under <workdir>/.cowork/."""
    workdir_a = tmp_path / "proj-a"
    workdir_b = tmp_path / "proj-b"
    workdir_a.mkdir()
    workdir_b.mkdir()

    def resolver(_uid: str, project: str) -> Path:
        return Path(project)

    store = FSProjectStore(workdir_resolver=resolver)
    store.write("local", str(workdir_a), "memory/pages/x.md", b"A")
    store.write("local", str(workdir_b), "memory/pages/x.md", b"B")

    assert store.read("local", str(workdir_a), "memory/pages/x.md") == b"A"
    assert store.read("local", str(workdir_b), "memory/pages/x.md") == b"B"
    # Lands under <workdir>/.cowork/ (the existing local-dir convention).
    assert (workdir_a / ".cowork" / "memory" / "pages" / "x.md").read_bytes() == b"A"
    assert (workdir_b / ".cowork" / "memory" / "pages" / "x.md").read_bytes() == b"B"


# ───────────────────────── SQLite user store ─────────────────────────


def test_sqlite_user_store_round_trip_and_user_isolation() -> None:
    conn = _open_sqlite(":memory:")
    store = SqliteUserStore(conn)

    store.write("alice", "memory/pages/x.md", b"alice's note")
    store.write("bob", "memory/pages/x.md", b"bob's note")

    assert store.read("alice", "memory/pages/x.md") == b"alice's note"
    assert store.read("bob", "memory/pages/x.md") == b"bob's note"
    assert store.read("carol", "memory/pages/x.md") is None


def test_sqlite_user_store_upsert_overwrites_and_bumps_timestamp() -> None:
    conn = _open_sqlite(":memory:")
    store = SqliteUserStore(conn)

    store.write("alice", "k", b"v1")
    row1 = conn.execute(
        "SELECT updated_at FROM user_state WHERE user_id='alice' AND key='k'",
    ).fetchone()
    store.write("alice", "k", b"v2")
    row2 = conn.execute(
        "SELECT value, updated_at FROM user_state WHERE user_id='alice' AND key='k'",
    ).fetchone()

    assert bytes(row2[0]) == b"v2"
    # updated_at is monotonic-ish (string ISO comparison works).
    assert row2[1] >= row1[0]


def test_sqlite_user_store_list_and_delete() -> None:
    conn = _open_sqlite(":memory:")
    store = SqliteUserStore(conn)
    store.write("alice", "memory/a", b"A")
    store.write("alice", "memory/b", b"B")
    store.write("alice", "skills/x", b"X")
    store.write("bob", "memory/a", b"BobA")

    assert store.list("alice", "memory/") == ["memory/a", "memory/b"]
    assert store.list("bob", "memory/") == ["memory/a"]

    store.delete("alice", "memory/a")
    assert store.list("alice", "memory/") == ["memory/b"]
    # Idempotent.
    store.delete("alice", "memory/a")


# ───────────────────────── SQLite project store ─────────────────────────


def test_sqlite_project_store_isolation_across_user_and_project() -> None:
    conn = _open_sqlite(":memory:")
    store = SqliteProjectStore(conn)

    store.write("alice", "lima", "memory/x", b"AL")
    store.write("alice", "mike", "memory/x", b"AM")
    store.write("bob", "lima", "memory/x", b"BL")

    assert store.read("alice", "lima", "memory/x") == b"AL"
    assert store.read("alice", "mike", "memory/x") == b"AM"
    assert store.read("bob", "lima", "memory/x") == b"BL"
    # Listing scopes correctly.
    assert store.list("alice", "lima", "") == ["memory/x"]
    assert store.list("alice", "mike", "") == ["memory/x"]


# ───────────────────────── Factory + backend registry ─────────────────────────


def test_build_stores_returns_fs_pair_in_single_user(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    workspace = Workspace(root=tmp_path)
    user, project = build_stores(cfg, workspace)
    assert isinstance(user, FSUserStore)
    assert isinstance(project, FSProjectStore)


def test_build_stores_returns_sqlite_pair_in_multi_user(tmp_path: Path) -> None:
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(keys={"key1": "alice"}),
    )
    workspace = Workspace(root=tmp_path)
    user, project = build_stores(cfg, workspace)
    assert isinstance(user, SqliteUserStore)
    assert isinstance(project, SqliteProjectStore)
    # DB file appears at <workspace>/multiuser.db on first write.
    user.write("alice", "k", b"v")
    assert (tmp_path / "multiuser.db").is_file()


def test_build_stores_dispatches_through_backend_registry(tmp_path: Path) -> None:
    """Smoke test for the Postgres-or-other-DB seam: register a fake
    backend, set ``cfg.storage.backend`` to its name, verify the
    factory dispatches there. Proves the registry is wired without
    shipping a second real backend."""
    sentinel_user = InMemoryUserStore()
    sentinel_project = InMemoryProjectStore()

    def _fake_builder(_cfg: CoworkConfig, _ws: Workspace) -> tuple[UserStore, ProjectStore]:
        return sentinel_user, sentinel_project

    register_backend("fake-test-backend", _fake_builder)
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(keys={"k": "u"}),
        storage=StorageConfig(backend="fake-test-backend"),
    )
    workspace = Workspace(root=tmp_path)
    user, project = build_stores(cfg, workspace)
    assert user is sentinel_user
    assert project is sentinel_project


def test_build_stores_unknown_backend_raises_with_listing(tmp_path: Path) -> None:
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(keys={"k": "u"}),
        storage=StorageConfig(backend="nonexistent"),
    )
    workspace = Workspace(root=tmp_path)
    with pytest.raises(StorageBackendError) as ex:
        build_stores(cfg, workspace)
    assert "nonexistent" in str(ex.value)
    assert "sqlite" in str(ex.value)  # available backends listed


# ───────────────────────── Runtime + context wiring ─────────────────────────


def test_build_runtime_populates_stores_in_single_user(tmp_path: Path) -> None:
    from cowork_core.runner import build_runtime

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    assert isinstance(runtime.user_store, FSUserStore)
    assert isinstance(runtime.project_store, FSProjectStore)


def test_build_runtime_populates_stores_in_multi_user(tmp_path: Path) -> None:
    from cowork_core.runner import build_runtime

    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(keys={"key1": "alice"}),
    )
    runtime = build_runtime(cfg)
    assert isinstance(runtime.user_store, SqliteUserStore)
    assert isinstance(runtime.project_store, SqliteProjectStore)


@pytest.mark.asyncio
async def test_cowork_tool_context_carries_stores(tmp_path: Path) -> None:
    """Runtime → ``_build_context`` → ``CoworkToolContext`` propagates
    the stores so tools can reach them via ``ctx.user_store`` /
    ``ctx.project_store``."""
    from cowork_core.runner import build_runtime
    from cowork_core.tools.base import COWORK_CONTEXT_KEY, CoworkToolContext

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    project = runtime.registry_for("local").create("Foxtrot")
    _, _, sid = await runtime.open_session(
        user_id="local", project_name="Foxtrot",
    )
    sess = await runtime.runner.session_service.get_session(
        app_name="cowork", user_id="local", session_id=sid,
    )
    ctx = sess.state[COWORK_CONTEXT_KEY]
    assert isinstance(ctx, CoworkToolContext)
    assert ctx.user_store is runtime.user_store
    assert ctx.project_store is runtime.project_store
    assert project.slug == "foxtrot"


# ───────────────────── Cross-mode key-shape compat ─────────────────────


def test_same_key_shape_works_against_either_backing(tmp_path: Path) -> None:
    """The whole point of path-shaped string keys: a memory tool that
    calls ``ctx.user_store.write(uid, "memory/pages/x.md", body)``
    works identically regardless of FS vs SQLite backing."""
    KEY = "memory/pages/scratch.md"
    BODY = b"hello"

    fs_store = FSUserStore(tmp_path / "fs")
    sqlite_store = SqliteUserStore(_open_sqlite(":memory:"))

    fs_store.write("alice", KEY, BODY)
    sqlite_store.write("alice", KEY, BODY)

    assert fs_store.read("alice", KEY) == BODY
    assert sqlite_store.read("alice", KEY) == BODY
    assert KEY in fs_store.list("alice", "memory/")
    assert KEY in sqlite_store.list("alice", "memory/")
