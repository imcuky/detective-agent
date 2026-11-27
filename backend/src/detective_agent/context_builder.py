"""Strict context builders enforcing information isolation between DM and NPC subagents."""

from __future__ import annotations

from .engine import NpcDispatch
from .schemas import CaseDefinition, NpcContextSnapshot, WorldState


def build_dm_system_prompt(case: CaseDefinition, state: WorldState) -> str:
    """Build the DM Orchestrator system prompt.

    Contains ONLY public case setup and current observable WorldState.
    Never exposes `case.solution` or any NPC's `private_knowledge`.
    """
    current_room = case.get_room(state.player_location)
    assert current_room is not None

    room_lines = []
    for room in case.rooms:
        marker = " [CURRENT]" if room.room_id == state.player_location else ""
        adj = ", ".join(room.connected_rooms)
        objs = ", ".join(
            f"{o.object_id} ({o.name}{' - inspected' if o.object_id in state.inspected_objects else ''})"
            for o in room.objects
        )
        npcs_here = ", ".join(
            f"{n.npc_id} ({n.name})"
            for n in case.npcs
            if state.npc_states[n.npc_id].location == room.room_id
        )
        room_lines.append(
            f"- {room.room_id} ({room.name}){marker}\n"
            f"  Connected to: {adj}\n"
            f"  Objects: {objs}\n"
            f"  Suspects present: {npcs_here or 'none'}"
        )

    owned_clues = []
    for clue_id in state.discovered_clues:
        clue = case.get_clue(clue_id)
        if clue:
            owned_clues.append(f"- {clue.clue_id} [{clue.category}] {clue.title}: {clue.summary}")

    suspect_lines = [
        f"- {npc.npc_id}: {npc.name} ({npc.role}) — in {state.npc_states[npc.npc_id].location}. "
        f"Public profile: {npc.public_profile}"
        for npc in case.npcs
    ]

    return f"""You are the Detective Game Master & Orchestrator for "{case.title}".

PUBLIC CASE BRIEFING:
{case.public_intro}

CURRENT STATE (Turn {state.turn_count}, Status: {state.status}):
- Detective Location: {current_room.room_id} ({current_room.name})
- Accusation Attempts Used: {state.accusation_attempts}/{state.max_accusation_attempts}

MANOR MAP & OBSERVABLE ENTITIES:
{chr(10).join(room_lines)}

SUSPECTS (PUBLIC PROFILES ONLY):
{chr(10).join(suspect_lines)}

DISCOVERED CLUES OWNED BY DETECTIVE:
{chr(10).join(owned_clues) if owned_clues else "- None discovered yet."}

STRICT RULES:
1. You NEVER invent state mutations or speak on behalf of suspects yourself. Always use the provided tools:
   - `move_to` to change rooms (only along connected_rooms; chain multiple moves if needed).
   - `inspect_object` to examine objects in the detective's current room.
   - `talk_to_npc` to ask a suspect in the current room a question (this delegates to their isolated NPC subagent).
   - `present_evidence` to confront a suspect in the current room with an owned clue ID.
   - `submit_accusation` only when the player explicitly accuses a suspect.
2. If a tool returns an error (such as OBJECT_NOT_IN_ROOM or ROOM_NOT_ADJACENT), follow its `recovery_hint` cleanly (for example, move to the required room first if the player asked to go there and inspect/talk).
3. Never reveal internal IDs awkwardly in prose unless helpful, and never invent clues or suspect confessions that did not come from tool results.
4. Keep your narrative responses atmospheric, concise, and faithful to exact tool outputs. When an NPC responds via `talk_to_npc` or `present_evidence`, quote or faithfully present their reply and note any newly unlocked clues."""


