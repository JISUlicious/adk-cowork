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
from cowork_core.storage import InMemoryProjectStore, InMemoryUserStore
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
        user_store=InMemoryUserStore(),
        project_store=InMemoryProjectStore(),
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
        user_store=InMemoryUserStore(),
        project_store=InMemoryProjectStore(),
    )
    fake = MagicMock()
    fake.state = {COWORK_CONTEXT_KEY: ctx}
    out = load_skill("nope", fake)
    assert "error" in out


def test_parse_version_and_triggers(tmp_path: Path) -> None:
    """Optional frontmatter fields land on the Skill dataclass."""
    p = tmp_path / "SKILL.md"
    p.write_text(
        "---\n"
        "name: hello\n"
        'description: "use for hello"\n'
        "license: MIT\n"
        "version: 1.2.3\n"
        "triggers:\n  - foo\n  - bar\n"
        "---\nbody\n",
        encoding="utf-8",
    )
    skill = parse_skill_md(p)
    assert skill.version == "1.2.3"
    assert skill.triggers == ["foo", "bar"]
    # content_hash is the SHA-256 of the SKILL.md bytes, lowercase hex.
    assert len(skill.content_hash) == 64
    assert all(c in "0123456789abcdef" for c in skill.content_hash)


def test_parse_rejects_non_printable_in_description(tmp_path: Path) -> None:
    """Prompt-injection guard: control chars in user-visible string
    fields are rejected outright."""
    p = tmp_path / "SKILL.md"
    p.write_text(
        '---\nname: hello\ndescription: "line1\\nline2"\nlicense: MIT\n---\nbody\n',
        encoding="utf-8",
    )
    # YAML's double-quoted string interprets \n as a real newline,
    # which is U+000A — the parser must reject it.
    with pytest.raises(SkillLoadError, match="control character"):
        parse_skill_md(p)


def test_parse_rejects_invalid_triggers_type(tmp_path: Path) -> None:
    p = tmp_path / "SKILL.md"
    p.write_text(
        '---\nname: hello\ndescription: "x"\ntriggers: not-a-list\n---\nbody\n',
        encoding="utf-8",
    )
    with pytest.raises(SkillLoadError, match="triggers"):
        parse_skill_md(p)


def test_validate_skill_zip_dry_run(tmp_path: Path) -> None:
    """``runtime.validate_skill_zip`` runs the full validation
    pipeline but does NOT write to ``<workspace>/global/skills/``.
    Used by ``POST /v1/skills/validate``."""
    from cowork_core import CoworkConfig
    from cowork_core.config import WorkspaceConfig
    from cowork_core.runner import build_runtime

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)

    parsed = runtime.validate_skill_zip(_zip_skill("dryrun"))
    assert parsed.name == "dryrun"
    # Nothing landed in the user skills dir.
    assert not (tmp_path / "global" / "skills" / "dryrun").exists()
    # Registry isn't mutated either.
    assert "dryrun" not in runtime.skills.names()


def test_validate_skill_zip_rejects_invalid(tmp_path: Path) -> None:
    from cowork_core import CoworkConfig
    from cowork_core.config import WorkspaceConfig
    from cowork_core.runner import SkillInstallError, build_runtime

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    with pytest.raises(SkillInstallError, match="unsafe path"):
        runtime.validate_skill_zip(_zip_with_path("../evil/SKILL.md"))


def test_bundled_plot_ships_quick_chart_script() -> None:
    """The plot skill exercises the manifest() contract — its
    scripts/ folder must list quick_chart.py."""
    from cowork_core import CoworkConfig
    from cowork_core.runner import build_runtime
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        from cowork_core.config import WorkspaceConfig

        runtime = build_runtime(
            CoworkConfig(workspace=WorkspaceConfig(root=Path(tmp))),
        )
        plot = runtime.skills.get("plot")
        manifest = plot.manifest()
        assert "quick_chart.py" in manifest["scripts"]


def test_bundled_xlsx_basic_ships_table_io_script() -> None:
    from cowork_core import CoworkConfig
    from cowork_core.runner import build_runtime
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        from cowork_core.config import WorkspaceConfig

        runtime = build_runtime(
            CoworkConfig(workspace=WorkspaceConfig(root=Path(tmp))),
        )
        xlsx = runtime.skills.get("xlsx-basic")
        manifest = xlsx.manifest()
        assert "table_io.py" in manifest["scripts"]


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


