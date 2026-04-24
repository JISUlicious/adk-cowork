"""Tests for the skill loader and load_skill tool (M1.7)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cowork_core.config import CoworkConfig
from cowork_core.execenv import ManagedExecEnv
from cowork_core.approvals import InMemoryApprovalStore
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
        env=ManagedExecEnv(project=project, session=session),
        approvals=InMemoryApprovalStore(),
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
        env=ManagedExecEnv(project=project, session=session),
        approvals=InMemoryApprovalStore(),
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


import pytest as _pytest


@_pytest.mark.asyncio
async def test_runtime_picks_up_project_skills(tmp_path: Path) -> None:
    """Spec §2.5.1 — project-scoped skills shadow global ones at the
    runtime layer, not just in the raw registry. This pins the
    ``_build_context`` scan so the project/skills/ path stays wired."""
    from cowork_core.config import WorkspaceConfig
    from cowork_core.runner import build_runtime
    from cowork_core.tools.base import COWORK_CONTEXT_KEY, CoworkToolContext

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)

    # Seed a project-scoped skill: projects/<slug>/skills/custom/SKILL.md.
    project = runtime.registry_for("local").create("Echo")
    _make_skill(project.skills_dir, "custom", "custom body from project")

    # Open a session — this triggers _build_context and writes the
    # CoworkToolContext into ADK state under COWORK_CONTEXT_KEY.
    _, _, adk_sid = await runtime.open_session(
        user_id="local", project_name="Echo",
    )
    sess = await runtime.runner.session_service.get_session(
        app_name="cowork", user_id="local", session_id=adk_sid,
    )
    assert sess is not None
    ctx = sess.state[COWORK_CONTEXT_KEY]
    assert isinstance(ctx, CoworkToolContext)
    # Registry in the session context carries the project-scoped skill.
    names = ctx.skills.names()
    assert "custom" in names, f"expected 'custom' in {names}"
    assert ctx.skills.get("custom").load_body().strip() == "custom body from project"


@_pytest.mark.asyncio
async def test_runtime_project_skill_shadows_global(tmp_path: Path) -> None:
    """Bundled ``docx-basic`` ships under cowork-core; a project's own
    ``docx-basic/SKILL.md`` must override it in that session's
    registry (spec: project-scoped shadows global)."""
    from cowork_core.config import WorkspaceConfig
    from cowork_core.runner import build_runtime
    from cowork_core.tools.base import COWORK_CONTEXT_KEY

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)

    # Global registry already has bundled docx-basic.
    assert "docx-basic" in runtime.skills.names()

    project = runtime.registry_for("local").create("Foxtrot")
    _make_skill(project.skills_dir, "docx-basic", "overridden in project")

    _, _, adk_sid = await runtime.open_session(
        user_id="local", project_name="Foxtrot",
    )
    sess = await runtime.runner.session_service.get_session(
        app_name="cowork", user_id="local", session_id=adk_sid,
    )
    ctx = sess.state[COWORK_CONTEXT_KEY]
    body = ctx.skills.get("docx-basic").load_body()
    assert "overridden in project" in body
