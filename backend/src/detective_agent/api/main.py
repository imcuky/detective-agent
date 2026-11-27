"""FastAPI application factory for Detective Agent."""

from __future__ import annotations

from collections.abc import Callable

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..llm_client import AgentConfig, LLMClient
from ..schemas import CaseDefinition
from .routes import build_router
from .sessions import SessionManager


def create_app(
    *,
    case: CaseDefinition | None = None,
    llm_client_factory: Callable[[], LLMClient] | None = None,
    config: AgentConfig | None = None,
) -> FastAPI:
    load_dotenv()

    app = FastAPI(
        title="Detective Agent API",
        version="0.1.0",
        description="Deterministic state machine + multi-agent detective mystery SSE backend.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    sessions = SessionManager(
        case=case,
        llm_client_factory=llm_client_factory,
        config=config,
    )
    app.state.sessions = sessions
    app.include_router(build_router(sessions))
    return app


app = create_app()
