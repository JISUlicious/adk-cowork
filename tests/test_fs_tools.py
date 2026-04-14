"""Tests for the fs.* tool family (M1.3)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cowork_core.config import CoworkConfig
from cowork_core.skills import SkillRegistry
from cowork_core.tools import COWORK_CONTEXT_KEY, CoworkToolContext, ToolRegistry
from cowork_core.tools.fs import (
    fs_edit,
    fs_glob,
    fs_list,
    fs_promote,
    fs_read,
    fs_stat,
    fs_write,
    register_fs_tools,
)
from cowork_core.workspace import ProjectRegistry, Workspace, WorkspaceError


@pytest.fixture
def tctx(tmp_path: Path) -> MagicMock:
    ws = Workspace(root=tmp_path)
    reg = ProjectRegistry(workspace=ws)
    project = reg.create("Hotel")
    session = reg.new_session("hotel")
    ctx = CoworkToolContext(
        workspace=ws,
        registry=reg,
        project=project,
        session=session,
        config=CoworkConfig(),
        skills=SkillRegistry(),
    )
    fake = MagicMock()
    fake.state = {COWORK_CONTEXT_KEY: ctx}
    return fake


def test_register_fs_tools_covers_family() -> None:
    reg = ToolRegistry()
    register_fs_tools(reg)
    assert reg.names() == [
        "fs_edit",
        "fs_glob",
        "fs_list",
        "fs_promote",
        "fs_read",
        "fs_stat",
        "fs_write",
    ]


def test_write_then_read_roundtrip(tctx: MagicMock) -> None:
    w = fs_write("scratch/note.md", "hello\nworld\n", tctx)
    assert w["bytes"] == 12
    r = fs_read("scratch/note.md", tctx)
    assert r["content"] == "hello\nworld\n"
    assert r["truncated"] is False


def test_read_missing(tctx: MagicMock) -> None:
    assert "error" in fs_read("scratch/nope.md", tctx)


def test_list_and_stat(tctx: MagicMock) -> None:
    fs_write("scratch/a.txt", "a", tctx)
    fs_write("scratch/b.txt", "bb", tctx)
    listing = fs_list("scratch", tctx)
    names = [e["name"] for e in listing["entries"]]  # type: ignore[index]
    assert names == ["a.txt", "b.txt"]
    st = fs_stat("scratch/b.txt", tctx)
    assert st["kind"] == "file"
    assert st["size"] == 2


def test_glob(tctx: MagicMock) -> None:
    fs_write("scratch/a.md", "a", tctx)
    fs_write("scratch/sub/b.md", "b", tctx)
    fs_write("scratch/c.txt", "c", tctx)
    out = fs_glob("scratch/**/*.md", tctx)
    assert set(out["matches"]) == {"scratch/a.md", "scratch/sub/b.md"}  # type: ignore[arg-type]
    assert out["truncated"] is False


def test_edit_unique_match(tctx: MagicMock) -> None:
    fs_write("scratch/e.md", "alpha beta gamma", tctx)
    fs_read("scratch/e.md", tctx)  # must read before editing
    out = fs_edit("scratch/e.md", "beta", "BETA", tctx)
    assert "error" not in out
    assert fs_read("scratch/e.md", tctx)["content"] == "alpha BETA gamma"


def test_edit_rejects_no_match(tctx: MagicMock) -> None:
    fs_write("scratch/e.md", "alpha", tctx)
    fs_read("scratch/e.md", tctx)
    assert "error" in fs_edit("scratch/e.md", "zeta", "ZETA", tctx)


def test_edit_rejects_multi_match(tctx: MagicMock) -> None:
    fs_write("scratch/e.md", "x x x", tctx)
    fs_read("scratch/e.md", tctx)
    assert "error" in fs_edit("scratch/e.md", "x", "Y", tctx)


def test_edit_rejects_identical(tctx: MagicMock) -> None:
    fs_write("scratch/e.md", "hi", tctx)
    fs_read("scratch/e.md", tctx)
    assert "error" in fs_edit("scratch/e.md", "hi", "hi", tctx)


def test_edit_rejects_unread_file(tctx: MagicMock) -> None:
    fs_write("scratch/e.md", "hello", tctx)
    out = fs_edit("scratch/e.md", "hello", "world", tctx)
    assert "error" in out
    assert "must read" in out["error"]  # type: ignore[operator]


def test_promote_moves_to_files(tctx: MagicMock) -> None:
    fs_write("scratch/draft.md", "done", tctx)
    out = fs_promote("draft.md", tctx)
    assert out["path"] == "files/draft.md"
    assert "error" in fs_read("scratch/draft.md", tctx)
    assert fs_read("files/draft.md", tctx)["content"] == "done"


def test_traversal_rejected(tctx: MagicMock) -> None:
    with pytest.raises(WorkspaceError):
        fs_read("../../etc/passwd", tctx)
    with pytest.raises(WorkspaceError):
        fs_write("../escape.txt", "nope", tctx)
