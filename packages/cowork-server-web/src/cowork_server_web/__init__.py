"""Cowork hosted server — multi-user backend for the web UI.

Thin wrapper around ``cowork_server.app.create_app(mode="web")``.
Registers the common routes + managed projects + managed files +
multi-user config edits; local-dir browsing routes are filtered
out (the web frontend never opens an arbitrary workdir on the
server's machine).

Refuses to start without ``[auth].keys`` configured — multi-user
deployments require explicit API key → user_id mappings.

Spawned via ``python -m cowork_server_web`` — see ``__main__.py``.
"""

from __future__ import annotations

from cowork_server_web.app_factory import create_app

__all__ = ["create_app"]
