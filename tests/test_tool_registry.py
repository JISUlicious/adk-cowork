"""Tests for the tool registry and cowork tool context (M1.2)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cowork_core.config import CoworkConfig
from cowork_core.skills import SkillRegistry
from cowork_core.tools import (
    COWORK_CONTEXT_KEY,
    CoworkToolContext,
    ToolRegistry,
    get_cowork_context,
)
from cowork_core.workspace import ProjectRegistry, Workspace
from google.adk.tools.function_tool import FunctionTool


def _echo(text: str) -> str:
    """Echoes back the text."""
    return text


def _shout(text: str) -> str:
    """Uppercases the text."""
    return text.upper()


def test_registry_register_and_lookup() -> None:
    reg = ToolRegistry()
    tool = FunctionTool(_echo)
    reg.register(tool)
    assert "_echo" in reg
    assert reg.get("_echo") is tool
    assert len(reg) == 1


def test_registry_duplicate_rejected() -> None:
    reg = ToolRegistry()
    reg.register(FunctionTool(_echo))
    with pytest.raises(ValueError):
        reg.register(FunctionTool(_echo))


def test_registry_as_list_sorted() -> None:
    reg = ToolRegistry()
    reg.register(FunctionTool(_shout))
    reg.register(FunctionTool(_echo))
    assert [t.name for t in reg.as_list()] == ["_echo", "_shout"]
    assert reg.names() == ["_echo", "_shout"]


def test_get_cowork_context_roundtrip(tmp_path: Path) -> None:
    ws = Workspace(root=tmp_path)
    registry = ProjectRegistry(workspace=ws)
    project = registry.create("Gamma")
    session = registry.new_session("gamma")
    ctx = CoworkToolContext(
        workspace=ws,
        registry=registry,
        project=project,
        session=session,
        config=CoworkConfig(),
        skills=SkillRegistry(),
    )

    fake = MagicMock()
    fake.state = {COWORK_CONTEXT_KEY: ctx}
    assert get_cowork_context(fake) is ctx


def test_get_cowork_context_missing_raises() -> None:
    fake = MagicMock()
    fake.state = {}
    with pytest.raises(RuntimeError):
        get_cowork_context(fake)


def test_get_cowork_context_wrong_type_raises() -> None:
    fake = MagicMock()
    fake.state = {COWORK_CONTEXT_KEY: "not-a-context"}
    with pytest.raises(TypeError):
        get_cowork_context(fake)
