"""Security regression tests proving strict context isolation for NPC subagents and DM."""

from detective_agent.context_builder import build_dm_system_prompt, build_npc_context_snapshot
from detective_agent.engine import DM_AGENT_NAME, GameEngine
from detective_agent.schemas import default_case_path, load_case


def test_npc_context_strictly_isolates_solution_and_other_npcs() -> None:
    case = load_case(default_case_path())
    engine = GameEngine(case)

    # Seed private episodic memory & witnessed dialogue for each NPC
    engine.begin_turn()
    engine.execute_tool(
        "npc_evelyn",
        "update_npc_memory",
        {
            "npc_id": "npc_evelyn",
            "memory_summary": "EVELYN_PRIVATE_MEM_SENTINEL: hid the glass vial in my pocket.",
            "importance": "high",
        },
    )
    engine.execute_tool(
        "npc_clara",
        "update_npc_memory",
        {
            "npc_id": "npc_clara",
            "memory_summary": "CLARA_PRIVATE_MEM_SENTINEL: worried about my medical license.",
            "importance": "high",
        },
    )
    engine.execute_tool(
        "npc_marcus",
        "update_npc_memory",
        {
            "npc_id": "npc_marcus",
            "memory_summary": "MARCUS_PRIVATE_MEM_SENTINEL: panicked about forged invoices.",
            "importance": "high",
        },
    )

    # Talk to Evelyn in study, then record a distinct witnessed line
    talk_ev = engine.execute_tool(
        DM_AGENT_NAME,
        "talk_to_npc",
        {"npc_id": "npc_evelyn", "message": "EVELYN_DIALOGUE_SENTINEL: Did you see Arthur?"},
    )
    assert talk_ev.result.ok and talk_ev.npc_dispatch is not None
    engine.record_npc_reply("npc_evelyn", "EVELYN_REPLY_SENTINEL: I was upstairs reading.")

    # Move to conservatory and build Clara's context snapshot
    engine.execute_tool(DM_AGENT_NAME, "move_to", {"target_room_id": "conservatory"})
    talk_clara = engine.execute_tool(
        DM_AGENT_NAME,
        "talk_to_npc",
        {"npc_id": "npc_clara", "message": "What happened to Arthur?"},
    )
    assert talk_clara.result.ok and talk_clara.npc_dispatch is not None

    snapshot = build_npc_context_snapshot(case, engine.state, talk_clara.npc_dispatch)
    serialized = snapshot.system_prompt + "\n" + str(snapshot.dialogue_messages)

    # 1. Clara MUST see her own secrets and memory
    clara_def = case.get_npc("npc_clara")
    assert clara_def is not None
    for own_secret in clara_def.private_knowledge.secrets:
        assert own_secret in snapshot.system_prompt
    assert "CLARA_PRIVATE_MEM_SENTINEL" in snapshot.system_prompt

    # 2. Clara MUST NOT see the global solution
    assert case.solution.summary not in serialized
    assert "culprit_id" not in serialized

    # 3. Clara MUST NOT see Evelyn's or Marcus's private secrets, alibis, memories, or dialogues
    for other_id in ("npc_evelyn", "npc_marcus"):
        other_def = case.get_npc(other_id)
        assert other_def is not None
        assert other_def.private_knowledge.alibi not in serialized
        for secret in other_def.private_knowledge.secrets:
            assert secret not in serialized
        for reaction in other_def.evidence_reactions.values():
            assert reaction.reaction_guidance not in serialized

    assert "EVELYN_PRIVATE_MEM_SENTINEL" not in serialized
    assert "MARCUS_PRIVATE_MEM_SENTINEL" not in serialized
    assert "EVELYN_DIALOGUE_SENTINEL" not in serialized
    assert "EVELYN_REPLY_SENTINEL" not in serialized


def test_dm_prompt_excludes_solution_and_npc_private_secrets() -> None:
    case = load_case(default_case_path())
    engine = GameEngine(case)
    dm_prompt = build_dm_system_prompt(case, engine.state)

    assert case.solution.summary not in dm_prompt
    for npc in case.npcs:
        for secret in npc.private_knowledge.secrets:
            assert secret not in dm_prompt
        for reaction in npc.evidence_reactions.values():
            assert reaction.reaction_guidance not in dm_prompt
