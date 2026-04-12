"""Tests for Project/Session/ProjectRegistry (M1.1)."""

from __future__ import annotations

from pathlib import Path

import pytest
from cowork_core.workspace import (
    ProjectRegistry,
    Workspace,
    WorkspaceError,
    slugify,
)


def _registry(tmp_path: Path) -> ProjectRegistry:
    return ProjectRegistry(workspace=Workspace(root=tmp_path))


def test_slugify_basic() -> None:
    assert slugify("Q4 Report") == "q4-report"
    assert slugify("  Hello World!  ") == "hello-world"
    assert slugify("Already_Slug-1") == "already_slug-1"


def test_slugify_rejects_empty() -> None:
    with pytest.raises(ValueError):
        slugify("!!!")


def test_create_then_get(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    proj = reg.create("Q4 Report")
    assert proj.slug == "q4-report"
    assert proj.files_dir.is_dir()
    assert proj.sessions_dir.is_dir()
    assert proj.skills_dir.is_dir()
    assert proj.toml_path.exists()

    fetched = reg.get("q4-report")
    assert fetched.slug == proj.slug
    assert fetched.name == "Q4 Report"


def test_create_duplicate_rejected(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.create("Alpha")
    with pytest.raises(WorkspaceError):
        reg.create("Alpha")


def test_get_or_create_is_idempotent(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    a = reg.get_or_create("Beta")
    b = reg.get_or_create("Beta")
    assert a.root == b.root


def test_list_sorted(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.create("Charlie")
    reg.create("Alpha")
    reg.create("Bravo")
    slugs = [p.slug for p in reg.list()]
    assert slugs == ["alpha", "bravo", "charlie"]


def test_new_session_and_get(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.create("Delta")
    sess = reg.new_session("delta", title="kickoff")
    assert sess.scratch_dir.is_dir()
    assert sess.transcript_path.exists()
    assert sess.toml_path.exists()

    fetched = reg.get_session("delta", sess.id)
    assert fetched.id == sess.id
    assert fetched.title == "kickoff"


def test_promote_moves_scratch_to_files(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.create("Echo")
    sess = reg.new_session("echo")
    draft = sess.scratch_dir / "draft.md"
    draft.write_text("hello", encoding="utf-8")

    dst = reg.promote(sess, "draft.md")
    assert dst.read_text(encoding="utf-8") == "hello"
    assert not draft.exists()
    assert dst.parent.name == "files"


def test_promote_rejects_traversal(tmp_path: Path) -> None:
    reg = _registry(tmp_path)
    reg.create("Foxtrot")
    sess = reg.new_session("foxtrot")
    with pytest.raises(WorkspaceError):
        reg.promote(sess, "../../etc/passwd")
