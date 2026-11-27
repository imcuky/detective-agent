"""Unit and end-to-end deterministic playthrough tests for GameEngine."""

import pytest

from detective_agent.engine import DM_AGENT_NAME, GameEngine
from detective_agent.schemas import default_case_path, load_case


@pytest.fixture
def engine() -> GameEngine:
    case = load_case(default_case_path())
    return GameEngine(case)


def test_initial_world_state(engine: GameEngine) -> None:
    assert engine.state.player_location == "study"
    assert engine.state.turn_count == 0
    assert engine.state.status == "in_progress"
    assert engine.state.discovered_clues == []
    assert set(engine.state.npc_states.keys()) == {"npc_evelyn", "npc_clara", "npc_marcus"}


def test_move_to_valid_and_invalid_adjacency(engine: GameEngine) -> None:
    # Already in study
    already = engine.execute_tool(DM_AGENT_NAME, "move_to", {"target_room_id": "study"})
    assert not already.result.ok
    assert already.result.error is not None
    assert already.result.error.code == "ALREADY_IN_ROOM"
    assert already.diffs == []

    # Unknown room
    unknown = engine.execute_tool(DM_AGENT_NAME, "move_to", {"target_room_id": "attic"})
    assert not unknown.result.ok
    assert unknown.result.error is not None
    assert unknown.result.error.code == "UNKNOWN_ROOM"

    # Valid move: study -> conservatory
    moved = engine.execute_tool(DM_AGENT_NAME, "move_to", {"target_room_id": "conservatory"})
    assert moved.result.ok
    assert engine.state.player_location == "conservatory"
    assert any(d.path == "player_location" and d.after == "conservatory" for d in moved.diffs)

    # Invalid non-adjacent move: conservatory -> cellar
    non_adj = engine.execute_tool(DM_AGENT_NAME, "move_to", {"target_room_id": "cellar"})
    assert not non_adj.result.ok
    assert non_adj.result.error is not None
    assert non_adj.result.error.code == "ROOM_NOT_ADJACENT"
    assert "study" in non_adj.result.error.recovery_hint
    assert engine.state.player_location == "conservatory"


def test_inspect_object_cross_room_rejected_and_local_unlocks_clue(engine: GameEngine) -> None:
    # Trying to inspect cellar breaker_box while in study must fail cleanly
    wrong_room = engine.execute_tool(DM_AGENT_NAME, "inspect_object", {"object_id": "breaker_box"})
    assert not wrong_room.result.ok
    assert wrong_room.result.error is not None
    assert wrong_room.result.error.code == "OBJECT_NOT_IN_ROOM"
    assert "cellar" in wrong_room.result.error.recovery_hint

    # Inspecting oak_desk in study unlocks clue_poisoned_teacup
    inspected = engine.execute_tool(DM_AGENT_NAME, "inspect_object", {"object_id": "oak_desk"})
    assert inspected.result.ok
    assert inspected.result.data is not None
    assert inspected.result.data["unlocked_clue"]["clue_id"] == "clue_poisoned_teacup"
    assert "clue_poisoned_teacup" in engine.state.discovered_clues
    assert any(d.path.startswith("discovered_clues") for d in inspected.diffs)

    # Re-inspecting is idempotent and does not duplicate clues
    again = engine.execute_tool(DM_AGENT_NAME, "inspect_object", {"object_id": "oak_desk"})
    assert again.result.ok
    assert again.result.data is not None
    assert again.result.data["already_inspected"] is True
    assert again.result.data["unlocked_clue"] is None
    assert engine.state.discovered_clues.count("clue_poisoned_teacup") == 1


def test_talk_and_present_evidence_validation(engine: GameEngine) -> None:
    # Talking to Clara while in study fails (she is in conservatory)
    talk_err = engine.execute_tool(
        DM_AGENT_NAME,
        "talk_to_npc",
        {"npc_id": "npc_clara", "message": "Where were you at 11 PM?"},
    )
    assert not talk_err.result.ok
    assert talk_err.result.error is not None
    assert talk_err.result.error.code == "NPC_NOT_IN_ROOM"

    # Presenting an unowned clue to Evelyn in study fails
    unowned = engine.execute_tool(
        DM_AGENT_NAME,
        "present_evidence",
        {
            "npc_id": "npc_evelyn",
            "clue_id": "clue_broken_vial_clasp",
            "framing_question": "Explain this crimson thread.",
        },
    )
    assert not unowned.result.ok
    assert unowned.result.error is not None
    assert unowned.result.error.code == "CLUE_NOT_OWNED"


