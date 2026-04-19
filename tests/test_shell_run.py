"""Tests for shell.run (M1.4)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cowork_core.config import CoworkConfig, PolicyConfig
from cowork_core.execenv import ManagedExecEnv
from cowork_core.approvals import InMemoryApprovalStore
from cowork_core.skills import SkillRegistry
from cowork_core.tools import COWORK_CONTEXT_KEY, CoworkToolContext
from cowork_core.tools.shell import shell_run
from cowork_core.workspace import ProjectRegistry, Workspace


@pytest.fixture
def tctx(tmp_path: Path) -> MagicMock:
    ws = Workspace(root=tmp_path)
    reg = ProjectRegistry(workspace=ws)
    project = reg.create("India")
    session = reg.new_session("india")
    cfg = CoworkConfig(policy=PolicyConfig(shell_allowlist=[sys.executable, "git", "python"]))
    ctx = CoworkToolContext(
        workspace=ws,
        registry=reg,
        project=project,
        session=session,
        config=cfg,
        skills=SkillRegistry(),
        env=ManagedExecEnv(project=project, session=session),
        approvals=InMemoryApprovalStore(),
    )
    fake = MagicMock()
    fake.state = {COWORK_CONTEXT_KEY: ctx}
    return fake


def test_rejects_string_argv(tctx: MagicMock) -> None:
    out = shell_run("echo hi", tctx)  # type: ignore[arg-type]
    assert "error" in out


def test_rejects_empty_argv(tctx: MagicMock) -> None:
    assert "error" in shell_run([], tctx)


def test_non_allowlisted_returns_confirmation(tctx: MagicMock) -> None:
    out = shell_run(["/bin/ls"], tctx)
    assert out.get("confirmation_required") is True
    assert "allowlist" in str(out.get("summary", ""))


def test_runs_python_version(tctx: MagicMock) -> None:
    out = shell_run([sys.executable, "--version"], tctx)
    assert out["exit_code"] == 0
    combined = str(out["stdout"]) + str(out["stderr"])
    assert "Python" in combined


def test_runs_in_scratch_by_default(tctx: MagicMock) -> None:
    out = shell_run(
        [sys.executable, "-c", "import os; print(os.getcwd())"],
        tctx,
    )
    assert out["exit_code"] == 0
    ctx_obj: CoworkToolContext = tctx.state[COWORK_CONTEXT_KEY]
    assert str(ctx_obj.session.scratch_dir.resolve()) in str(out["stdout"])


def test_timeout_returns_error(tctx: MagicMock) -> None:
    out = shell_run(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        tctx,
        timeout_sec=1,
    )
    assert "error" in out
    assert "timed out" in str(out["error"])


def test_cwd_traversal_rejected(tctx: MagicMock) -> None:
    out = shell_run([sys.executable, "--version"], tctx, cwd="../../etc")
    assert "error" in out
