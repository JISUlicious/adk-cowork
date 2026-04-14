"""FastAPI application factory for ``cowork-server``.

Routes live inline for M0/M1 to keep the surface small; they split into
``routes/`` modules once project/session CRUD and previews land in M2.
"""

from __future__ import annotations

import asyncio
from typing import Any

from cowork_core import CoworkConfig, CoworkRuntime, PreviewCache, build_runtime
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from google.adk.events.event import Event
from google.genai import types as genai_types

from cowork_server.auth import TokenGuard, generate_token
from cowork_server.transport import event_to_payload, events_to_history


def create_app(cfg: CoworkConfig | None = None, token: str | None = None) -> FastAPI:
    cfg = cfg or CoworkConfig()
    token = token or generate_token()
    guard = TokenGuard(token)
    runtime: CoworkRuntime = build_runtime(cfg)

    cache_dir = runtime.workspace.root / "global" / ".preview-cache"
    preview_cache = PreviewCache(cache_dir)

    queues: dict[str, asyncio.Queue[str]] = {}
    tasks: set[asyncio.Task[None]] = set()

    app = FastAPI(title="cowork-server")
    # The desktop WebView (tauri://localhost on macOS, https://tauri.localhost on
    # Windows) and the Vite dev server (http://localhost:5173) both hit us
    # cross-origin. Auth is still enforced by the x-cowork-token header guard —
    # CORS only governs *which origins the browser lets see the response*.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^(tauri://.*|https?://(localhost|127\.0\.0\.1)(:\d+)?|https://tauri\.localhost)$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.token = token
    app.state.runtime = runtime
    app.state.cfg = cfg
    app.state.queues = queues
    app.state.tasks = tasks
    app.state.preview_cache = preview_cache

    @app.get("/v1/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "tools": runtime.tools.names(),
            "skills": runtime.skills.names(),
        }

    @app.get("/v1/policy/mode", dependencies=[Depends(guard)])
    async def get_policy_mode() -> dict[str, str]:
        return {"mode": cfg.policy.mode}

    @app.put("/v1/policy/mode", dependencies=[Depends(guard)])
    async def set_policy_mode(body: dict[str, Any]) -> dict[str, str]:
        mode = body.get("mode", "")
        if mode not in ("plan", "work", "auto"):
            raise HTTPException(status_code=400, detail="mode must be plan, work, or auto")
        cfg.policy.mode = mode
        return {"mode": cfg.policy.mode}

    @app.post("/v1/sessions", dependencies=[Depends(guard)])
    async def create_session(body: dict[str, Any] | None = None) -> dict[str, str]:
        project_name = None
        if body is not None:
            project_name = body.get("project")
        project, session, adk_sid = await runtime.open_session(project_name=project_name)
        queues[adk_sid] = asyncio.Queue()
        return {
            "session_id": adk_sid,
            "project": project.slug,
            "cowork_session_id": session.id,
        }

    @app.post("/v1/sessions/{session_id}/resume", dependencies=[Depends(guard)])
    async def resume_session(session_id: str, body: dict[str, Any]) -> dict[str, str]:
        project_slug = body.get("project", "")
        if not project_slug:
            raise HTTPException(status_code=400, detail="project is required")
        try:
            project, session, adk_sid = await runtime.resume_session(
                project_slug=project_slug, session_id=session_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        queues.setdefault(adk_sid, asyncio.Queue())
        return {
            "session_id": adk_sid,
            "project": project.slug,
            "cowork_session_id": session.id,
        }

    @app.get("/v1/sessions/{session_id}/history", dependencies=[Depends(guard)])
    async def session_history(session_id: str) -> list[dict[str, Any]]:
        svc = runtime.runner.session_service
        existing = await svc.get_session(
            app_name=getattr(runtime.runner, "app_name", "cowork"),
            user_id="local",
            session_id=session_id,
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="session not found")
        return events_to_history(getattr(existing, "events", []) or [])

    @app.post("/v1/sessions/{session_id}/messages", dependencies=[Depends(guard)])
    async def send_message(session_id: str, body: dict[str, Any]) -> dict[str, str]:
        text = body.get("text", "")
        queue = queues.get(session_id)
        if queue is None:
            raise HTTPException(status_code=404, detail="unknown session")
        task = asyncio.create_task(_run_turn(runtime.runner, queue, session_id, str(text)))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return {"status": "accepted"}

    @app.get("/v1/sessions/{session_id}/events/stream", dependencies=[Depends(guard)])
    async def events_sse(session_id: str) -> StreamingResponse:
        """Stream ADK events as SSE.

        Wire contract matches Google ADK's ``/run_sse``: each ``data:``
        line is a full Event JSON. Stream closes after an event with
        ``turnComplete: true`` — the same signal ADK uses.
        """
        queue = queues.get(session_id)
        if queue is None:
            raise HTTPException(status_code=404, detail="unknown session")

        async def gen() -> Any:
            import json as _json
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                yield f"data: {payload}\n\n"
                try:
                    done = _json.loads(payload).get("turnComplete") is True
                except (ValueError, AttributeError):
                    done = False
                if done:
                    return

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.websocket("/v1/sessions/{session_id}/events")
    async def events_ws(ws: WebSocket, session_id: str) -> None:
        # Browsers can't set headers on WebSocket upgrade, so accept the token
        # from a query param as a fallback for the web/desktop UI.
        provided = ws.headers.get("x-cowork-token") or ws.query_params.get("token")
        if provided != token:
            await ws.close(code=4401)
            return
        queue = queues.get(session_id)
        if queue is None:
            await ws.close(code=4404)
            return
        await ws.accept()
        try:
            while True:
                frame = await queue.get()
                await ws.send_text(frame)
        except WebSocketDisconnect:
            return

    @app.get("/v1/projects", dependencies=[Depends(guard)])
    async def list_projects() -> list[dict[str, str]]:
        projects = runtime.projects.list()
        return [
            {"slug": p.slug, "name": p.name, "created_at": p.created_at}
            for p in projects
        ]

    @app.post("/v1/projects", dependencies=[Depends(guard)])
    async def create_project(body: dict[str, Any]) -> dict[str, str]:
        name = body.get("name", "")
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        try:
            project = runtime.projects.create(name)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"slug": project.slug, "name": project.name, "created_at": project.created_at}

    @app.get("/v1/projects/{project}/sessions", dependencies=[Depends(guard)])
    async def list_sessions(project: str) -> list[dict[str, Any]]:
        try:
            proj = runtime.projects.get(project)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        sessions_dir = proj.sessions_dir
        result: list[dict[str, Any]] = []
        if sessions_dir.is_dir():
            import tomllib
            for entry in sorted(sessions_dir.iterdir()):
                toml_path = entry / "session.toml"
                if not toml_path.exists():
                    continue
                with toml_path.open("rb") as f:
                    data = tomllib.load(f)
                result.append({
                    "id": data.get("id", entry.name),
                    "title": data.get("title") or None,
                    "created_at": data.get("created_at", ""),
                })
        return result

    @app.get("/v1/projects/{project}/files/{path:path}", dependencies=[Depends(guard)])
    async def list_files(project: str, path: str) -> list[dict[str, Any]]:
        try:
            full_path = runtime.workspace.resolve(f"projects/{project}/{path}")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not full_path.is_dir():
            raise HTTPException(status_code=404, detail=f"not a directory: {path}")
        entries: list[dict[str, Any]] = []
        for child in sorted(full_path.iterdir()):
            stat = child.stat()
            entries.append({
                "name": child.name,
                "kind": "dir" if child.is_dir() else "file",
                "size": stat.st_size if child.is_file() else None,
                "modified": stat.st_mtime,
            })
        return entries

    @app.post("/v1/projects/{project}/upload", dependencies=[Depends(guard)])
    async def upload_file(
        project: str,
        file: UploadFile = File(...),  # noqa: B008 — FastAPI dependency marker
        prefix: str = "files",
    ) -> dict[str, Any]:
        """Store an uploaded file under ``projects/<project>/<prefix>/<basename>``.

        Used by the desktop app's drag-drop handler. ``prefix`` defaults to
        ``files/`` so drops become durable project assets; pass ``scratch``
        to drop into transient session storage.
        """
        if prefix not in ("files", "scratch"):
            raise HTTPException(status_code=400, detail="prefix must be 'files' or 'scratch'")
        basename = (file.filename or "upload.bin").split("/")[-1].split("\\")[-1]
        try:
            dest = runtime.workspace.resolve(f"projects/{project}/{prefix}/{basename}")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        dest.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
                size += len(chunk)
        return {
            "name": basename,
            "path": f"{prefix}/{basename}",
            "size": size,
        }

    @app.get("/v1/projects/{project}/preview/{path:path}", dependencies=[Depends(guard)])
    async def preview_file(project: str, path: str) -> Response:
        try:
            full_path = runtime.workspace.resolve(f"projects/{project}/{path}")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not full_path.is_file():
            raise HTTPException(status_code=404, detail=f"file not found: {path}")
        try:
            result = preview_cache.get(full_path)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(
            content=result.body,
            media_type=result.content_type,
            headers={"X-Content-Hash": result.content_hash},
        )

    return app


