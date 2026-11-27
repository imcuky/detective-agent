"""Validated tool contracts for the 6 detective engine tools."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .state import GameStatus, NpcMemoryEntry


class ObjectSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    name: str
    inspected: bool


class NpcSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    npc_id: str
    name: str
    role: str


class ClueSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clue_id: str
    title: str
    category: Literal["physical", "testimony"]
    summary: str


ToolErrorCode = Literal[
    "GAME_OVER",
    "VALIDATION_ERROR",
    "UNAUTHORIZED_AGENT",
    "UNKNOWN_ROOM",
    "ROOM_NOT_ADJACENT",
    "ALREADY_IN_ROOM",
    "UNKNOWN_OBJECT",
    "OBJECT_NOT_IN_ROOM",
    "UNKNOWN_NPC",
    "NPC_NOT_IN_ROOM",
    "UNKNOWN_CLUE",
    "CLUE_NOT_OWNED",
]


class ToolError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: ToolErrorCode
    message: str
    recovery_hint: str


class ToolExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    tool_name: str
    data: dict[str, Any] | None = None
    error: ToolError | None = None


# --- 1. move_to ---


class MoveToInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_room_id: str = Field(description="ID of an adjacent room to move into.")


class MoveToResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    previous_room_id: str
    current_room_id: str
    room_name: str
    room_description: str
    connected_rooms: list[str]
    visible_objects: list[ObjectSummary]
    present_npcs: list[NpcSummary]


# --- 2. inspect_object ---


class InspectObjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str = Field(description="ID of an inspectable object in the current room.")


class InspectObjectResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    object_name: str
    observation: str
    already_inspected: bool
    unlocked_clue: ClueSummary | None = None


# --- 3. talk_to_npc ---


class TalkToNpcInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    npc_id: str = Field(description="ID of a suspect present in the current room.")
    message: str = Field(min_length=1, description="Question or statement addressed to the suspect.")


class TalkToNpcResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    npc_id: str
    npc_name: str
    npc_reply: str
    trust: int
    suspicion: int
    memory_updated: bool = False


# --- 4. present_evidence ---


class PresentEvidenceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    npc_id: str = Field(description="ID of a suspect present in the current room.")
    clue_id: str = Field(description="ID of a discovered clue currently owned by the detective.")
    framing_question: str = Field(
        min_length=1,
        description="How the detective confronts the suspect with this clue.",
    )


class PresentEvidenceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    npc_id: str
    npc_name: str
    clue_id: str
    already_presented: bool
    unlocked_clue: ClueSummary | None = None
    trust_delta: int
    suspicion_delta: int
    npc_reply: str = ""


# --- 5. update_npc_memory (NPC subagent ONLY) ---


class UpdateNpcMemoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    npc_id: str = Field(description="Must match the calling NPC subagent's own npc_id.")
    memory_summary: str = Field(
        min_length=1,
        max_length=400,
        description="Concise episodic note of what the detective just asked, implied, or revealed.",
    )
    importance: Literal["low", "medium", "high"] = "medium"
    trust_delta: int = Field(default=0, ge=-2, le=2)
    suspicion_delta: int = Field(default=0, ge=-2, le=2)


class UpdateNpcMemoryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    npc_id: str
    recorded_memory: NpcMemoryEntry
    new_trust: int
    new_suspicion: int


# --- 6. submit_accusation ---


class SubmitAccusationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suspect_id: str = Field(description="ID of the suspect accused of the murder.")
    evidence_clue_ids: list[str] = Field(
        min_length=1,
        description="Owned clue IDs supporting the accusation.",
    )
    reasoning: str = Field(
        min_length=10,
        description="Detective's summary of motive, means, and opportunity.",
    )


class SubmitAccusationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correct: bool
    game_status: GameStatus
    attempts_remaining: int
    verdict_summary: str
    missing_required_clues: list[str] = Field(default_factory=list)


DM_ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "move_to",
        "inspect_object",
        "talk_to_npc",
        "present_evidence",
        "submit_accusation",
    }
)

NPC_ALLOWED_TOOLS: frozenset[str] = frozenset({"update_npc_memory"})