def test_update_npc_memory_authorization_and_clamping(engine: GameEngine) -> None:
    # DM cannot call update_npc_memory
    dm_attempt = engine.execute_tool(
        DM_AGENT_NAME,
        "update_npc_memory",
        {"npc_id": "npc_evelyn", "memory_summary": "Tried to tamper."},
    )
    assert not dm_attempt.result.ok
    assert dm_attempt.result.error is not None
    assert dm_attempt.result.error.code == "UNAUTHORIZED_AGENT"

    # NPC cannot mutate ANOTHER NPC's memory
    cross_npc = engine.execute_tool(
        "npc_evelyn",
        "update_npc_memory",
        {"npc_id": "npc_clara", "memory_summary": "Cross-agent leak."},
    )
    assert not cross_npc.result.ok
    assert cross_npc.result.error is not None
    assert cross_npc.result.error.code == "UNAUTHORIZED_AGENT"

    # NPC cannot call DM tools
    npc_move = engine.execute_tool("npc_evelyn", "move_to", {"target_room_id": "cellar"})
    assert not npc_move.result.ok
    assert npc_move.result.error is not None
    assert npc_move.result.error.code == "UNAUTHORIZED_AGENT"

    # Out-of-range deltas fail Pydantic validation
    bad_delta = engine.execute_tool(
        "npc_evelyn",
        "update_npc_memory",
        {"npc_id": "npc_evelyn", "memory_summary": "Big jump", "trust_delta": 5},
    )
    assert not bad_delta.result.ok
    assert bad_delta.result.error is not None
    assert bad_delta.result.error.code == "VALIDATION_ERROR"

    # Valid self-memory update succeeds and emits state diff
    engine.begin_turn()
    ok_mem = engine.execute_tool(
        "npc_evelyn",
        "update_npc_memory",
        {
            "npc_id": "npc_evelyn",
            "memory_summary": "Detective asked probing questions about my shawl.",
            "importance": "high",
            "trust_delta": -1,
            "suspicion_delta": 2,
        },
    )
    assert ok_mem.result.ok
    assert engine.state.npc_states["npc_evelyn"].trust == 4
    assert engine.state.npc_states["npc_evelyn"].suspicion == 4
    assert len(engine.state.npc_states["npc_evelyn"].episodic_memory) == 1
    assert len(ok_mem.diffs) >= 3


