"""Isolated NPC Subagent runner with strict context boundaries."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from ..context_builder import build_npc_context_snapshot
from ..engine import GameEngine, NpcDispatch
from ..llm_client import LLMClient, LLMMessage, LLMToolResponse, ToolSpec
from ..schemas import (
    AgentSelectedEvent,
    AssistantMessageEvent,
    LoopGuardTriggeredEvent,
    NpcContextSnapshot,
    NpcContextSnapshotEvent,
    StateDiffEvent,
    ToolCallRequestedEvent,
    ToolCallResultEvent,
    TraceEvent,
    UpdateNpcMemoryInput,
)

NPC_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="update_npc_memory",
        description=(
            "Record a concise episodic memory note of this interaction and optionally adjust "
            "your own trust/suspicion (-2 to +2). Only pass your own npc_id."
        ),
        input_model=UpdateNpcMemoryInput,
    )
]


@dataclass
class NpcRunResult:
    """Mutable result box populated as `run_npc_subagent` streams TraceEvents."""

    npc_id: str
    npc_name: str
    reply: str = ""
    memory_updated: bool = False
    snapshot: NpcContextSnapshot | None = None


async def run_npc_subagent(
    *,
    engine: GameEngine,
    llm_client: LLMClient,
    dispatch: NpcDispatch,
    model: str,
    max_steps: int,
    step_counter: list[int],
    result_box: NpcRunResult,
) -> AsyncIterator[TraceEvent]:
    """Execute an isolated NPC subagent turn and stream its TraceEvents.

    The subagent ONLY sees `NpcContextSnapshot` (public briefing + own private knowledge
    + own episodic memory + own witnessed dialogue) and ONLY has access to `update_npc_memory`.
    """
    turn = engine.state.turn_count
    npc_def = engine.case.get_npc(dispatch.npc_id)
    assert npc_def is not None

    def next_step() -> int:
        step_counter[0] += 1
        return step_counter[0]

    reason = (
        f"Confronted with evidence '{dispatch.presented_clue.title}'"
        if dispatch.mode == "present_evidence" and dispatch.presented_clue
        else "Responding to detective questioning"
    )
    yield AgentSelectedEvent(
        turn=turn,
        step=next_step(),
        agent_name=dispatch.npc_id,
        active_agent=dispatch.npc_id,
        reason=reason,
    )

    snapshot = build_npc_context_snapshot(engine.case, engine.state, dispatch)
    result_box.snapshot = snapshot

    yield NpcContextSnapshotEvent(
        turn=turn,
        step=next_step(),
        agent_name=dispatch.npc_id,
        snapshot=snapshot,
    )

    messages: list[LLMMessage] = [
        LLMMessage(
            role="user" if m["role"] == "user" else "model",
            text=m["content"],
        )
        for m in snapshot.dialogue_messages
    ]

    final_reply = ""
    for _ in range(max_steps):
        response = await llm_client.generate(
            model=model,
            system_instruction=snapshot.system_prompt,
            messages=messages,
            tools=NPC_TOOL_SPECS,
            temperature=0.6,
        )

        if response.tool_calls:
            messages.append(
                LLMMessage(
                    role="model",
                    text=response.text or None,
                    tool_calls=response.tool_calls,
                    raw_content=response.raw_content,
                )
            )
            tool_responses: list[LLMToolResponse] = []

            for tc in response.tool_calls:
                step_num = next_step()
                yield ToolCallRequestedEvent(
                    turn=turn,
                    step=step_num,
                    agent_name=dispatch.npc_id,
                    call_id=tc.call_id,
                    tool_name=tc.name,
                    arguments=tc.arguments,
                )

                outcome = engine.execute_tool(dispatch.npc_id, tc.name, tc.arguments)
                if outcome.result.ok and tc.name == "update_npc_memory":
                    result_box.memory_updated = True

                yield ToolCallResultEvent(
                    turn=turn,
                    step=step_num,
                    agent_name=dispatch.npc_id,
                    call_id=tc.call_id,
                    tool_name=tc.name,
                    ok=outcome.result.ok,
                    result=outcome.result.data,
                    error=outcome.result.error,
                )

                if outcome.diffs:
                    yield StateDiffEvent(
                        turn=turn,
                        step=step_num,
                        agent_name=dispatch.npc_id,
                        changes=outcome.diffs,
                        state_snapshot=engine.snapshot_state(),
                    )

                tool_responses.append(
                    LLMToolResponse(
                        call_id=tc.call_id,
                        name=tc.name,
                        response=outcome.result.model_dump(mode="json", exclude_none=True),
                    )
                )

            messages.append(LLMMessage(role="tool", tool_responses=tool_responses))
            continue

        final_reply = response.text.strip()
        break

    if not final_reply:
        yield LoopGuardTriggeredEvent(
            turn=turn,
            step=next_step(),
            agent_name=dispatch.npc_id,
            max_steps=max_steps,
            reason=f"NPC subagent '{dispatch.npc_id}' reached max_steps={max_steps} without a spoken reply.",
        )
        final_reply = f"*{npc_def.name} hesitates and falls silent for a moment.*"

    result_box.reply = final_reply
    reply_diffs = engine.record_npc_reply(dispatch.npc_id, final_reply)
    if reply_diffs:
        yield StateDiffEvent(
            turn=turn,
            step=next_step(),
            agent_name=dispatch.npc_id,
            changes=reply_diffs,
            state_snapshot=engine.snapshot_state(),
        )

    yield AssistantMessageEvent(
        turn=turn,
        step=next_step(),
        agent_name=dispatch.npc_id,
        speaker_label=npc_def.name,
        content=final_reply,
        is_final=True,
    )
