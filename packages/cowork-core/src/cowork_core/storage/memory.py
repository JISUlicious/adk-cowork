"""In-memory ``UserStore`` / ``ProjectStore`` — for tests + ephemeral
demos.

Zero-arg constructors keep test fixtures small (mirrors
``InMemoryApprovalStore`` from ``cowork_core.approvals``). Backed by
plain dicts; thread-unsafe by design — tests don't share contexts
across threads.
"""

from __future__ import annotations

from cowork_core.storage.protocols import ProjectStore, UserStore


class InMemoryUserStore(UserStore):
    def __init__(self) -> None:
        self._data: dict[tuple[str, str], bytes] = {}

    def read(self, user_id: str, key: str) -> bytes | None:
        return self._data.get((user_id, key))

    def write(self, user_id: str, key: str, value: bytes) -> None:
        self._data[(user_id, key)] = value

    def list(self, user_id: str, prefix: str = "") -> list[str]:
        return sorted(
            key
            for (uid, key) in self._data
            if uid == user_id and key.startswith(prefix)
        )

    def delete(self, user_id: str, key: str) -> None:
        self._data.pop((user_id, key), None)


class InMemoryProjectStore(ProjectStore):
    def __init__(self) -> None:
        self._data: dict[tuple[str, str, str], bytes] = {}

    def read(self, user_id: str, project: str, key: str) -> bytes | None:
        return self._data.get((user_id, project, key))

    def write(
        self, user_id: str, project: str, key: str, value: bytes,
    ) -> None:
        self._data[(user_id, project, key)] = value

    def list(
        self, user_id: str, project: str, prefix: str = "",
    ) -> list[str]:
        return sorted(
            key
            for (uid, proj, key) in self._data
            if uid == user_id and proj == project and key.startswith(prefix)
        )

    def delete(self, user_id: str, project: str, key: str) -> None:
        self._data.pop((user_id, project, key), None)
