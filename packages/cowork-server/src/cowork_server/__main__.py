"""``python -m cowork_server`` / ``cowork-server`` entrypoint.

Starts uvicorn on a random local port and prints one handshake line to
stdout that launchers parse::

    COWORK_READY host=127.0.0.1 port=<p> token=<t>

The CLI and the desktop-app Tauri sidecar both read that line to discover
the server they just started.
"""

from __future__ import annotations

import os
import socket

import uvicorn
from cowork_core import CoworkConfig

from cowork_server.app import create_app
from cowork_server.auth import generate_token


def _pick_port(host: str) -> int:
    with socket.socket() as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def main() -> None:
    cfg = CoworkConfig.from_env()
    token = os.environ.get("COWORK_TOKEN") or generate_token()
    host = cfg.server.host
    port = cfg.server.port or _pick_port(host)
    app = create_app(cfg, token=token)
    print(f"COWORK_READY host={host} port={port} token={token}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
