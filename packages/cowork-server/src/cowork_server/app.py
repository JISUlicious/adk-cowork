"""FastAPI application factory for ``cowork-server``.

All shared state is behind abstract protocols (EventBus, AuthGuard,
ConnectionLimiter) so backends can be swapped without touching routes.
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

from cowork_server.auth import UserIdentity, create_guard, generate_token
from cowork_server.connections import InMemoryConnectionLimiter
from cowork_server.queues import InMemoryEventBus
from cowork_server.transport import event_to_payload, events_to_history


def create_app(cfg: CoworkConfig | None = None, token: str | None = None) -> FastAPI:
    cfg = cfg or CoworkConfig()
    token = token or cfg.auth.token or generate_token()
    guard = create_guard(token, cfg.auth.keys or None)
    runtime: CoworkRuntime = build_runtime(cfg)

    cache_dir = runtime.workspace.root / "global" / ".preview-cache"
    preview_cache = PreviewCache(cache_dir)

    bus = InMemoryEventBus()
    limiter = InMemoryConnectionLimiter()
    # Default policy from config — never mutated at runtime
    default_policy_mode = cfg.policy.mode

    app = FastAPI(title="cowork-server")
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
    app.state.bus = bus
    app.state.limiter = limiter
    app.state.preview_cache = preview_cache

    # ── Health ─────────────────────────────────────────────────────────

    @app.get("/v1/health")
    async def health() -> dict[str, Any]:
        """Service + per-component status.

        ``backend`` names the runtime backend in use (today always
        ``local``). ``components`` is a dict of subsystem → status;
        distributed deployments extend this with ``eventbus``,
        ``sessions``, etc. ``auth`` reports whether multi-user keys are
        configured, so clients can distinguish sidecar from hosted.
        """
        return {
            "status": "ok",
            "backend": cfg.runtime.backend,
            "auth": "multi-user" if runtime.multi_user else "sidecar",
            "components": {
                "eventbus": "ok",
                "limiter": "ok",
                "sessions": "ok",
            },
            "tools": runtime.tools.names(),
            "skills": runtime.skills.names(),
        }

    # ── Policy (per-session, falls back to server default) ─────────────

    @app.get("/v1/policy/mode")
    async def get_policy_mode(user: UserIdentity = Depends(guard)) -> dict[str, str]:
        """Server-wide default used for fresh sessions. Read-only today."""
        return {"mode": default_policy_mode}

    @app.put("/v1/policy/mode")
    async def set_policy_mode(
        body: dict[str, Any],
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        """Deprecated: use ``/v1/sessions/{id}/policy/mode`` instead.

        Accepts and validates the mode but does not mutate the server default.
        Clients should move to the per-session endpoint.
        """
        mode = body.get("mode", "")
        if mode not in ("plan", "work", "auto"):
            raise HTTPException(status_code=400, detail="mode must be plan, work, or auto")
        return {"mode": mode}

    @app.get("/v1/sessions/{session_id}/policy/mode")
    async def get_session_policy_mode(
        session_id: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        try:
            mode = await runtime.get_session_policy_mode(
                session_id=session_id, user_id=user.user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"mode": mode}

    @app.put("/v1/sessions/{session_id}/policy/mode")
    async def set_session_policy_mode(
        session_id: str,
        body: dict[str, Any],
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        mode = body.get("mode", "")
        try:
            applied = await runtime.set_session_policy_mode(
                session_id=session_id, mode=mode, user_id=user.user_id,
            )
        except ValueError as exc:
            # 400 for unknown mode, 404 for missing session.
            if "unknown policy mode" in str(exc):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"mode": applied}

    @app.get("/v1/sessions/{session_id}/policy/python_exec")
    async def get_session_python_exec_policy(
        session_id: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        try:
            policy = await runtime.get_session_python_exec(
                session_id=session_id, user_id=user.user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"policy": policy}

    @app.put("/v1/sessions/{session_id}/policy/python_exec")
    async def set_session_python_exec_policy(
        session_id: str,
        body: dict[str, Any],
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        policy = body.get("policy", "")
        try:
            applied = await runtime.set_session_python_exec(
                session_id=session_id, policy=policy, user_id=user.user_id,
            )
        except ValueError as exc:
            if "unknown python_exec policy" in str(exc):
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"policy": applied}

    # ── Per-session tool approvals ─────────────────────────────────────

    @app.get("/v1/sessions/{session_id}/approvals")
    async def list_approvals(
        session_id: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, int]:
        """Return ``{tool_name: pending_count}`` for this session."""
        try:
            return await runtime.list_tool_approvals(
                session_id=session_id, user_id=user.user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/sessions/{session_id}/approvals")
    async def grant_approval(
        session_id: str,
        body: dict[str, Any],
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Grant one approval for a tool name.

        Body: ``{"tool": "python_exec_run"}``. The permission callback
        consumes the approval on the next invocation of that tool, so one
        POST allows exactly one subsequent call.
        """
        tool = body.get("tool", "")
        if not isinstance(tool, str) or not tool:
            raise HTTPException(status_code=400, detail="'tool' is required")
        try:
            remaining = await runtime.grant_tool_approval(
                session_id=session_id, tool_name=tool, user_id=user.user_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"tool": tool, "remaining": remaining}

    # ── Sessions ───────────────────────────────────────────────────────

    @app.post("/v1/sessions")
    async def create_session(
        body: dict[str, Any] | None = None,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        """Create a new session.

        Body:
            {"project": "<slug or name>"}   — managed mode (web surface), or
            {"workdir": "/abs/path"}        — local-dir mode (desktop surface)

        Supplying ``workdir`` is the **surface selector**: present = desktop,
        absent = web. Providing both is rejected.
        """
        project_name: str | None = None
        workdir: str | None = None
        if body is not None:
            project_name = body.get("project")
            workdir = body.get("workdir")
        if project_name and workdir:
            raise HTTPException(
                status_code=400,
                detail="supply either 'project' or 'workdir', not both",
            )
        try:
            project, session, adk_sid = await runtime.open_session(
                user_id=user.user_id,
                project_name=project_name,
                workdir=workdir,
            )
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "session_id": adk_sid,
            "project": project.slug,
            "cowork_session_id": session.id,
            "workdir": str(workdir) if workdir else "",
        }

    @app.post("/v1/sessions/{session_id}/resume")
    async def resume_session(
        session_id: str,
        body: dict[str, Any],
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        project_slug = body.get("project") or None
        workdir = body.get("workdir") or None
        if not project_slug and not workdir:
            raise HTTPException(
                status_code=400, detail="project or workdir is required",
            )
        if project_slug and workdir:
            raise HTTPException(
                status_code=400,
                detail="supply either 'project' or 'workdir', not both",
            )
        try:
            project, session, adk_sid = await runtime.resume_session(
                session_id=session_id,
                project_slug=project_slug,
                workdir=workdir,
                user_id=user.user_id,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "session_id": adk_sid,
            "project": project.slug,
            "cowork_session_id": session.id,
            "workdir": str(workdir) if workdir else "",
        }

    @app.get("/v1/sessions/{session_id}/history")
    async def session_history(
        session_id: str,
        user: UserIdentity = Depends(guard),
    ) -> list[dict[str, Any]]:
        svc = runtime.runner.session_service
        existing = await svc.get_session(
            app_name=getattr(runtime.runner, "app_name", "cowork"),
            user_id=user.user_id,
            session_id=session_id,
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="session not found")
        return events_to_history(getattr(existing, "events", []) or [])

    # ── Local-dir file browser (desktop surface) ───────────────────────

    @app.get("/v1/local-files")
    async def list_local_files(
        workdir: str,
        path: str = "",
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """List entries of ``<workdir>/<path>``. Path confined via
        ``LocalDirExecEnv``. Hides the ``.cowork/`` bookkeeping subtree."""
        from pathlib import Path as _P

        from cowork_core.execenv import ExecEnvError, LocalDirExecEnv

        try:
            env = LocalDirExecEnv(workdir=_P(workdir), session_id="browse")
        except ExecEnvError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            abspath = env.resolve(path or ".")
        except ExecEnvError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not abspath.is_dir():
            raise HTTPException(status_code=404, detail=f"not a directory: {path}")
        entries: list[dict[str, Any]] = []
        for child in sorted(abspath.iterdir()):
            if child.name == ".cowork":
                continue  # bookkeeping, not user content
            if child.is_dir():
                entries.append({"name": child.name, "kind": "dir", "size": None})
            else:
                try:
                    size = child.stat().st_size
                except OSError:
                    size = None
                entries.append({"name": child.name, "kind": "file", "size": size})
        return {"path": path or ".", "entries": entries}

    @app.get("/v1/local-files/content")
    async def read_local_file(
        workdir: str,
        path: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, Any]:
        """Read up to 2 MB of ``<workdir>/<path>`` as UTF-8 text."""
        from pathlib import Path as _P

        from cowork_core.execenv import ExecEnvError, LocalDirExecEnv

        try:
            env = LocalDirExecEnv(workdir=_P(workdir), session_id="browse")
            abspath = env.resolve(path)
        except ExecEnvError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not abspath.is_file():
            raise HTTPException(status_code=404, detail=f"not a file: {path}")
        max_bytes = 2_000_000
        data = abspath.read_bytes()
        truncated = len(data) > max_bytes
        if truncated:
            data = data[:max_bytes]
        return {
            "path": path,
            "content": data.decode("utf-8", errors="replace"),
            "truncated": truncated,
            "size": abspath.stat().st_size,
        }

    # ── Local-dir sessions (desktop surface) ───────────────────────────

    @app.get("/v1/local-sessions")
    async def list_local_sessions_endpoint(
        workdir: str,
        user: UserIdentity = Depends(guard),
    ) -> list[dict[str, Any]]:
        """List sessions recorded under ``<workdir>/.cowork/sessions/``."""
        from pathlib import Path as _P

        sessions = runtime.list_local_sessions(_P(workdir))
        return [
            {
                "id": s.id,
                "created_at": s.created_at,
                "title": s.title,
            }
            for s in sessions
        ]

    @app.delete("/v1/local-sessions/{session_id}")
    async def delete_local_session_endpoint(
        session_id: str,
        workdir: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        from pathlib import Path as _P

        await runtime.delete_local_session(
            workdir=_P(workdir),
            session_id=session_id,
            user_id=user.user_id,
        )
        return {"status": "ok"}

    @app.post("/v1/sessions/{session_id}/messages")
    async def send_message(
        session_id: str,
        body: dict[str, Any],
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        text = body.get("text", "")
        task = asyncio.create_task(
            _run_turn(runtime.runner, bus, session_id, str(text), user.user_id)
        )
        # Fire-and-forget — errors are published as events
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        return {"status": "accepted"}

    # ── Event Streaming ────────────────────────────────────────────────

    @app.get("/v1/sessions/{session_id}/events/stream")
    async def events_sse(
        session_id: str,
        user: UserIdentity = Depends(guard),
    ) -> StreamingResponse:
        await limiter.acquire(user.user_id)

        async def gen() -> Any:
            import json as _json
            try:
                async with bus.subscribe(session_id) as queue:
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
            finally:
                await limiter.release(user.user_id)

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
        # WebSocket auth: validate from header or query param
        provided = ws.headers.get("x-cowork-token") or ws.query_params.get("token")
        if not provided:
            await ws.close(code=4401)
            return
        # Validate against guard — for sidecar, check the token directly
        try:
            user = guard(x_cowork_token=provided)
        except HTTPException:
            await ws.close(code=4401)
            return

        await limiter.acquire(user.user_id)
        await ws.accept()
        try:
            async with bus.subscribe(session_id) as queue:
                while True:
                    frame = await queue.get()
                    await ws.send_text(frame)
        except WebSocketDisconnect:
            pass
        finally:
            await limiter.release(user.user_id)

    # ── Projects ───────────────────────────────────────────────────────

    @app.get("/v1/projects")
    async def list_projects(user: UserIdentity = Depends(guard)) -> list[dict[str, str]]:
        projects = runtime.registry_for(user.user_id).list()
        return [
            {"slug": p.slug, "name": p.name, "created_at": p.created_at}
            for p in projects
        ]

    @app.post("/v1/projects")
    async def create_project(
        body: dict[str, Any],
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        name = body.get("name", "")
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        try:
            project = runtime.registry_for(user.user_id).create(name)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"slug": project.slug, "name": project.name, "created_at": project.created_at}

    @app.get("/v1/projects/{project}/sessions")
    async def list_sessions(
        project: str,
        user: UserIdentity = Depends(guard),
    ) -> list[dict[str, Any]]:
        try:
            proj = runtime.registry_for(user.user_id).get(project)
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

    @app.delete("/v1/projects/{project}")
    async def delete_project(
        project: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        try:
            runtime.registry_for(user.user_id).delete_project(project)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"status": "deleted"}

    @app.delete("/v1/projects/{project}/sessions/{session_id}")
    async def delete_session(
        project: str,
        session_id: str,
        user: UserIdentity = Depends(guard),
    ) -> dict[str, str]:
        try:
            runtime.registry_for(user.user_id).delete_session(project, session_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"status": "deleted"}

    # ── Files ──────────────────────────────────────────────────────────

    @app.get("/v1/projects/{project}/files/{path:path}")
    async def list_files(
        project: str,
        path: str,
        user: UserIdentity = Depends(guard),
    ) -> list[dict[str, Any]]:
        try:
            full_path = runtime.workspace_for(user.user_id).resolve(f"projects/{project}/{path}")
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

    @app.post("/v1/projects/{project}/upload")
    async def upload_file(
        project: str,
        user: UserIdentity = Depends(guard),
        file: UploadFile = File(...),  # noqa: B008
        prefix: str = "files",
    ) -> dict[str, Any]:
        if prefix not in ("files", "scratch"):
            raise HTTPException(status_code=400, detail="prefix must be 'files' or 'scratch'")
        basename = (file.filename or "upload.bin").split("/")[-1].split("\\")[-1]
        try:
            dest = runtime.workspace_for(user.user_id).resolve(f"projects/{project}/{prefix}/{basename}")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        dest.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        with dest.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                out.write(chunk)
                size += len(chunk)
        return {"name": basename, "path": f"{prefix}/{basename}", "size": size}

    @app.get("/v1/projects/{project}/preview/{path:path}")
    async def preview_file(
        project: str,
        path: str,
        user: UserIdentity = Depends(guard),
    ) -> Response:
        try:
            full_path = runtime.workspace_for(user.user_id).resolve(f"projects/{project}/{path}")
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


async def _run_turn(
    runner: Any,
    bus: InMemoryEventBus,
    session_id: str,
    text: str,
    user_id: str = "local",
) -> None:
    """Drive one ADK run and publish each Event (JSON) to the bus."""
    import sys
    content = genai_types.Content(role="user", parts=[genai_types.Part(text=text)])
    event_count = 0
    last_event: Event | None = None
    try:
        async for event in runner.run_async(
            user_id=user_id, session_id=session_id, new_message=content
        ):
            event_count += 1
            last_event = event
            await bus.publish(session_id, event_to_payload(event))
    except Exception as e:
        print(f"[cowork-server] run_turn error: {e!r}", file=sys.stderr, flush=True)
        err = Event(
            author=_SERVER_AUTHOR,
            invocation_id=getattr(last_event, "invocation_id", "") or "",
            error_code="INTERNAL",
            error_message=str(e),
            turn_complete=True,
        )
        await bus.publish(session_id, event_to_payload(err))
        return
    finally:
        print(f"[cowork-server] run_turn done, {event_count} events", file=sys.stderr, flush=True)

    if last_event is None or not getattr(last_event, "turn_complete", False):
        sentinel = Event(
            author=_SERVER_AUTHOR,
            invocation_id=getattr(last_event, "invocation_id", "") or "",
            turn_complete=True,
        )
        await bus.publish(session_id, event_to_payload(sentinel))
