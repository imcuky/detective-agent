"""Tests for DetectiveAgentLoop using a deterministic mocked LLMClient."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from detective_agent.agent_loop import DetectiveAgentLoop
from detective_agent.engine import GameEngine
from detective_agent.llm_client import AgentConfig, LLMMessage, LLMResponse, LLMToolCall, ToolSpec
from detective_agent.schemas import (
    AssistantMessageEvent,
    LoopGuardTriggeredEvent,
    NpcContextSnapshotEvent,
    StateDiffEvent,
    ToolCallResultEvent,
    TurnCompletedEvent,
    default_case_path,
    load_case,
)


@dataclass
class RecordedCall:
    model: str
    system_instruction: str
    messages: list[LLMMessage]
    tool_names: list[str]


class ScriptedLLMClient:
    """Deterministic fake LLM client that pops scripted responses and records every prompt."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[RecordedCall] = []

    async def generate(
        self,
        *,
        model: str,
        system_instruction: str,
        messages: list[LLMMessage],
        tools: list[ToolSpec],
        temperature: float = 0.4,
    ) -> LLMResponse:
        self.calls.append(
            RecordedCall(
                model=model,
                system_instruction=system_instruction,
                messages=list(messages),
                tool_names=[t.name for t in tools],
            )
        )
        if not self._responses:
            return LLMResponse(text="Default fallback narration.")
        return self._responses.pop(0)


async def _collect_turn(loop: DetectiveAgentLoop, text: str) -> list:
    return [ev async for ev in loop.run_turn(text)]


@pytest.mark.asyncio
async def test_tool_error_recovery_across_rooms() -> None:
    """DM mistakenly tries to inspect breaker_box from study, reads OBJECT_NOT_IN_ROOM hint, moves, and succeeds."""
    case = load_case(default_case_path())
    engine = GameEngine(case)

    fake_llm = ScriptedLLMClient(
        [
            # Step 1: DM tries to inspect breaker_box while still in study -> OBJECT_NOT_IN_ROOM
            LLMResponse(
                text="",
                tool_calls=[
                    LLMToolCall(call_id="c1", name="inspect_object", arguments={"object_id": "breaker_box"})
                ],
            ),
            # Step 2: DM recovers by moving to cellar
            LLMResponse(
                text="",
                tool_calls=[
                    LLMToolCall(call_id="c2", name="move_to", arguments={"target_room_id": "cellar"})
                ],
            ),
            # Step 3: DM inspects breaker_box in cellar -> unlocks clue_jammed_breaker
            LLMResponse(
                text="",
                tool_calls=[
                    LLMToolCall(call_id="c3", name="inspect_object", arguments={"object_id": "breaker_box"})
                ],
            ),
            # Step 4: DM produces final narrative
            LLMResponse(
                text="You head down to the Cellar and find Marcus's forged invoice wedged in the Study breaker."
            ),
        ]
    )

    loop = DetectiveAgentLoop(engine, fake_llm, AgentConfig(max_agent_steps=6))
    events = await _collect_turn(loop, "Check the electrical breaker box.")

    tool_results = [e for e in events if isinstance(e, ToolCallResultEvent)]
    assert len(tool_results) == 3
    assert tool_results[0].ok is False
    assert tool_results[0].error is not None
    assert tool_results[0].error.code == "OBJECT_NOT_IN_ROOM"
    assert tool_results[1].ok is True
    assert tool_results[2].ok is True

    assert engine.state.player_location == "cellar"
    assert "clue_jammed_breaker" in engine.state.discovered_clues

    # Confirm the error response was actually sent back to the LLM on step 2
    step2_tool_msg = fake_llm.calls[1].messages[-1]
    assert step2_tool_msg.role == "tool"
    assert step2_tool_msg.tool_responses[0].response["error"]["code"] == "OBJECT_NOT_IN_ROOM"


