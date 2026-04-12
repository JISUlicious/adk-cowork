"""Tests for http.fetch and search.web (M1.6)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest
from cowork_core.config import CoworkConfig
from cowork_core.skills import SkillRegistry
from cowork_core.tools import COWORK_CONTEXT_KEY, CoworkToolContext
from cowork_core.tools.http import http_fetch
from cowork_core.tools.search import search_web
from cowork_core.workspace import ProjectRegistry, Workspace


@pytest.fixture
def tctx(tmp_path: Path) -> MagicMock:
    ws = Workspace(root=tmp_path)
    reg = ProjectRegistry(workspace=ws)
    project = reg.create("Kilo")
    session = reg.new_session("kilo")
    ctx = CoworkToolContext(
        workspace=ws,
        registry=reg,
        project=project,
        session=session,
        config=CoworkConfig(),
        skills=SkillRegistry(),
    )
    fake = MagicMock()
    fake.state = {COWORK_CONTEXT_KEY: ctx}
    return fake


def test_http_rejects_bad_scheme(tctx: MagicMock) -> None:
    assert "error" in http_fetch("file:///etc/passwd", tctx)
    assert "error" in http_fetch("ftp://example.com", tctx)


def test_http_rejects_missing_host(tctx: MagicMock) -> None:
    assert "error" in http_fetch("http://", tctx)


def test_http_fetch_ok(tctx: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/plain"},
            content=b"hello world",
        )

    transport = httpx.MockTransport(handler)
    original = httpx.Client.__init__

    def patched(self: httpx.Client, *args: object, **kwargs: object) -> None:
        kwargs["transport"] = transport  # type: ignore[index]
        original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx.Client, "__init__", patched)
    out = http_fetch("https://example.com/", tctx)
    assert out["status"] == 200
    assert out["content"] == "hello world"
    assert out["truncated"] is False


def test_http_error_surfaced(tctx: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    transport = httpx.MockTransport(handler)
    original = httpx.Client.__init__

    def patched(self: httpx.Client, *args: object, **kwargs: object) -> None:
        kwargs["transport"] = transport  # type: ignore[index]
        original(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(httpx.Client, "__init__", patched)
    out = http_fetch("https://example.com/", tctx)
    assert "error" in out


def test_search_rejects_empty(tctx: MagicMock) -> None:
    assert "error" in search_web("", tctx)
    assert "error" in search_web("   ", tctx)


def test_search_web_dispatches_ddg(tctx: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int]] = []

    def fake(query: str, max_results: int) -> list[dict[str, str]]:
        calls.append((query, max_results))
        return [
            {"title": "T1", "url": "https://a", "snippet": "S1"},
            {"title": "T2", "url": "https://b", "snippet": "S2"},
        ]

    monkeypatch.setattr("cowork_core.tools.search.web._ddg_search", fake)
    out = search_web("cowork agent", tctx, max_results=2)
    assert calls == [("cowork agent", 2)]
    assert out["provider"] == "duckduckgo"
    results = out["results"]
    assert isinstance(results, list)
    assert len(results) == 2


def test_search_provider_error_surfaced(tctx: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(query: str, max_results: int) -> list[dict[str, str]]:
        raise RuntimeError("rate limited")

    monkeypatch.setattr("cowork_core.tools.search.web._ddg_search", boom)
    out = search_web("hi", tctx)
    assert "error" in out
