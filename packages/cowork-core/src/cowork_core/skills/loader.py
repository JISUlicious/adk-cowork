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

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]

_FRONTMATTER_FENCE = "---"

# Hard cap on how many description characters reach the root agent's
# system prompt. The full description is still available verbatim
# via ``Skill.description`` for the UI; only the prompt-injection
# snippet is truncated. Slice II safety: a third-party skill can't
# smuggle long instructions in via its description.
DESCRIPTION_PROMPT_CAP = 300

# Where a skill came from. ``bundled`` ships inside the
# ``cowork-core`` package and is immutable; ``user`` lives under
# ``<workspace>/global/skills/`` and can be uninstalled by the user.
# ``project`` / ``workdir`` skills are session-scoped and not
# removable via the uninstall flow either (they belong to the
# project owner, not the current session user). Slice B uses this
# to gate the uninstall path.
SkillSource = Literal["bundled", "user", "project", "workdir"]


class SkillLoadError(Exception):
    """Raised for malformed SKILL.md files."""


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    license: str
    root: Path
    frontmatter: dict[str, Any] = field(default_factory=dict)
    source: SkillSource = "bundled"
    # Optional frontmatter fields. Permissive defaults so skills
    # written for Claude Code (where these aren't required) round-
    # trip cleanly through Cowork's parser.
    version: str = "0.0.0"
    triggers: list[str] = field(default_factory=list)
    # SHA-256 of the SKILL.md bytes at scan time, lower-case hex.
    # Surfaced to the UI so users can see what they actually have
    # on disk vs. what was originally installed.
    content_hash: str = ""

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


def parse_skill_md(path: Path, source: SkillSource = "bundled") -> Skill:
    """Parse a ``SKILL.md`` file into a ``Skill`` (body loaded lazily).

    ``source`` tags the provenance. Callers picking a skill up from a
    user-writable location (``<workspace>/global/skills/``) pass
    ``"user"`` so the uninstall flow can find it; the default
    matches the common case of bundled package assets.

    Required frontmatter: ``name``, ``description``. Optional
    fields recognised: ``license`` (default ``"unspecified"``),
    ``version`` (default ``"0.0.0"``), ``triggers`` (default
    ``[]``). Unknown fields stay in ``frontmatter`` untouched —
    skills authored for Claude Code round-trip cleanly. All
    string-typed fields are scanned for non-printable / control
    characters as a prompt-injection guard; offending values are
    rejected outright.
    """
    if not path.is_file():
        raise SkillLoadError(f"not a file: {path}")
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="strict")
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
    version = fm.get("version", "0.0.0")
    if not isinstance(version, str):
        raise SkillLoadError(f"'version' must be a string in {path}")
    triggers_raw = fm.get("triggers", [])
    if not isinstance(triggers_raw, list) or not all(
        isinstance(t, str) for t in triggers_raw
    ):
        raise SkillLoadError(f"'triggers' must be a list of strings in {path}")
    for value, label in (
        (name, "name"),
        (description, "description"),
        (license_val, "license"),
        (version, "version"),
    ):
        _reject_non_printable(value, label, path)
    for t in triggers_raw:
        _reject_non_printable(t, "triggers entry", path)
    content_hash = hashlib.sha256(raw).hexdigest()
    return Skill(
        name=name,
        description=description,
        license=license_val,
        root=path.parent,
        frontmatter=fm,
        source=source,
        version=version,
        triggers=list(triggers_raw),
        content_hash=content_hash,
    )


def _reject_non_printable(value: str, label: str, path: Path) -> None:
    """Disallow control characters in user-visible string values.

    Defence against a malicious zip whose frontmatter description
    embeds a newline + injected directives the model might honor
    when the description is rendered into the root prompt.
    Whitespace inside the string (regular spaces) is fine; what we
    reject are codepoints below 0x20 other than tab (handled
    leniently — YAML strips most of these anyway, but be explicit).
    """
    for ch in value:
        if ord(ch) < 0x20 and ch not in ("\t",):
            raise SkillLoadError(
                f"control character in {label!r} of {path}: "
                f"U+{ord(ch):04X} not permitted",
            )


@dataclass
class SkillRegistry:
    """In-memory index of skills discovered under one or more roots."""

    _skills: dict[str, Skill] = field(default_factory=dict)

    def scan(self, root: Path, source: SkillSource = "bundled") -> int:
        """Scan ``root`` for ``<name>/SKILL.md`` entries. Returns count added.

        Later scans overwrite earlier ones with the same ``name`` —
        that's how the ``project`` / ``workdir`` scan layers on top of
        bundled + user-global defaults inside ``_build_context``.
        """
        if not root.is_dir():
            return 0
        added = 0
        for entry in sorted(root.iterdir()):
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.is_file():
                continue
            skill = parse_skill_md(skill_md, source=source)
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

    def injection_snippet(
        self,
        enabled: Callable[[str], bool] | None = None,
    ) -> str:
        """One line per skill for the root agent's system prompt.

        Each line is capped at ``DESCRIPTION_PROMPT_CAP`` characters
        (with a trailing ellipsis when clipped) so a malicious
        third-party skill can't smuggle long instructions into the
        system prompt via its description field. The full description
        is still surfaced verbatim to the UI through ``SkillInfo``.

        ``enabled`` is an optional per-session predicate: skills for
        which it returns False are omitted entirely. ``None`` (the
        default) treats every skill as enabled.
        """
        if not self._skills:
            return ""
        lines: list[str] = []
        for s in self.all_skills():
            if enabled is not None and not enabled(s.name):
                continue
            desc = s.description
            if len(desc) > DESCRIPTION_PROMPT_CAP:
                desc = desc[: DESCRIPTION_PROMPT_CAP - 1].rstrip() + "…"
            lines.append(f"- {s.name}: {desc}")
        if not lines:
            return ""
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
