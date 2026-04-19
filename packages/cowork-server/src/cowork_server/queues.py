"""Deprecated — re-export shim.

The event-bus protocol and implementations moved to ``cowork_server.bus`` in
Phase 3a. Import from there directly; this module is kept only so existing
callers don't break mid-refactor. Slated for removal after Phase 3 ships.
"""

from cowork_server.bus import EventBus, InMemoryEventBus

__all__ = ["EventBus", "InMemoryEventBus"]