_SERVER_AUTHOR = "cowork-server"


async def _run_turn(runner: Any, queue: asyncio.Queue[str], session_id: str, text: str) -> None:
    """Drive one ADK run and push each Event (JSON) onto ``queue``.

    Wire format mirrors ADK's own ``/run_sse`` and ``/run_live``: the full
    ``Event.model_dump_json(exclude_none=True, by_alias=True)``. The last
    event of a turn carries ``turnComplete: true``; SSE consumers close
    the stream on that flag.
    """
    import sys
    content = genai_types.Content(role="user", parts=[genai_types.Part(text=text)])
    event_count = 0
    last_event: Event | None = None
    try:
        async for event in runner.run_async(
            user_id="local", session_id=session_id, new_message=content
        ):
            event_count += 1
            last_event = event
            await queue.put(event_to_payload(event))
    except Exception as e:
        print(f"[cowork-server] run_turn error: {e!r}", file=sys.stderr, flush=True)
        err = Event(
            author=_SERVER_AUTHOR,
            invocation_id=getattr(last_event, "invocation_id", "") or "",
            error_code="INTERNAL",
            error_message=str(e),
            turn_complete=True,
        )
        await queue.put(event_to_payload(err))
        return
    finally:
        print(f"[cowork-server] run_turn done, {event_count} events", file=sys.stderr, flush=True)

    # Guarantee a final event with turn_complete=True so SSE consumers
    # know to close. ADK usually sets this on the last event already; if
    # it didn't, emit a trailing sentinel.
    if last_event is None or not getattr(last_event, "turn_complete", False):
        sentinel = Event(
            author=_SERVER_AUTHOR,
            invocation_id=getattr(last_event, "invocation_id", "") or "",
            turn_complete=True,
        )
        await queue.put(event_to_payload(sentinel))
