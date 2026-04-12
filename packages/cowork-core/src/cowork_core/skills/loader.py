"""Skill frontmatter parser and ``SkillRegistry``.

The ``SKILL.md`` format (adopted from Claude Code, see SPEC §2.5.1) is:

    ---
    name: docx-basic
    description: "When the user wants to read/write .docx files..."
    license: MIT
    ---

    # body markdown the agent only sees via `load_skill`

Collision policy: project-scoped skills shadow global ones with the same
``name`` so users can override a default in a single project.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

_FRONTMATTER_FENCE = "---"


class SkillLoadError(Exception):
    """Raised for malformed SKILL.md files."""


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    license: str
    root: Path
    frontmatter: dict[str, Any] = field(default_factory=dict)

    @property
    def skill_md(self) -> Path:
        return self.root / "SKILL.md"

    @property
    def scripts_dir(self) -> Path:
        return self.root / "scripts"

    @property
    def assets_dir(self) -> Path:
        return self.root / "assets"

    def load_body(self) -> str:
        """Return the Markdown body (everything after the closing fence)."""
        text = self.skill_md.read_text(encoding="utf-8")
        _, body = _split_frontmatter(text, self.skill_md)
        return body

    def manifest(self) -> dict[str, list[str]]:
        """Return lists of relative paths under scripts/ and assets/."""
        return {
            "scripts": _relative_listing(self.scripts_dir),
            "assets": _relative_listing(self.assets_dir),
        }


def parse_skill_md(path: Path) -> Skill:
    """Parse a ``SKILL.md`` file into a ``Skill`` (body loaded lazily)."""
    if not path.is_file():
        raise SkillLoadError(f"not a file: {path}")
    text = path.read_text(encoding="utf-8")
    fm, _body = _split_frontmatter(text, path)
    name = fm.get("name")
    description = fm.get("description")
    if not isinstance(name, str) or not name:
        raise SkillLoadError(f"missing 'name' in {path}")
    if not isinstance(description, str) or not description:
        raise SkillLoadError(f"missing 'description' in {path}")
    license_val = fm.get("license") or "unspecified"
    if not isinstance(license_val, str):
        raise SkillLoadError(f"'license' must be a string in {path}")
    return Skill(
        name=name,
        description=description,
        license=license_val,
        root=path.parent,
        frontmatter=fm,
    )


@dataclass
class SkillRegistry:
    """In-memory index of skills discovered under one or more roots."""

    _skills: dict[str, Skill] = field(default_factory=dict)

    def scan(self, root: Path) -> int:
        """Scan ``root`` for ``<name>/SKILL.md`` entries. Returns count added."""
        if not root.is_dir():
            return 0
        added = 0
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.is_file():
                continue
            skill = parse_skill_md(skill_md)
            self._skills[skill.name] = skill
            added += 1
        return added

    def all_skills(self) -> list[Skill]:
        return [self._skills[n] for n in sorted(self._skills)]

    def get(self, name: str) -> Skill:
        if name not in self._skills:
            raise SkillLoadError(f"unknown skill: {name!r}")
        return self._skills[name]

    def names(self) -> list[str]:
        return sorted(self._skills)

    def injection_snippet(self) -> str:
        """One line per skill for the root agent's system prompt."""
        if not self._skills:
            return ""
        lines = [f"- {s.name}: {s.description}" for s in self.all_skills()]
        return "Available skills (call `load_skill(name)` to load):\n" + "\n".join(lines)


def _split_frontmatter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    if not text.lstrip().startswith(_FRONTMATTER_FENCE):
        raise SkillLoadError(f"missing frontmatter fence in {path}")
    stripped = text.lstrip()
    rest = stripped[len(_FRONTMATTER_FENCE) :].lstrip("\n")
    close_idx = rest.find(f"\n{_FRONTMATTER_FENCE}")
    if close_idx < 0:
        raise SkillLoadError(f"unterminated frontmatter in {path}")
    fm_text = rest[:close_idx]
    body = rest[close_idx + len(_FRONTMATTER_FENCE) + 1 :]
    try:
        data = yaml.safe_load(fm_text) or {}
    except yaml.YAMLError as e:
        raise SkillLoadError(f"invalid YAML frontmatter in {path}: {e}") from e
    if not isinstance(data, dict):
        raise SkillLoadError(f"frontmatter must be a mapping in {path}")
    return data, body.lstrip("\n")


def _relative_listing(base: Path) -> list[str]:
    if not base.is_dir():
        return []
    return sorted(str(p.relative_to(base)) for p in base.rglob("*") if p.is_file())
