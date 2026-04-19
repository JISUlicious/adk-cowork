"""Deprecated — re-export shim.

The limiter protocol and implementation moved to ``cowork_server.limiter`` in
Phase 3a. Import from there directly; this module is kept only so existing
callers don't break mid-refactor. Slated for removal after Phase 3 ships.
"""

from cowork_server.limiter import ConnectionLimiter, InMemoryConnectionLimiter

__all__ = ["ConnectionLimiter", "InMemoryConnectionLimiter"]
