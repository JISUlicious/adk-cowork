"""Tests for the @-mention / auto-route prompt machinery (Tier E.E2).

The routing protocol itself is prompt-level — the instruction paragraph
tells the root agent to transfer on a leading ``@<agent_name>``. These
tests pin down the composition (paragraph present vs. absent based on
the ``cowork.auto_route`` flag) and the runtime state round-trip. We
don't assert model behaviour against a live LLM; that's manual QA per
the plan's "non-deterministic @-mentions" risk line.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cowork_core.agents.root_agent import (
    AT_MENTION_PROTOCOL,
    _compose_instruction,
)


class TestInstructionComposition:
    def test_auto_route_on_includes_protocol(self) -> None:
        prompt = _compose_instruction(
            working_context="Working here.",
            skills_snippet="",
            policy_mode="work",
            auto_route=True,
        )
        # Pick a specific sentence from the protocol so we don't trip
        # on copy changes elsewhere.
        assert "User-directed routing:" in prompt
        assert "@<agent_name>" in prompt
        # A spot-check of the actual protocol body makes the test fail
        # loudly if someone accidentally shortens the paragraph.
        assert AT_MENTION_PROTOCOL.strip().splitlines()[0] in prompt

    def test_auto_route_off_omits_protocol(self) -> None:
        prompt = _compose_instruction(
            working_context="Working here.",
            skills_snippet="",
            policy_mode="work",
            auto_route=False,
        )
        assert "User-directed routing:" not in prompt
        assert "@<agent_name>" not in prompt
        # The rest of the system prompt still composes normally.
        assert "Sub-agent delegation" in prompt

    def test_plan_mode_still_gets_addendum_with_protocol(self) -> None:
        """Regression guard: plan-mode addendum is appended after the
        protocol paragraph, not folded into it. Both should be present."""
        prompt = _compose_instruction(
            working_context="Working here.",
            skills_snippet="",
            policy_mode="plan",
            auto_route=True,
        )
        assert "User-directed routing:" in prompt
        assert "PLAN MODE" in prompt

    def test_auto_route_defaults_to_on(self) -> None:
        """``_compose_instruction`` default parameter, used for fresh
        sessions before state is populated."""
        prompt = _compose_instruction(
            working_context="Working here.",
            skills_snippet="",
            policy_mode="work",
        )
        assert "User-directed routing:" in prompt


@pytest.mark.asyncio
class TestRuntimeAutoRoute:
    async def test_runtime_round_trip(self, tmp_path: Path) -> None:
        """Runtime setter writes a state_delta event; getter reads it
        back. Fresh sessions default to ``True``."""
        from cowork_core import CoworkConfig
        from cowork_core.config import WorkspaceConfig
        from cowork_core.runner import build_runtime

        cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
        runtime = build_runtime(cfg)
        _, _, sid = await runtime.open_session(project_name="TestAutoRouteProj")

        # Fresh session inherits the default ``True``.
        assert await runtime.get_session_auto_route(sid) is True

        # Flip off, verify persists.
        await runtime.set_session_auto_route(sid, False)
        assert await runtime.get_session_auto_route(sid) is False

        # Flip back on.
        await runtime.set_session_auto_route(sid, True)
        assert await runtime.get_session_auto_route(sid) is True

        # Non-bool payloads are rejected before the state_delta write.
        with pytest.raises(ValueError):
            await runtime.set_session_auto_route(sid, "yes")  # type: ignore[arg-type]

    async def test_missing_session_raises(self, tmp_path: Path) -> None:
        from cowork_core import CoworkConfig
        from cowork_core.config import WorkspaceConfig
        from cowork_core.runner import build_runtime

        cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
        runtime = build_runtime(cfg)

        with pytest.raises(ValueError):
            await runtime.get_session_auto_route("no-such-session")
        with pytest.raises(ValueError):
            await runtime.set_session_auto_route("no-such-session", True)
