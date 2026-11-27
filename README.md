# Detective Agent — *The Midnight Ledger*

A deterministic state machine + strictly isolated multi-agent detective mystery game built as a reference project for production-grade AI agent engineering.

## Architecture Highlights

1. **Deterministic Game Engine (`backend/src/detective_agent/engine.py`)**:
   - Owns all canonical `WorldState` (location, inspected objects, discovered clues, presented evidence, NPC trust/suspicion/memory, accusation attempts).
   - LLMs never mutate state directly; every tool call (`move_to`, `inspect_object`, `talk_to_npc`, `present_evidence`, `update_npc_memory`, `submit_accusation`) is Pydantic-validated and returns structured `ToolError`s with `recovery_hint`s on invalid actions.
2. **Strict Context Isolation (`backend/src/detective_agent/context_builder.py`, `agents/npc.py`)**:
   - Each suspect runs as an independent NPC subagent that receives **only** the public briefing, their own private secrets/alibi/knowledge graph, their own episodic memory, and their own witnessed dialogue.
   - Verified by security regression tests (`tests/test_context_isolation.py`) and inspectable live in the UI via `NpcContextSnapshot`.
3. **Explicit Framework-Free Agent Loop (`backend/src/detective_agent/agent_loop.py`)**:
   - Built directly on `google-genai` with bounded `max_agent_steps` / `max_npc_steps` guards, structured tool-error recovery, and live `TraceEvent` streaming.
4. **Split-Screen Agent X-Ray UI (`frontend/`)**:
   - **Left Pane**: Archival Detective Casebook with chat, room/object quick actions, suspect trust/suspicion meters, collected clues drawer, and Accusation Modal.
   - **Right Pane**: Live SSE Agent X-Ray console showing active agent handoffs, tool calls & validated results/errors, JSON state diffs, and an **Inspect NPC System Context** modal.

---

## Quickstart

### 1. Backend Setup

```bash
cd backend
cp .env.example .env
# Edit .env and set GEMINI_API_KEY=...
uv sync
```

Run the test suite (zero network calls required):

```bash
uv run pytest -v
```

### 2. Play in the Terminal (CLI — Milestone 2)

```bash
cd backend
uv run detective-cli
```

Useful CLI commands: `/state`, `/trace`, `/inspect-npc <npc_evelyn|npc_clara|npc_marcus>`, `/quit`.

### 3. Run the Split-Screen Web App (Milestone 3)

Terminal 1 — FastAPI SSE server:
```bash
cd backend
uv run uvicorn detective_agent.api.main:app --reload --port 8000
```

Terminal 2 — Vite + React frontend:
```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.