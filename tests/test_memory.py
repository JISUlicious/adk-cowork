"""Tests for the memory subsystem (Slice S2).

Memory tools (memory_read, memory_write, memory_log,
memory_remember) on top of the S1 UserStore / ProjectStore
abstractions; bootstrap idempotency; injection_snippet shape.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cowork_core.approvals import InMemoryApprovalStore
from cowork_core.config import (
    AuthConfig,
    CoworkConfig,
    WorkspaceConfig,
)
from cowork_core.execenv import ManagedExecEnv
from cowork_core.memory import MemoryRegistry, register_memory_tools
from cowork_core.memory.bootstrap import (
    bundled_default_schema,
    is_writable_target,
    memory_key,
)
from cowork_core.memory.tools import (
    memory_log,
    memory_read,
    memory_remember,
    memory_write,
)
from cowork_core.skills import SkillRegistry
from cowork_core.storage import (
    InMemoryProjectStore,
    InMemoryUserStore,
)
from cowork_core.tools import COWORK_CONTEXT_KEY, CoworkToolContext, ToolRegistry
from cowork_core.workspace import ProjectRegistry, Workspace


@pytest.fixture()
def tctx(tmp_path: Path) -> MagicMock:
    """Tool context with in-memory stores (zero-arg, no FS dependence)."""
    ws = Workspace(root=tmp_path)
    reg = ProjectRegistry(workspace=ws)
    project = reg.create("Mem")
    session = reg.new_session("mem")
    ctx = CoworkToolContext(
        workspace=ws,
        registry=reg,
        project=project,
        session=session,
        config=CoworkConfig(),
        skills=SkillRegistry(),
        env=ManagedExecEnv(project=project, session=session),
        approvals=InMemoryApprovalStore(),
        user_store=InMemoryUserStore(),
        project_store=InMemoryProjectStore(),
        user_id="alice",
    )
    fake = MagicMock()
    fake.state = {COWORK_CONTEXT_KEY: ctx}
    return fake


# ───────────────────────── helpers + key shape ─────────────────────────


def test_memory_key_namespace_prefix() -> None:
    assert memory_key("schema.md") == "memory/schema.md"
    assert memory_key("pages/scratch.md") == "memory/pages/scratch.md"


def test_memory_key_rejects_path_traversal() -> None:
    with pytest.raises(ValueError):
        memory_key("../escape.md")
    with pytest.raises(ValueError):
        memory_key("/abs/x.md")
    with pytest.raises(ValueError):
        memory_key("")


def test_is_writable_target_allows_index_and_pages() -> None:
    assert is_writable_target("index.md") is True
    assert is_writable_target("pages/foo.md") is True
    assert is_writable_target("pages/sub/note.md") is True


def test_is_writable_target_rejects_schema_log_raw() -> None:
    # schema.md is user-edited; the agent must not rewrite it.
    assert is_writable_target("schema.md") is False
    # log.md uses memory_log(), not memory_write().
    assert is_writable_target("log.md") is False
    # raw/ is user uploads, sacred.
    assert is_writable_target("raw/file.md") is False
    # Random other paths are also rejected.
    assert is_writable_target("notes.md") is False
    assert is_writable_target("pages/binary.png") is False


def test_bundled_default_schema_is_non_empty_markdown() -> None:
    body = bundled_default_schema()
    assert len(body) > 200
    assert "# Memory schema" in body
    assert "memory_log" in body
    assert "memory_remember" in body


# ───────────────────────── Bootstrap ─────────────────────────


def test_first_read_bootstraps_default_schema(tctx: MagicMock) -> None:
    """Lazy bootstrap: reading schema.md on a fresh scope creates it
    from the bundled default."""
    out = memory_read("user", "schema.md", tctx)
    assert "error" not in out
    assert "# Memory schema" in str(out["content"])

    # The page is now persisted in the store.
    ctx = tctx.state[COWORK_CONTEXT_KEY]
    raw = ctx.user_store.read("alice", "memory/schema.md")
    assert raw is not None and b"Memory schema" in raw


def test_bootstrap_idempotent(tctx: MagicMock) -> None:
    """Calling a memory tool twice doesn't overwrite the user's
    edited schema.md."""
    ctx = tctx.state[COWORK_CONTEXT_KEY]
    # Pre-seed a user-customised schema.
    custom = b"# My custom schema\n\nThe agent does what I say."
    ctx.user_store.write("alice", "memory/schema.md", custom)

    # Triggering the bootstrap path (any memory tool) must not clobber.
    memory_log("user", "ingest", "first", tool_context=tctx)

    after = ctx.user_store.read("alice", "memory/schema.md")
    assert after == custom


# ───────────────────────── memory_read ─────────────────────────


def test_memory_read_missing_returns_error(tctx: MagicMock) -> None:
    out = memory_read("project", "pages/missing.md", tctx)
    assert "error" in out
    assert "not found" in str(out["error"]).lower()


def test_memory_read_invalid_name_returns_error(tctx: MagicMock) -> None:
    out = memory_read("user", "../escape.md", tctx)
    assert "error" in out


# ───────────────────────── memory_write ─────────────────────────


def test_memory_write_round_trip_to_pages(tctx: MagicMock) -> None:
    out = memory_write("project", "pages/decisions.md", "We chose A.", tctx)
    assert out.get("scope") == "project"
    assert out.get("name") == "pages/decisions.md"
    assert out.get("bytes", 0) > 0

    read = memory_read("project", "pages/decisions.md", tctx)
    assert read["content"] == "We chose A."


def test_memory_write_index_md_allowed(tctx: MagicMock) -> None:
    out = memory_write("project", "index.md", "- [a](pages/a.md) — first", tctx)
    assert "error" not in out


def test_memory_write_rejects_schema_md(tctx: MagicMock) -> None:
    out = memory_write("user", "schema.md", "evil", tctx)
    assert "error" in out
    assert "not allowed" in str(out["error"])


def test_memory_write_rejects_log_md(tctx: MagicMock) -> None:
    out = memory_write("user", "log.md", "## fake", tctx)
    assert "error" in out


def test_memory_write_rejects_raw_path(tctx: MagicMock) -> None:
    out = memory_write("user", "raw/file.md", "evil", tctx)
    assert "error" in out


# ───────────────────────── memory_log ─────────────────────────


def test_memory_log_appends_dated_entry(tctx: MagicMock) -> None:
    out1 = memory_log(
        "project", "ingest", "First source",
        body="A summary.",
        tool_context=tctx,
    )
    assert out1.get("kind") == "ingest"
    out2 = memory_log(
        "project", "query", "Some question", tool_context=tctx,
    )
    assert "error" not in out2

    log = memory_read("project", "log.md", tctx)
    body = str(log["content"])
    # Both entries present, header format consistent.
    assert "ingest | First source" in body
    assert "query | Some question" in body
    assert "## [" in body and "]" in body
    # Body is included for the first entry, omitted for the second.
    assert "A summary." in body


def test_memory_log_rejects_invalid_kind(tctx: MagicMock) -> None:
    out = memory_log("user", "BAD KIND!", "Something", tool_context=tctx)
    assert "error" in out
    out = memory_log("user", "with spaces", "x", tool_context=tctx)
    assert "error" in out


def test_memory_log_rejects_multiline_title(tctx: MagicMock) -> None:
    out = memory_log("user", "ingest", "two\nlines", tool_context=tctx)
    assert "error" in out
    out = memory_log("user", "ingest", "   ", tool_context=tctx)
    assert "error" in out


# ───────────────────────── memory_remember ─────────────────────────


def test_memory_remember_appends_to_scratch_with_timestamp(tctx: MagicMock) -> None:
    out1 = memory_remember(
        "Prefer matplotlib over plotly.", tool_context=tctx,
    )
    out2 = memory_remember(
        "Tabs not spaces.", tool_context=tctx,
    )
    assert out1.get("name") == "pages/scratch.md"
    assert out2.get("name") == "pages/scratch.md"

    page = memory_read("project", "pages/scratch.md", tctx)
    body = str(page["content"])
    assert "Prefer matplotlib" in body
    assert "Tabs not spaces" in body
    # Timestamp format YYYY-MM-DD HH:MM:SS
    assert "## [" in body and "] note" in body


def test_memory_remember_default_scope_is_project(tctx: MagicMock) -> None:
    """Default scope is project; ``user`` page should not be created
    when the call doesn't specify scope."""
    memory_remember("project-bound fact", tool_context=tctx)
    project_page = memory_read("project", "pages/scratch.md", tctx)
    assert "error" not in project_page
    user_page = memory_read("user", "pages/scratch.md", tctx)
    assert "error" in user_page


