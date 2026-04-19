"""Tests for the ExecEnv protocol implementations."""

from __future__ import annotations

from pathlib import Path

import pytest
from cowork_core.execenv import ExecEnvError, LocalDirExecEnv, ManagedExecEnv
from cowork_core.workspace import ProjectRegistry, Workspace


# ────────────────────────── ManagedExecEnv ──────────────────────────────


@pytest.fixture
def managed(tmp_path: Path) -> ManagedExecEnv:
    ws = Workspace(root=tmp_path)
    reg = ProjectRegistry(workspace=ws)
    project = reg.create("TestProj")
    session = reg.new_session("testproj")
    return ManagedExecEnv(project=project, session=session)


class TestManagedExecEnv:
    def test_resolves_scratch(self, managed: ManagedExecEnv) -> None:
        p = managed.resolve("scratch/draft.md")
        assert p.is_relative_to(managed.session.scratch_dir.resolve())

    def test_resolves_files(self, managed: ManagedExecEnv) -> None:
        p = managed.resolve("files/report.md")
        assert p.is_relative_to(managed.project.files_dir.resolve())

    def test_rejects_bad_prefix(self, managed: ManagedExecEnv) -> None:
        with pytest.raises(ExecEnvError):
            managed.resolve("secrets/etc.key")

    def test_rejects_traversal(self, managed: ManagedExecEnv) -> None:
        with pytest.raises(ExecEnvError):
            managed.resolve("scratch/../../escape")

    def test_try_resolve_returns_error_string(self, managed: ManagedExecEnv) -> None:
        r = managed.try_resolve("nope/x")
        assert isinstance(r, str)
        assert "scratch" in r and "files" in r

    def test_empty_path_rejected(self, managed: ManagedExecEnv) -> None:
        with pytest.raises(ExecEnvError):
            managed.resolve("")

    def test_namespaces(self, managed: ManagedExecEnv) -> None:
        assert managed.namespaces() == ["scratch", "files"]

    def test_describe_mentions_both_namespaces(self, managed: ManagedExecEnv) -> None:
        desc = managed.describe_for_prompt()
        assert "scratch/" in desc and "files/" in desc

    def test_glob_searches_both_namespaces_by_default(self, managed: ManagedExecEnv) -> None:
        (managed.session.scratch_dir / "a.md").write_text("a")
        managed.project.files_dir.mkdir(parents=True, exist_ok=True)
        (managed.project.files_dir / "b.md").write_text("b")
        hits, truncated = managed.glob("*.md")
        assert set(hits) == {"scratch/a.md", "files/b.md"}
        assert not truncated


# ────────────────────────── LocalDirExecEnv ─────────────────────────────


@pytest.fixture
def local(tmp_path: Path) -> LocalDirExecEnv:
    return LocalDirExecEnv(workdir=tmp_path, session_id="sess-1")


class TestLocalDirExecEnv:
    def test_resolves_plain_relative(self, local: LocalDirExecEnv) -> None:
        p = local.resolve("draft.md")
        assert p == (local.root() / "draft.md").resolve()

    def test_resolves_nested(self, local: LocalDirExecEnv) -> None:
        p = local.resolve("sub/dir/file.md")
        assert p.is_relative_to(local.root())

    def test_strips_leading_dot_slash(self, local: LocalDirExecEnv) -> None:
        p = local.resolve("./foo.md")
        assert p == (local.root() / "foo.md").resolve()

    def test_rejects_absolute(self, local: LocalDirExecEnv) -> None:
        with pytest.raises(ExecEnvError):
            local.resolve("/etc/passwd")

    def test_rejects_traversal(self, local: LocalDirExecEnv) -> None:
        with pytest.raises(ExecEnvError):
            local.resolve("../outside.txt")

    def test_rejects_empty(self, local: LocalDirExecEnv) -> None:
        with pytest.raises(ExecEnvError):
            local.resolve("")

    def test_scratch_dir_is_hidden(self, local: LocalDirExecEnv) -> None:
        s = local.scratch_dir()
        assert s.is_relative_to(local.root())
        assert ".cowork" in s.parts

    def test_namespaces_is_single_empty(self, local: LocalDirExecEnv) -> None:
        assert local.namespaces() == [""]

    def test_describe_mentions_workdir(self, local: LocalDirExecEnv) -> None:
        desc = local.describe_for_prompt()
        assert str(local.root()) in desc

    def test_missing_workdir_raises_at_construction(self, tmp_path: Path) -> None:
        with pytest.raises(ExecEnvError):
            LocalDirExecEnv(workdir=tmp_path / "nope", session_id="x")

    def test_workdir_file_not_dir_raises(self, tmp_path: Path) -> None:
        fp = tmp_path / "f.txt"
        fp.write_text("hi")
        with pytest.raises(ExecEnvError):
            LocalDirExecEnv(workdir=fp, session_id="x")

    def test_glob_hides_cowork_subdir(self, local: LocalDirExecEnv) -> None:
        (local.root() / "a.md").write_text("a")
        # Materialize scratch so .cowork/ exists
        local.scratch_dir()
        hits, truncated = local.glob("**/*.md")
        # a.md should be present; any path under .cowork must NOT.
        assert "a.md" in hits
        assert all(not h.startswith(".cowork") for h in hits)