def test_full_scripted_playthrough_to_victory(engine: GameEngine) -> None:
    """Walk through all 3 rooms, unlock all 6 clues, and solve the case deterministically."""
    # 1. Inspect Study desk -> clue_poisoned_teacup
    engine.begin_turn()
    r = engine.execute_tool(DM_AGENT_NAME, "inspect_object", {"object_id": "oak_desk"})
    assert r.result.ok

    # 2. Move to Conservatory -> inspect cabinet -> clue_broken_vial_clasp
    engine.begin_turn()
    assert engine.execute_tool(DM_AGENT_NAME, "move_to", {"target_room_id": "conservatory"}).result.ok
    r = engine.execute_tool(DM_AGENT_NAME, "inspect_object", {"object_id": "apothecary_cabinet"})
    assert r.result.ok
    assert "clue_broken_vial_clasp" in engine.state.discovered_clues

    # 3. Present poisoned teacup to Clara -> unlocks clue_clara_testimony
    engine.begin_turn()
    clara = engine.execute_tool(
        DM_AGENT_NAME,
        "present_evidence",
        {
            "npc_id": "npc_clara",
            "clue_id": "clue_poisoned_teacup",
            "framing_question": "This teacup smells of bitter almonds and laurel resin.",
        },
    )
    assert clara.result.ok
    assert clara.npc_dispatch is not None
    assert clara.npc_dispatch.reaction_guidance is not None
    assert "clue_clara_testimony" in engine.state.discovered_clues
    engine.record_npc_reply("npc_clara", "It was cherry-laurel cyanide dosed between 11:00 and 11:10.")

    # 4. Return to Study -> present broken cabinet to Evelyn -> unlocks clue_evelyn_motive
    engine.begin_turn()
    assert engine.execute_tool(DM_AGENT_NAME, "move_to", {"target_room_id": "study"}).result.ok
    evelyn = engine.execute_tool(
        DM_AGENT_NAME,
        "present_evidence",
        {
            "npc_id": "npc_evelyn",
            "clue_id": "clue_broken_vial_clasp",
            "framing_question": "Why is a thread from your crimson shawl on the pried cabinet?",
        },
    )
    assert evelyn.result.ok
    assert "clue_evelyn_motive" in engine.state.discovered_clues

    # 5. Go to Cellar -> inspect breaker_box -> clue_jammed_breaker -> confront Marcus -> clue_marcus_testimony
    engine.begin_turn()
    assert engine.execute_tool(DM_AGENT_NAME, "move_to", {"target_room_id": "cellar"}).result.ok
    assert engine.execute_tool(DM_AGENT_NAME, "inspect_object", {"object_id": "breaker_box"}).result.ok
    marcus = engine.execute_tool(
        DM_AGENT_NAME,
        "present_evidence",
        {
            "npc_id": "npc_marcus",
            "clue_id": "clue_jammed_breaker",
            "framing_question": "Your forged invoice jammed the Study breaker. Talk.",
        },
    )
    assert marcus.result.ok
    assert "clue_marcus_testimony" in engine.state.discovered_clues
    assert len(engine.state.discovered_clues) == 6

    # 6. Premature accusation missing required clue consumes 1 attempt but stays in_progress
    engine.begin_turn()
    weak = engine.execute_tool(
        DM_AGENT_NAME,
        "submit_accusation",
        {
            "suspect_id": "npc_evelyn",
            "evidence_clue_ids": ["clue_poisoned_teacup"],
            "reasoning": "Evelyn poisoned Arthur's teacup in the study.",
        },
    )
    assert weak.result.ok
    assert weak.result.data is not None
    assert weak.result.data["correct"] is False
    assert engine.state.status == "in_progress"
    assert engine.state.accusation_attempts == 1

    # 7. Complete accusation wins the case
    engine.begin_turn()
    win = engine.execute_tool(
        DM_AGENT_NAME,
        "submit_accusation",
        {
            "suspect_id": "npc_evelyn",
            "evidence_clue_ids": [
                "clue_poisoned_teacup",
                "clue_broken_vial_clasp",
                "clue_marcus_testimony",
                "clue_evelyn_motive",
            ],
            "reasoning": "Evelyn stole Clara's laurel cyanide with the letter opener to prevent disinheritance and poisoned Arthur's tea.",
        },
    )
    assert win.result.ok
    assert win.result.data is not None
    assert win.result.data["correct"] is True
    assert engine.state.status == "won"
    assert engine.state.final_outcome is not None

    # 8. Subsequent actions after game over are blocked
    post_game = engine.execute_tool(DM_AGENT_NAME, "move_to", {"target_room_id": "study"})
    assert not post_game.result.ok
    assert post_game.result.error is not None
    assert post_game.result.error.code == "GAME_OVER"


def test_wrong_accusations_exhaust_attempts_and_lose(engine: GameEngine) -> None:
    engine.execute_tool(DM_AGENT_NAME, "inspect_object", {"object_id": "oak_desk"})

    # Citing an unowned clue returns CLUE_NOT_OWNED and does NOT burn an attempt
    bad_cite = engine.execute_tool(
        DM_AGENT_NAME,
        "submit_accusation",
        {
            "suspect_id": "npc_marcus",
            "evidence_clue_ids": ["clue_jammed_breaker"],
            "reasoning": "Marcus did it in the cellar.",
        },
    )
    assert not bad_cite.result.ok
    assert bad_cite.result.error is not None
    assert bad_cite.result.error.code == "CLUE_NOT_OWNED"
    assert engine.state.accusation_attempts == 0

    # Two wrong accusations -> lost
    for _ in range(2):
        res = engine.execute_tool(
            DM_AGENT_NAME,
            "submit_accusation",
            {
                "suspect_id": "npc_marcus",
                "evidence_clue_ids": ["clue_poisoned_teacup"],
                "reasoning": "Marcus poisoned Arthur's tea after their argument.",
            },
        )
        assert res.result.ok

    assert engine.state.status == "lost"
    assert engine.state.final_outcome is not None
    assert engine.state.final_outcome.correct is False
