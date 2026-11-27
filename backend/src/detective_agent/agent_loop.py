"""Explicit, framework-free multi-agent tool-calling loop with TraceEvent streaming."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from .agents.dm import DM_TOOL_SPECS
from .agents.npc import NpcRunResult, run_npc_subagent
from .context_builder import build_dm_system_prompt
from .engine import DM_AGENT_NAME, GameEngine
from .llm_client import AgentConfig, LLMClient, LLMMessage, LLMToolResponse
from .schemas import (
    AgentSelectedEvent,
    AssistantMessageEvent,
    LoopGuardTriggeredEvent,
    NpcContextSnapshot,
    StateDiffEvent,
    ToolCallRequestedEvent,
    ToolCallResultEvent,
    TraceEvent,
    TurnCompletedEvent,
    TurnStartedEvent,
)


class DetectiveAgentLoop:
    """Orchestrates a detective turn across the DM agent, GameEngine, and isolated NPC subagents.

    Key engineering guarantees:
    - Explicit bounded `while` loop with max-step guard (no black-box agent framework).
    - Every state mutation flows through `GameEngine.execute_tool`.
    - Invalid tool calls return structured `ToolError` payloads directly back into the model's
      function-response turn so the DM can recover autonomously.
    - Every step emits typed `TraceEvent`s suitable for SSE streaming and UI inspection.
    """

    def __init__(
        self,
        engine: GameEngine,
        llm_client: LLMClient,
        config: AgentConfig | None = None,
    ) -> None:
        self.engine = engine
        self.llm_client = llm_client
        self.config = config or AgentConfig.from_env()
        self.dm_history: list[LLMMessage] = []
        self.latest_npc_contexts: dict[str, NpcContextSnapshot] = {}

    async def run_turn(self, user_input: str) -> AsyncIterator[TraceEvent]:
        """Execute one detective turn and stream every TraceEvent as it happens."""
        turn = self.engine.begin_turn()
        step_counter = [0]

        def next_step() -> int:
            step_counter[0] += 1
            return step_counter[0]

        yield TurnStartedEvent(
            turn=turn,
            step=next_step(),
            agent_name=DM_AGENT_NAME,
            user_input=user_input,
        )

        yield AgentSelectedEvent(
            turn=turn,
            step=next_step(),
            agent_name=DM_AGENT_NAME,
            active_agent=DM_AGENT_NAME,
            reason="Interpreting detective action and planning tool calls",
        )

        # Keep recent public DM dialogue history + current player prompt.
        # (State is always injected fresh via `build_dm_system_prompt` on each step.)
        turn_messages: list[LLMMessage] = [
            *self.dm_history[-12:],
            LLMMessage(role="user", text=user_input),
        ]

        final_dm_text = ""
        dm_steps_used = 0
        hit_guard = True

        while dm_steps_used < self.config.max_agent_steps:
            dm_steps_used += 1
            dm_system_prompt = build_dm_system_prompt(self.engine.case, self.engine.state)

            response = await self.llm_client.generate(
                model=self.config.model_dm,
                system_instruction=dm_system_prompt,
                messages=turn_messages,
                tools=DM_TOOL_SPECS,
                temperature=0.35,
            )

            if response.tool_calls:
                turn_messages.append(
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
                        agent_name=DM_AGENT_NAME,
                        call_id=tc.call_id,
                        tool_name=tc.name,
                        arguments=tc.arguments,
                    )

                    outcome = self.engine.execute_tool(DM_AGENT_NAME, tc.name, tc.arguments)

                    if outcome.diffs:
                        yield StateDiffEvent(
                            turn=turn,
                            step=step_num,
                            agent_name=DM_AGENT_NAME,
                            changes=outcome.diffs,
                            state_snapshot=self.engine.snapshot_state(),
                        )

                    enriched_data: dict[str, Any] | None = (
                        dict(outcome.result.data) if outcome.result.data is not None else None
                    )

                    # Delegate to isolated NPC subagent when engine validates talk/present_evidence
                    if outcome.result.ok and outcome.npc_dispatch is not None:
                        dispatch = outcome.npc_dispatch
                        npc_def = self.engine.case.get_npc(dispatch.npc_id)
                        assert npc_def is not None
                        npc_box = NpcRunResult(npc_id=dispatch.npc_id, npc_name=npc_def.name)

                        async for npc_event in run_npc_subagent(
                            engine=self.engine,
                            llm_client=self.llm_client,
                            dispatch=dispatch,
                            model=self.config.model_npc,
                            max_steps=self.config.max_npc_steps,
                            step_counter=step_counter,
                            result_box=npc_box,
                        ):
                            yield npc_event

                        if npc_box.snapshot is not None:
                            self.latest_npc_contexts[dispatch.npc_id] = npc_box.snapshot

                        npc_state = self.engine.state.npc_states[dispatch.npc_id]
                        if enriched_data is not None:
                            enriched_data["npc_reply"] = npc_box.reply
                            if tc.name == "talk_to_npc":
                                enriched_data["trust"] = npc_state.trust
                                enriched_data["suspicion"] = npc_state.suspicion
                                enriched_data["memory_updated"] = npc_box.memory_updated

                        yield AgentSelectedEvent(
                            turn=turn,
                            step=next_step(),
                            agent_name=DM_AGENT_NAME,
                            active_agent=DM_AGENT_NAME,
                            reason=f"Received reply from {npc_def.name}; resuming orchestration",
                        )

                    yield ToolCallResultEvent(
                        turn=turn,
                        step=next_step(),
                        agent_name=DM_AGENT_NAME,
                        call_id=tc.call_id,
                        tool_name=tc.name,
                        ok=outcome.result.ok,
                        result=enriched_data,
                        error=outcome.result.error,
                    )

                    response_payload: dict[str, Any]
                    if outcome.result.ok:
                        response_payload = {"ok": True, "result": enriched_data}
                    else:
                        response_payload = {
                            "ok": False,
                            "error": (
                                outcome.result.error.model_dump(mode="json")
                                if outcome.result.error
                                else {"code": "VALIDATION_ERROR", "message": "Tool failed"}
                            ),
                        }

                    tool_responses.append(
                        LLMToolResponse(
                            call_id=tc.call_id,
                            name=tc.name,
                            response=response_payload,
                        )
                    )

                turn_messages.append(LLMMessage(role="tool", tool_responses=tool_responses))
                continue

            # Model produced final natural-language narration without further tool calls
            final_dm_text = response.text.strip() or "You take a moment to assess the scene."
            hit_guard = False
            break

        if hit_guard:
            yield LoopGuardTriggeredEvent(
                turn=turn,
                step=next_step(),
                agent_name=DM_AGENT_NAME,
                max_steps=self.config.max_agent_steps,
                reason=(
                    f"DM orchestrator reached max_agent_steps={self.config.max_agent_steps} "
                    "without producing a final narrative response."
                ),
            )
            final_dm_text = (
                "The investigation pauses after several rapid actions. "
                "Review the latest tool results and state, then decide your next move."
            )

        yield AssistantMessageEvent(
            turn=turn,
            step=next_step(),
            agent_name=DM_AGENT_NAME,
            speaker_label="Narrator",
            content=final_dm_text,
            is_final=True,
        )

        # Persist clean public turn pair for DM multi-turn continuity
        self.dm_history.append(LLMMessage(role="user", text=user_input))
        self.dm_history.append(LLMMessage(role="model", text=final_dm_text))

        yield TurnCompletedEvent(
            turn=turn,
            step=next_step(),
            agent_name="engine",
            game_status=self.engine.state.status,
            total_steps=step_counter[0],
        )
