"""Tests for W5 — per-agent shell allowlist gate.

The gate is mounted in each sub-agent's ``before_tool_callback`` chain
and intercepts ``shell_run`` calls. Other tools pass through. For
``shell_run``:

1. Hardcoded global deny → ``{"error": ...}`` (no override possible).
2. ``argv[0]`` basename in the per-agent allowlist → pass through.
3. Otherwise, try to consume an approval token. If consumed → pass.
4. Else return ``confirmation_required`` so the UI can prompt.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from cowork_core.agents.analyst import (
    ANALYST_DEFAULT_ALLOWED_TOOLS,
    ANALYST_DEFAULT_SHELL_ALLOWLIST,
)
from cowork_core.agents.root_agent import (
    SUB_AGENT_SHELL_ALLOWLISTS,
    build_root_agent,
)
from cowork_core.agents.verifier import VERIFIER_DEFAULT_SHELL_ALLOWLIST
from cowork_core.approvals import InMemoryApprovalStore
from cowork_core.config import AgentConfig, CoworkConfig
from cowork_core.policy.permissions import make_shell_allowlist_gate
from cowork_core.tools.base import COWORK_CONTEXT_KEY


def _make_tool(name: str) -> MagicMock:
    t = MagicMock()
    t.name = name
    return t


def _ctx_with_approvals(session_id: str = "sess-1") -> tuple[MagicMock, object]:
    """Return (tool_context, approval_store) so tests can grant tokens."""
    store = InMemoryApprovalStore()
    cowork_ctx = MagicMock()
    cowork_ctx.session.id = session_id
    cowork_ctx.approvals = store
    ctx = MagicMock()
    ctx.state = {COWORK_CONTEXT_KEY: cowork_ctx}
    return ctx, store


class TestShellGateBasics:
    def test_other_tools_pass_through(self) -> None:
        """The gate only inspects shell_run; fs_read etc. fall through
        without comment."""
        gate = make_shell_allowlist_gate("analyst", ("pandoc",))
        ctx, _ = _ctx_with_approvals()
        result = gate(_make_tool("fs_read"), {"path": "x"}, ctx)
        assert result is None

    def test_allowlisted_program_passes(self) -> None:
        gate = make_shell_allowlist_gate("analyst", ("pandoc", "git"))
        ctx, _ = _ctx_with_approvals()
        result = gate(
            _make_tool("shell_run"),
            {"argv": ["pandoc", "-o", "out.pdf", "in.md"]},
            ctx,
        )
        assert result is None

    def test_absolute_path_program_normalised_to_basename(self) -> None:
        """``/usr/local/bin/pandoc`` is the same as ``pandoc`` from the
        gate's perspective so the allowlist isn't bypassed by an
        absolute path."""
        gate = make_shell_allowlist_gate("analyst", ("pandoc",))
        ctx, _ = _ctx_with_approvals()
        result = gate(
            _make_tool("shell_run"),
            {"argv": ["/usr/local/bin/pandoc", "-v"]},
            ctx,
        )
        assert result is None

    def test_non_allowlisted_returns_confirmation(self) -> None:
        gate = make_shell_allowlist_gate("analyst", ("pandoc",))
        ctx, _ = _ctx_with_approvals()
        result = gate(
            _make_tool("shell_run"),
            {"argv": ["wkhtmltopdf", "in.html", "out.pdf"]},
            ctx,
        )
        assert result is not None
        assert result.get("confirmation_required") is True
        assert result.get("tool") == "shell_run"
        assert result.get("agent") == "analyst"

    def test_description_surfaces_in_summary(self) -> None:
        """Agent-supplied description shows in the confirm prompt
        instead of raw argv when present."""
        gate = make_shell_allowlist_gate("analyst", ())
        ctx, _ = _ctx_with_approvals()
        result = gate(
            _make_tool("shell_run"),
            {
                "argv": ["wkhtmltopdf", "in.html", "out.pdf"],
                "description": "Convert HTML to PDF",
            },
            ctx,
        )
        assert result is not None
        assert "Convert HTML to PDF" in result["summary"]


class TestShellGateApproval:
    """Approval tokens granted via the UI's ``POST .../approvals``
    endpoint can release one shell_run call past the gate."""

    def test_approval_token_passes_through(self) -> None:
        gate = make_shell_allowlist_gate("analyst", ("pandoc",))
        ctx, store = _ctx_with_approvals(session_id="sess-1")
        # Grant one approval for shell_run on this session.
        store.grant("sess-1", "shell_run")
        # Non-allowlisted call now passes (token consumed).
        result = gate(
            _make_tool("shell_run"),
            {"argv": ["wkhtmltopdf", "in.html", "out.pdf"]},
            ctx,
        )
        assert result is None
        # Token was consumed — next call needs a fresh approval.
        result_again = gate(
            _make_tool("shell_run"),
            {"argv": ["wkhtmltopdf", "in.html", "out.pdf"]},
            ctx,
        )
        assert result_again is not None
        assert result_again.get("confirmation_required") is True


class TestShellGateDeny:
    """Global deny rules win over allowlist + approval."""

    def test_deny_blocks_even_when_allowlisted(self) -> None:
        # sudo isn't in the allowlist anyway, but pretend it was —
        # the deny check fires first.
        gate = make_shell_allowlist_gate("analyst", ("sudo",))
        ctx, _ = _ctx_with_approvals()
        result = gate(
            _make_tool("shell_run"),
            {"argv": ["sudo", "ls"]},
            ctx,
        )
        assert result is not None
        assert "error" in result
        assert "deny" in result["error"].lower()

    def test_deny_blocks_even_with_approval_token(self) -> None:
        """User approval doesn't override the global deny — that's the
        whole point of having a deny list at all."""
        gate = make_shell_allowlist_gate("analyst", ())
        ctx, store = _ctx_with_approvals()
        store.grant("sess-1", "shell_run")
        result = gate(
            _make_tool("shell_run"),
            {"argv": ["mkfs.ext4", "/dev/sda1"]},
            ctx,
        )
        assert result is not None
        assert "error" in result
        # Token should NOT have been consumed (deny rules short-circuit
        # before approval consumption).
        assert store.consume("sess-1", "shell_run") is True


class TestShellAllowlistDefaults:
    """Built-in defaults match the documented W5 design."""

    def test_analyst_default_includes_binary_doc_tools(self) -> None:
        for tool in ("pandoc", "wkhtmltopdf", "ffmpeg", "libreoffice"):
            assert tool in ANALYST_DEFAULT_SHELL_ALLOWLIST

    def test_verifier_default_is_read_only(self) -> None:
        for tool in ("git", "ls", "cat", "head", "diff"):
            assert tool in VERIFIER_DEFAULT_SHELL_ALLOWLIST
        # No write/mutation tools in the default.
        for forbidden in ("rm", "mv", "cp", "tee", "mkdir"):
            assert forbidden not in VERIFIER_DEFAULT_SHELL_ALLOWLIST

    def test_only_analyst_and_verifier_have_built_in_allowlists(self) -> None:
        """W5 — only the two agents that actually have shell_run on
        their surface get a built-in allowlist; others fall back to
        ``cfg.policy.shell_allowlist``."""
        assert set(SUB_AGENT_SHELL_ALLOWLISTS.keys()) == {
            "analyst", "verifier",
        }


class TestBuildRootAgentWiresShellGate:
    """``build_root_agent`` plumbs the shell gate onto each sub-agent
    using either the cfg override, the per-agent default, or
    ``cfg.policy.shell_allowlist`` as fallback."""

    def test_analyst_gate_passes_pandoc(self) -> None:
        agent = build_root_agent(CoworkConfig(), tools=[])
        analyst = next(a for a in agent.sub_agents if a.name == "analyst")
        ctx, _ = _ctx_with_approvals()
        # Walk the chain — pandoc is in analyst's default allowlist so
        # SOME callback might still reject (allowlist callback doesn't
        # populate session state) but the shell gate specifically must
        # pass it. Find the shell gate by behaviour.
        callbacks = analyst.before_tool_callback
        assert isinstance(callbacks, list)
        # Any callback rejecting pandoc means we have a wiring bug.
        for cb in callbacks:
            result = cb(
                _make_tool("shell_run"),
                {"argv": ["pandoc", "-o", "out.pdf", "in.md"]},
                ctx,
            )
            if result is not None and "confirmation_required" in result:
                raise AssertionError(
                    "shell gate prompted for pandoc despite it being "
                    "on analyst's default shell allowlist",
                )

    def test_analyst_gate_prompts_for_unknown_program(self) -> None:
        agent = build_root_agent(CoworkConfig(), tools=[])
        analyst = next(a for a in agent.sub_agents if a.name == "analyst")
        ctx, _ = _ctx_with_approvals()
        callbacks = analyst.before_tool_callback
        prompted = False
        for cb in callbacks:
            result = cb(
                _make_tool("shell_run"),
                {"argv": ["wkhtmltopdf-experimental", "x.html"]},
                ctx,
            )
            if result is not None and result.get("confirmation_required"):
                assert result.get("agent") == "analyst"
                prompted = True
                break
        assert prompted, "shell gate did not prompt for unknown program"

    def test_cfg_shell_allowlist_overrides_default(self) -> None:
        """``cfg.agents.<name>.shell_allowlist`` replaces the per-agent
        default wholesale — explicit user config wins."""
        cfg = CoworkConfig(
            agents={
                "analyst": AgentConfig(
                    shell_allowlist=["only-this-program"],
                ),
            },
        )
        agent = build_root_agent(cfg, tools=[])
        analyst = next(a for a in agent.sub_agents if a.name == "analyst")
        ctx, _ = _ctx_with_approvals()
        # pandoc was in the default but is no longer allowed.
        callbacks = analyst.before_tool_callback
        prompted = False
        for cb in callbacks:
            result = cb(
                _make_tool("shell_run"),
                {"argv": ["pandoc", "-v"]},
                ctx,
            )
            if result is not None and result.get("confirmation_required"):
                prompted = True
                break
        assert prompted, "user override did not narrow analyst's shell allowlist"
