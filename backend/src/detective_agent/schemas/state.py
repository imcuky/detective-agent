"""Mutable runtime WorldState schema owned exclusively by GameEngine."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GameStatus = Literal["in_progress", "won", "lost"]


class NpcMemoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn: int = Field(ge=0)
    summary: str = Field(min_length=1, max_length=400)
    importance: Literal["low", "medium", "high"] = "medium"


class DialogueTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turn: int = Field(ge=0)
    speaker: Literal["detective", "npc"]
    content: str
    presented_clue_id: str | None = None


class NpcRuntimeState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    npc_id: str
    location: str
    trust: int = Field(ge=0, le=10)
    suspicion: int = Field(ge=0, le=10)
    episodic_memory: list[NpcMemoryEntry] = Field(default_factory=list)
    witnessed_dialogue: list[DialogueTurn] = Field(default_factory=list)


class AccusationOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accused_npc_id: str
    cited_clue_ids: list[str]
    reasoning: str
    correct: bool
    verdict_summary: str


class WorldState(BaseModel):
    """Canonical mutable state of an active investigation session."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    turn_count: int = Field(default=0, ge=0)
    status: GameStatus = "in_progress"
    player_location: str
    inspected_objects: list[str] = Field(default_factory=list)
    discovered_clues: list[str] = Field(default_factory=list)
    presented_evidence: dict[str, list[str]] = Field(default_factory=dict)
    npc_states: dict[str, NpcRuntimeState] = Field(default_factory=dict)
    accusation_attempts: int = Field(default=0, ge=0)
    max_accusation_attempts: int = Field(default=2, ge=1)
    final_outcome: AccusationOutcome | None = None
