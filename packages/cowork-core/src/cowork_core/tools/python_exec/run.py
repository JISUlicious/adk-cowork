"""``python_exec.run`` — execute a Python snippet in a subprocess.

The snippet is written to a temp ``.py`` inside the session scratch directory
and then run with the *same interpreter* (``sys.executable``) so whatever
libraries are installed in Cowork's venv (python-docx, openpyxl, pandas,
pypdf, matplotlib, markdown-it-py, Pillow, …) are available to skills.

Hardening:

* ``cwd`` = session scratch — snippet cannot silently wander the filesystem.
* ``PYTHONNOUSERSITE=1`` — user site-packages are ignored.
* ``PYTHONPATH`` removed — nothing ambient on the import path.
* ``network=False`` (default) sets a bad ``HTTP(S)_PROXY`` so accidental
  HTTP calls fail fast instead of silently exfiltrating data.
* Output is captured and truncated at ``_MAX_OUTPUT_BYTES``.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from google.adk.tools.tool_context import ToolContext

from cowork_core.tools.base import get_cowork_context

_MAX_OUTPUT_BYTES = 200_000
_BAD_PROXY = "http://127.0.0.1:1"


def _truncate(data: bytes) -> tuple[str, bool]:
    truncated = len(data) > _MAX_OUTPUT_BYTES
    if truncated:
        data = data[:_MAX_OUTPUT_BYTES]
    return data.decode("utf-8", errors="replace"), truncated


def _build_env(network: bool) -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONNOUSERSITE"] = "1"
    env.pop("PYTHONPATH", None)
    if not network:
        env["HTTP_PROXY"] = _BAD_PROXY
        env["HTTPS_PROXY"] = _BAD_PROXY
        env["http_proxy"] = _BAD_PROXY
        env["https_proxy"] = _BAD_PROXY
        env["NO_PROXY"] = ""
    return env


def python_exec_run(
    code: str,
    tool_context: ToolContext,
    network: bool = False,
    timeout_sec: int = 60,
) -> dict[str, object]:
    """Run a Python snippet in a subprocess rooted at the session scratch dir.

    Args:
        code: Python source to execute. Written to a temp file under scratch.
        network: If False (default), outbound HTTP is broken via a bad proxy.
        timeout_sec: Wall-clock timeout. Capped at 600.

    Returns:
        ``{"exit_code", "stdout", "stderr", "stdout_truncated",
        "stderr_truncated", "duration_ms"}`` or ``{"error": ...}``.
    """
    if not isinstance(code, str) or not code.strip():
        return {"error": "code must be a non-empty string"}
    ctx = get_cowork_context(tool_context)
    timeout_sec = max(1, min(int(timeout_sec), 600))
    # Temp script always lives under scratch so it's cleaned up and
    # doesn't clutter the user's folder.
    scratch: Path = ctx.env.scratch_dir()
    scratch.mkdir(parents=True, exist_ok=True)
    # CWD for the snippet follows the env: managed stays sandboxed
    # inside scratch; local-dir runs from the user's workdir so
    # ``os.getcwd()`` / relative paths match the folder the agent was
    # told about.
    run_cwd: Path = ctx.env.agent_cwd()

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        dir=scratch,
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write(code)
        script_path = Path(tmp.name)

    env = _build_env(network)
    start = time.monotonic()
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=run_cwd,
            capture_output=True,
            timeout=timeout_sec,
            shell=False,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"timed out after {timeout_sec}s"}
    finally:
        with contextlib.suppress(OSError):
            script_path.unlink()

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
