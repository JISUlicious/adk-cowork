"""Tests for model callbacks + dynamic root-agent instruction."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from cowork_core.agents.root_agent import _compose_instruction
from cowork_core.callbacks.model import (
    DEFAULT_MAX_TURNS,
    make_model_callbacks,
)
from cowork_core.tools.base import COWORK_CONTEXT_KEY, COWORK_POLICY_MODE_KEY


# ───────────────────────── dynamic instruction ──────────────────────────


def test_compose_instruction_header_working_tail() -> None:
    out = _compose_instruction(
        working_context="Working context:\n- test paragraph",
        skills_snippet="",
        policy_mode="work",
    )
    assert "You are Cowork" in out
    assert "test paragraph" in out
    assert "Tool use:" in out
    assert "PLAN MODE" not in out


def test_compose_instruction_adds_plan_addendum() -> None:
    out = _compose_instruction(
        working_context="Working context:\n- test",
        skills_snippet="",
        policy_mode="plan",
    )
    assert "PLAN MODE — ACTIVE" in out


def test_compose_instruction_injects_skills() -> None:
    out = _compose_instruction(
        working_context="Working context:\n- test",
        skills_snippet="Available skills:\n- foo: bar",
        policy_mode="auto",
    )
    assert "Available skills:" in out
    assert "- foo: bar" in out


def test_dynamic_instruction_uses_env_description() -> None:
    """The per-turn instruction must come from the session's ExecEnv, not the
    hard-coded scratch/+files/ fallback."""
    from cowork_core import CoworkConfig
    from cowork_core.agents.root_agent import build_root_agent

    cfg = CoworkConfig()
    root = build_root_agent(cfg, tools=[], skills_snippet="")

    ctx = MagicMock()
    # Session state with a fake CoworkToolContext whose env returns custom text.
    fake_env = MagicMock()
    fake_env.describe_for_prompt.return_value = "Working context: CUSTOM ENV X"
    fake_cowork_ctx = MagicMock()
    fake_cowork_ctx.env = fake_env
    ctx.state = {
        COWORK_CONTEXT_KEY: fake_cowork_ctx,
        COWORK_POLICY_MODE_KEY: "work",
    }

    prompt = root.instruction(ctx)
    assert "CUSTOM ENV X" in prompt
    # Fallback should NOT appear when a live env exists.
    assert "draft directory" not in prompt


def test_dynamic_instruction_falls_back_without_env() -> None:
    """Before a CoworkToolContext is injected (e.g. during static import), the
    root instruction must still render a sensible default."""
    from cowork_core import CoworkConfig
    from cowork_core.agents.root_agent import build_root_agent

    cfg = CoworkConfig()
    root = build_root_agent(cfg, tools=[], skills_snippet="")

    ctx = MagicMock()
    ctx.state = {}  # no CoworkToolContext stashed yet
    prompt = root.instruction(ctx)
    assert "scratch/" in prompt  # fallback text
    assert "files/" in prompt


def test_sub_agents_receive_local_dir_working_context() -> None:
    """Desktop (local-dir) sessions must push the workdir description down to
    every sub-agent's prompt, not just the root. Otherwise delegating to
    ``writer`` would tell it to fs_write into ``scratch/`` — a namespace
    that does not exist in local-dir mode."""
    from cowork_core import CoworkConfig
    from cowork_core.agents.root_agent import build_root_agent

    cfg = CoworkConfig()
    root = build_root_agent(cfg, tools=[], skills_snippet="")
    assert root.sub_agents, "root has no sub-agents"

    ctx = MagicMock()
    fake_env = MagicMock()
    fake_env.describe_for_prompt.return_value = (
        "Working context:\n- You are working in `/tmp/desktop-folder`."
    )
    fake_cowork_ctx = MagicMock()
    fake_cowork_ctx.env = fake_env
    ctx.state = {
        COWORK_CONTEXT_KEY: fake_cowork_ctx,
        COWORK_POLICY_MODE_KEY: "work",
    }

    for sub in root.sub_agents:
        assert callable(sub.instruction), (
            f"sub-agent {sub.name!r} instruction must be a callable for "
            f"env-aware rendering"
        )
        rendered = sub.instruction(ctx)
        assert "/tmp/desktop-folder" in rendered, (
            f"sub-agent {sub.name!r} prompt missing env description"
        )


def test_sub_agents_fall_back_to_managed_working_context() -> None:
    """When no env is injected the sub-agents should still render managed
    (scratch/+files/) vocabulary, same as the root."""
    from cowork_core import CoworkConfig
    from cowork_core.agents.root_agent import build_root_agent

    root = build_root_agent(CoworkConfig(), tools=[], skills_snippet="")
    ctx = MagicMock()
    ctx.state = {}

    for sub in root.sub_agents:
        rendered = sub.instruction(ctx)
        assert "scratch/" in rendered, (
            f"sub-agent {sub.name!r} managed fallback missing scratch/"
        )


# ───────────────────────── model callbacks ──────────────────────────────


def test_turn_counter_increments_and_bails(tmp_path: Path) -> None:
    from google.adk.models.llm_request import LlmRequest

    before, _after = make_model_callbacks(max_turns=3)
    ctx = MagicMock()
    ctx.state = {}
    req = LlmRequest()

    # First three calls: all return None (model runs).
    for _ in range(3):
        r = before(ctx, req)
        assert r is None
    # Fourth call: budget exceeded, returns a synthesized response.
    r = before(ctx, req)
    assert r is not None
    text_parts = [p.text for p in r.content.parts if p.text]
    assert any("budget exceeded" in t.lower() for t in text_parts)


def test_after_model_appends_transcript_line(tmp_path: Path) -> None:
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    transcript = tmp_path / "transcript.jsonl"

    # Build a fake CoworkToolContext with the transcript path.
    session = MagicMock()
    session.transcript_path = transcript
    cowork_ctx = MagicMock()
    cowork_ctx.session = session

    _before, after = make_model_callbacks()
    ctx = MagicMock()
    ctx.state = {COWORK_CONTEXT_KEY: cowork_ctx}

    response = LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text="ok")])
    )
    after(ctx, response)

    lines = transcript.read_text().splitlines()
    assert len(lines) == 1
    assert '"event": "model_call"' in lines[0]


def test_default_max_turns_is_conservative() -> None:
    # A sanity check: should not ship with a huge default that defeats the guard.
    assert DEFAULT_MAX_TURNS <= 100
