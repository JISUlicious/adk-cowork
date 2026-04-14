"""``cowork`` CLI entrypoint. Developer tool only.

Spawns ``python -m cowork_server`` as a subprocess, parses its handshake
line, opens a WebSocket for events, and prints streamed text to the
terminal. End users use the web UI or the desktop app instead.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from typing import Any

import httpx
import typer
import websockets
from rich.console import Console

app = typer.Typer(help="Cowork developer CLI")
console = Console()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """Start a chat session against a local cowork-server."""
    if ctx.invoked_subcommand is not None:
        return
    server_url = os.environ.get("COWORK_SERVER_URL")
    token = os.environ.get("COWORK_TOKEN")
    proc: subprocess.Popen[str] | None = None
    if not server_url or not token:
        proc, server_url, token = _spawn_server()
    try:
        asyncio.run(_chat(server_url, token))
    except KeyboardInterrupt:
        pass
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def _spawn_server() -> tuple[subprocess.Popen[str], str, str]:
    env = {**os.environ}
    proc = subprocess.Popen(
        [sys.executable, "-m", "cowork_server"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    assert proc.stdout is not None
    while True:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("cowork-server exited before ready")
        if line.startswith("COWORK_READY"):
            parts = dict(kv.split("=", 1) for kv in line.strip().split()[1:])
            return proc, f"http://{parts['host']}:{parts['port']}", parts["token"]


async def _chat(server_url: str, token: str) -> None:
    headers = {"x-cowork-token": token}
    async with httpx.AsyncClient(base_url=server_url, headers=headers, timeout=10) as http:
        r = await http.post("/v1/sessions")
        r.raise_for_status()
        sid = r.json()["session_id"]

    ws_url = server_url.replace("http", "ws", 1) + f"/v1/sessions/{sid}/events"
    async with websockets.connect(ws_url, additional_headers=headers) as ws:
        console.print(f"[dim]session {sid} — type 'exit' to quit[/dim]")
        while True:
            try:
                user = typer.prompt("you")
            except (EOFError, typer.Abort):
                return
            if user.strip() in {"exit", "quit"}:
                return
            async with httpx.AsyncClient(base_url=server_url, headers=headers, timeout=120) as http:
                await http.post(f"/v1/sessions/{sid}/messages", json={"text": user})
            while True:
                raw = await ws.recv()
                frame: dict[str, Any] = json.loads(raw)
                kind = frame.get("type")
                if kind == "end_turn":
                    console.print()
                    break
                if kind == "error":
                    console.print(f"[red]{frame.get('message')}[/red]")
                    break
                if kind == "multi":
                    for sub in frame.get("frames", []):
                        _render_frame(sub)
                else:
                    _render_frame(frame)


def _render_frame(frame: dict[str, Any]) -> None:
    kind = frame.get("type")
    if kind == "text" and frame.get("text"):
        console.print(frame["text"], end="")
    elif kind == "tool_call":
        name = frame.get("name", "?")
        args = frame.get("args") or {}
        console.print(f"\n[bold cyan]▶ {name}[/bold cyan]")
        for key, val in args.items():
            rendered = _truncate(val, 200)
            console.print(f"  [dim]{key}:[/dim] {rendered}")
    elif kind == "tool_result":
        name = frame.get("name", "?")
        result = frame.get("result") or {}
        if isinstance(result, dict) and result.get("confirmation_required"):
            console.print(
                f"  [yellow]⚠ {name}: {result.get('summary', 'confirmation needed')}[/yellow]"
            )
        elif isinstance(result, dict) and result.get("error"):
            console.print(f"  [red]✗ {name}: {result['error']}[/red]")
        else:
            summary = _result_summary(name, result)
            console.print(f"  [green]✓ {name}[/green]{summary}")


def _truncate(val: Any, limit: int) -> str:
    s = str(val)
    if len(s) <= limit:
        return s
    return s[:limit] + "…"


def _result_summary(name: str, result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    # Show a short preview for read-like results
    content = result.get("content") or result.get("text") or result.get("output")
    if content and isinstance(content, str):
        preview = content.replace("\n", "↵ ")
        if len(preview) > 120:
            preview = preview[:120] + "…"
        return f" [dim]→ {preview}[/dim]"
    return ""
