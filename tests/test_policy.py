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


def _ctx() -> MagicMock:
    """A tool_context mock whose .state is a real dict so .get(KEY, default)
    behaves like ADK's real ToolContext."""
    c = MagicMock()
    c.state = {}
    return c


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
        ctx = _ctx()
        for tool_name in ("fs_edit", "fs_promote", "shell_run", "python_exec_run"):
            result = cb(_make_tool(tool_name), {}, ctx)
            assert result is not None
            assert "error" in result
            assert "plan mode" in result["error"]

    def test_blocks_fs_write_to_non_plan_path(self, plan_policy: PolicyConfig) -> None:
        cb = make_permission_callback(plan_policy)
        ctx = _ctx()
        result = cb(_make_tool("fs_write"), {"path": "scratch/report.md"}, ctx)
        assert result is not None
        assert "error" in result
        assert "plan.md" in result["error"]

    def test_allows_fs_write_to_plan_md(self, plan_policy: PolicyConfig) -> None:
        cb = make_permission_callback(plan_policy)
        ctx = _ctx()
        result = cb(_make_tool("fs_write"), {"path": "scratch/plan.md"}, ctx)
        assert result is None

    def test_allows_read_tools(self, plan_policy: PolicyConfig) -> None:
        cb = make_permission_callback(plan_policy)
        ctx = _ctx()
        for tool_name in ("fs_read", "fs_glob", "fs_list", "fs_stat", "search_web", "http_fetch"):
            result = cb(_make_tool(tool_name), {}, ctx)
            assert result is None


