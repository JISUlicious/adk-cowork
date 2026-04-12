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
                if kind == "text" and frame.get("text"):
                    console.print(frame["text"], end="")
