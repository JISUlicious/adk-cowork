"""Tests for policy/permissions enforcement."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from cowork_core.config import PolicyConfig
from cowork_core.policy.permissions import make_permission_callback


def _make_tool(name: str) -> MagicMock:
    t = MagicMock()
    t.name = name
    return t


@pytest.fixture()
def plan_policy() -> PolicyConfig:
    return PolicyConfig(mode="plan")


@pytest.fixture()
def work_policy() -> PolicyConfig:
    return PolicyConfig(mode="work")


@pytest.fixture()
def auto_policy() -> PolicyConfig:
    return PolicyConfig(mode="auto")


class TestPlanMode:
    def test_blocks_write_tools(self, plan_policy: PolicyConfig) -> None:
        cb = make_permission_callback(plan_policy)
        ctx = MagicMock()
        for tool_name in ("fs_edit", "fs_promote", "shell_run", "python_exec_run"):
            result = cb(_make_tool(tool_name), {}, ctx)
            assert result is not None
            assert "error" in result
            assert "plan mode" in result["error"]

    def test_blocks_fs_write_to_non_plan_path(self, plan_policy: PolicyConfig) -> None:
        cb = make_permission_callback(plan_policy)
        ctx = MagicMock()
        result = cb(_make_tool("fs_write"), {"path": "scratch/report.md"}, ctx)
        assert result is not None
        assert "error" in result
        assert "plan.md" in result["error"]

    def test_allows_fs_write_to_plan_md(self, plan_policy: PolicyConfig) -> None:
        cb = make_permission_callback(plan_policy)
        ctx = MagicMock()
        result = cb(_make_tool("fs_write"), {"path": "scratch/plan.md"}, ctx)
        assert result is None

    def test_allows_read_tools(self, plan_policy: PolicyConfig) -> None:
        cb = make_permission_callback(plan_policy)
        ctx = MagicMock()
        for tool_name in ("fs_read", "fs_glob", "fs_list", "fs_stat", "search_web", "http_fetch"):
            result = cb(_make_tool(tool_name), {}, ctx)
            assert result is None


class TestWorkMode:
    def test_allows_write_tools(self, work_policy: PolicyConfig) -> None:
        cb = make_permission_callback(work_policy)
        ctx = MagicMock()
        for tool_name in ("fs_write", "fs_edit", "shell_run"):
            result = cb(_make_tool(tool_name), {}, ctx)
            assert result is None

    def test_blocks_email_send_when_deny(self) -> None:
        policy = PolicyConfig(mode="work", email_send="deny")
        cb = make_permission_callback(policy)
        ctx = MagicMock()
        result = cb(_make_tool("email_send"), {}, ctx)
        assert result is not None
        assert "error" in result

    def test_allows_email_send_when_confirm(self, work_policy: PolicyConfig) -> None:
        cb = make_permission_callback(work_policy)
        ctx = MagicMock()
        result = cb(_make_tool("email_send"), {}, ctx)
        assert result is None


class TestAutoMode:
    def test_allows_everything(self, auto_policy: PolicyConfig) -> None:
        cb = make_permission_callback(auto_policy)
        ctx = MagicMock()
        for tool_name in ("fs_write", "fs_edit", "shell_run", "email_send"):
            result = cb(_make_tool(tool_name), {}, ctx)
            assert result is None
