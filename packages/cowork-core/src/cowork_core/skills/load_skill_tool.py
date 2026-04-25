"""``load_skill`` tool — fetches a skill's body into the agent's context.

The registry is populated at runtime and stashed on ``CoworkToolContext``;
this tool simply looks up by name and returns the body + a manifest of
``scripts/`` and ``assets/`` paths the skill exposes to ``python_exec`` and
``shell.run``.
"""

from __future__ import annotations

from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext

from cowork_core.skills.loader import SkillLoadError
from cowork_core.tools.base import COWORK_SKILLS_ENABLED_KEY, get_cowork_context
from cowork_core.tools.registry import ToolRegistry


def load_skill(name: str, tool_context: ToolContext) -> dict[str, object]:
    """Load a skill by name and return its body markdown + file manifest.

    Args:
        name: The skill's ``name`` field from its ``SKILL.md`` frontmatter.

    Returns:
        ``{"name", "description", "license", "body", "root",
        "scripts": [...], "assets": [...]}`` or ``{"error": ...}``.
    """
    ctx = get_cowork_context(tool_context)
    registry = ctx.skills
    # Slice II — refuse disabled skills at the tool layer too. The
    # prompt registry already omits them, but the model could still
    # call ``load_skill`` by name (it knows about previously-enabled
    # skills, or it might guess). Mirror the prompt-side gate here so
    # the disable is enforced regardless of the model's knowledge.
    enabled_state = tool_context.state.get(COWORK_SKILLS_ENABLED_KEY, {})
    if isinstance(enabled_state, dict) and enabled_state.get(name) is False:
        return {
            "error": (
                f"skill {name!r} is disabled for this session. "
                f"Re-enable it in Settings → Skills before calling load_skill."
            ),
        }
    try:
        skill = registry.get(name)
    except SkillLoadError as e:
        return {"error": str(e)}
    try:
        body = skill.load_body()
    except OSError as e:
        return {"error": f"failed to read skill body: {e}"}
    manifest = skill.manifest()
    rel_root = skill.root
    return {
        "name": skill.name,
        "description": skill.description,
        "license": skill.license,
        "body": body,
        "root": str(rel_root),
        "scripts": manifest["scripts"],
        "assets": manifest["assets"],
    }


def register_skill_tools(registry: ToolRegistry) -> None:
    registry.register(FunctionTool(load_skill))
