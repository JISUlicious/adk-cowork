"""Abstract execution environment — the agent's view of the filesystem.

The agent always speaks *agent-relative* paths. An ``ExecEnv`` translates
those into absolute filesystem paths and rejects anything that escapes the
env's root. The two concrete environments are:

- ``ManagedExecEnv`` — classic cowork layout: ``scratch/`` + ``files/``
  namespaces bound to a Project + Session. Used by the web surface.
- ``LocalDirExecEnv`` — agent operates directly on a user-picked directory;
  plain relative paths; scratch in a hidden ``.cowork/`` subdir. Used by the
  desktop surface once a workdir is chosen.

Surfaces construct the appropriate ``ExecEnv`` at session creation time and
stash it on ``CoworkToolContext.env``; every fs tool goes through it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


class ExecEnvError(Exception):
    """Raised when a requested path escapes the env's root or is malformed."""


@runtime_checkable
class ExecEnv(Protocol):
    """Agent-facing filesystem view."""

    def resolve(self, agent_path: str) -> Path:
        """Resolve an agent path to absolute. Raises ``ExecEnvError`` on escape."""

    def try_resolve(self, agent_path: str) -> "Path | str":
        """Like ``resolve`` but returns the error message as a string on failure.

        Tools use this to surface errors to the agent as tool results rather
        than raising, which lets the agent self-correct.
        """

    def root(self) -> Path:
        """Absolute filesystem root of this env (for display / cwd)."""

    def scratch_dir(self) -> Path:
        """Directory the agent can freely write scratch work to."""

    def agent_cwd(self) -> Path:
        """Default cwd for shell / python execution.

        Managed mode keeps the agent sandboxed inside ``scratch_dir`` so
        snippets can't wander the workspace; local-dir mode returns the
        user-picked workdir so prints like ``os.getcwd()`` match the
        folder the user is actually editing.
        """

    def namespaces(self) -> list[str]:
        """Agent-visible path namespaces.

        ``["scratch", "files"]`` for managed mode, ``[""]`` for local-dir
        mode. Used by the prompt and by ``glob``.
        """

    def describe_for_prompt(self) -> str:
        """Human-readable paragraph explaining the path vocabulary.

        Injected into the system prompt so the agent knows what paths mean.
        """

    def glob(self, pattern: str, limit: int = 500) -> tuple[list[str], bool]:
        """Return agent-relative paths matching ``pattern`` + a truncated flag.

        Implementations decide whether namespace prefixes are honored.
        """
