"""Tests for the skill loader and load_skill tool (M1.7)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cowork_core.config import CoworkConfig
from cowork_core.skills import (
    Skill,
    SkillLoadError,
    SkillRegistry,
    load_skill,
    parse_skill_md,
)
from cowork_core.tools import COWORK_CONTEXT_KEY, CoworkToolContext
from cowork_core.workspace import ProjectRegistry, Workspace


def _make_skill(root: Path, name: str, body: str = "body text") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "Use for {name}."\nlicense: MIT\n---\n\n{body}\n',
        encoding="utf-8",
    )
    return skill_dir


def test_parse_skill_md_ok(tmp_path: Path) -> None:
    d = _make_skill(tmp_path, "hello", "hello body")
    skill = parse_skill_md(d / "SKILL.md")
    assert skill.name == "hello"
    assert skill.license == "MIT"
    assert "Use for hello" in skill.description
    assert skill.load_body().strip() == "hello body"


def test_parse_skill_md_missing_name(tmp_path: Path) -> None:
    p = tmp_path / "SKILL.md"
    p.write_text("---\ndescription: x\n---\nbody\n", encoding="utf-8")
    with pytest.raises(SkillLoadError):
        parse_skill_md(p)


def test_parse_skill_md_missing_fence(tmp_path: Path) -> None:
    p = tmp_path / "SKILL.md"
    p.write_text("no frontmatter here", encoding="utf-8")
    with pytest.raises(SkillLoadError):
        parse_skill_md(p)


def test_registry_scans_directory(tmp_path: Path) -> None:
    _make_skill(tmp_path, "alpha")
    _make_skill(tmp_path, "bravo")
    reg = SkillRegistry()
    added = reg.scan(tmp_path)
    assert added == 2
    assert reg.names() == ["alpha", "bravo"]


def test_registry_project_shadows_global(tmp_path: Path) -> None:
    global_dir = tmp_path / "global"
    project_dir = tmp_path / "project"
    _make_skill(global_dir, "md", "global-body")
    _make_skill(project_dir, "md", "project-body")
    reg = SkillRegistry()
    reg.scan(global_dir)
    reg.scan(project_dir)  # later scan wins
    assert reg.get("md").load_body().strip() == "project-body"


def test_injection_snippet(tmp_path: Path) -> None:
    _make_skill(tmp_path, "docx-basic")
    reg = SkillRegistry()
    reg.scan(tmp_path)
    snippet = reg.injection_snippet()
    assert "load_skill" in snippet
    assert "docx-basic" in snippet


def test_manifest_lists_scripts_and_assets(tmp_path: Path) -> None:
    d = _make_skill(tmp_path, "plot")
    (d / "scripts").mkdir()
    (d / "scripts" / "helper.py").write_text("print(1)", encoding="utf-8")
    (d / "assets").mkdir()
    (d / "assets" / "template.md").write_text("tpl", encoding="utf-8")
    skill = parse_skill_md(d / "SKILL.md")
    mf = skill.manifest()
    assert mf["scripts"] == ["helper.py"]
    assert mf["assets"] == ["template.md"]


def test_load_skill_tool_roundtrip(tmp_path: Path) -> None:
    ws_root = tmp_path / "ws"
    ws_root.mkdir()
    ws = Workspace(root=ws_root)
    pr = ProjectRegistry(workspace=ws)
    project = pr.create("Lima")
    session = pr.new_session("lima")

    skills_dir = project.skills_dir
    _make_skill(skills_dir, "hello", "hello body")
    skill_reg = SkillRegistry()
    skill_reg.scan(skills_dir)

    ctx = CoworkToolContext(
        workspace=ws,
        registry=pr,
        project=project,
        session=session,
        config=CoworkConfig(),
        skills=skill_reg,
    )
    fake = MagicMock()
    fake.state = {COWORK_CONTEXT_KEY: ctx}

    out = load_skill("hello", fake)
    assert out["name"] == "hello"
    assert out["license"] == "MIT"
    assert "hello body" in str(out["body"])


def test_load_skill_unknown(tmp_path: Path) -> None:
    ws = Workspace(root=tmp_path)
    pr = ProjectRegistry(workspace=ws)
    project = pr.create("Mike")
    session = pr.new_session("mike")
    ctx = CoworkToolContext(
        workspace=ws,
        registry=pr,
        project=project,
        session=session,
        config=CoworkConfig(),
        skills=SkillRegistry(),
    )
    fake = MagicMock()
    fake.state = {COWORK_CONTEXT_KEY: ctx}
    out = load_skill("nope", fake)
    assert "error" in out


def test_skill_is_frozen_dataclass() -> None:
    s = Skill(
        name="x",
        description="d",
        license="MIT",
        root=Path("/tmp/x"),
    )
    with pytest.raises(Exception):  # noqa: B017
        s.name = "y"  # type: ignore[misc]
