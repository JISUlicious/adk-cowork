"""``create_app`` for the multi-user hosted backend.

Calls into ``cowork_server.app.create_app`` with ``mode="web"`` so
local-dir browsing routes are filtered out. The shared base owns
route definitions; this package owns the MU deployment shape
(non-empty auth.keys required, future operator gate, future audit
log, …).

Future MU-only routes (e.g. operator self-service for adding /
removing keys, audit-log queries, per-tenant analytics) land
directly in this package — register them on the returned
``FastAPI`` instance after ``create_app`` returns, without touching
``cowork-server`` at all.
"""

from __future__ import annotations

from pathlib import Path

from cowork_core import CoworkConfig
from cowork_server.app import create_app as _shared_create_app
from fastapi import FastAPI


def create_app(
    cfg: CoworkConfig | None = None,
    token: str | None = None,
    config_path: Path | None = None,
) -> FastAPI:
    """Build the multi-user FastAPI app.

    Refuses to start with empty ``cfg.auth.keys``. Multi-user
    deployments must have at least one API key configured;
    deploying the web backend without auth would expose every
    session to every connection.
    """
    cfg = cfg or CoworkConfig()
    if not cfg.auth.keys:
        raise ValueError(
            "cowork-server-web is the multi-user hosted backend; "
            "cfg.auth.keys must be non-empty. Set [auth].keys in "
            "cowork.toml. Use cowork-server-app for single-user "
            "sidecar deployments.",
        )
    return _shared_create_app(
        cfg=cfg, token=token, config_path=config_path, mode="web",
    )
