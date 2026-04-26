"""Tests for W2 — custom agent loader (``.cowork/agents/<name>.md``).

The loader mirrors Claude Code's ``.claude/agents/<name>.md`` pattern:
YAML frontmatter for name + description + tool gates + model override,
Markdown body for the system prompt. Two scopes: user
(``~/.config/cowork/agents/``) and workspace-global
(``<workspace>/global/agents/``); workspace shadows user.

Built-in sub-agent names (researcher/writer/analyst/reviewer) are
reserved at parse time so the routing surface stays predictable.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cowork_core.agents.custom import (
    CustomAgent,
    CustomAgentLoadError,
    CustomAgentRegistry,
    parse_agent_md,
)
from cowork_core.agents.root_agent import build_root_agent
from cowork_core.config import CoworkConfig


_GOOD_FRONTMATTER = """\
---
name: legal_reviewer
description: Reviews contracts for compliance issues.
allowed_tools: [fs_read, search_web]
disallowed_tools: [shell_run]
---

You are the Legal Reviewer.

Read carefully and report findings.
"""


def _make_tool(name: str) -> MagicMock:
    t = MagicMock()
    t.name = name
    return t


def _ctx() -> MagicMock:
    c = MagicMock()
    c.state = {}
    return c


class TestParseAgentMd:
    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "legal_reviewer.md"
        path.write_text(_GOOD_FRONTMATTER, encoding="utf-8")
        agent = parse_agent_md(path, source="user")
        assert agent.name == "legal_reviewer"
        assert agent.description == "Reviews contracts for compliance issues."
        assert agent.config.allowed_tools == ["fs_read", "search_web"]
        assert agent.config.disallowed_tools == ["shell_run"]
        assert agent.config.model is None
        assert agent.source == "user"
        # Body is everything after the closing fence, with surrounding
        # whitespace stripped.
        assert agent.instruction.startswith("You are the Legal Reviewer.")
        assert "Read carefully" in agent.instruction

    def test_model_override_parses_into_model_config(self, tmp_path: Path) -> None:
        path = tmp_path / "fast_explorer.md"
        path.write_text(
            "---\n"
            "name: fast_explorer\n"
            "description: Quick read-only search across the workspace.\n"
            "model:\n"
            "  base_url: http://cheap.local/v1\n"
            "  model: haiku-class\n"
            "  api_key: env:CHEAP_KEY\n"
            "---\n\n"
            "You are the Explorer. Find files fast.\n",
            encoding="utf-8",
        )
        agent = parse_agent_md(path, source="user")
        assert agent.config.model is not None
        assert agent.config.model.base_url == "http://cheap.local/v1"
        assert agent.config.model.model == "haiku-class"

    def test_missing_frontmatter_fence_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "x.md"
        path.write_text("Hello\nWorld\n", encoding="utf-8")
        with pytest.raises(CustomAgentLoadError, match="frontmatter"):
            parse_agent_md(path, source="user")

    def test_missing_closing_fence_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "x.md"
        path.write_text(
            "---\nname: thing\ndescription: foo\n",
            encoding="utf-8",
        )
        with pytest.raises(CustomAgentLoadError, match="closing"):
            parse_agent_md(path, source="user")

    def test_missing_name_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "x.md"
        path.write_text(
            "---\ndescription: foo\n---\n\nbody\n", encoding="utf-8",
        )
        with pytest.raises(CustomAgentLoadError, match="missing 'name'"):
            parse_agent_md(path, source="user")

    def test_missing_description_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "x.md"
        path.write_text(
            "---\nname: thing\n---\n\nbody\n", encoding="utf-8",
        )
        with pytest.raises(CustomAgentLoadError, match="missing 'description'"):
            parse_agent_md(path, source="user")

    def test_empty_body_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "x.md"
        path.write_text(
            "---\nname: thing\ndescription: a description\n---\n\n   \n",
            encoding="utf-8",
        )
        with pytest.raises(CustomAgentLoadError, match="empty instruction body"):
            parse_agent_md(path, source="user")

    @pytest.mark.parametrize("reserved", [
        "researcher", "writer", "analyst", "reviewer",
        "explorer", "planner", "verifier",
        "cowork_root",
    ])
    def test_reserved_name_rejected(self, tmp_path: Path, reserved: str) -> None:
        path = tmp_path / f"{reserved}.md"
        path.write_text(
            f"---\nname: {reserved}\ndescription: x\n---\n\nbody\n",
            encoding="utf-8",
        )
        with pytest.raises(CustomAgentLoadError, match="reserved"):
            parse_agent_md(path, source="user")

    def test_non_identifier_name_rejected(self, tmp_path: Path) -> None:
        """ADK's ``LlmAgent`` requires Python-identifier names. Reject
        hyphens / spaces / leading digits at parse time so the author
        gets a clear error pointed at their .md file."""
        path = tmp_path / "x.md"
        path.write_text(
            "---\nname: legal-reviewer\ndescription: x\n---\n\nbody\n",
            encoding="utf-8",
        )
        with pytest.raises(CustomAgentLoadError, match="identifier"):
            parse_agent_md(path, source="user")

    def test_control_char_in_description_rejected(self, tmp_path: Path) -> None:
        """Mirror the skill loader's defence: a description with a
        control character could embed injected directives in the root
        prompt's sub-agent catalog. Reject at parse time."""
        path = tmp_path / "x.md"
        # YAML double-quoted string allows \x07; we write the byte
        # directly to be sure it survives the parse.
        path.write_text(
            "---\nname: thing\ndescription: \"hi\\x07nasty\"\n---\n\nbody\n",
            encoding="utf-8",
        )
        with pytest.raises(CustomAgentLoadError, match="control"):
            parse_agent_md(path, source="user")

    def test_allowed_tools_must_be_list_of_strings(self, tmp_path: Path) -> None:
        path = tmp_path / "x.md"
        path.write_text(
            "---\nname: thing\ndescription: x\nallowed_tools: 42\n---\n\nbody\n",
            encoding="utf-8",
        )
        with pytest.raises(CustomAgentLoadError, match="allowed_tools"):
            parse_agent_md(path, source="user")

    def test_invalid_model_block_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "x.md"
        path.write_text(
            "---\nname: thing\ndescription: x\nmodel: not-a-mapping\n---\n\nbody\n",
            encoding="utf-8",
        )
        with pytest.raises(CustomAgentLoadError, match="model"):
            parse_agent_md(path, source="user")


