"""Immutable case definition schemas loaded from JSON."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InspectableObjectDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    name: str
    description: str
    inspect_text: str
    unlocks_clue_id: str | None = None


class RoomDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    room_id: str
    name: str
    description: str
    connected_rooms: list[str]
    objects: list[InspectableObjectDef] = Field(default_factory=list)


class ClueDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clue_id: str
    title: str
    category: Literal["physical", "testimony"]
    summary: str
    source_id: str


class NpcPrivateKnowledge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alibi: str
    persona_instructions: str
    secrets: list[str]
    knowledge_graph: dict[str, str]


class EvidenceReactionDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unlocks_clue_id: str | None = None
    trust_delta: int = 0
    suspicion_delta: int = 0
    reaction_guidance: str


class NpcDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    npc_id: str
    name: str
    role: str
    starting_room_id: str
    initial_trust: int = Field(ge=0, le=10)
    initial_suspicion: int = Field(ge=0, le=10)
    public_profile: str
    private_knowledge: NpcPrivateKnowledge
    evidence_reactions: dict[str, EvidenceReactionDef] = Field(default_factory=dict)


class SolutionDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    culprit_id: str
    required_clue_ids: list[str] = Field(min_length=1)
    summary: str


class CaseDefinition(BaseModel):
    """Canonical immutable definition of a mystery case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    title: str
    public_intro: str
    starting_room_id: str
    max_accusation_attempts: int = Field(default=2, ge=1)
    rooms: list[RoomDef]
    clues: list[ClueDef]
    npcs: list[NpcDef]
    solution: SolutionDef

    @model_validator(mode="after")
    def validate_references(self) -> "CaseDefinition":
        room_ids = {r.room_id for r in self.rooms}
        clue_ids = {c.clue_id for c in self.clues}
        npc_ids = {n.npc_id for n in self.npcs}

        if self.starting_room_id not in room_ids:
            raise ValueError(f"Unknown starting_room_id: {self.starting_room_id}")

        for room in self.rooms:
            for adj in room.connected_rooms:
                if adj not in room_ids:
                    raise ValueError(f"Room {room.room_id} references unknown connected room {adj}")
            for obj in room.objects:
                if obj.unlocks_clue_id and obj.unlocks_clue_id not in clue_ids:
                    raise ValueError(
                        f"Object {obj.object_id} unlocks unknown clue {obj.unlocks_clue_id}"
                    )

        for npc in self.npcs:
            if npc.starting_room_id not in room_ids:
                raise ValueError(f"NPC {npc.npc_id} starts in unknown room {npc.starting_room_id}")
            for clue_id, reaction in npc.evidence_reactions.items():
                if clue_id not in clue_ids:
                    raise ValueError(f"NPC {npc.npc_id} reacts to unknown clue {clue_id}")
                if reaction.unlocks_clue_id and reaction.unlocks_clue_id not in clue_ids:
                    raise ValueError(
                        f"NPC {npc.npc_id} unlocks unknown clue {reaction.unlocks_clue_id}"
                    )

        if self.solution.culprit_id not in npc_ids:
            raise ValueError(f"Solution culprit {self.solution.culprit_id} is not a valid NPC")
        for req_clue in self.solution.required_clue_ids:
            if req_clue not in clue_ids:
                raise ValueError(f"Solution requires unknown clue {req_clue}")

        return self

    def get_room(self, room_id: str) -> RoomDef | None:
        return next((r for r in self.rooms if r.room_id == room_id), None)

    def get_clue(self, clue_id: str) -> ClueDef | None:
        return next((c for c in self.clues if c.clue_id == clue_id), None)

    def get_npc(self, npc_id: str) -> NpcDef | None:
        return next((n for n in self.npcs if n.npc_id == npc_id), None)

    def find_object(self, object_id: str) -> tuple[RoomDef, InspectableObjectDef] | None:
        for room in self.rooms:
            for obj in room.objects:
                if obj.object_id == object_id:
                    return room, obj
        return None

    def to_public_metadata(self) -> dict:
        """Return safe client/DM metadata with zero solution or private NPC secrets."""
        return {
            "case_id": self.case_id,
            "title": self.title,
            "public_intro": self.public_intro,
            "starting_room_id": self.starting_room_id,
            "max_accusation_attempts": self.max_accusation_attempts,
            "rooms": [
                {
                    "room_id": r.room_id,
                    "name": r.name,
                    "description": r.description,
                    "connected_rooms": r.connected_rooms,
                    "objects": [
                        {
                            "object_id": o.object_id,
                            "name": o.name,
                            "description": o.description,
                        }
                        for o in r.objects
                    ],
                }
                for r in self.rooms
            ],
            "npcs": [
                {
                    "npc_id": n.npc_id,
                    "name": n.name,
                    "role": n.role,
                    "starting_room_id": n.starting_room_id,
                    "public_profile": n.public_profile,
                }
                for n in self.npcs
            ],
            "clues_catalog": {
                c.clue_id: {
                    "clue_id": c.clue_id,
                    "title": c.title,
                    "category": c.category,
                    "summary": c.summary,
                }
                for c in self.clues
            },
        }


def load_case(path: str | Path) -> CaseDefinition:
    """Load and validate a case JSON file."""
    return CaseDefinition.model_validate_json(Path(path).read_text(encoding="utf-8"))


def default_case_path() -> Path:
    """Return the repository path to backend/data/case_01.json."""
    return Path(__file__).resolve().parents[3] / "data" / "case_01.json"
