"""REST & Server-Sent Events (SSE) routes for Detective Agent."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from ..context_builder import build_npc_context_snapshot
from ..engine import NpcDispatch
from ..schemas import NpcContextSnapshot
from .sessions import SessionManager


class TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2000)


class CreateSessionResponse(BaseModel):
    session_id: str
    public_case: dict[str, Any]
    state: dict[str, Any]


class SessionStateResponse(BaseModel):
    session_id: str
    state: dict[str, Any]
    available_npc_contexts: list[str]


def build_router(sessions: SessionManager) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["detective"])

    @router.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "case_id": sessions.case.case_id,
            "model_dm": sessions._config.model_dm,
            "model_npc": sessions._config.model_npc,
            "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
        }

    @router.post("/sessions", response_model=CreateSessionResponse)
    async def create_session() -> CreateSessionResponse:
        session = sessions.create_session()
        return CreateSessionResponse(
            session_id=session.session_id,
            public_case=sessions.case.to_public_metadata(),
            state=session.engine.snapshot_state(),
        )

    @router.get("/sessions/{session_id}/state", response_model=SessionStateResponse)
    async def get_session_state(session_id: str) -> SessionStateResponse:
        session = sessions.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
        contexts = list(session.loop.latest_npc_contexts.keys()) if session.loop else []
        return SessionStateResponse(
            session_id=session.session_id,
            state=session.engine.snapshot_state(),
            available_npc_contexts=contexts,
        )

    @router.get(
        "/sessions/{session_id}/npc-context/{npc_id}",
        response_model=NpcContextSnapshot,
    )
    async def get_npc_context(
        session_id: str,
        npc_id: str,
        preview: bool = False,
    ) -> NpcContextSnapshot:
        """Return the exact isolated system context visible to the given NPC subagent."""
        session = sessions.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

        if session.engine.case.get_npc(npc_id) is None:
            raise HTTPException(status_code=404, detail=f"Unknown suspect '{npc_id}'.")

        if session.loop and npc_id in session.loop.latest_npc_contexts:
            return session.loop.latest_npc_contexts[npc_id]

        if preview:
            preview_dispatch = NpcDispatch(
                npc_id=npc_id,
                mode="talk",
                player_message="[Preview only — no question sent yet]",
            )
            return build_npc_context_snapshot(session.engine.case, session.engine.state, preview_dispatch)

        raise HTTPException(
            status_code=404,
            detail=f"NPC '{npc_id}' has not been interrogated yet in this session.",
        )

    @router.post("/sessions/{session_id}/turn")
    async def run_turn_stream(
        session_id: str,
        body: TurnRequest,
        request: Request,
    ) -> EventSourceResponse:
        """Run one detective turn and stream every TraceEvent via SSE."""
        session = sessions.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

        async def event_generator() -> AsyncIterator[dict[str, str]]:
            try:
                loop = sessions.ensure_loop(session)
            except ValueError as exc:
                yield {
                    "event": "error",
                    "data": json.dumps({"code": "CONFIG_ERROR", "message": str(exc)}),
                }
                return

            try:
                async for trace_event in loop.run_turn(body.message):
                    if await request.is_disconnected():
                        break
                    session.trace_history.append(trace_event)
                    yield {
                        "event": "trace",
                        "data": trace_event.model_dump_json(),
                    }
            except Exception as exc:  # noqa: BLE001
                yield {
                    "event": "error",
                    "data": json.dumps({"code": "RUNTIME_ERROR", "message": str(exc)}),
                }

        return EventSourceResponse(event_generator())

    return router