class TestCustomAgentRegistry:
    def test_scan_picks_up_md_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.md").write_text(
            "---\nname: a\ndescription: aa\n---\n\nbody a\n",
            encoding="utf-8",
        )
        (tmp_path / "b.md").write_text(
            "---\nname: b\ndescription: bb\n---\n\nbody b\n",
            encoding="utf-8",
        )
        # Non-md files are ignored.
        (tmp_path / "skip.txt").write_text("not an agent", encoding="utf-8")

        reg = CustomAgentRegistry()
        added = reg.scan(tmp_path, source="user")
        assert added == 2
        names = {a.name for a in reg}
        assert names == {"a", "b"}

    def test_missing_root_returns_zero(self, tmp_path: Path) -> None:
        reg = CustomAgentRegistry()
        assert reg.scan(tmp_path / "nope", source="user") == 0
        assert len(reg) == 0

    def test_workspace_scope_shadows_user_scope(self, tmp_path: Path) -> None:
        """Layered scan: a workspace-global agent with the same name as
        a user-scoped one wins (later scan replaces earlier)."""
        user_dir = tmp_path / "user"
        ws_dir = tmp_path / "workspace"
        user_dir.mkdir()
        ws_dir.mkdir()
        (user_dir / "house_style.md").write_text(
            "---\nname: house_style\ndescription: USER VERSION\n---\n\nuser body\n",
            encoding="utf-8",
        )
        (ws_dir / "house_style.md").write_text(
            "---\nname: house_style\ndescription: WORKSPACE VERSION\n---\n\nws body\n",
            encoding="utf-8",
        )
        reg = CustomAgentRegistry()
        reg.scan(user_dir, source="user")
        reg.scan(ws_dir, source="global")
        agent = reg.get("house_style")
        assert agent is not None
        assert agent.description == "WORKSPACE VERSION"
        assert agent.source == "global"