class TestWorkMode:
    def test_allows_write_tools(self, work_policy: PolicyConfig) -> None:
        cb = make_permission_callback(work_policy)
        ctx = _ctx()
        for tool_name in ("fs_write", "fs_edit", "shell_run"):
            result = cb(_make_tool(tool_name), {}, ctx)
            assert result is None

    def test_blocks_email_send_when_deny(self) -> None:
        policy = PolicyConfig(mode="work", email_send="deny")
        cb = make_permission_callback(policy)
        ctx = _ctx()
        result = cb(_make_tool("email_send"), {}, ctx)
        assert result is not None
        assert "error" in result

    def test_email_send_requires_confirmation_by_default(
        self, work_policy: PolicyConfig,
    ) -> None:
        cb = make_permission_callback(work_policy)
        ctx = _ctx()
        result = cb(
            _make_tool("email_send"),
            {"to": "x@example.com", "subject": "hi", "body": "hello"},
            ctx,
        )
        assert result is not None
        assert result["confirmation_required"] is True
        assert result["to"] == "x@example.com"

    def test_python_exec_requires_confirmation_by_default(
        self, work_policy: PolicyConfig,
    ) -> None:
        """Regression guard: python_exec_run must not run without approval.

        Claims to be path-confined but in reality Python can read anything
        the host process can. Discovered by user who denied a shell_run and
        watched the agent pivot to python_exec_run — which silently ran.
        """
        cb = make_permission_callback(work_policy)
        ctx = _ctx()
        result = cb(
            _make_tool("python_exec_run"),
            {"code": "open('/etc/passwd').read()"},
            ctx,
        )
        assert result is not None
        assert result["confirmation_required"] is True
        assert "open('/etc/passwd')" in result.get("code_preview", "")

    def test_python_exec_deny_policy_blocks_entirely(self) -> None:
        from cowork_core.config import PolicyConfig

        policy = PolicyConfig(mode="work", python_exec="deny")
        cb = make_permission_callback(policy)
        ctx = _ctx()
        result = cb(_make_tool("python_exec_run"), {"code": "print(1)"}, ctx)
        assert result is not None
        assert "error" in result
        assert "disabled" in result["error"]

    def test_python_exec_allow_policy_skips_gate(self) -> None:
        from cowork_core.config import PolicyConfig

        policy = PolicyConfig(mode="work", python_exec="allow")
        cb = make_permission_callback(policy)
        ctx = _ctx()
        result = cb(_make_tool("python_exec_run"), {"code": "print(1)"}, ctx)
        assert result is None

    def test_per_session_python_exec_overrides_cfg(self) -> None:
        """Session state COWORK_PYTHON_EXEC_KEY wins over cfg.policy.python_exec.

        Lets the UI toggle python_exec policy per-session via
        ``PUT /v1/sessions/{id}/policy/python_exec`` without restarting
        the server or mutating global config.
        """
        from cowork_core.config import PolicyConfig
        from cowork_core.tools.base import COWORK_PYTHON_EXEC_KEY

        # Config default: confirm. Session override: allow.
        cb = make_permission_callback(PolicyConfig(mode="work"))
        ctx = _ctx()
        ctx.state[COWORK_PYTHON_EXEC_KEY] = "allow"
        result = cb(_make_tool("python_exec_run"), {"code": "print(1)"}, ctx)
        assert result is None

        # Session override deny blocks regardless of cfg default.
        cb2 = make_permission_callback(PolicyConfig(mode="work", python_exec="allow"))
        ctx2 = _ctx()
        ctx2.state[COWORK_PYTHON_EXEC_KEY] = "deny"
        result2 = cb2(_make_tool("python_exec_run"), {"code": "print(1)"}, ctx2)
        assert result2 is not None
        assert "disabled" in result2["error"]

    def test_approval_counter_consumed_on_next_call(
        self, work_policy: PolicyConfig,
    ) -> None:
        """Granting an approval lets exactly one subsequent call through;
        the call after that is gated again. Approvals live on a process-
        local store (not ADK session state) so writing them never races
        with ``runner.run_async``."""
        from unittest.mock import MagicMock

        from cowork_core.approvals import InMemoryApprovalStore
        from cowork_core.tools.base import COWORK_CONTEXT_KEY

        store = InMemoryApprovalStore()
        fake_session = MagicMock()
        fake_session.id = "sess-1"
        fake_cowork_ctx = MagicMock()
        fake_cowork_ctx.session = fake_session
        fake_cowork_ctx.approvals = store

        cb = make_permission_callback(work_policy)
        ctx = _ctx()
        ctx.state[COWORK_CONTEXT_KEY] = fake_cowork_ctx

        store.grant("sess-1", "python_exec_run")

        # First call: approval consumed, passes through.
        first = cb(_make_tool("python_exec_run"), {"code": "x"}, ctx)
        assert first is None
        assert store.list("sess-1") == {"python_exec_run": 0}

        # Second call: no approval left → gated again.
        second = cb(_make_tool("python_exec_run"), {"code": "x"}, ctx)
        assert second is not None
        assert second["confirmation_required"] is True


class TestAutoMode:
    def test_allows_everything(self, auto_policy: PolicyConfig) -> None:
        cb = make_permission_callback(auto_policy)
        ctx = _ctx()
        for tool_name in (
            "fs_write", "fs_edit", "shell_run",
            "email_send", "python_exec_run",
        ):
            result = cb(_make_tool(tool_name), {}, ctx)
            assert result is None


class TestPerSessionMode:
    def test_session_mode_overrides_config_default(
        self, work_policy: PolicyConfig,
    ) -> None:
        from cowork_core.tools.base import COWORK_POLICY_MODE_KEY

        cb = make_permission_callback(work_policy)  # default: work
        ctx = _ctx()
        ctx.state[COWORK_POLICY_MODE_KEY] = "plan"
        # In plan mode a write tool should be blocked even though the server
        # default is 'work'.
        result = cb(_make_tool("fs_edit"), {}, ctx)
        assert result is not None
        assert "plan mode" in result["error"]

    def test_session_mode_switch_back_to_work(
        self, plan_policy: PolicyConfig,
    ) -> None:
        from cowork_core.tools.base import COWORK_POLICY_MODE_KEY

        cb = make_permission_callback(plan_policy)  # default: plan
        ctx = _ctx()
        ctx.state[COWORK_POLICY_MODE_KEY] = "work"
        # Server default is plan, session override is work → writes allowed.
        result = cb(_make_tool("fs_edit"), {}, ctx)
        assert result is None


