"""Skill loader + runtime for Cowork.

A *skill* is a filesystem bundle the agent loads on demand. See
``SPEC.md`` §2.5.1 for the on-disk layout and rationale for the split between
"name + description in the prompt" and "body only when the agent asks".

Search path (first match wins on name collision):

1. ``<project_root>/skills/<name>/SKILL.md``  — project-scoped
2. ``<workspace_root>/global/skills/<name>/SKILL.md``  — user-global

Only ``name`` + ``description`` are injected into the root agent prompt;
the body text is loaded via the ``load_skill`` tool.
"""

from __future__ import annotations

from cowork_core.skills.load_skill_tool import load_skill, register_skill_tools
from cowork_core.skills.loader import (
    Skill,
    SkillLoadError,
    SkillRegistry,
    parse_skill_md,
)

__all__ = [
    "Skill",
    "SkillLoadError",
    "SkillRegistry",
    "load_skill",
    "parse_skill_md",
    "register_skill_tools",
]