def test_memory_remember_user_scope_routes_to_user_store(tctx: MagicMock) -> None:
    memory_remember("cross-project fact", scope="user", tool_context=tctx)
    user_page = memory_read("user", "pages/scratch.md", tctx)
    assert "cross-project fact" in str(user_page["content"])


def test_memory_remember_rejects_empty_content(tctx: MagicMock) -> None:
    out = memory_remember("   ", tool_context=tctx)
    assert "error" in out


# ───────────────────────── MemoryRegistry snippet ─────────────────────────


def test_injection_snippet_empty_when_no_pages(tctx: MagicMock) -> None:
    reg = MemoryRegistry()
    ctx = tctx.state[COWORK_CONTEXT_KEY]
    assert reg.injection_snippet(ctx) == ""


def test_injection_snippet_counts_pages_per_scope(tctx: MagicMock) -> None:
    """Pages count after the agent files something. Bootstrap files
    schema.md but not pages — schema is not under pages/."""
    memory_write("user", "pages/a.md", "A", tctx)
    memory_write("user", "pages/b.md", "B", tctx)
    memory_write("project", "pages/c.md", "C", tctx)

    reg = MemoryRegistry()
    ctx = tctx.state[COWORK_CONTEXT_KEY]
    out = reg.injection_snippet(ctx)
    assert "user" in out
    assert "(2 pages)" in out
    assert "project" in out
    assert "(1 pages)" in out
    assert 'memory_read(scope, "schema.md")' in out


