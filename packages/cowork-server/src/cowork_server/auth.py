"""Local single-user token auth for ``cowork-server``.

On startup the server generates a random token and requires it on every HTTP
and WebSocket request. Hosted multi-user auth is post-v0.1.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException


def generate_token() -> str:
    return secrets.token_urlsafe(32)


class TokenGuard:
    """FastAPI dependency that validates the ``x-cowork-token`` header."""

    def __init__(self, token: str) -> None:
        self._token = token

    def __call__(self, x_cowork_token: str = Header(default="")) -> None:
        if not secrets.compare_digest(x_cowork_token, self._token):
            raise HTTPException(status_code=401, detail="invalid token")
