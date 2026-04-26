"""Authentication guards for ``cowork-server``.

Supports two modes via config:

- **token** (default, sidecar): Single random token, backward-compatible.
- **multi-key**: Dict of ``api_key → user label`` for multi-user setups.

Both modes use ``x-cowork-token`` header or ``?token=`` query param. The
``AuthGuard`` protocol allows future implementations (JWT, OAuth) to be
swapped in without changing app.py.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from fastapi import Header, HTTPException, Query


def generate_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class UserIdentity:
    """Authenticated user returned by all guard implementations."""

    user_id: str
    label: str


@runtime_checkable
class AuthGuard(Protocol):
    """FastAPI dependency protocol for request authentication."""

    def __call__(
        self,
        x_cowork_token: str = Header(default=""),
        token: str = Query(default=""),
    ) -> UserIdentity: ...


class TokenGuard:
    """Single-token guard for sidecar/desktop mode (backward-compatible).

    All requests authenticate as ``user_id="local"``.
    """

    def __init__(self, token: str) -> None:
        self._token = token

    def __call__(
        self,
        x_cowork_token: str = Header(default=""),
        token: str = Query(default=""),
    ) -> UserIdentity:
        provided = x_cowork_token or token
        if not secrets.compare_digest(provided, self._token):
            raise HTTPException(status_code=401, detail="invalid token")
        return UserIdentity(user_id="local", label="local")


class MultiKeyGuard:
    """Multi-key guard mapping API keys to user identities.

    Each key in ``keys`` maps to a user label. The user_id is derived
    from the key itself (first 16 chars of its hash) for stability.
    """

    def __init__(self, keys: dict[str, str]) -> None:
        # Build lookup: api_key → UserIdentity
        self._lookup: dict[str, UserIdentity] = {}
        for api_key, label in keys.items():
            # Stable user_id from the key
            uid = secrets.token_hex(0)  # placeholder
            import hashlib
            uid = hashlib.sha256(api_key.encode()).hexdigest()[:16]
            self._lookup[api_key] = UserIdentity(user_id=uid, label=label)

    def __call__(
        self,
        x_cowork_token: str = Header(default=""),
        token: str = Query(default=""),
    ) -> UserIdentity:
        provided = x_cowork_token or token
        # Constant-time comparison against each key to prevent timing attacks
        matched: UserIdentity | None = None
        for key, identity in self._lookup.items():
            if secrets.compare_digest(provided, key):
                matched = identity
        if matched is None:
            raise HTTPException(status_code=401, detail="invalid token")
        return matched


def create_guard(
    token: str,
    keys: dict[str, str] | None = None,
) -> TokenGuard | MultiKeyGuard:
    """Factory: returns MultiKeyGuard if keys are configured, else TokenGuard."""
    if keys:
        return MultiKeyGuard(keys)
    return TokenGuard(token)


def is_operator(cfg: "CoworkConfig", user: UserIdentity) -> bool:
    """Slice U1 — return True iff the calling user is the configured
    operator for workspace-wide settings edits.

    Single-user mode: there's only one user (``label="local"``), and
    they're the operator by definition. The operator gate doesn't
    fire for SU PUT routes — but we return True here anyway for
    consistency with the health surface.

    Multi-user mode: ``cfg.auth.operator`` must match the caller's
    ``user.label`` exactly. Empty operator field = no operator
    configured (everyone gets 403). R3 defence-in-depth: refuses if
    multiple keys somehow share the operator's label (the validator
    on ``AuthConfig`` should have prevented this at config load, but
    we double-check here in case the validator is bypassed by a
    test harness).
    """
    if not cfg.auth.keys:
        # Single-user mode — the local user is the operator by
        # definition. Most SU code paths don't consult is_operator at
        # all (they bypass the gate via the runtime.multi_user check)
        # but exposing this predicate consistently keeps the health
        # surface uniform across modes.
        return True
    if not cfg.auth.operator:
        return False
    matches = [
        key for key, label in cfg.auth.keys.items()
        if label == cfg.auth.operator
    ]
    if len(matches) != 1:
        # 0: nobody is the operator (operator name doesn't match any key)
        # >1: ambiguous — refuse defensively (R3)
        return False
    return user.label == cfg.auth.operator


# Forward-ref import resolution — ``CoworkConfig`` is needed only for
# typing, and importing it at module level creates a cycle with
# cowork_core.config. Keep it as a TYPE_CHECKING import.
from typing import TYPE_CHECKING  # noqa: E402

if TYPE_CHECKING:
    from cowork_core.config import CoworkConfig
