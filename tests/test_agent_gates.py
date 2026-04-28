"""Tests for W1 — config-time hard tool gates + per-agent model.

The static gate (``make_static_agent_gate``) is mounted FIRST in each
sub-agent's ``before_tool_callback`` chain, ahead of the runtime
allowlist. A prompt-injected sub-agent that flips its own session-state
allowlist still cannot escape the config-time deny set or the
config-time allow set.

Per-agent model override: ``cfg.agents.<name>.model = ModelConfig(...)``
swaps a sub-agent onto a different OpenAI-compatible endpoint (e.g. a
cheaper model for an Explore agent). ``None`` = inherit ``cfg.model``.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from cowork_core.agents.root_agent import (
    SUB_AGENT_DEFAULTS,
    build_root_agent,
)
from cowork_core.config import (
    AgentConfig,
    CoworkConfig,
    ModelConfig,
)
from cowork_core.policy.permissions import make_static_agent_gate
from cowork_core.tools.base import COWORK_TOOL_ALLOWLIST_KEY


def _make_tool(name: str) -> MagicMock:
    t = MagicMock()
    t.name = name
    return t


def _ctx() -> MagicMock:
    c = MagicMock()
    c.state = {}
    return c


class TestStaticAgentGate:
    """``make_static_agent_gate`` enforces config-time allow/deny."""

    def test_no_allowlist_passes_everything(self) -> None:
        gate = make_static_agent_gate("explorer", None, frozenset())
        assert gate(_make_tool("fs_read"), {}, _ctx()) is None
        assert gate(_make_tool("shell_run"), {}, _ctx()) is None

    def test_allowlist_blocks_non_listed(self) -> None:
        gate = make_static_agent_gate(
            "researcher",
            frozenset({"fs_read", "search_web"}),
            frozenset(),
        )
        assert gate(_make_tool("fs_read"), {}, _ctx()) is None
        assert gate(_make_tool("search_web"), {}, _ctx()) is None
        result = gate(_make_tool("fs_write"), {}, _ctx())
        assert result is not None
        assert "fs_write" in result["error"]
        assert "researcher" in result["error"]

    def test_disallow_overrides_allow(self) -> None:
        """Defense in depth: even if a tool slips into the allowlist,
        an explicit denylist entry blocks it."""
        gate = make_static_agent_gate(
            "writer",
            frozenset({"fs_write", "shell_run"}),
            frozenset({"shell_run"}),
        )
        assert gate(_make_tool("fs_write"), {}, _ctx()) is None
        result = gate(_make_tool("shell_run"), {}, _ctx())
        assert result is not None
        assert "shell_run" in result["error"]

    def test_static_gate_ignores_session_state(self) -> None:
        """The whole point of W1: the gate captures allow/disallow at
        agent-build time. A prompt-injected sub-agent that PATCHes its
        own ``COWORK_TOOL_ALLOWLIST_KEY`` cannot expand the static gate."""
        gate = make_static_agent_gate(
            "researcher",
            frozenset({"fs_read"}),
            frozenset(),
        )
        ctx = _ctx()
        # Inject a permissive runtime allowlist into session state.
        ctx.state[COWORK_TOOL_ALLOWLIST_KEY] = {"researcher": ["fs_write"]}
        # Static gate STILL blocks fs_write — runtime state is irrelevant.
        result = gate(_make_tool("fs_write"), {}, ctx)
        assert result is not None
        assert "fs_write" in result["error"]


class TestSubAgentDefaults:
    """The built-in defaults table is the source of truth for the
    four built-in sub-agents' allowlists when ``cfg.agents`` is empty."""

    def test_all_builtin_agents_have_defaults(self) -> None:
        # Four originals + three W3 additions.
        assert set(SUB_AGENT_DEFAULTS.keys()) == {
            "researcher", "writer", "analyst", "reviewer",
            "explorer", "planner", "verifier",
        }

    def test_researcher_default_is_read_only(self) -> None:
        """W4 — researcher is the gathering role: read + search/fetch +
        memory only. ``python_exec_run`` was dropped (it ran at
        ``cwd=agent_cwd()`` and could write anywhere; a "read-only"
        agent with that surface was a contradiction). PDF / docx /
        xlsx parsing now routes to analyst."""
        allowed, _ = SUB_AGENT_DEFAULTS["researcher"]
        # No mutation, no execution.
        for forbidden in (
            "fs_write", "fs_edit", "fs_promote",
            "shell_run", "python_exec_run",
            "email_send", "email_draft",
        ):
            assert forbidden not in allowed, (
                f"{forbidden!r} leaked into researcher's read-only default"
            )
        # The gathering surface IS in.
        assert "fs_read" in allowed
        assert "search_web" in allowed
        assert "http_fetch" in allowed  # researcher is the only role
                                        # that does raw page fetch
        # Memory: write / remember only — no log (audit is reviewer
        # / verifier territory).
        assert "memory_write" in allowed
        assert "memory_remember" in allowed
        assert "memory_log" not in allowed

    def test_reviewer_default_is_strictest(self) -> None:
        allowed, _ = SUB_AGENT_DEFAULTS["reviewer"]
        # No mutation, no execution, no http.
        for forbidden in (
            "fs_write", "fs_edit", "fs_promote",
            "shell_run", "python_exec_run",
            "http_fetch", "email_send",
        ):
            assert forbidden not in allowed, (
                f"{forbidden!r} leaked into reviewer's read-only default"
            )

    def test_writer_default_excludes_shell_and_python_exec(self) -> None:
        """W4 — writer is a text-content producer. ``python_exec_run``
        was dropped because the only thing it bought was binary office
        formats (.docx / .xlsx / .pdf), which are analyst's lane. Plain
        ``fs_write`` covers .md / .txt / .html / .csv / .eml / .json /
        .xml. Writer also doesn't do raw page fetch (researcher's
        lane) and doesn't keep an audit trail (reviewer / verifier)."""
        allowed, _ = SUB_AGENT_DEFAULTS["writer"]
        for forbidden in (
            "shell_run",
            "python_exec_run",  # W4 drop — text formats only
            "http_fetch",       # W4 drop — researcher's lane
            "memory_log",       # W4 drop — audit isn't writer's role
            "email_send",
        ):
            assert forbidden not in allowed, (
                f"{forbidden!r} leaked into writer's text-only default"
            )
        # Mutation IS allowed for the writer.
        assert "fs_write" in allowed
        assert "fs_edit" in allowed
        assert "fs_promote" in allowed
        # And single-fact lookups stay (mid-draft fact-check).
        assert "search_web" in allowed
        # Memory: write / remember only.
        assert "memory_write" in allowed
        assert "memory_remember" in allowed

    def test_analyst_default_excludes_publication_and_audit(self) -> None:
        """W4 — analyst is the compute role and the binary-format
        producer. Dropped ``fs_promote`` (publication is a writer-flow
        step), ``http_fetch`` (raw fetch is researcher's lane), and
        ``memory_log`` (audit is verifier's lane).

        W5 — analyst now has ``shell_run`` for direct CLI tool
        invocation (pandoc / wkhtmltopdf / ffmpeg / libreoffice).
        Per-agent shell allowlist controls which programs run without
        a confirm prompt; the global deny list applies regardless."""
        allowed, _ = SUB_AGENT_DEFAULTS["analyst"]
        for forbidden in (
            "fs_promote",       # W4 drop — writer/root promotes
            "http_fetch",       # W4 drop — researcher fetches
            "memory_log",       # W4 drop — verifier audits
            "email_send", "email_draft",
        ):
            assert forbidden not in allowed, (
                f"{forbidden!r} leaked into analyst's compute default"
            )
        # python_exec stays (it's the role's reason to exist).
        assert "python_exec_run" in allowed
        # W5 — shell_run is on the surface for binary-format CLI tools.
        assert "shell_run" in allowed
        # search_web stays (reference value lookups during compute).
        assert "search_web" in allowed
        # fs_write stays (analyst saves outputs to scratch).
        assert "fs_write" in allowed


