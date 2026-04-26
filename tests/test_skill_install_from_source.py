"""Tests for V3 — skill discovery + install via vercel-labs/skills.

Mocks the npx subprocess so tests don't need Node installed and
don't hit the network. Exercises:
- npx-detection 503 path
- single-skill source happy path (one SKILL.md in tmp)
- multi-skill source happy path (multiple SKILL.md in tmp)
- partial failure (one skill installs, another skipped on validation)
- subprocess failure surfaces stderr
- MU non-operator 403
- MU local-path rejection (heuristic)
- _looks_like_github_shorthand helper
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cowork_core import CoworkConfig
from cowork_core.config import AuthConfig, WorkspaceConfig
from cowork_core.runner import (
    SkillInstallError,
    SkillInstallFromSourceResult,
    build_runtime,
)
from cowork_server.app import _looks_like_github_shorthand, create_app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Path:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    return fake_home


# ──────────────── _looks_like_github_shorthand ────────────────


def test_github_shorthand_recognises_simple_owner_repo() -> None:
    assert _looks_like_github_shorthand("vercel-labs/skills") is True
    assert _looks_like_github_shorthand("owner/repo") is True
    assert _looks_like_github_shorthand("a/b") is True


def test_github_shorthand_rejects_paths_and_urls() -> None:
    assert _looks_like_github_shorthand("/abs/path") is False
    assert _looks_like_github_shorthand("./rel/path") is False
    assert _looks_like_github_shorthand("a/b/c") is False
    assert _looks_like_github_shorthand("https://github.com/x/y") is False
    assert _looks_like_github_shorthand("plain") is False
    assert _looks_like_github_shorthand("") is False


# ──────────────── runtime.install_skills_from_source ────────────────


def _seed_skill(parent: Path, name: str, body: str = "demo body") -> Path:
    """Create a directory containing a valid SKILL.md."""
    skill_dir = parent / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f'---\nname: {name}\n'
        f'description: "Use for {name}."\n'
        f'license: MIT\n'
        f'---\n\n{body}\n',
        encoding="utf-8",
    )
    return skill_dir


@pytest.mark.asyncio
async def test_install_from_source_503s_when_npx_missing(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    with patch("shutil.which", return_value=None):
        with pytest.raises(SkillInstallError, match="npx not found"):
            await runtime.install_skills_from_source("vercel-labs/skills")


@pytest.mark.asyncio
async def test_install_from_source_single_skill(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)

    extracted = tmp_path / "extracted"
    _seed_skill(extracted, "demo-skill")

    async def _fake_subprocess(*args: object, **kwargs: object) -> object:
        # Move the seeded skill into the --target dir the CLI was
        # asked for. Find --target in args.
        argv = list(args)
        target_idx = argv.index("--target")
        target = Path(argv[target_idx + 1])
        target.mkdir(parents=True, exist_ok=True)
        import shutil
        for child in extracted.iterdir():
            shutil.move(str(child), str(target / child.name))

        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.kill = MagicMock()
        return proc

    with patch("shutil.which", return_value="/usr/local/bin/npx"), \
            patch("asyncio.create_subprocess_exec", side_effect=_fake_subprocess):
        result = await runtime.install_skills_from_source("dummy/source")

    assert len(result.installed) == 1
    assert result.installed[0].name == "demo-skill"
    assert result.skipped == []
    # On disk in the workspace's user-skills dir.
    assert (tmp_path / "global" / "skills" / "demo-skill" / "SKILL.md").is_file()


@pytest.mark.asyncio
async def test_install_from_source_multiple_skills(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)

    extracted = tmp_path / "extracted"
    _seed_skill(extracted / "skills", "skill-a")
    _seed_skill(extracted / "skills" / "nested", "skill-b")

    async def _fake_subprocess(*args: object, **kwargs: object) -> object:
        argv = list(args)
        target_idx = argv.index("--target")
        target = Path(argv[target_idx + 1])
        target.mkdir(parents=True, exist_ok=True)
        import shutil
        for child in extracted.iterdir():
            shutil.move(str(child), str(target / child.name))
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.kill = MagicMock()
        return proc

    with patch("shutil.which", return_value="/usr/local/bin/npx"), \
            patch("asyncio.create_subprocess_exec", side_effect=_fake_subprocess):
        result = await runtime.install_skills_from_source("multi/source")

    names = sorted(s.name for s in result.installed)
    assert names == ["skill-a", "skill-b"]


@pytest.mark.asyncio
async def test_install_from_source_subprocess_failure_surfaces_stderr(
    tmp_path: Path,
) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)

    async def _fake_subprocess(*args: object, **kwargs: object) -> object:
        proc = MagicMock()
        proc.returncode = 1
        proc.communicate = AsyncMock(
            return_value=(b"", b"could not resolve repo: not-a-real-org/x"),
        )
        proc.kill = MagicMock()
        return proc

    with patch("shutil.which", return_value="/usr/local/bin/npx"), \
            patch("asyncio.create_subprocess_exec", side_effect=_fake_subprocess):
        with pytest.raises(SkillInstallError, match="could not resolve"):
            await runtime.install_skills_from_source("not-a-real-org/x")


@pytest.mark.asyncio
async def test_install_from_source_no_skills_found(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)

    async def _fake_subprocess(*args: object, **kwargs: object) -> object:
        # CLI exits 0 but writes nothing to --target.
        proc = MagicMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.kill = MagicMock()
        return proc

    with patch("shutil.which", return_value="/usr/local/bin/npx"), \
            patch("asyncio.create_subprocess_exec", side_effect=_fake_subprocess):
        with pytest.raises(SkillInstallError, match="no SKILL.md"):
            await runtime.install_skills_from_source("empty/source")


# ──────────────── /v1/skills/install-from-source ────────────────


def test_route_503s_when_npx_missing(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    client = TestClient(create_app(cfg, token="t"))
    with patch("shutil.which", return_value=None):
        r = client.post(
            "/v1/skills/install-from-source",
            headers={"x-cowork-token": "t"},
            json={"source": "owner/repo"},
        )
    assert r.status_code == 503
    assert "npx not found" in r.json()["detail"]


def test_route_403s_non_operator_in_mu(tmp_path: Path) -> None:
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(
            keys={"alice-k": "alice", "bob-k": "bob"},
            operator="alice",
        ),
    )
    client = TestClient(create_app(cfg, token="t"))
    r = client.post(
        "/v1/skills/install-from-source",
        headers={"x-cowork-token": "bob-k"},
        json={"source": "owner/repo"},
    )
    assert r.status_code == 403
    assert "operator-only" in r.json()["detail"]


def test_route_rejects_local_paths_in_mu(tmp_path: Path) -> None:
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(
            keys={"alice-k": "alice"}, operator="alice",
        ),
    )
    client = TestClient(create_app(cfg, token="t"))
    for bad in ("/abs/path", "./rel", "../parent", "~/home"):
        r = client.post(
            "/v1/skills/install-from-source",
            headers={"x-cowork-token": "alice-k"},
            json={"source": bad},
        )
        assert r.status_code == 400, f"expected 400 for {bad!r}, got {r.status_code}"
        assert "local path" in r.json()["detail"]
