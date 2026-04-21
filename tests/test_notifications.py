"""Notification store smoke tests.

Covers the in-memory default only — the Protocol exists so a distributed
deployment can swap in a shared backend later without retesting the
route / producer layer.
"""

from __future__ import annotations

from cowork_core.notifications import InMemoryNotificationStore


def test_add_list_roundtrip() -> None:
    store = InMemoryNotificationStore()
    n1 = store.add("alice", "turn_complete", "Turn complete", session_id="s1")
    n2 = store.add("alice", "error", "boom", session_id="s2")
    n3 = store.add("bob", "turn_complete", "Turn complete", session_id="s9")

    # Most-recent-first per user; bob's entry must not leak to alice.
    alice = store.list("alice")
    assert [n.id for n in alice] == [n2.id, n1.id]
    assert store.list("bob") == [n3]
    assert store.list("nobody") == []


def test_mark_read_scoped_to_user() -> None:
    store = InMemoryNotificationStore()
    n = store.add("alice", "approval_needed", "shell_run needs approval")
    # Wrong user can't mark another user's entry read.
    assert store.mark_read("bob", n.id) is False
    assert store.list("alice")[0].read is False

    assert store.mark_read("alice", n.id) is True
    assert store.list("alice")[0].read is True

    # Unknown id is a soft no.
    assert store.mark_read("alice", "ntf-missing") is False


def test_clear_drops_only_caller() -> None:
    store = InMemoryNotificationStore()
    store.add("alice", "turn_complete", "a1")
    store.add("alice", "turn_complete", "a2")
    store.add("bob", "turn_complete", "b1")

    removed = store.clear("alice")
    assert removed == 2
    assert store.list("alice") == []
    assert len(store.list("bob")) == 1


def test_to_wire_shape() -> None:
    store = InMemoryNotificationStore()
    n = store.add("alice", "error", "fail", session_id="s1", project="demo")
    wire = n.to_wire()
    assert set(wire.keys()) == {
        "id", "kind", "text", "session_id", "project", "created_at", "read",
    }
    assert wire["kind"] == "error"
    assert wire["session_id"] == "s1"
    assert wire["project"] == "demo"
    assert wire["read"] is False
