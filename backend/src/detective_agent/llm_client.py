"""Thin, mockable wrapper directly over the official `google-genai` SDK."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from uuid import uuid4

from google import genai
from google.genai import types
from pydantic import BaseModel


@dataclass(frozen=True)
class AgentConfig:
    """Runtime model and loop-guard configuration loaded from environment."""

    model_dm: str = "gemini-2.5-flash"
    model_npc: str = "gemini-2.5-flash"
    max_agent_steps: int = 6
    max_npc_steps: int = 3

    @classmethod
    def from_env(cls) -> "AgentConfig":
        return cls(
            model_dm=os.getenv("GEMINI_MODEL_DM", "gemini-2.5-flash"),
            model_npc=os.getenv("GEMINI_MODEL_NPC", "gemini-2.5-flash"),
            max_agent_steps=int(os.getenv("MAX_AGENT_STEPS", "6")),
            max_npc_steps=int(os.getenv("MAX_NPC_STEPS", "3")),
        )


@dataclass(frozen=True)
class ToolSpec:
    """Pydantic-backed tool declaration exposed to Gemini."""

    name: str
    description: str
    input_model: type[BaseModel]

    def to_gemini_declaration(self) -> types.FunctionDeclaration:
        schema = self.input_model.model_json_schema()
        # Strip top-level Pydantic metadata not needed by Gemini schemas
        schema.pop("title", None)
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters_json_schema=schema,
        )


@dataclass(frozen=True)
class LLMToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMToolResponse:
    call_id: str
    name: str
    response: dict[str, Any]


@dataclass(frozen=True)
class LLMMessage:
    role: Literal["user", "model", "tool"]
    text: str | None = None
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    tool_responses: list[LLMToolResponse] = field(default_factory=list)
    raw_content: Any = None


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    raw_content: Any = None


class LLMClient(Protocol):
    """Minimal protocol enabling deterministic mocked testing of agent loops."""

    async def generate(
        self,
        *,
        model: str,
        system_instruction: str,
        messages: list[LLMMessage],
        tools: list[ToolSpec],
        temperature: float = 0.4,
    ) -> LLMResponse: ...


class GeminiLLMClient:
    """Direct async adapter on top of `google-genai` (no external agent framework)."""

    def __init__(self, api_key: str | None = None) -> None:
        resolved_key = api_key or os.getenv("GEMINI_API_KEY")
        if not resolved_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. Export GEMINI_API_KEY or add it to backend/.env."
            )
        self._client = genai.Client(api_key=resolved_key)

    @staticmethod
    def _to_gemini_contents(messages: list[LLMMessage]) -> list[types.Content]:
        contents: list[types.Content] = []
        for msg in messages:
            if msg.raw_content is not None and isinstance(msg.raw_content, types.Content):
                contents.append(msg.raw_content)
                continue

            if msg.role == "user":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=msg.text or "")],
                    )
                )
            elif msg.role == "model":
                parts: list[types.Part] = []
                if msg.text:
                    parts.append(types.Part.from_text(text=msg.text))
                for tc in msg.tool_calls:
                    parts.append(types.Part.from_function_call(name=tc.name, args=tc.arguments))
                contents.append(types.Content(role="model", parts=parts))
            elif msg.role == "tool":
                parts = [
                    types.Part.from_function_response(
                        name=tr.name,
                        response=tr.response,
                    )
                    for tr in msg.tool_responses
                ]
                contents.append(types.Content(role="user", parts=parts))
        return contents

    async def generate(
        self,
        *,
        model: str,
        system_instruction: str,
        messages: list[LLMMessage],
        tools: list[ToolSpec],
        temperature: float = 0.4,
    ) -> LLMResponse:
        gemini_tools = (
            [types.Tool(function_declarations=[spec.to_gemini_declaration() for spec in tools])]
            if tools
            else None
        )

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            tools=gemini_tools,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        response = await self._client.aio.models.generate_content(
            model=model,
            contents=self._to_gemini_contents(messages),
            config=config,
        )

        raw_content: types.Content | None = None
        if response.candidates and response.candidates[0].content is not None:
            raw_content = response.candidates[0].content

        text_chunks: list[str] = []
        tool_calls: list[LLMToolCall] = []

        if raw_content and raw_content.parts:
            for part in raw_content.parts:
                if part.text:
                    text_chunks.append(part.text)
                if part.function_call is not None:
                    fc = part.function_call
                    tool_calls.append(
                        LLMToolCall(
                            call_id=getattr(fc, "id", None) or f"call_{uuid4().hex[:8]}",
                            name=fc.name or "",
                            arguments=dict(fc.args) if fc.args else {},
                        )
                    )

        return LLMResponse(
            text="\n".join(chunk.strip() for chunk in text_chunks if chunk.strip()),
            tool_calls=tool_calls,
            raw_content=raw_content,
        )
