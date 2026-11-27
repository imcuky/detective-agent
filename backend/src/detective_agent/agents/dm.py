"""DM Orchestrator tool specifications."""

from ..llm_client import ToolSpec
from ..schemas import (
    InspectObjectInput,
    MoveToInput,
    PresentEvidenceInput,
    SubmitAccusationInput,
    TalkToNpcInput,
)

DM_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="move_to",
        description="Move the detective to an adjacent connected room in Vance Manor.",
        input_model=MoveToInput,
    ),
    ToolSpec(
        name="inspect_object",
        description="Inspect a physical object located in the detective's current room.",
        input_model=InspectObjectInput,
    ),
    ToolSpec(
        name="talk_to_npc",
        description="Speak to a suspect who is present in the detective's current room.",
        input_model=TalkToNpcInput,
    ),
    ToolSpec(
        name="present_evidence",
        description="Confront a suspect in the current room with a discovered clue owned by the detective.",
        input_model=PresentEvidenceInput,
    ),
    ToolSpec(
        name="submit_accusation",
        description="Submit a formal final accusation naming the killer and citing owned evidence clues.",
        input_model=SubmitAccusationInput,
    ),
]