def _zip_skill(name: str, description: str = "zipped skill") -> bytes:
    """Build an in-memory zip containing exactly ``<name>/SKILL.md``."""
    import io
    import zipfile

    frontmatter = (
        f"---\nname: {name}\ndescription: \"{description}\"\nlicense: MIT\n---\n\nbody\n"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{name}/SKILL.md", frontmatter)
    return buf.getvalue()


def _zip_with_path(path: str, body: str = "---\nname: x\ndescription: y\n---\nz") -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(path, body)
    return buf.getvalue()


def test_install_skill_happy_path(tmp_path: Path) -> None:
    from cowork_core import CoworkConfig
    from cowork_core.config import WorkspaceConfig
    from cowork_core.runner import build_runtime

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    assert "mytool" not in runtime.skills.names()

    installed = runtime.install_skill_zip(_zip_skill("mytool"))
    assert installed.name == "mytool"
    assert installed.source == "user"
    # Registry sees it after reload.
    assert "mytool" in runtime.skills.names()
    # The archive landed under <workspace>/global/skills/<name>/.
    assert (tmp_path / "global" / "skills" / "mytool" / "SKILL.md").is_file()


def test_install_skill_rejects_bundled_collision(tmp_path: Path) -> None:
    from cowork_core import CoworkConfig
    from cowork_core.config import WorkspaceConfig
    from cowork_core.runner import SkillInstallError, build_runtime

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    # ``docx-basic`` ships bundled — user can't shadow it via install.
    assert runtime.skills.get("docx-basic").source == "bundled"
    with _pytest.raises(SkillInstallError, match="bundled"):
        runtime.install_skill_zip(_zip_skill("docx-basic"))


def test_install_skill_rejects_path_traversal(tmp_path: Path) -> None:
    from cowork_core import CoworkConfig
    from cowork_core.config import WorkspaceConfig
    from cowork_core.runner import SkillInstallError, build_runtime

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    data = _zip_with_path("../evil/SKILL.md")
    with _pytest.raises(SkillInstallError, match="unsafe path"):
        runtime.install_skill_zip(data)


def test_install_skill_rejects_missing_skill_md(tmp_path: Path) -> None:
    from cowork_core import CoworkConfig
    from cowork_core.config import WorkspaceConfig
    from cowork_core.runner import SkillInstallError, build_runtime

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    # archive with a folder but no SKILL.md
    data = _zip_with_path("mytool/README.md", body="hi")
    with _pytest.raises(SkillInstallError, match="SKILL.md"):
        runtime.install_skill_zip(data)


def test_install_skill_rejects_name_mismatch(tmp_path: Path) -> None:
    import io
    import zipfile

    from cowork_core import CoworkConfig
    from cowork_core.config import WorkspaceConfig
    from cowork_core.runner import SkillInstallError, build_runtime

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    # Top-level dir says ``alpha`` but frontmatter says ``beta``.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "alpha/SKILL.md",
            '---\nname: beta\ndescription: "b"\nlicense: MIT\n---\nbody\n',
        )
    with _pytest.raises(SkillInstallError, match="does not match"):
        runtime.install_skill_zip(buf.getvalue())


def test_install_skill_rejects_invalid_name(tmp_path: Path) -> None:
    from cowork_core import CoworkConfig
    from cowork_core.config import WorkspaceConfig
    from cowork_core.runner import SkillInstallError, build_runtime

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    with _pytest.raises(SkillInstallError, match="invalid skill name"):
        runtime.install_skill_zip(_zip_skill("has space"))


def test_uninstall_user_skill_removes_folder(tmp_path: Path) -> None:
    from cowork_core import CoworkConfig
    from cowork_core.config import WorkspaceConfig
    from cowork_core.runner import build_runtime

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    runtime.install_skill_zip(_zip_skill("ephemeral"))
    dest = tmp_path / "global" / "skills" / "ephemeral"
    assert dest.is_dir()

    runtime.uninstall_skill("ephemeral")
    assert not dest.exists()
    assert "ephemeral" not in runtime.skills.names()


