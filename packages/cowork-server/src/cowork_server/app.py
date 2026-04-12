"""FastAPI application factory for ``cowork-server``.

Routes live inline for M0/M1 to keep the surface small; they split into
``routes/`` modules once project/session CRUD and previews land in M2.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from cowork_core import CoworkConfig, CoworkRuntime, build_runtime
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from google.genai import types as genai_types

from cowork_server.auth import TokenGuard, generate_token
from cowork_server.transport import event_to_frame


def create_app(cfg: CoworkConfig | None = None, token: str | None = None) -> FastAPI:
    cfg = cfg or CoworkConfig()
    token = token or generate_token()
    guard = TokenGuard(token)
    runtime: CoworkRuntime = build_runtime(cfg)

    queues: dict[str, asyncio.Queue[str]] = {}
    tasks: set[asyncio.Task[None]] = set()

    app = FastAPI(title="cowork-server")
    app.state.token = token
    app.state.runtime = runtime
    app.state.cfg = cfg
    app.state.queues = queues
    app.state.tasks = tasks

    @app.get("/v1/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "tools": runtime.tools.names(),
            "skills": runtime.skills.names(),
        }

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

    @app.websocket("/v1/sessions/{session_id}/events")
    async def events_ws(ws: WebSocket, session_id: str) -> None:
        if ws.headers.get("x-cowork-token") != token:
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

    return app


async def _run_turn(runner: Any, queue: asyncio.Queue[str], session_id: str, text: str) -> None:
    content = genai_types.Content(role="user", parts=[genai_types.Part(text=text)])
    try:
        async for event in runner.run_async(
            user_id="local", session_id=session_id, new_message=content
        ):
            await queue.put(json.dumps(event_to_frame(event)))
    except Exception as e:
        await queue.put(json.dumps({"type": "error", "message": str(e)}))
    finally:
        await queue.put(json.dumps({"type": "end_turn"}))
