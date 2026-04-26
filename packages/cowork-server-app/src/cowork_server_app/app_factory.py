"""``create_app`` for the single-user sidecar backend.

Calls into ``cowork_server.app.create_app`` with ``mode="app"`` so
managed-project and managed-files routes are filtered out. The
shared base owns route definitions; this package owns the SU
deployment shape (no auth keys, sidecar token, local-dir focus).

Future SU-only routes (e.g. native file-picker integration with
the Tauri shell) land directly in this package — register them on
the returned ``FastAPI`` instance after ``create_app`` returns,
without touching ``cowork-server`` at all.
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
    """Build the single-user FastAPI app.

    Refuses to start if ``cfg.auth.keys`` is non-empty — the
    sidecar backend isn't multi-user-aware. Use ``cowork-server-web``
    for hosted deployments instead.
    """
    cfg = cfg or CoworkConfig()
    if cfg.auth.keys:
        raise ValueError(
            "cowork-server-app is the single-user sidecar backend; "
            "cfg.auth.keys must be empty. Use cowork-server-web for "
            "multi-user deployments.",
        )
    return _shared_create_app(
        cfg=cfg, token=token, config_path=config_path, mode="app",
    )