class TestBuildRootAgentWithCustomAgents:
    """Custom agents land in ``sub_agents`` alongside the four built-ins,
    each with the W1 static gate + permission + audit + allowlist chain."""

    def test_no_registry_means_only_builtins(self) -> None:
        cfg = CoworkConfig()
        agent = build_root_agent(cfg, tools=[])
        sub_names = {sa.name for sa in agent.sub_agents}
        # The seven built-ins (W1's four originals + W3's three new).
        assert sub_names == {
            "researcher", "writer", "analyst", "reviewer",
            "explorer", "planner", "verifier",
        }

    def test_custom_agent_appears_alongside_builtins(self, tmp_path: Path) -> None:
        (tmp_path / "legal.md").write_text(_GOOD_FRONTMATTER, encoding="utf-8")
        reg = CustomAgentRegistry()
        reg.scan(tmp_path, source="user")
        cfg = CoworkConfig()
        agent = build_root_agent(cfg, tools=[], custom_agents=reg)
        sub_names = {sa.name for sa in agent.sub_agents}
        assert "legal_reviewer" in sub_names
        # All four builtins still there.
        assert {"researcher", "writer", "analyst", "reviewer"} <= sub_names

    def test_custom_agent_static_gate_uses_frontmatter_allowlist(
        self, tmp_path: Path,
    ) -> None:
        """The frontmatter's ``allowed_tools`` must end up in the static
        gate, blocking everything else for that agent."""
        (tmp_path / "legal.md").write_text(_GOOD_FRONTMATTER, encoding="utf-8")
        reg = CustomAgentRegistry()
        reg.scan(tmp_path, source="user")
        agent = build_root_agent(CoworkConfig(), tools=[], custom_agents=reg)
        legal = next(a for a in agent.sub_agents if a.name == "legal_reviewer")
        callbacks = legal.before_tool_callback
        assert isinstance(callbacks, list)
        # Allowed tools pass.
        ctx = _ctx()
        # Walk the chain — at least one callback should reject fs_write
        # (it's not in the agent's allowlist).
        rejected = False
        for cb in callbacks:
            result = cb(_make_tool("fs_write"), {}, ctx)
            if result is not None:
                assert "legal_reviewer" in result["error"]
                rejected = True
                break
        assert rejected, "static gate did not block fs_write for legal_reviewer"

        # Tool that IS in the disallowed list → blocked.
        rejected = False
        for cb in callbacks:
            result = cb(_make_tool("shell_run"), {}, _ctx())
            if result is not None:
                assert "legal_reviewer" in result["error"]
                rejected = True
                break
        assert rejected, "static gate did not block shell_run for legal_reviewer"

    def test_custom_agent_with_model_override(self, tmp_path: Path) -> None:
        (tmp_path / "fast.md").write_text(
            "---\n"
            "name: fast_explorer\n"
            "description: Cheap read-only specialist.\n"
            "model:\n"
            "  base_url: http://cheap.local/v1\n"
            "  model: haiku-class\n"
            "  api_key: env:CHEAP_KEY\n"
            "---\n\n"
            "You are the explorer.\n",
            encoding="utf-8",
        )
        reg = CustomAgentRegistry()
        reg.scan(tmp_path, source="user")
        cfg = CoworkConfig()
        agent = build_root_agent(cfg, tools=[], custom_agents=reg)
        fast = next(a for a in agent.sub_agents if a.name == "fast_explorer")
        assert (
            fast.model._additional_args["api_base"] == "http://cheap.local/v1"
        )
        # Root keeps its default endpoint.
        assert (
            agent.model._additional_args["api_base"]
            != "http://cheap.local/v1"
        )

    def test_custom_agent_description_appears_on_llm_agent(
        self, tmp_path: Path,
    ) -> None:
        """ADK's ``LlmAgent.description`` is what the parent uses for
        routing decisions; make sure the frontmatter description ends
        up there (truncated if necessary)."""
        (tmp_path / "legal.md").write_text(_GOOD_FRONTMATTER, encoding="utf-8")
        reg = CustomAgentRegistry()
        reg.scan(tmp_path, source="user")
        agent = build_root_agent(CoworkConfig(), tools=[], custom_agents=reg)
        legal = next(a for a in agent.sub_agents if a.name == "legal_reviewer")
        assert "Reviews contracts" in legal.description


class TestBuildRuntimeLoadsCustomAgents:
    """``build_runtime`` scans ~/.config/cowork/agents/ and
    <workspace>/global/agents/, populates ``runtime.custom_agents``,
    and threads them through ``build_root_agent``."""

    def test_runtime_picks_up_workspace_global_agents(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from cowork_core import build_runtime
        from cowork_core.config import CoworkConfig, ModelConfig
        from cowork_core import runner as runner_mod

        # Redirect XDG-style user agent dir to a temp path so the test
        # doesn't depend on the developer's ~/.config/cowork/.
        monkeypatch.setattr(
            runner_mod,
            "_user_agents_dir",
            lambda: tmp_path / "user_home_agents",
        )

        # Drop a .md under <workspace>/global/agents/.
        ws_root = tmp_path / "ws"
        ws_global_agents = ws_root / "global" / "agents"
        ws_global_agents.mkdir(parents=True)
        (ws_global_agents / "house_style.md").write_text(
            "---\nname: house_style\ndescription: House style guard.\n"
            "allowed_tools: [fs_read]\n---\n\nYou are the house style guard.\n",
            encoding="utf-8",
        )
        cfg = CoworkConfig(
            model=ModelConfig(
                base_url="http://x/v1",
                model="m",
                api_key="k",
            ),
        )
        cfg.workspace.root = ws_root
        runtime = build_runtime(cfg)
        names = {ca.name for ca in runtime.custom_agents}
        assert "house_style" in names
        # And it actually lives on the agent tree.
        sub_names = {sa.name for sa in runtime.runner.agent.sub_agents}
        assert "house_style" in sub_names
