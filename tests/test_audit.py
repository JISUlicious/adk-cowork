"""Tests for the V1 audit subsystem.

AuditSink protocol + SqliteAuditSink + per-tool capture policy +
hook callbacks + /v1/audit query route + settings_change row from
the workspace-settings PUT path.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from cowork_core import CoworkConfig
from cowork_core.audit import (
    AuditEntry,
    NullAuditSink,
    SqliteAuditSink,
    open_audit_db,
    serialize_args,
    serialize_result,
)
from cowork_core.audit_policy import (
    DEFAULT_POLICY,
    TOOL_AUDIT_POLICIES,
    ToolAuditPolicy,
    policy_for,
)
from cowork_core.config import AuthConfig, WorkspaceConfig
from cowork_core.policy.hooks import make_audit_callbacks
from cowork_core.tools.base import COWORK_CONTEXT_KEY, CoworkToolContext
from cowork_server.app import create_app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolate_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Redirect HOME so single-user FS UserStore writes don't pollute
    the developer's real ``~/.config/cowork/``."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    return fake_home


# ──────────────── ToolAuditPolicy ────────────────


def test_policy_for_known_tool() -> None:
    p = policy_for("fs_read")
    assert "path" in p.args_keys
    assert p.capture_result_kind == "summary"


def test_policy_for_unknown_tool_uses_default() -> None:
    p = policy_for("nonexistent_tool")
    assert p == DEFAULT_POLICY
    # Defaults capture nothing structured.
    assert p.args_keys == frozenset()
    assert p.capture_result_kind == "none"


def test_policy_table_is_conservative() -> None:
    """No tool defaults to 'full' capture — full result-logging
    must be opted in by the operator (via cfg, Tier F). Catches
    accidental full-capture additions in PR review."""
    for name, policy in TOOL_AUDIT_POLICIES.items():
        assert policy.capture_result_kind != "full", (
            f"tool {name!r} captures full results — must be opted in "
            f"by operator, not default-shipped"
        )


# ──────────────── serialize_args ────────────────


def test_serialize_args_whitelist() -> None:
    policy = ToolAuditPolicy(args_keys=frozenset({"path"}))
    out = serialize_args(
        {"path": "/etc/passwd", "secret": "p@ss"},
        policy,
    )
    assert out is not None
    parsed = json.loads(out)
    assert "path" in parsed
    assert "secret" not in parsed


def test_serialize_args_truncates_long_values() -> None:
    policy = ToolAuditPolicy(
        args_keys=frozenset({"code"}),
        truncate_arg_to_bytes=20,
    )
    out = serialize_args({"code": "x" * 1000}, policy)
    assert out is not None
    parsed = json.loads(out)
    assert len(parsed["code"]) <= 20
    assert parsed["code"].endswith("…")


def test_serialize_args_empty_whitelist_returns_none() -> None:
    out = serialize_args({"path": "x"}, DEFAULT_POLICY)
    assert out is None


def test_serialize_args_missing_keys_dropped() -> None:
    policy = ToolAuditPolicy(args_keys=frozenset({"path", "mode"}))
    out = serialize_args({"path": "/x"}, policy)
    assert out is not None
    parsed = json.loads(out)
    assert "path" in parsed
    assert "mode" not in parsed


# ──────────────── serialize_result ────────────────


def test_serialize_result_none_kind() -> None:
    policy = ToolAuditPolicy(capture_result_kind="none")
    rj, et = serialize_result({"content": "secret stuff"}, policy)
    assert rj is not None
    parsed = json.loads(rj)
    assert parsed == {"ok": True}
    assert et is None


def test_serialize_result_summary_extracts_indicators_only() -> None:
    """Summary captures indicator keys only — never arbitrary content
    fields. Catches regressions that would let file content / memory
    page bodies / stdout leak into audit summaries."""
    policy = ToolAuditPolicy(capture_result_kind="summary")
    rj, et = serialize_result(
        {"exit_code": 0, "stdout": "x" * 5000, "status": "ok"},
        policy,
    )
    assert rj is not None
    parsed = json.loads(rj)
    assert parsed["ok"] is True
    assert parsed["exit_code"] == 0
    assert parsed["status"] == "ok"
    # Stdout content NOT captured.
    assert "stdout" not in parsed


def test_serialize_result_summary_excludes_arbitrary_content() -> None:
    """Even small payloads with unknown keys don't leak into the
    summary. fs_read's content, memory_read's content, search results,
    etc. all stay out."""
    policy = ToolAuditPolicy(capture_result_kind="summary")
    rj, _ = serialize_result(
        {"content": "secret stuff", "size": 12},
        policy,
    )
    assert rj is not None
    parsed = json.loads(rj)
    # size IS an indicator key.
    assert parsed["size"] == 12
    # content is NOT.
    assert "content" not in parsed
    assert "secret" not in (rj or "")


def test_serialize_result_extracts_error_text() -> None:
    policy = ToolAuditPolicy(capture_result_kind="none")
    rj, et = serialize_result(
        {"error": "permission denied"}, policy,
    )
    assert rj is not None
    parsed = json.loads(rj)
    assert parsed["ok"] is False
    assert et == "permission denied"


def test_serialize_result_full_kind_truncates_at_4kb() -> None:
    policy = ToolAuditPolicy(capture_result_kind="full")
    big = {"data": "x" * 10000}
    rj, _ = serialize_result(big, policy)
    assert rj is not None
    assert len(rj) <= 4096


# ──────────────── SqliteAuditSink ────────────────


def test_sqlite_audit_sink_round_trip() -> None:
    conn = open_audit_db(":memory:")
    sink = SqliteAuditSink(conn)
    sink.record(AuditEntry(
        ts="2026-04-26T10:00:00Z",
        user_id="alice",
        kind="tool_call",
        tool_name="fs_read",
        session_id="sess-1",
        args_json='{"path": "/x"}',
    ))
    rows = sink.query()
    assert len(rows) == 1
    assert rows[0].user_id == "alice"
    assert rows[0].tool_name == "fs_read"


def test_sqlite_audit_sink_query_filters() -> None:
    conn = open_audit_db(":memory:")
    sink = SqliteAuditSink(conn)
    for i, (uid, tool) in enumerate([
        ("alice", "fs_read"),
        ("alice", "shell_run"),
        ("bob", "fs_read"),
    ]):
        sink.record(AuditEntry(
            ts=f"2026-04-26T10:{i:02d}:00Z",
            user_id=uid,
            kind="tool_call",
            tool_name=tool,
        ))

    # Newest-first by default.
    rows = sink.query()
    assert len(rows) == 3
    assert rows[0].user_id == "bob"

    # Filter by user.
    alice_rows = sink.query(user_id="alice")
    assert len(alice_rows) == 2
    assert all(r.user_id == "alice" for r in alice_rows)

    # Filter by tool.
    fs_rows = sink.query(tool_name="fs_read")
    assert len(fs_rows) == 2

    # Filter by user AND tool.
    alice_fs = sink.query(user_id="alice", tool_name="fs_read")
    assert len(alice_fs) == 1


def test_sqlite_audit_sink_limit_cap() -> None:
    conn = open_audit_db(":memory:")
    sink = SqliteAuditSink(conn)
    for i in range(50):
        sink.record(AuditEntry(
            ts=f"2026-04-26T10:00:{i:02d}Z",
            user_id="alice",
            kind="tool_call",
            tool_name="fs_read",
        ))
    rows = sink.query(limit=10)
    assert len(rows) == 10
    # Hard cap.
    rows = sink.query(limit=99999)
    assert len(rows) == 50  # Only 50 rows total


def test_sqlite_audit_sink_record_swallows_errors() -> None:
    """Audit failures must not crash the agent."""
    conn = open_audit_db(":memory:")
    sink = SqliteAuditSink(conn)
    conn.close()  # poison the connection
    # Should not raise.
    sink.record(AuditEntry(
        ts="x", user_id="y", kind="z", tool_name="w",
    ))


def test_null_audit_sink_drops_everything() -> None:
    sink = NullAuditSink()
    sink.record(AuditEntry(ts="x", user_id="y", kind="z", tool_name="w"))
    assert sink.query() == []


# ──────────────── Hook callbacks ────────────────


def test_audit_callbacks_record_to_sink_via_context() -> None:
    """make_audit_callbacks reads the sink off ctx.audit_sink and
    records both before + after rows."""
    conn = open_audit_db(":memory:")
    sink = SqliteAuditSink(conn)

    cowork_ctx = MagicMock()
    cowork_ctx.user_id = "alice"
    cowork_ctx.session = MagicMock(id="sess-1", transcript_path=None)
    cowork_ctx.project = MagicMock(root="/tmp/proj")
    cowork_ctx.audit_sink = sink

    fake_tool = MagicMock(name="fs_read")
    fake_tool.name = "fs_read"
    tool_ctx = MagicMock()
    tool_ctx.state = {COWORK_CONTEXT_KEY: cowork_ctx}

    # Patch isinstance check by making cowork_ctx pass it.
    import cowork_core.policy.hooks as hooks_mod
    orig_get = hooks_mod._get_cowork_ctx
    hooks_mod._get_cowork_ctx = lambda tc: cowork_ctx
    try:
        before, after = make_audit_callbacks()
        before(fake_tool, {"path": "/etc/passwd"}, tool_ctx)
        after(fake_tool, {"path": "/etc/passwd"}, tool_ctx, {"content": "secret"})
    finally:
        hooks_mod._get_cowork_ctx = orig_get

    rows = sink.query()
    assert len(rows) == 2
    # Order: newest-first → after row first.
    assert rows[0].kind == "tool_result"
    assert rows[1].kind == "tool_call"
    # Per-tool policy: fs_read captures path arg.
    args = json.loads(rows[1].args_json or "{}")
    assert "path" in args
    # Per-tool policy: fs_read summary doesn't capture full content.
    result = json.loads(rows[0].result_json or "{}")
    assert result["ok"] is True
    # No raw 'secret' content in summary.
    assert "secret" not in (rows[0].result_json or "")


# ──────────────── Build-runtime integration ────────────────


def test_build_runtime_creates_audit_sink_in_su(tmp_path: Path) -> None:
    """SU mode → audit.db at <workspace>/audit.db."""
    from cowork_core.runner import build_runtime

    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    runtime = build_runtime(cfg)
    assert isinstance(runtime.audit_sink, SqliteAuditSink)
    assert (tmp_path / "audit.db").is_file()


def test_build_runtime_creates_audit_sink_in_mu(tmp_path: Path) -> None:
    """MU mode → audit_log table inside the existing multiuser.db."""
    from cowork_core.runner import build_runtime

    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(keys={"k1": "alice"}),
    )
    runtime = build_runtime(cfg)
    assert isinstance(runtime.audit_sink, SqliteAuditSink)
    # Single shared file with the other MU stores.
    assert (tmp_path / "multiuser.db").is_file()
    assert not (tmp_path / "audit.db").exists()


# ──────────────── /v1/audit route ────────────────


def test_audit_route_returns_records_in_su(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    cfg_path = tmp_path / "cowork.toml"
    cfg_path.write_text("[model]\nmodel = 'x'\n", encoding="utf-8")
    app = create_app(cfg, token="t", config_path=cfg_path)
    client = TestClient(app)

    # Trigger a settings_change row by saving a model edit.
    client.put(
        "/v1/config/model",
        headers={"x-cowork-token": "t"},
        json={"model": "qwen-7b"},
    )
    r = client.get("/v1/audit", headers={"x-cowork-token": "t"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["entries"]) >= 1
    settings_rows = [
        e for e in body["entries"] if e["kind"] == "settings_change"
    ]
    assert len(settings_rows) == 1
    assert settings_rows[0]["tool_name"] == "config.model"


def test_audit_route_403s_non_operator_in_mu(tmp_path: Path) -> None:
    cfg = CoworkConfig(
        workspace=WorkspaceConfig(root=tmp_path),
        auth=AuthConfig(
            keys={"alice-k": "alice", "bob-k": "bob"},
            operator="alice",
        ),
    )
    client = TestClient(create_app(cfg, token="t"))
    # Bob is not the operator → 403.
    r = client.get("/v1/audit", headers={"x-cowork-token": "bob-k"})
    assert r.status_code == 403
    # Alice is the operator → 200.
    r = client.get("/v1/audit", headers={"x-cowork-token": "alice-k"})
    assert r.status_code == 200


def test_audit_route_filters_via_query_params(tmp_path: Path) -> None:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    cfg_path = tmp_path / "cowork.toml"
    cfg_path.write_text("[model]\nmodel = 'x'\n", encoding="utf-8")
    app = create_app(cfg, token="t", config_path=cfg_path)
    client = TestClient(app)

    client.put(
        "/v1/config/model",
        headers={"x-cowork-token": "t"},
        json={"model": "qwen-7b"},
    )
    # Filter to model section only.
    r = client.get(
        "/v1/audit?tool_name=config.model",
        headers={"x-cowork-token": "t"},
    )
    assert r.status_code == 200
    body = r.json()
    assert all(e["tool_name"] == "config.model" for e in body["entries"])
    # Filter to a non-matching tool — empty.
    r = client.get(
        "/v1/audit?tool_name=fs_read",
        headers={"x-cowork-token": "t"},
    )
    assert r.json()["entries"] == []
