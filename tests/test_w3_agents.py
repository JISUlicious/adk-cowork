"""Tests for W3 — Explorer + Planner + Verifier built-in agents.

Three new sub-agents on top of W1+W2's primitives:

- ``explorer`` — strict read-only navigator (fast, cheap-model
  candidate). No mutation, no python_exec, no http_fetch.
- ``planner`` — read-only planner that writes ONLY to
  ``scratch/plan.md`` (the policy callback enforces the path; the
  static gate just permits ``fs_write`` in the allowlist).
- ``verifier`` — adversarial correctness checker. Read-only for the
  project; ``python_exec_run`` allowed so probes can actually open
  files / recompute formulas / validate schemas.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from cowork_core.agents.explorer import (
    EXPLORER_DEFAULT_ALLOWED_TOOLS,
    EXPLORER_INSTRUCTION,
)
from cowork_core.agents.planner import (
    PLANNER_DEFAULT_ALLOWED_TOOLS,
    PLANNER_INSTRUCTION,
)
from cowork_core.agents.root_agent import build_root_agent
from cowork_core.agents.verifier import (
    VERIFIER_DEFAULT_ALLOWED_TOOLS,
    VERIFIER_INSTRUCTION,
)
from cowork_core.config import CoworkConfig


def _make_tool(name: str) -> MagicMock:
    t = MagicMock()
    t.name = name
    return t


def _ctx() -> MagicMock:
    c = MagicMock()
    c.state = {}
    return c


def _gate_blocks(agent: object, tool_name: str, agent_name: str) -> bool:
    """Walk the sub-agent's before_tool_callback chain, return True iff
    any callback blocks ``tool_name`` with an error mentioning
    ``agent_name``."""
    callbacks = agent.before_tool_callback  # type: ignore[attr-defined]
    if not isinstance(callbacks, list):
        callbacks = [callbacks]
    for cb in callbacks:
        result = cb(_make_tool(tool_name), {}, _ctx())
        if result is not None and "error" in result:
            assert agent_name in result["error"]
            return True
    return False


class TestExplorerSurface:
    """Explorer is the strictest read-only specialist."""

    def test_default_excludes_mutation_and_execution(self) -> None:
        for forbidden in (
            "fs_write", "fs_edit", "fs_promote",
            "shell_run", "python_exec_run",
            "http_fetch",  # search_web is enough; no arbitrary fetches
            "email_send", "email_draft",
        ):
            assert forbidden not in EXPLORER_DEFAULT_ALLOWED_TOOLS, (
                f"{forbidden!r} leaked into explorer's read-only default"
            )

    def test_default_includes_navigation_tools(self) -> None:
        for needed in ("fs_read", "fs_glob", "fs_list", "fs_stat", "search_web"):
            assert needed in EXPLORER_DEFAULT_ALLOWED_TOOLS

    def test_explorer_instruction_says_read_only(self) -> None:
        assert "read-only" in EXPLORER_INSTRUCTION.lower()

    def test_static_gate_blocks_writes_for_explorer(self) -> None:
        agent = build_root_agent(CoworkConfig(), tools=[])
        explorer = next(a for a in agent.sub_agents if a.name == "explorer")
        for forbidden in ("fs_write", "shell_run", "python_exec_run"):
            assert _gate_blocks(explorer, forbidden, "explorer"), (
                f"explorer's static gate did not block {forbidden!r}"
            )


class TestPlannerSurface:
    """Planner is read-only EXCEPT it can fs_write — the policy
    callback restricts fs_write to ``scratch/plan.md``. The static
    gate permits the tool name; path enforcement is plan-mode's job."""

    def test_default_includes_fs_write_for_plan_md(self) -> None:
        # Plan mode allows fs_write only to scratch/plan.md (enforced
        # in the permission callback). The static gate permits the
        # tool name; otherwise the planner literally couldn't save the
        # plan.
        assert "fs_write" in PLANNER_DEFAULT_ALLOWED_TOOLS

    def test_default_excludes_arbitrary_execution(self) -> None:
        for forbidden in (
            "fs_edit", "fs_promote",
            "shell_run", "python_exec_run",
            "email_send", "email_draft",
        ):
            assert forbidden not in PLANNER_DEFAULT_ALLOWED_TOOLS

    def test_planner_instruction_directs_to_scratch_plan_md(self) -> None:
        assert "scratch/plan.md" in PLANNER_INSTRUCTION

    def test_static_gate_blocks_arbitrary_execution_for_planner(self) -> None:
        agent = build_root_agent(CoworkConfig(), tools=[])
        planner = next(a for a in agent.sub_agents if a.name == "planner")
        for forbidden in ("shell_run", "python_exec_run", "fs_edit"):
            assert _gate_blocks(planner, forbidden, "planner"), (
                f"planner's static gate did not block {forbidden!r}"
            )


class TestVerifierSurface:
    """Verifier needs python_exec to actually run probes (open .docx,
    recompute formulas, validate schemas). Read-only for project files
    via the static gate; python_exec snippet sandboxing keeps it from
    writing back to scratch/files namespaces."""

    def test_default_includes_python_exec(self) -> None:
        assert "python_exec_run" in VERIFIER_DEFAULT_ALLOWED_TOOLS

    def test_default_excludes_mutation_and_email(self) -> None:
        # W5 note: shell_run IS in verifier's surface (read-only probes
        # like git status / cat / diff) — the per-agent shell allowlist
        # restricts it; mutation tools below are still excluded.
        for forbidden in (
            "fs_write", "fs_edit", "fs_promote",
            "email_send", "email_draft",
        ):
            assert forbidden not in VERIFIER_DEFAULT_ALLOWED_TOOLS, (
                f"{forbidden!r} leaked into verifier's default"
            )

    def test_verifier_instruction_emphasises_break_first(self) -> None:
        # The instruction must steer the model toward adversarial
        # correctness — distinct from the reviewer's style/tone focus.
        text = VERIFIER_INSTRUCTION.lower()
        assert "break" in text or "adversarial" in text
        assert "verdict" in text  # PASS/FAIL/PARTIAL contract
        assert "pass" in text and "fail" in text

    def test_static_gate_blocks_writes_for_verifier(self) -> None:
        # W5 note: shell_run is on verifier's surface (read-only probes);
        # the static gate doesn't block it. The shell allowlist gate
        # below it restricts which programs run without confirm.
        agent = build_root_agent(CoworkConfig(), tools=[])
        verifier = next(a for a in agent.sub_agents if a.name == "verifier")
        for forbidden in ("fs_write", "fs_edit", "email_send"):
            assert _gate_blocks(verifier, forbidden, "verifier"), (
                f"verifier's static gate did not block {forbidden!r}"
            )

    def test_verifier_can_call_python_exec_via_static_gate(self) -> None:
        """Distinct from the reviewer (which has no python_exec): the
        verifier's static gate must NOT block python_exec_run, or it
        loses its whole reason for existing."""
        agent = build_root_agent(CoworkConfig(), tools=[])
        verifier = next(a for a in agent.sub_agents if a.name == "verifier")
        # The gate is the FIRST callback; it should pass python_exec_run.
        callbacks = verifier.before_tool_callback
        first = callbacks[0] if isinstance(callbacks, list) else callbacks
        # The static gate returns None when the tool is in the allowlist
        # AND not in the denylist.
        result = first(_make_tool("python_exec_run"), {}, _ctx())
        assert result is None, (
            f"verifier's static gate (first callback) blocked "
            f"python_exec_run: {result!r}"
        )