def build_npc_context_snapshot(
    case: CaseDefinition,
    state: WorldState,
    dispatch: NpcDispatch,
) -> NpcContextSnapshot:
    """Build the strictly isolated prompt & message history for a single NPC subagent.

    Guarantees:
    - NEVER includes `case.solution`.
    - NEVER includes any other NPC's `private_knowledge`, `evidence_reactions`,
      `episodic_memory`, or `witnessed_dialogue`.
    """
    npc_def = case.get_npc(dispatch.npc_id)
    assert npc_def is not None
    npc_state = state.npc_states[dispatch.npc_id]
    current_room = case.get_room(npc_state.location)
    assert current_room is not None

    secrets_block = "\n".join(f"- {s}" for s in npc_def.private_knowledge.secrets)
    kg_block = "\n".join(
        f"- {entity}: {belief}"
        for entity, belief in npc_def.private_knowledge.knowledge_graph.items()
    )
    memory_block = (
        "\n".join(
            f"- [Turn {m.turn} | {m.importance}] {m.summary}"
            for m in npc_state.episodic_memory
        )
        if npc_state.episodic_memory
        else "- No prior episodic memories recorded yet."
    )

    # Public roster of the house (names & roles only — never other NPCs' private secrets)
    public_roster = "\n".join(
        f"- {other.name} ({other.role})"
        for other in case.npcs
        if other.npc_id != npc_def.npc_id
    )

    reaction_section = ""
    if dispatch.mode == "present_evidence" and dispatch.presented_clue is not None:
        reaction_section = (
            f"\nCURRENT CONFRONTATION:\n"
            f"The detective is showing you physical/testimonial evidence right now:\n"
            f"- Evidence Title: {dispatch.presented_clue.title}\n"
            f"- Evidence Summary: {dispatch.presented_clue.summary}\n"
        )
        if dispatch.reaction_guidance:
            reaction_section += (
                f"- Mandatory Emotional & Factual Reaction Guidance: {dispatch.reaction_guidance}\n"
            )
        else:
            reaction_section += (
                "- This evidence does not directly corner your hidden secrets; react in character based only on what you know.\n"
            )

    system_prompt = f"""You are roleplaying as **{npc_def.name}** ({npc_def.role}) in the mystery "{case.title}".

PUBLIC CASE CONTEXT:
{case.public_intro}
Your current location: {current_room.name} ({current_room.description})
Other guests in the manor (public info only):
{public_roster}

YOUR PUBLIC PERSONA:
{npc_def.public_profile}

YOUR PRIVATE KNOWLEDGE (KNOWN ONLY TO YOU):
- Claimed Alibi: {npc_def.private_knowledge.alibi}
- Persona & Speech Style: {npc_def.private_knowledge.persona_instructions}
- Private Secrets:
{secrets_block}
- Your Personal Beliefs About Others:
{kg_block}

YOUR CURRENT INTERNAL STATE:
- Trust toward the detective: {npc_state.trust}/10
- Suspicion / defensiveness level: {npc_state.suspicion}/10
- Your Episodic Memory of Earlier Turns:
{memory_block}
{reaction_section}
SUBAGENT RULES:
1. Stay strictly in character as {npc_def.name} (first person, 2–4 sharp sentences).
2. You ONLY know what is listed above and in your witnessed dialogue. Do not invent facts about rooms or events you did not witness.
3. Protect your private secrets unless the detective confronts you with decisive evidence matching your reaction guidance.
4. Before giving your final spoken reply, you MAY optionally call `update_npc_memory` with `npc_id="{npc_def.npc_id}"` if the detective asked something notable or shifted your trust/suspicion (deltas bounded to -2..+2). Then produce your final spoken response."""

    # Witnessed dialogue is ONLY this NPC's own dialogue turns.
    # Exclude the just-appended final detective message so we pass it cleanly as the latest user turn.
    history = npc_state.witnessed_dialogue
    prior_turns = history[:-1] if history and history[-1].speaker == "detective" else history

    dialogue_messages: list[dict[str, str]] = [
        {
            "role": "user" if turn.speaker == "detective" else "model",
            "content": turn.content,
        }
        for turn in prior_turns
    ]

    if dispatch.mode == "present_evidence" and dispatch.presented_clue is not None:
        latest_content = (
            f"[The detective presents '{dispatch.presented_clue.title}': "
            f"{dispatch.presented_clue.summary}]\n"
            f"Detective: {dispatch.player_message}"
        )
    else:
        latest_content = f"Detective: {dispatch.player_message}"

    dialogue_messages.append({"role": "user", "content": latest_content})

    return NpcContextSnapshot(
        npc_id=npc_def.npc_id,
        npc_name=npc_def.name,
        turn=state.turn_count,
        system_prompt=system_prompt,
        dialogue_messages=dialogue_messages,
        memory_count=len(npc_state.episodic_memory),
        witnessed_dialogue_count=len(npc_state.witnessed_dialogue),
    )
