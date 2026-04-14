"""``python -m cowork_server`` / ``cowork-server`` entrypoint.

Starts uvicorn on a random local port and prints one handshake line to
stdout that launchers parse::

    COWORK_READY host=127.0.0.1 port=<p> token=<t>

The CLI and the desktop-app Tauri sidecar both read that line to discover
the server they just started.
"""

from __future__ import annotations

import os
import signal
import socket
import threading
import time

import uvicorn
from cowork_core import CoworkConfig

from cowork_server.app import create_app
from cowork_server.auth import generate_token


def _pick_port(host: str) -> int:
    with socket.socket() as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def _parent_death_watchdog(original_ppid: int) -> None:
    """Exit this process if our launcher dies.

    The Tauri sidecar spawns us in a fresh session (setsid) so POSIX signal
    propagation isn't reliable on every OS. Polling ``getppid()`` catches
    both graceful parent exit (ppid becomes 1 on Unix) and SIGKILL. Only
    runs when ``COWORK_WATCH_PARENT`` is set — CLI mode doesn't need it.
    """
    while True:
        time.sleep(1.0)
        try:
            ppid = os.getppid()
        except OSError:
            ppid = 1
        if ppid != original_ppid:
            os.kill(os.getpid(), signal.SIGTERM)
            return


def main() -> None:
    cfg = CoworkConfig.from_env()
    token = os.environ.get("COWORK_TOKEN") or generate_token()
    host = cfg.server.host
    port = int(os.environ.get("COWORK_PORT", 0)) or cfg.server.port or _pick_port(host)

    if os.environ.get("COWORK_WATCH_PARENT"):
        ppid = os.getppid()
        t = threading.Thread(
            target=_parent_death_watchdog, args=(ppid,), daemon=True
        )
        t.start()

    app = create_app(cfg, token=token)
    print(f"COWORK_READY host={host} port={port} token={token}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