class TestSubAgentCallbacks:
    """Regression: sub-agents must carry the same policy+audit callbacks as
    the root so plan-mode applies uniformly when the root delegates work."""

    def test_all_sub_agents_carry_before_tool_callback(self) -> None:
        from cowork_core import CoworkConfig
        from cowork_core.agents.root_agent import build_root_agent

        root = build_root_agent(CoworkConfig(), tools=[], skills_snippet="")
        assert root.sub_agents, "root has no sub-agents"
        for sub in root.sub_agents:
            cb = sub.before_tool_callback
            assert cb, f"sub-agent {sub.name!r} has no before_tool_callback"
        for sub in root.sub_agents:
            cb = sub.after_tool_callback
            assert cb, f"sub-agent {sub.name!r} has no after_tool_callback"


class TestToolApprovalRuntime:
    """End-to-end: the runtime's grant_tool_approval() writes into ADK
    session state and the permission callback consumes it on the next
    call of that tool."""

    @pytest.mark.asyncio
    async def test_grant_then_call_lets_through(self, tmp_path) -> None:
        """End-to-end: runtime.grant_tool_approval writes to the in-memory
        store; the permission callback reads it via the injected
        CoworkToolContext and passes the next call through."""
        from unittest.mock import MagicMock

        from cowork_core import CoworkConfig
        from cowork_core.config import WorkspaceConfig
        from cowork_core.runner import build_runtime
        from cowork_core.tools.base import COWORK_CONTEXT_KEY

        cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
        runtime = build_runtime(cfg)
        _, _, sid = await runtime.open_session(project_name="Approvals")

        # Before any grant: the counter dict is empty.
        assert await runtime.list_tool_approvals(sid) == {}

        remaining = await runtime.grant_tool_approval(sid, "python_exec_run")
        assert remaining == 1
        assert await runtime.list_tool_approvals(sid) == {"python_exec_run": 1}

        # The runtime writes approvals to its in-memory store, not ADK
        # session state — so runner.run_async and the grant endpoint can
        # never race on the session's update_time.
        cb = make_permission_callback(cfg.policy)
        adk_session = await runtime.runner.session_service.get_session(
            app_name="cowork", user_id="local", session_id=sid,
        )
        ctx = MagicMock()
        # The real ctx.state carries the injected CoworkToolContext —
        # which is what the permission callback reads to find the
        # approval store.
        ctx.state = dict(adk_session.state)

        result = cb(
            _make_tool("python_exec_run"),
            {"code": "print(1)"},
            ctx,
        )
        assert result is None
        # Counter decremented in the live store.
        assert runtime.approvals.list(sid) == {"python_exec_run": 0}


class TestSessionPolicyEndpoint:
    """End-to-end: PUT /v1/sessions/{id}/policy/mode persists and the
    permission callback sees the new mode on the next check."""

    @pytest.mark.asyncio
    async def test_runtime_set_and_get(self, tmp_path) -> None:
        from cowork_core import CoworkConfig
        from cowork_core.config import WorkspaceConfig
        from cowork_core.runner import build_runtime

        cfg = CoworkConfig(
            workspace=WorkspaceConfig(root=tmp_path),
            policy=PolicyConfig(mode="work"),
        )
        runtime = build_runtime(cfg)
        _, _, sid = await runtime.open_session(project_name="TestProj")

        # Fresh session inherits the server default.
        assert await runtime.get_session_policy_mode(sid) == "work"

        # Flip to plan, verify get + state_delta stuck.
        await runtime.set_session_policy_mode(sid, "plan")
        assert await runtime.get_session_policy_mode(sid) == "plan"

        # Unknown modes are rejected.
        with pytest.raises(ValueError):
            await runtime.set_session_policy_mode(sid, "cowboy")