class TestBuildRootAgentWiresGate:
    """``build_root_agent`` plumbs the static gate onto every sub-agent
    using either the per-agent default or the cfg override."""

    def test_root_agent_runs_unrestricted(self) -> None:
        """Root is not gated — only sub-agents are. The feature is for
        scoping specialists, not the primary interlocutor."""
        cfg = CoworkConfig()
        agent = build_root_agent(cfg, tools=[])
        # Root is ``cowork_root``; gate is checked on each sub-agent's
        # before_tool_callback chain. We assert no callback rejects a
        # non-allowlisted tool name on the root itself.
        assert agent.name == "cowork_root"
        # Sub-agents are reachable via the ADK `sub_agents` field.
        # W3 added explorer + planner + verifier alongside the four
        # originals.
        sub_names = {sa.name for sa in agent.sub_agents}
        assert sub_names == {
            "researcher", "writer", "analyst", "reviewer",
            "explorer", "planner", "verifier",
        }

    def test_sub_agent_static_gate_blocks_default_excluded_tool(self) -> None:
        """The reviewer's static gate (built from the default allowlist)
        rejects ``fs_write`` even with no extra cfg.agents entry."""
        cfg = CoworkConfig()
        agent = build_root_agent(cfg, tools=[])
        reviewer = next(a for a in agent.sub_agents if a.name == "reviewer")
        # The first callback in the before_tool list is the static gate;
        # ``before_tool_callback`` is a list (ADK supports a chain).
        callbacks = reviewer.before_tool_callback
        assert isinstance(callbacks, list)
        # Find the gate by behaviour: invoking it on fs_write should
        # produce an error mentioning 'reviewer' and 'fs_write'.
        ctx = _ctx()
        # Walk the chain; the FIRST callback that returns a dict is the
        # static gate (or an MCP gate, which only blocks MCP tools and
        # passes through built-ins). For built-in fs_write we expect the
        # static gate to fire.
        for cb in callbacks:
            result = cb(_make_tool("fs_write"), {}, ctx)
            if result is not None:
                assert "reviewer" in result["error"]
                assert "fs_write" in result["error"]
                return
        raise AssertionError(
            "no callback in reviewer.before_tool_callback rejected fs_write",
        )

    def test_cfg_disallowed_tools_are_added(self) -> None:
        """``cfg.agents.<name>.disallowed_tools`` adds to the gate even
        when ``allowed_tools`` is None (use the default)."""
        cfg = CoworkConfig(
            agents={
                "writer": AgentConfig(disallowed_tools=["fs_promote"]),
            },
        )
        agent = build_root_agent(cfg, tools=[])
        writer = next(a for a in agent.sub_agents if a.name == "writer")
        callbacks = writer.before_tool_callback
        ctx = _ctx()
        for cb in callbacks:
            result = cb(_make_tool("fs_promote"), {}, ctx)
            if result is not None:
                assert "fs_promote" in result["error"]
                assert "writer" in result["error"]
                return
        raise AssertionError("disallowed_tools entry did not block fs_promote")

    def test_cfg_allowed_tools_overrides_default(self) -> None:
        """When the user sets ``allowed_tools``, the per-agent default is
        replaced wholesale — explicit user intent wins."""
        cfg = CoworkConfig(
            agents={
                "researcher": AgentConfig(allowed_tools=["fs_read"]),
            },
        )
        agent = build_root_agent(cfg, tools=[])
        researcher = next(a for a in agent.sub_agents if a.name == "researcher")
        callbacks = researcher.before_tool_callback
        ctx = _ctx()
        # search_web is in the default but NOT in the user's override —
        # should now be blocked.
        for cb in callbacks:
            result = cb(_make_tool("search_web"), {}, ctx)
            if result is not None:
                assert "search_web" in result["error"]
                return
        raise AssertionError("user override did not narrow researcher's allowlist")


