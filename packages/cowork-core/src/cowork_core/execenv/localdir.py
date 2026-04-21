"""``LocalDirExecEnv`` — agent operates directly on a user-picked directory.

Used by the desktop surface after the user chooses "Open Folder…". The
chosen directory becomes the session root; the agent's vocabulary is plain
relative paths rooted there. Per-session bookkeeping (scratch, transcript,
session.toml) lives under ``<workdir>/.cowork/sessions/<session_id>/`` — the
same layout as managed mode, just anchored at the user's folder instead of
``~/CoworkWorkspaces``.

Sandboxing is path-confinement: ``resolve()`` absolutizes the candidate and
verifies it sits under ``workdir``. No OS-level sandbox — shell and python
tools keep their own argv allowlist / subprocess hardening.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from cowork_core.execenv.base import ExecEnvError

_COWORK_DIR = ".cowork"


@dataclass(frozen=True)
class LocalDirExecEnv:
    workdir: Path
    session_id: str
    _resolved_workdir: Path = field(init=False, repr=False)

    def __post_init__(self) -> None:
        resolved = self.workdir.resolve()
        if not resolved.exists():
            raise ExecEnvError(f"workdir does not exist: {self.workdir}")
        if not resolved.is_dir():
            raise ExecEnvError(f"workdir is not a directory: {self.workdir}")
        # Dataclass is frozen; bypass to cache the resolved path.
        object.__setattr__(self, "_resolved_workdir", resolved)

    def resolve(self, agent_path: str) -> Path:
        if not agent_path:
            raise ExecEnvError("empty path")
        if agent_path.startswith("/"):
            raise ExecEnvError(f"path must be relative: {agent_path}")
        # Normalize leading "./" for cleanliness.
        rel = agent_path[2:] if agent_path.startswith("./") else agent_path
        if rel.startswith("/") or not rel:
            raise ExecEnvError(f"invalid path: {agent_path}")
        candidate = (self._resolved_workdir / rel).resolve()
        try:
            candidate.relative_to(self._resolved_workdir)
        except ValueError as e:
            raise ExecEnvError(f"path escapes workdir: {agent_path}") from e
        return candidate

    def try_resolve(self, agent_path: str) -> "Path | str":
        try:
            return self.resolve(agent_path)
        except ExecEnvError as e:
            return str(e)

    def root(self) -> Path:
        return self._resolved_workdir

    def scratch_dir(self) -> Path:
        p = (
            self._resolved_workdir
            / _COWORK_DIR
            / "sessions"
            / self.session_id
            / "scratch"
        )
        p.mkdir(parents=True, exist_ok=True)
        return p

    def agent_cwd(self) -> Path:
        # Local-dir mode: the user picked this folder specifically for
        # the agent to work in. Running snippets from the hidden
        # ``.cowork/sessions/.../scratch`` would confuse the agent
        # (``os.getcwd()`` wouldn't match the workdir it was told
        # about). Run them from the workdir root instead.
        return self._resolved_workdir

    def namespaces(self) -> list[str]:
        return [""]

    def describe_for_prompt(self) -> str:
        return (
            f"Working context:\n"
            f"- You are working in `{self._resolved_workdir}`.\n"
            f"- All paths are relative to this directory. "
            f"Example: `fs_read(\"draft.md\")`.\n"
            f"- `python_exec_run` and `shell_run` execute with cwd set "
            f"to this workdir — plain `open(\"data.csv\")` or "
            f"`pathlib.Path(\"data.csv\")` resolves against it.\n"
            f"- The directory `.cowork/` is reserved for session scratch — "
            f"ignore it when listing files."
        )

    def glob(self, pattern: str, limit: int = 500) -> tuple[list[str], bool]:
        if pattern.startswith("/"):
            return [], False  # absolute not allowed
        base = self._resolved_workdir
        matches: list[str] = []
        for hit in sorted(base.glob(pattern)):
            try:
                rel = hit.resolve().relative_to(base)
            except ValueError:
                continue
            rel_str = str(rel)
            # Hide the .cowork/ bookkeeping from globs by default.
            if rel_str.startswith(_COWORK_DIR + "/") or rel_str == _COWORK_DIR:
                continue
            matches.append(rel_str)
            if len(matches) >= limit:
                return matches, True
        return matches, False
