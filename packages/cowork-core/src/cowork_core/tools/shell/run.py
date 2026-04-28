"""``shell.run`` — portable, argv-only subprocess execution.

Hard rules (constitution §3.5):

* ``argv`` is always a ``list[str]``. No single-string form. No shell expansion.
* ``argv[0]`` is checked against the calling agent's effective shell allowlist
  by a per-agent ``before_tool_callback`` (W5). Non-allowlisted commands hit
  the user-confirm flow; allowlisted commands run without prompting.
* ``cwd`` defaults to the *current session's* scratch directory, so even a
  hostile command cannot touch files outside the sandbox by default.
* Output is captured, truncated at ``_MAX_OUTPUT_BYTES`` per stream, and
  returned along with the exit code and wall-clock duration.

The tool body itself enforces:

* ``check_shell_deny`` — global hardcoded deny rules (W5). Catastrophic
  commands (sudo, mkfs, recursive rm against system paths, dd to device
  files, etc.) are blocked even when the user has granted approval. This
  is defence-in-depth — the gate also runs the same check, but the tool
  body re-checks so a callback-ordering bug can't bypass it.
* Argv shape + cwd traversal validation.

Confirmation prompting + per-agent allowlist live in
``cowork_core.policy.permissions.make_shell_allowlist_gate`` — see
``build_root_agent`` for the wiring.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from google.adk.tools.tool_context import ToolContext

from cowork_core.tools.base import get_cowork_context
from cowork_core.tools.shell.deny import check_shell_deny

_MAX_OUTPUT_BYTES = 200_000


def _truncate(data: bytes) -> tuple[str, bool]:
    truncated = len(data) > _MAX_OUTPUT_BYTES
    if truncated:
        data = data[:_MAX_OUTPUT_BYTES]
    return data.decode("utf-8", errors="replace"), truncated


def shell_run(
    argv: list[str],
    tool_context: ToolContext,
    description: str | None = None,
    cwd: str | None = None,
    timeout_sec: int = 30,
) -> dict[str, object]:
    """Run a subprocess identified by an argv list (no shell interpretation).

    Args:
        argv: Executable + arguments. Must be a non-empty list of strings.
            Constitution §3.5: argv-only — no single-string form, no shell
            expansion. For pipelines or redirects, write a Python snippet
            via ``python_exec_run`` instead.
        description: One-line human-readable summary of what the command
            does, surfaced to the user in the confirmation prompt when
            the command isn't on the agent's allowlist (e.g. "Convert
            markdown to PDF" beats raw argv). Optional but recommended.
        cwd: Project-relative working directory (``scratch/...`` or
            ``files/...``). Defaults to the current session's scratch dir.
        timeout_sec: Wall-clock timeout. Capped at 600.

    Returns:
        ``{"exit_code", "stdout", "stderr", "stdout_truncated",
        "stderr_truncated", "duration_ms"}`` on completion, or
        ``{"error": ...}`` if the call hits a deny rule, fails type
        validation, or times out.
    """
    ctx = get_cowork_context(tool_context)
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        return {"error": "argv must be a non-empty list of strings"}

    # Defence-in-depth — the per-agent gate runs this same check before
    # the tool body executes, but re-checking here means a
    # callback-ordering bug or future direct-call path can't bypass the
    # global deny list.
    deny_reason = check_shell_deny(argv)
    if deny_reason is not None:
        return {"error": f"Blocked: {deny_reason}"}

    # ``description`` is consumed by the gate (mounted in the
    # ``before_tool_callback`` chain), not the tool body. By the time
    # we reach this function the gate has either accepted the call or
    # short-circuited. Accepting the kwarg keeps it visible to the
    # model's tool schema without doing anything with it here.
    del description

    timeout_sec = max(1, min(int(timeout_sec), 600))

    if cwd is None:
        # Managed mode: sandboxed scratch. Local-dir mode: the user's
        # workdir, so relative paths the agent sees match what it'd
        # get from fs tools.
        work_dir: Path = ctx.env.agent_cwd()
    else:
        resolved = ctx.env.try_resolve(cwd)
        if isinstance(resolved, str):
            return {"error": resolved}
        if not resolved.is_dir():
            return {"error": f"cwd is not a directory: {cwd}"}
        work_dir = resolved

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
