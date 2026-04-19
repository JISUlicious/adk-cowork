"""Tests for python_exec.run (M1.5)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cowork_core.config import CoworkConfig
from cowork_core.execenv import ManagedExecEnv
from cowork_core.approvals import InMemoryApprovalStore
from cowork_core.skills import SkillRegistry
from cowork_core.tools import COWORK_CONTEXT_KEY, CoworkToolContext
from cowork_core.tools.python_exec import python_exec_run
from cowork_core.workspace import ProjectRegistry, Workspace


@pytest.fixture
def tctx(tmp_path: Path) -> MagicMock:
    ws = Workspace(root=tmp_path)
    reg = ProjectRegistry(workspace=ws)
    project = reg.create("Juliet")
    session = reg.new_session("juliet")
    ctx = CoworkToolContext(
        workspace=ws,
        registry=reg,
        project=project,
        session=session,
        config=CoworkConfig(),
        skills=SkillRegistry(),
        env=ManagedExecEnv(project=project, session=session),
        approvals=InMemoryApprovalStore(),
    )
    fake = MagicMock()
    fake.state = {COWORK_CONTEXT_KEY: ctx}
    return fake


def test_rejects_empty_code(tctx: MagicMock) -> None:
    assert "error" in python_exec_run("", tctx)
    assert "error" in python_exec_run("   \n", tctx)


def test_runs_simple_snippet(tctx: MagicMock) -> None:
    out = python_exec_run("print(2 + 3)", tctx)
    assert out["exit_code"] == 0
    assert "5" in str(out["stdout"])


def test_cwd_is_session_scratch(tctx: MagicMock) -> None:
    out = python_exec_run("import os; print(os.getcwd())", tctx)
    ctx: CoworkToolContext = tctx.state[COWORK_CONTEXT_KEY]
    assert str(ctx.session.scratch_dir.resolve()) in str(out["stdout"])


def test_exit_code_propagates(tctx: MagicMock) -> None:
    out = python_exec_run("raise SystemExit(7)", tctx)
    assert out["exit_code"] == 7


def test_timeout_returns_error(tctx: MagicMock) -> None:
    out = python_exec_run("import time; time.sleep(5)", tctx, timeout_sec=1)
    assert "error" in out
    assert "timed out" in str(out["error"])


def test_no_network_by_default(tctx: MagicMock) -> None:
    out = python_exec_run("import os; print(os.environ.get('HTTP_PROXY', ''))", tctx)
    assert "127.0.0.1:1" in str(out["stdout"])


def test_script_cleanup(tctx: MagicMock) -> None:
    python_exec_run("print('ok')", tctx)
    ctx: CoworkToolContext = tctx.state[COWORK_CONTEXT_KEY]
    leftover = list(ctx.session.scratch_dir.glob("*.py"))
    assert leftover == []
