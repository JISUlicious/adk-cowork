# 06 — Skills

Markdown-driven, lazily-loaded capability packs.

## Claude Code

Skills are a first-class extension surface. They sit between tools
(callable primitives) and agents (full behaviors with their own
prompt and tool subset). One skill can bind its own allowed tools,
hooks, and even a specific subagent.

### Sources

`src/skills/loadSkillsDir.ts` merges multiple sources, in order:

```ts
type LoadedFrom =
  | 'commands_DEPRECATED'
  | 'skills'           // user / project
  | 'plugin'           // plugin-provided
  | 'managed'          // org-policy pushed
  | 'bundled'          // src/skills/bundled/
  | 'mcp'              // MCP server advertises them
```

Later sources can shadow earlier ones on name collision.

### SKILL.md frontmatter

A skill is a directory with a `SKILL.md` plus optional
`scripts/` and `assets/`. Frontmatter keys include:

```yaml
---
description: "What this skill does."
whenToUse: "When the model should invoke this skill."
allowedTools:
  - Read
  - Write
context: fork        # run body in isolated subagent
agent: general-purpose
hooks:
  - event: PreToolUse
    command: "script.sh"
---
```

The body is the markdown instructions; it's shown to the model only
when the skill is invoked (lazy load, mirroring Cowork).

### Conditional activation

Skills can declare path patterns. When session file activity touches
a matching path, the skill is promoted from "dormant" into the
dynamically-active set so the model can see it. This keeps the
global skill catalog small even when many skills are installed.

### Invocation surfaces

Claude Code exposes skills three ways:

1. As **slash commands**: `/skill-name`.
2. As the **`Skill` tool**: model-visible tool that takes a skill
   name and optional args.
3. As **plugin-contributed commands** that may package a skill plus
   other artifacts.

### Security notes

`src/skills/loadSkillsDir.ts:205+` explicitly carves out MCP skills
from local-file skill privileges: no inline shell substitution for
remote-origin skills because they are untrusted.

## Cowork

One source model, one invocation surface, no frontmatter beyond
identity.

### Format

`packages/cowork-core/src/cowork_core/skills/loader.py:3-15`
documents the format (adopted from Claude Code):

```markdown
---
name: docx-basic
description: "When the user wants to read/write .docx files..."
license: MIT
---

# body markdown the agent only sees via `load_skill`
```

Only `name`, `description`, `license` are read. No `allowedTools`,
`whenToUse`, `hooks`, `agent`, `context` — the field set is
intentionally small.

### Registry and scan order

`packages/cowork-core/src/cowork_core/skills/loader.py:90-110`:

```python
@dataclass
class SkillRegistry:
    _skills: dict[str, Skill] = field(default_factory=dict)

    def scan(self, root: Path) -> int:
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
```

`packages/cowork-core/src/cowork_core/runner.py:245-247` scans
bundled then user-config skills at runtime build:

```python
skills = SkillRegistry()
skills.scan(_bundled_skills_dir())                  # packages/.../skills/bundled/
skills.scan(_user_config_dir() / "skills")          # ~/.config/cowork/skills
```

`packages/cowork-core/src/cowork_core/runner.py:162-172`
`_build_context` layers project-local skills per session
(`workspace.root/.cowork/skills`). These only affect the skills
carried in the per-session `CoworkToolContext`, not the prompt
injection — meaning project skills are callable but not advertised.

### Injection in the prompt

`packages/cowork-core/src/cowork_core/skills/loader.py:123-128`
produces a bullet list of advertised skills:

```python
def injection_snippet(self) -> str:
    if not self._skills:
        return ""
    lines = [f"- {s.name}: {s.description}" for s in self.all_skills()]
    return "Available skills (call `load_skill(name)` to load):\n" + "\n".join(lines)
```

This snippet is appended to `ROOT_INSTRUCTION_BASE` at
`root_agent.py:108-110`.

### Invocation

`packages/cowork-core/src/cowork_core/skills/load_skill_tool.py:19-49`
`load_skill(name)` returns the body + script/asset manifest. There
are no slash commands, no tool-level bindings — the model just
calls `load_skill` like any other tool, reads the returned markdown,
and follows its instructions.

```python
def load_skill(name: str, tool_context: ToolContext) -> dict[str, object]:
    ctx = get_cowork_context(tool_context)
    registry = ctx.skills
    try:
        skill = registry.get(name)
    except SkillLoadError as e:
        return {"error": str(e)}
    body = skill.load_body()
    manifest = skill.manifest()
    return {
        "name": skill.name,
        "description": skill.description,
        "license": skill.license,
        "body": body,
        "root": str(skill.root),
        "scripts": manifest["scripts"],
        "assets": manifest["assets"],
    }
```

### Bundled skills

`packages/cowork-core/src/cowork_core/skills/bundled/` ships:
`docx-basic`, `xlsx-basic`, `pdf-read`, `md`, `email-draft`, `plot`,
`research` (check the directory for the current set).

## Gap / takeaway

**Missing in Cowork:**

- *Conditional activation.* No "this skill wakes up when a `.xlsx`
  is touched" semantics. Every bundled skill is always advertised.
- *Per-skill tool restriction (`allowedTools`).* Skills run in the
  same tool pool as every other turn; a skill can call `shell_run`
  even if that's inappropriate.
- *Per-skill hook binding.* No way for a skill to attach a
  `PreToolUse` script.
- *Plugin / MCP skill sources.* Only bundled + user config + project.
- *Slash-command surface.* Skills are model-invoked only; there is
  no `/skill-name` shortcut in the web UI.
- *Project skills in prompt.* `_build_context` loads project skills
  into the per-session `SkillRegistry` but the system prompt is
  built once at runtime assembly, so project-local skills are
  reachable via `load_skill(name)` but invisible in the
  "Available skills" list.

**Not missing, because the scope is different:**

- The SKILL.md format is deliberately compatible with Claude Code,
  per the comment at `loader.py:3`. Users can bring their own
  Claude Code skills over as long as they only need the basic
  frontmatter.

**Potentially worth adding:**

- Refresh the "Available skills" list per turn (or recompute
  `skills_snippet` from the per-session registry) so project
  skills show up.
- Support at least `whenToUse` — it's already a convention in
  Claude Code skills that users will have, and the parser currently
  ignores it silently.
- A skill-level `allowedTools` enforced via the permission callback
  (chapter 03) so skills can be sandboxed without bolting on a
  separate subagent.
