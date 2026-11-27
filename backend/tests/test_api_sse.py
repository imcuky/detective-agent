"""API and SSE streaming contract tests for FastAPI backend."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import TypeAdapter

from detective_agent.api.main import create_app
from detective_agent.llm_client import LLMMessage, LLMResponse, LLMToolCall, ToolSpec
from detective_agent.schemas import TraceEvent


class FakeApiLLMClient:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)

    async def generate(
        self,
        *,
        model: str,
        system_instruction: str,
        messages: list[LLMMessage],
        tools: list[ToolSpec],
        temperature: float = 0.4,
    ) -> LLMResponse:
        return self._responses.pop(0) if self._responses else LLMResponse(text="Done.")


def _parse_sse_events(raw_body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event_name = "message"
    data_lines: list[str] = []

    for line in raw_body.splitlines():
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].strip())
        elif line == "" and data_lines:
            events.append((event_name, json.loads("\n".join(data_lines))))
            event_name = "message"
            data_lines = []

    if data_lines:
        events.append((event_name, json.loads("\n".join(data_lines))))
    return events


@pytest.mark.asyncio
async def test_session_lifecycle_sse_stream_and_npc_context_endpoint() -> None:
    responses = [
        # 1. DM inspects oak_desk -> unlocks clue_poisoned_teacup
        LLMResponse(
            text="",
            tool_calls=[
                LLMToolCall(call_id="c1", name="inspect_object", arguments={"object_id": "oak_desk"})
            ],
        ),
        # 2. DM talks to Evelyn in study
        LLMResponse(
            text="",
            tool_calls=[
                LLMToolCall(
                    call_id="c2",
                    name="talk_to_npc",
                    arguments={"npc_id": "npc_evelyn", "message": "Where were you at 11 PM?"},
                )
            ],
        ),
        # 3. Evelyn NPC subagent speaks
        LLMResponse(text="I was reading upstairs until I heard a dreadful thud."),
        # 4. DM final narration
        LLMResponse(
            text="You detect bitter almonds in Arthur's teacup. Evelyn insists she was upstairs reading."
        ),
    ]

    app = create_app(llm_client_factory=lambda: FakeApiLLMClient(responses))
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Health
        health = await client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["case_id"] == "case_01"

        # Create session
        created = await client.post("/api/sessions")
        assert created.status_code == 200
        body = created.json()
        session_id = body["session_id"]
        assert body["state"]["player_location"] == "study"
        assert "solution" not in body["public_case"]

        # Stream a turn over SSE
        turn_resp = await client.post(
            f"/api/sessions/{session_id}/turn",
            json={"message": "Inspect the desk and ask Evelyn where she was."},
        )
        assert turn_resp.status_code == 200
        assert "text/event-stream" in turn_resp.headers["content-type"]

        parsed = _parse_sse_events(turn_resp.text)
        trace_adapter = TypeAdapter(TraceEvent)
        trace_events = [trace_adapter.validate_python(payload) for ev_name, payload in parsed if ev_name == "trace"]
        event_types = [e.event_type for e in trace_events]

        assert event_types[0] == "turn_started"
        assert "tool_call_requested" in event_types
        assert "state_diff" in event_types
        assert "npc_context_snapshot" in event_types
        assert event_types[-1] == "turn_completed"

        # Inspect state endpoint
        state_resp = await client.get(f"/api/sessions/{session_id}/state")
        assert state_resp.status_code == 200
        state_data = state_resp.json()
        assert "clue_poisoned_teacup" in state_data["state"]["discovered_clues"]
        assert "npc_evelyn" in state_data["available_npc_contexts"]

        # Inspect NPC context endpoint returns isolated prompt
        ctx_resp = await client.get(f"/api/sessions/{session_id}/npc-context/npc_evelyn")
        assert ctx_resp.status_code == 200
        ctx = ctx_resp.json()
        assert ctx["npc_id"] == "npc_evelyn"
        assert "Evelyn Vance" in ctx["system_prompt"]
        assert "case.solution" in ctx["isolated_from"]
        # Clara's secret must never appear in Evelyn's context
        assert "pruning shears" not in ctx["system_prompt"]
