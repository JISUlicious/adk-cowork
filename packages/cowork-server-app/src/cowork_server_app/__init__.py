"""Cowork sidecar server — single-user backend for cowork-cli + cowork-app.

Thin wrapper around ``cowork_server.app.create_app(mode="app")``.
Registers the common routes + local-dir browsing + single-user
config edits; managed-project / managed-files routes are filtered
out so they don't appear in the OpenAPI surface or accept requests.

Spawned by ``cowork-cli`` and the Tauri desktop sidecar via
``python -m cowork_server_app`` — see ``__main__.py``.
"""

from __future__ import annotations

from cowork_server_app.app_factory import create_app

__all__ = ["create_app"]