@pytest.mark.asyncio
async def test_npc_subagent_delegation_context_snapshot_and_memory_update() -> None:
    """Presenting poisoned teacup to Clara delegates to isolated NPC subagent which calls update_npc_memory."""
    case = load_case(default_case_path())
    engine = GameEngine(case)
    # Pre-position detective in conservatory with clue_poisoned_teacup owned
    engine.execute_tool("dm_orchestrator", "inspect_object", {"object_id": "oak_desk"})
    engine.execute_tool("dm_orchestrator", "move_to", {"target_room_id": "conservatory"})

    fake_llm = ScriptedLLMClient(
        [
            # 1. DM calls present_evidence on Clara
            LLMResponse(
                text="",
                tool_calls=[
                    LLMToolCall(
                        call_id="dm_1",
                        name="present_evidence",
                        arguments={
                            "npc_id": "npc_clara",
                            "clue_id": "clue_poisoned_teacup",
                            "framing_question": "Why does Arthur's tea smell of bitter almonds?",
                        },
                    )
                ],
            ),
            # 2. Isolated Clara subagent calls update_npc_memory
            LLMResponse(
                text="",
                tool_calls=[
                    LLMToolCall(
                        call_id="npc_1",
                        name="update_npc_memory",
                        arguments={
                            "npc_id": "npc_clara",
                            "memory_summary": "Detective proved cyanide poisoning with the teacup.",
                            "importance": "high",
                            "trust_delta": 1,
                            "suspicion_delta": -1,
                        },
                    )
                ],
            ),
            # 3. Isolated Clara subagent speaks in character
            LLMResponse(
                text="Alright—it's cherry-laurel cyanide, dosed between 11:00 and 11:10 PM. At 11:05 I saw a dark coat heading to the cellar!"
            ),
            # 4. DM synthesizes Clara's response
            LLMResponse(
                text="Dr. Thorne's composure breaks. She confirms the 11:00–11:10 PM poisoning window and tells you about the figure heading to the cellar."
            ),
        ]
    )

    loop = DetectiveAgentLoop(engine, fake_llm)
    events = await _collect_turn(loop, "Show Clara the poisoned teacup.")

    # Verify NPC subagent was ONLY exposed update_npc_memory
    npc_llm_call = fake_llm.calls[1]
    assert npc_llm_call.tool_names == ["update_npc_memory"]
    assert case.solution.summary not in npc_llm_call.system_instruction

    # Verify NpcContextSnapshotEvent was emitted and stored on the loop
    snapshots = [e for e in events if isinstance(e, NpcContextSnapshotEvent)]
    assert len(snapshots) == 1
    assert snapshots[0].snapshot.npc_id == "npc_clara"
    assert "npc_clara" in loop.latest_npc_contexts

    # Verify deterministic clue unlock + NPC memory mutation + witnessed reply
    assert "clue_clara_testimony" in engine.state.discovered_clues
    clara_state = engine.state.npc_states["npc_clara"]
    assert len(clara_state.episodic_memory) == 1
    assert clara_state.witnessed_dialogue[-1].speaker == "npc"
    assert "11:00 and 11:10 PM" in clara_state.witnessed_dialogue[-1].content

    # Verify both NPC and DM AssistantMessageEvents + StateDiffEvents + TurnCompletedEvent emitted
    assistant_msgs = [e for e in events if isinstance(e, AssistantMessageEvent)]
    assert [m.agent_name for m in assistant_msgs] == ["npc_clara", "dm_orchestrator"]
    assert any(isinstance(e, StateDiffEvent) for e in events)
    assert isinstance(events[-1], TurnCompletedEvent)


@pytest.mark.asyncio
async def test_max_step_guard_stops_runaway_loop() -> None:
    """If the model keeps emitting tool calls forever, LoopGuardTriggeredEvent stops execution cleanly."""
    case = load_case(default_case_path())
    engine = GameEngine(case)

    endless_calls = [
        LLMResponse(
            text="",
            tool_calls=[
                LLMToolCall(call_id=f"c{i}", name="inspect_object", arguments={"object_id": "oak_desk"})
            ],
        )
        for i in range(5)
    ]
    fake_llm = ScriptedLLMClient(endless_calls)
    loop = DetectiveAgentLoop(engine, fake_llm, AgentConfig(max_agent_steps=2))
    events = await _collect_turn(loop, "Keep checking the desk forever.")

    guards = [e for e in events if isinstance(e, LoopGuardTriggeredEvent)]
    assert len(guards) == 1
    assert guards[0].max_steps == 2
    assert isinstance(events[-1], TurnCompletedEvent)
