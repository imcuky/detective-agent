"""Tests validating case_01.json schema integrity, structure, and solvability."""

from detective_agent.schemas import default_case_path, load_case


def test_case_01_loads_and_matches_constraints() -> None:
    case = load_case(default_case_path())
    assert case.case_id == "case_01"
    assert len(case.rooms) == 3
    assert len(case.npcs) == 3
    assert len(case.clues) == 6

    physical = [c for c in case.clues if c.category == "physical"]
    testimony = [c for c in case.clues if c.category == "testimony"]
    assert len(physical) == 3
    assert len(testimony) == 3


def test_room_adjacency_is_symmetric_and_non_complete() -> None:
    case = load_case(default_case_path())
    room_map = {r.room_id: set(r.connected_rooms) for r in case.rooms}

    for room_id, neighbors in room_map.items():
        for neighbor in neighbors:
            assert room_id in room_map[neighbor], (
                f"Adjacency mismatch: {room_id} -> {neighbor} is not symmetric"
            )

    # Conservatory and cellar must not be directly connected (tests move_to path validation)
    assert "cellar" not in room_map["conservatory"]
    assert "conservatory" not in room_map["cellar"]


def test_all_testimony_clues_are_unlockable_via_evidence_reactions() -> None:
    case = load_case(default_case_path())
    unlockable_by_objects = {
        obj.unlocks_clue_id
        for room in case.rooms
        for obj in room.objects
        if obj.unlocks_clue_id
    }
    unlockable_by_reactions = {
        reaction.unlocks_clue_id
        for npc in case.npcs
        for reaction in npc.evidence_reactions.values()
        if reaction.unlocks_clue_id
    }

    all_clue_ids = {c.clue_id for c in case.clues}
    assert unlockable_by_objects | unlockable_by_reactions == all_clue_ids
    assert set(case.solution.required_clue_ids).issubset(all_clue_ids)


def test_public_metadata_excludes_solution_and_private_knowledge() -> None:
    case = load_case(default_case_path())
    meta = case.to_public_metadata()
    raw = str(meta)

    assert "solution" not in meta
    assert case.solution.summary not in raw
    for npc in case.npcs:
        for secret in npc.private_knowledge.secrets:
            assert secret not in raw