def test_uninstall_bundled_rejected(tmp_path: Path) -> None:
    from cowork_core import CoworkConfig
    from cowork_core.config import WorkspaceConfig
    from cowork_core.runner import SkillInstallError, build_runtime

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    with _pytest.raises(SkillInstallError, match="bundled"):
        runtime.uninstall_skill("docx-basic")


@_pytest.mark.asyncio
async def test_install_skill_appears_in_root_prompt_without_restart(tmp_path: Path) -> None:
    """B2 — ``_dynamic_instruction`` must re-query the live registry so
    a newly-installed skill appears in the root agent's prompt
    snippet on the *next* invocation without re-building the agent."""
    from cowork_core import CoworkConfig
    from cowork_core.config import WorkspaceConfig
    from cowork_core.runner import build_runtime

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)

    # Sanity: snippet doesn't mention ``freshly`` yet.
    assert "freshly" not in runtime.skills.injection_snippet()

    runtime.install_skill_zip(_zip_skill("freshly", description="new install"))
    # After install, the live snippet includes the new entry.
    snippet = runtime.skills.injection_snippet()
    assert "freshly" in snippet
    assert "new install" in snippet


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


# ─────────────── Slice II — safety + per-session enable ───────────────


def test_injection_snippet_caps_long_description(tmp_path: Path) -> None:
    """A malicious skill with a 1000-char description gets truncated to
    ``DESCRIPTION_PROMPT_CAP`` chars in the prompt. The full
    description still reaches ``Skill.description`` for the UI."""
    from cowork_core.skills.loader import DESCRIPTION_PROMPT_CAP

    long = "X" * 1000
    skill_dir = tmp_path / "noisy"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        f'---\nname: noisy\ndescription: "{long}"\nlicense: MIT\n---\nbody\n',
        encoding="utf-8",
    )
    reg = SkillRegistry()
    reg.scan(tmp_path)

    snippet = reg.injection_snippet()
    # Each line is "- name: description". The line for ``noisy`` is
    # capped at DESCRIPTION_PROMPT_CAP chars of description, plus the
    # ellipsis and the "- noisy: " prefix.
    noisy_line = next(line for line in snippet.splitlines() if line.startswith("- noisy:"))
    desc = noisy_line[len("- noisy: ") :]
    assert len(desc) == DESCRIPTION_PROMPT_CAP, len(desc)
    assert desc.endswith("…")
    # Untruncated description preserved on the dataclass.
    assert reg.get("noisy").description == long


def test_injection_snippet_omits_disabled_skills(tmp_path: Path) -> None:
    """When ``enabled`` returns False for a skill, that skill is
    omitted from the snippet. Absent-from-map skills default to
    enabled (predicate returns True)."""
    _make_skill(tmp_path, "alpha")
    _make_skill(tmp_path, "beta")
    reg = SkillRegistry()
    reg.scan(tmp_path)

    snippet = reg.injection_snippet(enabled=lambda name: name != "beta")
    assert "alpha" in snippet
    assert "beta" not in snippet


def test_load_skill_refuses_disabled(tmp_path: Path) -> None:
    """Even if the model guesses a disabled skill's name, the tool
    refuses with an explanatory error instead of loading the body.
    Mirror of the prompt-side gate."""
    from cowork_core.tools.base import COWORK_SKILLS_ENABLED_KEY

    ws = Workspace(root=tmp_path)
    pr = ProjectRegistry(workspace=ws)
    project = pr.create("Sierra")
    session = pr.new_session("sierra")

    skills_dir = project.skills_dir
    _make_skill(skills_dir, "secret", "off-limits")
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
        user_store=InMemoryUserStore(),
        project_store=InMemoryProjectStore(),
    )
    fake = MagicMock()
    fake.state = {
        COWORK_CONTEXT_KEY: ctx,
        COWORK_SKILLS_ENABLED_KEY: {"secret": False},
    }

    out = load_skill("secret", fake)
    assert "error" in out
    assert "disabled" in str(out["error"]).lower()
    # And the body is *not* leaked through.
    assert "off-limits" not in str(out)