# ───────────────────────── Tool registration ─────────────────────────


def test_register_memory_tools_adds_four() -> None:
    reg = ToolRegistry()
    register_memory_tools(reg)
    names = {t.name for t in reg.as_list()}
    assert {
        "memory_read",
        "memory_write",
        "memory_log",
        "memory_remember",
    }.issubset(names)


# ─────────────────────── Build-runtime smoke ───────────────────────


def test_build_runtime_includes_memory_tools(tmp_path: Path) -> None:
    """Memory tools land in the runtime's tool registry alongside
    fs.*/skills/etc."""
    from cowork_core.runner import build_runtime

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    names = {t.name for t in runtime.tools.as_list()}
    assert {
        "memory_read",
        "memory_write",
        "memory_log",
        "memory_remember",
    }.issubset(names)


@pytest.mark.asyncio
async def test_memory_works_end_to_end_in_single_user_mode(tmp_path: Path) -> None:
    """Single-user smoke: write a page in the project scope, read it
    back, confirm the FS file landed under <workdir>/.cowork/."""
    from cowork_core.runner import build_runtime
    from cowork_core.tools.base import COWORK_CONTEXT_KEY

    workdir = tmp_path / "myproj"
    workdir.mkdir()
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    _, _, sid = await runtime.open_session(
        user_id="local", workdir=workdir,
    )
    sess = await runtime.runner.session_service.get_session(
        app_name="cowork", user_id="local", session_id=sid,
    )
    ctx = sess.state[COWORK_CONTEXT_KEY]

    fake = MagicMock()
    fake.state = {COWORK_CONTEXT_KEY: ctx}

    memory_write("project", "pages/x.md", "hello", fake)
    out = memory_read("project", "pages/x.md", fake)
    assert out["content"] == "hello"

    # FS landed where we expect.
    on_disk = workdir / ".cowork" / "memory" / "pages" / "x.md"
    assert on_disk.is_file()
    assert on_disk.read_text(encoding="utf-8") == "hello"


@pytest.mark.asyncio
async def test_memory_works_end_to_end_in_multi_user_mode(tmp_path: Path) -> None:
    """Multi-user smoke: pages persist as SQLite rows under
    multiuser.db; FS files do NOT appear."""
    from cowork_core.runner import build_runtime
    from cowork_core.tools.base import COWORK_CONTEXT_KEY

    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(keys={"k1": "alice"}),
    )
    runtime = build_runtime(cfg)
    project = runtime.registry_for("alice").create("Quebec")
    _, _, sid = await runtime.open_session(
        user_id="alice", project_name="Quebec",
    )
    sess = await runtime.runner.session_service.get_session(
        app_name="cowork", user_id="alice", session_id=sid,
    )
    ctx = sess.state[COWORK_CONTEXT_KEY]

    fake = MagicMock()
    fake.state = {COWORK_CONTEXT_KEY: ctx}

    memory_write("user", "pages/profile.md", "alice's prefs", fake)
    out = memory_read("user", "pages/profile.md", fake)
    assert out["content"] == "alice's prefs"

    # SQLite landed at multiuser.db.
    db_path = tmp_path / "multiuser.db"
    assert db_path.is_file()
    import sqlite3
    rows = sqlite3.connect(str(db_path)).execute(
        "SELECT key FROM user_state WHERE user_id='alice' "
        "AND key='memory/pages/profile.md'",
    ).fetchall()
    assert rows == [("memory/pages/profile.md",)]
    assert project.slug == "quebec"
