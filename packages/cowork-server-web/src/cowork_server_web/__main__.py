"""``python -m cowork_server_web`` — multi-user hosted entry point.

Hosted deployments expose the FastAPI app to the network at the
configured ``[server]`` host + port. Refuses to start without
``[auth].keys`` configured (the multi-user backend requires
explicit API key → user_id mappings).

Unlike ``cowork_server_app``, this entry point does NOT print the
sidecar handshake line — it's deployed standalone (systemd, k8s,
docker), not as a child process of cowork-cli or the desktop
shell.
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from cowork_core import CoworkConfig
from cowork_server.auth import generate_token
from cowork_server_web.app_factory import create_app


def _load_config() -> tuple[CoworkConfig, Path | None]:
    """Load config from ``COWORK_CONFIG_PATH``. Hosted deployments
    must have a TOML — the env-only fallback (used by the SU
    sidecar) doesn't support ``[auth].keys``."""
    path = os.environ.get("COWORK_CONFIG_PATH")
    if not path:
        raise SystemExit(
            "cowork-server-web requires COWORK_CONFIG_PATH pointing at a "
            "cowork.toml with [auth].keys configured.",
        )
    p = Path(path)
    if not p.exists():
        raise SystemExit(
            f"COWORK_CONFIG_PATH={path!r} does not exist.",
        )
    cfg = CoworkConfig.load(p)
    if not cfg.auth.keys:
        raise SystemExit(
            f"cowork.toml at {path} has empty [auth].keys; "
            f"multi-user deployments must configure at least one key.",
        )
    print(
        f"[config] loaded {path} — auth: multi-user "
        f"({len(cfg.auth.keys)} keys)",
        flush=True,
    )
    return cfg, p


def main() -> None:
    cfg, config_path = _load_config()
    token = os.environ.get("COWORK_TOKEN") or cfg.auth.token or generate_token()
    host = cfg.server.host
    port = int(os.environ.get("COWORK_PORT", 0)) or cfg.server.port or 8000

    app = create_app(cfg, token=token, config_path=config_path)
    print(f"[server] listening on http://{host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
