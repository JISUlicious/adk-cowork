"""``ManagedExecEnv`` — the current cowork two-namespace filesystem view.

Binds a Project and a Session together and exposes ``scratch/`` (draft
space, session-scoped) plus ``files/`` (durable, project-scoped). Used by
the web surface today; used by desktop when no workdir has been picked.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cowork_core.execenv.base import ExecEnvError
from cowork_core.workspace import Project, Session


@dataclass(frozen=True)
class ManagedExecEnv:
    project: Project
    session: Session

    def resolve(self, agent_path: str) -> Path:
        parts = Path(agent_path).parts
        if not parts:
            raise ExecEnvError("empty path")
        head = parts[0]
        tail = Path(*parts[1:]) if len(parts) > 1 else Path()
        if head == "scratch":
            base = self.session.scratch_dir.resolve()
        elif head == "files":
            base = self.project.files_dir.resolve()
        else:
            raise ExecEnvError(
                f"path must start with 'scratch/' or 'files/': {agent_path}"
            )
        candidate = (base / tail).resolve()
        try:
            candidate.relative_to(base)
        except ValueError as e:
            raise ExecEnvError(f"path escapes {head}/: {agent_path}") from e
        return candidate

    def try_resolve(self, agent_path: str) -> "Path | str":
        try:
            return self.resolve(agent_path)
        except ExecEnvError as e:
            return str(e)

    def root(self) -> Path:
        return self.project.root

    def scratch_dir(self) -> Path:
        return self.session.scratch_dir

    def agent_cwd(self) -> Path:
        # Managed mode sandboxes the agent inside scratch so python /
        # shell calls can't wander the project.
        return self.session.scratch_dir

    def namespaces(self) -> list[str]:
        return ["scratch", "files"]

    def describe_for_prompt(self) -> str:
        return (
            "Working context:\n"
            "- `scratch/` is the current session's draft directory — "
            "work here freely.\n"
            "- `files/` is the project's durable storage — call "
            "`fs_promote` to move a draft from scratch into it."
        )

    def glob(self, pattern: str, limit: int = 500) -> tuple[list[str], bool]:
        parts = Path(pattern).parts
        if not parts:
            return [], False
        head = parts[0]
        if head == "scratch":
            bases = [("scratch", self.session.scratch_dir.resolve())]
            sub = "/".join(parts[1:]) or "*"
        elif head == "files":
            bases = [("files", self.project.files_dir.resolve())]
            sub = "/".join(parts[1:]) or "*"
        else:
            # Bare pattern: search both namespaces with the full pattern.
            bases = [
                ("scratch", self.session.scratch_dir.resolve()),
                ("files", self.project.files_dir.resolve()),
            ]
            sub = pattern

        matches: list[str] = []
        for ns, base in bases:
            if not base.is_dir():
                continue
            for hit in sorted(base.glob(sub)):
                try:
                    rel = hit.resolve().relative_to(base)
                except ValueError:
                    continue
                matches.append(f"{ns}/{rel}")
                if len(matches) >= limit:
                    return matches, True
        return matches, False
