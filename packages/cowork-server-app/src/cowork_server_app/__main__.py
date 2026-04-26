"""``python -m cowork_server_app`` — single-user sidecar entry point.

Starts uvicorn on a random local port and prints one handshake line
to stdout that launchers parse::

    COWORK_READY host=127.0.0.1 port=<p> token=<t>

The CLI and the desktop-app Tauri sidecar both read that line to
discover the server they just started. Refuses to start if
``[auth].keys`` is non-empty in ``cowork.toml`` — that's
multi-user territory; use ``python -m cowork_server_web`` instead.
"""

from __future__ import annotations

import os
import signal
import socket
import threading
import time
from pathlib import Path

import uvicorn
from cowork_core import CoworkConfig
from cowork_server.auth import generate_token
from cowork_server_app.app_factory import create_app


def _pick_port(host: str) -> int:
    with socket.socket() as s:
        s.bind((host, 0))
        return int(s.getsockname()[1])


def _parent_death_watchdog(original_ppid: int) -> None:
    """Exit this process if our launcher dies.

    The Tauri sidecar spawns us in a fresh session (setsid) so POSIX
    signal propagation isn't reliable on every OS. Polling
    ``getppid()`` catches both graceful parent exit (ppid becomes 1
    on Unix) and SIGKILL. Only runs when ``COWORK_WATCH_PARENT`` is
    set — CLI mode doesn't need it.
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


def _load_config() -> tuple[CoworkConfig, Path | None]:
    """Load config from ``COWORK_CONFIG_PATH`` if set, else env-only.

    Returns ``(cfg, config_path)``; ``config_path`` is ``None`` when
    env-only. The single-user backend accepts both env-only and
    TOML-backed configurations; multi-user configurations are
    rejected by ``cowork_server_app.create_app``.
    """
    path = os.environ.get("COWORK_CONFIG_PATH")
    if path:
        p = Path(path)
        if not p.exists():
            raise SystemExit(
                f"COWORK_CONFIG_PATH={path!r} does not exist. "
                f"Either create the file or unset the var."
            )
        cfg = CoworkConfig.load(p)
        if cfg.auth.keys:
            raise SystemExit(
                "cowork-server-app is the single-user sidecar; "
                "cowork.toml has [auth].keys configured (multi-user). "
                "Use 'python -m cowork_server_web' for hosted deployments.",
            )
        print(f"[config] loaded {path} — auth: single-token", flush=True)
        return cfg, p
    return CoworkConfig.from_env(), None


def main() -> None:
    cfg, config_path = _load_config()
    token = os.environ.get("COWORK_TOKEN") or cfg.auth.token or generate_token()
    host = cfg.server.host
    port = int(os.environ.get("COWORK_PORT", 0)) or cfg.server.port or _pick_port(host)

    if os.environ.get("COWORK_WATCH_PARENT"):
        ppid = os.getppid()
        t = threading.Thread(
            target=_parent_death_watchdog, args=(ppid,), daemon=True
        )
        t.start()

    app = create_app(cfg, token=token, config_path=config_path)
    print(f"COWORK_READY host={host} port={port} token={token}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