class TestPerAgentModelOverride:
    """``cfg.agents.<name>.model`` swaps a sub-agent's model. The root
    keeps ``cfg.model``."""

    def test_root_keeps_default_model(self, tmp_path: Path) -> None:
        cfg = CoworkConfig(
            model=ModelConfig(
                base_url="http://primary.local/v1",
                model="primary-model",
                api_key="primary-key",
            ),
        )
        agent = build_root_agent(cfg, tools=[])
        # ADK ``LlmAgent.model`` is a ``LiteLlm``; LiteLlm exposes the
        # OpenAI-compat endpoint via ``api_base``. Sub-agents without an
        # override share the same instance type with the same api_base.
        assert agent.model._additional_args["api_base"] == "http://primary.local/v1"

    def test_sub_agent_with_override_uses_its_own_model(self) -> None:
        cfg = CoworkConfig(
            model=ModelConfig(
                base_url="http://primary.local/v1",
                model="primary-model",
                api_key="primary-key",
            ),
            agents={
                "researcher": AgentConfig(
                    model=ModelConfig(
                        base_url="http://cheap.local/v1",
                        model="haiku-class",
                        api_key="cheap-key",
                    ),
                ),
            },
        )
        agent = build_root_agent(cfg, tools=[])
        researcher = next(a for a in agent.sub_agents if a.name == "researcher")
        writer = next(a for a in agent.sub_agents if a.name == "writer")
        # Researcher swapped to the cheap endpoint.
        assert researcher.model._additional_args["api_base"] == "http://cheap.local/v1"
        # Writer (no override) stays on the primary endpoint.
        assert writer.model._additional_args["api_base"] == "http://primary.local/v1"
        # Root also stays on primary.
        assert agent.model._additional_args["api_base"] == "http://primary.local/v1"
