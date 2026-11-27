"""Interactive playable CLI with live Agent X-Ray tracing (Milestone 2)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from dotenv import load_dotenv

from .agent_loop import DetectiveAgentLoop
from .engine import GameEngine
from .llm_client import AgentConfig, GeminiLLMClient
from .schemas import (
    AgentSelectedEvent,
    AssistantMessageEvent,
    LoopGuardTriggeredEvent,
    NpcContextSnapshotEvent,
    StateDiffEvent,
    ToolCallRequestedEvent,
    ToolCallResultEvent,
    TraceEvent,
    TurnCompletedEvent,
    default_case_path,
    load_case,
)


def _format_trace_event(event: TraceEvent, show_trace: bool) -> str | None:
    if isinstance(event, AssistantMessageEvent):
        return f"\n[{event.speaker_label}] {event.content}"

    if not show_trace:
        return None

    if isinstance(event, AgentSelectedEvent):
        return f"  >> AGENT [{event.active_agent}]: {event.reason}"
    if isinstance(event, ToolCallRequestedEvent):
        args_str = json.dumps(event.arguments, ensure_ascii=False)
        return f"  -> TOOL CALL [{event.agent_name}] {event.tool_name}({args_str})"
    if isinstance(event, ToolCallResultEvent):
        if event.ok:
            return f"  <- TOOL OK   [{event.tool_name}]: {json.dumps(event.result, ensure_ascii=False)}"
        err = event.error.model_dump() if event.error else {}
        return f"  !! TOOL ERR  [{event.tool_name}]: {json.dumps(err, ensure_ascii=False)}"
    if isinstance(event, StateDiffEvent):
        lines = ["  ~~ STATE DIFF:"]
        for d in event.changes:
            lines.append(f"       {d.op.upper()} {d.path}: {d.before!r} -> {d.after!r}")
        return "\n".join(lines)
    if isinstance(event, NpcContextSnapshotEvent):
        snap = event.snapshot
        return (
            f"  @@ NPC CONTEXT ISOLATION [{snap.npc_id}]: "
            f"memories={snap.memory_count}, witnessed_turns={snap.witnessed_dialogue_count}, "
            f"excluded={snap.isolated_from}"
        )
    if isinstance(event, LoopGuardTriggeredEvent):
        return f"  !! LOOP GUARD [{event.agent_name}]: {event.reason}"
    if isinstance(event, TurnCompletedEvent):
        return f"  -- TURN {event.turn} COMPLETE (steps={event.total_steps}, status={event.game_status})"
    return None


def _print_state(engine: GameEngine) -> None:
    st = engine.state
    room = engine.case.get_room(st.player_location)
    assert room is not None
    print("\n=== CURRENT WORLD STATE ===")
    print(f"Turn: {st.turn_count} | Status: {st.status} | Location: {room.name} ({room.room_id})")
    print(f"Connected Rooms: {', '.join(room.connected_rooms)}")
    print(f"Objects Here: {', '.join(o.object_id for o in room.objects)}")
    print(f"Discovered Clues ({len(st.discovered_clues)}/6): {', '.join(st.discovered_clues) or 'none'}")
    print("Suspects:")
    for npc in engine.case.npcs:
        ns = st.npc_states[npc.npc_id]
        print(
            f"  - {npc.name} ({npc.npc_id}) @ {ns.location} | "
            f"trust={ns.trust}/10 suspicion={ns.suspicion}/10 memories={len(ns.episodic_memory)}"
        )
    print("===========================\n")


async def _repl(show_trace: bool) -> None:
    load_dotenv()
    case = load_case(default_case_path())
    engine = GameEngine(case)

    try:
        llm_client = GeminiLLMClient()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    config = AgentConfig.from_env()
    loop = DetectiveAgentLoop(engine=engine, llm_client=llm_client, config=config)

    print(f"\n=== {case.title} ({case.case_id}) ===")
    print(case.public_intro)
    print(f"Models: DM={config.model_dm}, NPC={config.model_npc}")
    print("Commands: /state, /trace, /inspect-npc <npc_id>, /quit\n")
    _print_state(engine)

    while True:
        try:
            user_input = input("Detective> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting investigation.")
            break

        if not user_input:
            continue
        if user_input in {"/quit", "/exit"}:
            break
        if user_input == "/state":
            _print_state(engine)
            continue
        if user_input == "/trace":
            show_trace = not show_trace
            print(f"Trace output {'ENABLED' if show_trace else 'DISABLED'}.")
            continue
        if user_input.startswith("/inspect-npc"):
            parts = user_input.split(maxsplit=1)
            if len(parts) < 2:
                print("Usage: /inspect-npc <npc_evelyn|npc_clara|npc_marcus>")
                continue
            snap = loop.latest_npc_contexts.get(parts[1].strip())
            if snap is None:
                print(f"No context snapshot recorded yet for '{parts[1].strip()}'.")
            else:
                print(f"\n=== ISOLATED NPC SYSTEM PROMPT ({snap.npc_name}, turn {snap.turn}) ===")
                print(snap.system_prompt)
                print("=============================================================\n")
            continue

        async for event in loop.run_turn(user_input):
            formatted = _format_trace_event(event, show_trace=show_trace)
            if formatted:
                print(formatted)

        if engine.state.status != "in_progress":
            print(f"\n*** GAME OVER: {engine.state.status.upper()} ***")
            if engine.state.final_outcome:
                print(engine.state.final_outcome.verdict_summary)
            break


def main() -> None:
    parser = argparse.ArgumentParser(description="Play Detective Agent in the terminal.")
    parser.add_argument(
        "--no-trace",
        action="store_true",
        help="Hide live Agent X-Ray tool/diff trace output.",
    )
    args = parser.parse_args()
    asyncio.run(_repl(show_trace=not args.no_trace))


if __name__ == "__main__":
    main()
