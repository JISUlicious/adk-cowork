"""``shell.run`` — portable, argv-only subprocess execution.

Hard rules (constitution §3.5):

* ``argv`` is always a ``list[str]``. No single-string form. No shell expansion.
* ``argv[0]`` is checked against ``config.policy.shell_allowlist`` before the
  process is spawned — if it is not listed the call fails fast.
* ``cwd`` defaults to the *current session's* scratch directory, so even a
  hostile command cannot touch files outside the sandbox by default.
* Output is captured, truncated at ``_MAX_OUTPUT_BYTES`` per stream, and
  returned along with the exit code and wall-clock duration.

Confirmation prompting (gated tools) will be layered on top via ADK's
``FunctionTool(require_confirmation=...)`` in the runner — this module stays
pure policy+execution.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from google.adk.tools.tool_context import ToolContext

from cowork_core.tools.base import get_cowork_context

_MAX_OUTPUT_BYTES = 200_000


def _truncate(data: bytes) -> tuple[str, bool]:
    truncated = len(data) > _MAX_OUTPUT_BYTES
    if truncated:
        data = data[:_MAX_OUTPUT_BYTES]
    return data.decode("utf-8", errors="replace"), truncated


def shell_run(
    argv: list[str],
    tool_context: ToolContext,
    cwd: str | None = None,
    timeout_sec: int = 30,
) -> dict[str, object]:
    """Run a subprocess identified by an argv list (no shell interpretation).

    Args:
        argv: Executable + arguments. Must be a non-empty list of strings.
        cwd: Project-relative working directory (``scratch/...`` or
            ``files/...``). Defaults to the current session's scratch dir.
        timeout_sec: Wall-clock timeout. Capped at 600.

    Returns:
        ``{"exit_code", "stdout", "stderr", "stdout_truncated",
        "stderr_truncated", "duration_ms"}`` on completion, or
        ``{"error": ...}`` if policy rejects the call or the process times out.
    """
    ctx = get_cowork_context(tool_context)
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        return {"error": "argv must be a non-empty list of strings"}
    allowlist = ctx.config.policy.shell_allowlist
    if argv[0] not in allowlist:
        return {
            "error": (
                f"executable not in shell_allowlist: {argv[0]!r}. allowed: {sorted(allowlist)}"
            )
        }
    timeout_sec = max(1, min(int(timeout_sec), 600))

    if cwd is None:
        work_dir: Path = ctx.session.scratch_dir
    else:
        from cowork_core.tools.fs._paths import resolve_project_path
        from cowork_core.workspace import WorkspaceError

        try:
            work_dir = resolve_project_path(ctx, cwd)
        except WorkspaceError as e:
            return {"error": str(e)}
        if not work_dir.is_dir():
            return {"error": f"cwd is not a directory: {cwd}"}

    start = time.monotonic()
    try:
        proc = subprocess.run(
            argv,
            cwd=work_dir,
            capture_output=True,
            timeout=timeout_sec,
            shell=False,
            check=False,
        )
    except FileNotFoundError:
        return {"error": f"executable not found: {argv[0]!r}"}
    except subprocess.TimeoutExpired:
        return {"error": f"timed out after {timeout_sec}s"}

    duration_ms = int((time.monotonic() - start) * 1000)
    stdout, stdout_trunc = _truncate(proc.stdout or b"")
    stderr, stderr_trunc = _truncate(proc.stderr or b"")
    return {
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": stdout_trunc,
        "stderr_truncated": stderr_trunc,
        "duration_ms": duration_ms,
    }
