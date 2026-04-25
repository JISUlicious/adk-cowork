"""Tests for policy/permissions enforcement."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from cowork_core.config import PolicyConfig
from cowork_core.policy.permissions import (
    make_allowlist_callback,
    make_permission_callback,
)
from cowork_core.tools.base import COWORK_TOOL_ALLOWLIST_KEY


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

    def test_email_send_passes_through_first_call(
        self, work_policy: PolicyConfig,
    ) -> None:
        """First call (``confirmed=False``) passes through the callback
        so the tool body can read the .eml and return a properly
        formatted ``confirmation_required`` dict. The callback only
        enforces the approval token on ``confirmed=True``."""
        cb = make_permission_callback(work_policy)
        ctx = _ctx()
        result = cb(
            _make_tool("email_send"),
            {"eml_id": "abc"},  # confirmed missing → tool gates itself
            ctx,
        )
        assert result is None

    def test_email_send_blocks_confirmed_without_approval(
        self, work_policy: PolicyConfig,
    ) -> None:
        """Model can't bypass user consent by setting ``confirmed=True``
        directly — without an approval token on file, the callback
        returns an explanatory error."""
        cb = make_permission_callback(work_policy)
        ctx = _ctx()
        result = cb(
            _make_tool("email_send"),
            {"eml_id": "abc", "confirmed": True},
            ctx,
        )
        assert result is not None
        assert "error" in result
        assert "approval" in result["error"].lower()

    def test_email_send_consumes_approval_on_confirmed(
        self, work_policy: PolicyConfig,
    ) -> None:
        """When the user has granted approval via the UI, the callback
        consumes the token and lets the tool body run with ``confirmed=True``.
        A follow-up ``confirmed=True`` call without re-granting blocks
        again — the approval is one-shot."""
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

        store.grant("sess-1", "email_send")

        first = cb(
            _make_tool("email_send"),
            {"eml_id": "abc", "confirmed": True},
            ctx,
        )
        assert first is None

        second = cb(
            _make_tool("email_send"),
            {"eml_id": "abc", "confirmed": True},
            ctx,
        )
        assert second is not None and "error" in second

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


class TestAllowlistCallback:
    """``make_allowlist_callback`` produces a per-agent closure used by
    ``build_root_agent`` to gate sub-agent tool access. The root agent is
    not wired with this callback — it runs unrestricted by design."""

    def test_no_allowlist_means_unrestricted(self) -> None:
        cb = make_allowlist_callback("researcher")
        ctx = _ctx()
        # Absent key → no restriction; every tool passes.
        for tool_name in ("fs_read", "python_exec_run", "shell_run"):
            assert cb(_make_tool(tool_name), {}, ctx) is None

    def test_agent_absent_from_dict_unrestricted(self) -> None:
        cb = make_allowlist_callback("analyst")
        ctx = _ctx()
        # Allowlist exists but analyst is absent → unrestricted.
        ctx.state[COWORK_TOOL_ALLOWLIST_KEY] = {"writer": ["fs_read"]}
        assert cb(_make_tool("python_exec_run"), {}, ctx) is None

    def test_allowlist_blocks_unapproved_tools(self) -> None:
        cb = make_allowlist_callback("researcher")
        ctx = _ctx()
        ctx.state[COWORK_TOOL_ALLOWLIST_KEY] = {
            "researcher": ["fs_read", "http_fetch"],
        }
        # Allowed tools pass.
        assert cb(_make_tool("fs_read"), {}, ctx) is None
        assert cb(_make_tool("http_fetch"), {}, ctx) is None
        # Disallowed tool is blocked with a readable error that names
        # both the tool and the agent so the UI can render it in-place.
        result = cb(_make_tool("python_exec_run"), {}, ctx)
        assert result is not None
        assert "python_exec_run" in result["error"]
        assert "researcher" in result["error"]

    def test_empty_list_silences_agent(self) -> None:
        cb = make_allowlist_callback("writer")
        ctx = _ctx()
        ctx.state[COWORK_TOOL_ALLOWLIST_KEY] = {"writer": []}
        # Every tool is blocked — the agent is effectively silenced.
        for tool_name in ("fs_read", "fs_write", "python_exec_run"):
            result = cb(_make_tool(tool_name), {}, ctx)
            assert result is not None
            assert "writer" in result["error"]

    def test_malformed_allowlist_falls_back_to_unrestricted(self) -> None:
        """Defensive: if someone writes the wrong type to state (pre-E1
        stale data, a bad PATCH, etc.), the callback shouldn't crash the
        whole turn — it should treat the agent as unrestricted."""
        cb = make_allowlist_callback("reviewer")
        ctx = _ctx()
        ctx.state[COWORK_TOOL_ALLOWLIST_KEY] = "not-a-dict"
        assert cb(_make_tool("fs_read"), {}, ctx) is None


@pytest.mark.asyncio
class TestRuntimeAllowlist:
    async def test_runtime_round_trip(self, tmp_path: object) -> None:
        """Runtime setter writes through ADK session state; getter reads
        back the same structure. Empty dict = no restrictions."""
        import pathlib

        from cowork_core import CoworkConfig
        from cowork_core.config import WorkspaceConfig
        from cowork_core.runner import build_runtime

        assert isinstance(tmp_path, pathlib.Path)
        cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
        runtime = build_runtime(cfg)
        _, _, sid = await runtime.open_session(project_name="TestAllowlistProj")

        # Fresh session has no allowlist.
        assert await runtime.get_session_tool_allowlist(sid) == {}

        # Set, then read back. Lists normalise to new list objects.
        applied = await runtime.set_session_tool_allowlist(
            sid, {"researcher": ["fs_read", "http_fetch"]},
        )
        assert applied == {"researcher": ["fs_read", "http_fetch"]}
        assert await runtime.get_session_tool_allowlist(sid) == {
            "researcher": ["fs_read", "http_fetch"],
        }

        # Bad payload types are rejected before any write.
        with pytest.raises(ValueError):
            await runtime.set_session_tool_allowlist(sid, "not-a-dict")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            await runtime.set_session_tool_allowlist(
                sid, {"writer": "not-a-list"},  # type: ignore[dict-item]
            )
        with pytest.raises(ValueError):
            await runtime.set_session_tool_allowlist(
                sid, {"writer": [1, 2, 3]},  # type: ignore[list-item]
            )
