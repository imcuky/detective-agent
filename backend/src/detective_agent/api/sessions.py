"""In-memory session store managing active DetectiveAgentLoop instances."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import uuid4

from ..agent_loop import DetectiveAgentLoop
from ..engine import GameEngine
from ..llm_client import AgentConfig, GeminiLLMClient, LLMClient
from ..schemas import CaseDefinition, TraceEvent, default_case_path, load_case


@dataclass
class GameSession:
    session_id: str
    engine: GameEngine
    loop: DetectiveAgentLoop | None
    config: AgentConfig
    trace_history: list[TraceEvent] = field(default_factory=list)


class SessionManager:
    """Thread/async-safe in-memory store for detective game sessions."""

    def __init__(
        self,
        case: CaseDefinition | None = None,
        llm_client_factory: Callable[[], LLMClient] | None = None,
        config: AgentConfig | None = None,
    ) -> None:
        self.case = case or load_case(default_case_path())
        self._llm_client_factory = llm_client_factory
        self._config = config or AgentConfig.from_env()
        self._sessions: dict[str, GameSession] = {}

    def create_session(self) -> GameSession:
        session_id = uuid4().hex[:12]
        engine = GameEngine(self.case)
        session = GameSession(
            session_id=session_id,
            engine=engine,
            loop=None,
            config=self._config,
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> GameSession | None:
        return self._sessions.get(session_id)

    def ensure_loop(self, session: GameSession) -> DetectiveAgentLoop:
        """Lazily initialize the LLM-backed agent loop so sessions can start even before API key setup."""
        if session.loop is None:
            client = (
                self._llm_client_factory()
                if self._llm_client_factory is not None
                else GeminiLLMClient()
            )
            session.loop = DetectiveAgentLoop(
                engine=session.engine,
                llm_client=client,
                config=session.config,
            )
        return session.loop
