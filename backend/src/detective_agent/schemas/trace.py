"""Structured TraceEvent schemas for SSE streaming and Agent X-Ray UI."""

from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Union
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .state import GameStatus
from .tools import ToolError


class StateDiffEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    op: Literal["add", "remove", "replace"]
    before: Any = None
    after: Any = None


class NpcContextSnapshot(BaseModel):
    """Exact read-only projection of what an NPC subagent saw on a given turn."""

    model_config = ConfigDict(extra="forbid")

    npc_id: str
    npc_name: str
    turn: int
    system_prompt: str
    dialogue_messages: list[dict[str, str]]
    memory_count: int
    witnessed_dialogue_count: int
    isolated_from: list[str] = Field(
        default_factory=lambda: [
            "case.solution",
            "other_npcs.private_knowledge",
            "other_npcs.witnessed_dialogue",
        ]
    )


class BaseTraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    turn: int
    step: int
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    agent_name: str


class TurnStartedEvent(BaseTraceEvent):
    event_type: Literal["turn_started"] = "turn_started"
    user_input: str


class AgentSelectedEvent(BaseTraceEvent):
    event_type: Literal["agent_selected"] = "agent_selected"
    active_agent: str
    reason: str


class ToolCallRequestedEvent(BaseTraceEvent):
    event_type: Literal["tool_call_requested"] = "tool_call_requested"
    call_id: str
    tool_name: str
    arguments: dict[str, Any]


class ToolCallResultEvent(BaseTraceEvent):
    event_type: Literal["tool_call_result"] = "tool_call_result"
    call_id: str
    tool_name: str
    ok: bool
    result: dict[str, Any] | None = None
    error: ToolError | None = None


class StateDiffEvent(BaseTraceEvent):
    event_type: Literal["state_diff"] = "state_diff"
    changes: list[StateDiffEntry]
    state_snapshot: dict[str, Any]


class NpcContextSnapshotEvent(BaseTraceEvent):
    event_type: Literal["npc_context_snapshot"] = "npc_context_snapshot"
    snapshot: NpcContextSnapshot


class AssistantMessageEvent(BaseTraceEvent):
    event_type: Literal["assistant_message"] = "assistant_message"
    speaker_label: str
    content: str
    is_final: bool = True


class LoopGuardTriggeredEvent(BaseTraceEvent):
    event_type: Literal["loop_guard_triggered"] = "loop_guard_triggered"
    max_steps: int
    reason: str


class TurnCompletedEvent(BaseTraceEvent):
    event_type: Literal["turn_completed"] = "turn_completed"
    game_status: GameStatus
    total_steps: int


TraceEvent = Annotated[
    Union[
        TurnStartedEvent,
        AgentSelectedEvent,
        ToolCallRequestedEvent,
        ToolCallResultEvent,
        StateDiffEvent,
        NpcContextSnapshotEvent,
        AssistantMessageEvent,
        LoopGuardTriggeredEvent,
        TurnCompletedEvent,
    ],
    Field(discriminator="event_type"),
]
