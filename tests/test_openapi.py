"""OpenAPI / Swagger surface smoke tests (Slice S1).

Pins the docs surface so it doesn't regress silently:

* `/docs`, `/redoc`, `/openapi.json` reachable without auth (FastAPI
  defaults; we don't auth-gate the docs themselves).
* App metadata populated (title, description, version, openapi_tags).
* Every HTTP route carries at least one tag — no flat ``"default"``
  group.
* ``cowork-token`` security scheme advertised so Swagger's Authorize
  button appears.

These are static-shape checks — they don't exercise route handlers.
"""

from __future__ import annotations

from pathlib import Path

from cowork_core import CoworkConfig
from cowork_core.config import WorkspaceConfig
from cowork_server.app import create_app
from fastapi.testclient import TestClient


def _client(tmp_path: Path) -> TestClient:
    cfg = CoworkConfig(workspace=WorkspaceConfig(root=tmp_path))
    return TestClient(create_app(cfg, token="t"))


def test_openapi_docs_reachable(tmp_path: Path) -> None:
    client = _client(tmp_path)
    # FastAPI defaults expose these without auth.
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_openapi_metadata_populated(tmp_path: Path) -> None:
    schema = _client(tmp_path).get("/openapi.json").json()
    info = schema["info"]
    assert info["title"] == "cowork-server"
    assert info["description"], "openapi description must be non-empty"
    # Version comes from importlib.metadata or the fallback.
    assert info["version"], "openapi version must be non-empty"
    # All ten declared tag groups present.
    tag_names = {t["name"] for t in schema.get("tags", [])}
    expected = {
        "health", "sessions", "policy", "approvals", "notifications",
        "search", "projects", "files", "local-dir", "streams",
    }
    assert tag_names == expected, f"missing or extra tags: {tag_names ^ expected}"


def test_every_http_route_is_tagged(tmp_path: Path) -> None:
    """No route ends up in the implicit ``default`` group."""
    schema = _client(tmp_path).get("/openapi.json").json()
    untagged: list[str] = []
    for path, methods in schema.get("paths", {}).items():
        for method, op in methods.items():
            if method.lower() not in {"get", "post", "put", "patch", "delete"}:
                continue
            if not op.get("tags"):
                untagged.append(f"{method.upper()} {path}")
    assert not untagged, f"untagged routes: {untagged}"


def test_security_scheme_advertised(tmp_path: Path) -> None:
    schema = _client(tmp_path).get("/openapi.json").json()
    schemes = schema.get("components", {}).get("securitySchemes", {})
    assert "cowork-token" in schemes, "cowork-token security scheme missing"
    cowork = schemes["cowork-token"]
    assert cowork["type"] == "apiKey"
    assert cowork["in"] == "header"
    assert cowork["name"] == "x-cowork-token"


def test_request_bodies_have_named_schemas(tmp_path: Path) -> None:
    """S2 invariant: every JSON request body resolves to a named
    component schema (not an inline `{}` from the legacy `dict[str, Any]`
    handlers). Multipart upload routes are exempt — UploadFile bodies
    don't produce a $ref."""
    schema = _client(tmp_path).get("/openapi.json").json()
    components = schema.get("components", {}).get("schemas", {})
    untyped: list[str] = []
    for path, methods in schema.get("paths", {}).items():
        for method, op in methods.items():
            if method.lower() not in {"post", "put", "patch"}:
                continue
            body = op.get("requestBody")
            if not body:
                continue
            content = (body.get("content") or {}).get("application/json")
            if not content:
                continue  # multipart / form-data is fine
            schema_ref = content.get("schema", {})
            if "$ref" not in schema_ref and "anyOf" not in schema_ref:
                untyped.append(f"{method.upper()} {path}")
    assert not untyped, f"routes still using inline body schema: {untyped}"
    # And the components dict has the policy + session models we declared.
    for expected in (
        "CreateSessionRequest", "ResumeSessionRequest",
        "SetPolicyModeRequest", "SetPythonExecRequest",
        "SetToolAllowlistRequest", "SetAutoRouteRequest",
        "GrantApprovalRequest", "SendMessageRequest",
        "PatchSessionRequest", "PatchLocalSessionRequest",
        "CreateProjectRequest",
    ):
        assert expected in components, f"missing schema: {expected}"


def test_policy_responses_use_literal_unions(tmp_path: Path) -> None:
    """Policy mode + python_exec endpoints must enumerate their valid
    values in the schema so Swagger renders an enum dropdown."""
    schema = _client(tmp_path).get("/openapi.json").json()
    components = schema.get("components", {}).get("schemas", {})
    mode_props = components["PolicyModeResponse"]["properties"]["mode"]
    # Pydantic v2 renders Literal as `enum`.
    assert set(mode_props.get("enum", [])) == {"plan", "work", "auto"}
    pe_props = components["PythonExecResponse"]["properties"]["policy"]
    assert set(pe_props.get("enum", [])) == {"confirm", "allow", "deny"}
