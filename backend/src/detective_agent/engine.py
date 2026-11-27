"""Deterministic GameEngine: single source of truth for all detective game state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .schemas import (
    DM_ALLOWED_TOOLS,
    NPC_ALLOWED_TOOLS,
    AccusationOutcome,
    CaseDefinition,
    ClueDef,
    ClueSummary,
    DialogueTurn,
    InspectObjectInput,
    InspectObjectResult,
    MoveToInput,
    MoveToResult,
    NpcMemoryEntry,
    NpcRuntimeState,
    NpcSummary,
    ObjectSummary,
    PresentEvidenceInput,
    PresentEvidenceResult,
    StateDiffEntry,
    SubmitAccusationInput,
    SubmitAccusationResult,
    TalkToNpcInput,
    TalkToNpcResult,
    ToolError,
    ToolErrorCode,
    ToolExecutionResult,
    UpdateNpcMemoryInput,
    UpdateNpcMemoryResult,
    WorldState,
)

DM_AGENT_NAME = "dm_orchestrator"


def _clamp(value: int, low: int = 0, high: int = 10) -> int:
    return max(low, min(high, value))


def _clue_to_summary(clue: ClueDef) -> ClueSummary:
    return ClueSummary(
        clue_id=clue.clue_id,
        title=clue.title,
        category=clue.category,
        summary=clue.summary,
    )


def compute_state_diff(
    before: Any,
    after: Any,
    prefix: str = "",
) -> list[StateDiffEntry]:
    """Compute a deterministic list of structured JSON diffs between two state dicts."""
    diffs: list[StateDiffEntry] = []

    if isinstance(before, dict) and isinstance(after, dict):
        all_keys = list(dict.fromkeys([*before.keys(), *after.keys()]))
        for key in all_keys:
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in before:
                diffs.append(StateDiffEntry(path=path, op="add", before=None, after=after[key]))
            elif key not in after:
                diffs.append(StateDiffEntry(path=path, op="remove", before=before[key], after=None))
            elif before[key] != after[key]:
                diffs.extend(compute_state_diff(before[key], after[key], path))
        return diffs

    if isinstance(before, list) and isinstance(after, list):
        if before == after:
            return diffs
        # If elements were strictly appended (common for clues, objects, memory, dialogue),
        # emit crisp "add" entries for newly appended items.
        if len(after) > len(before) and after[: len(before)] == before:
            for idx in range(len(before), len(after)):
                diffs.append(
                    StateDiffEntry(
                        path=f"{prefix}[{idx}]",
                        op="add",
                        before=None,
                        after=after[idx],
                    )
                )
            return diffs
        diffs.append(StateDiffEntry(path=prefix, op="replace", before=before, after=after))
        return diffs

    if before != after:
        diffs.append(StateDiffEntry(path=prefix, op="replace", before=before, after=after))
    return diffs


@dataclass(frozen=True)
class NpcDispatch:
    """Engine-validated instruction to invoke an isolated NPC subagent."""

    npc_id: str
    mode: str  # "talk" | "present_evidence"
    player_message: str
    presented_clue: ClueSummary | None = None
    reaction_guidance: str | None = None
    unlocked_clue: ClueSummary | None = None
    already_presented: bool = False
    trust_delta: int = 0
    suspicion_delta: int = 0


@dataclass(frozen=True)
class EngineToolOutcome:
    """Result of executing a single validated tool call against GameEngine."""

    result: ToolExecutionResult
    diffs: list[StateDiffEntry]
    npc_dispatch: NpcDispatch | None = None


class GameEngine:
    """Deterministic state machine owning canonical WorldState.

    LLMs never mutate state directly; every state change passes through
    validated tool handlers here.
    """

    def __init__(self, case: CaseDefinition, state: WorldState | None = None) -> None:
        self.case = case
        self.state = state if state is not None else self._build_initial_state(case)

    @staticmethod
    def _build_initial_state(case: CaseDefinition) -> WorldState:
        npc_states = {
            npc.npc_id: NpcRuntimeState(
                npc_id=npc.npc_id,
                location=npc.starting_room_id,
                trust=npc.initial_trust,
                suspicion=npc.initial_suspicion,
            )
            for npc in case.npcs
        }
        return WorldState(
            case_id=case.case_id,
            turn_count=0,
            status="in_progress",
            player_location=case.starting_room_id,
            max_accusation_attempts=case.max_accusation_attempts,
            npc_states=npc_states,
        )

    def snapshot_state(self) -> dict[str, Any]:
        """Return a JSON-serializable deep copy of current WorldState."""
        return self.state.model_dump(mode="json")

    def begin_turn(self) -> int:
        """Advance turn counter at the start of a detective turn."""
        self.state.turn_count += 1
        return self.state.turn_count

    def _error(
        self,
        tool_name: str,
        code: ToolErrorCode,
        message: str,
        recovery_hint: str,
    ) -> EngineToolOutcome:
        return EngineToolOutcome(
            result=ToolExecutionResult(
                ok=False,
                tool_name=tool_name,
                error=ToolError(code=code, message=message, recovery_hint=recovery_hint),
            ),
            diffs=[],
        )

    def _check_authorization(self, caller_agent: str, tool_name: str) -> EngineToolOutcome | None:
        if caller_agent == DM_AGENT_NAME:
            if tool_name not in DM_ALLOWED_TOOLS:
                return self._error(
                    tool_name,
                    "UNAUTHORIZED_AGENT",
                    f"Agent '{caller_agent}' is not permitted to invoke '{tool_name}'.",
                    "Only isolated NPC subagents may call 'update_npc_memory'.",
                )
            return None

        if caller_agent in self.state.npc_states:
            if tool_name not in NPC_ALLOWED_TOOLS:
                return self._error(
                    tool_name,
                    "UNAUTHORIZED_AGENT",
                    f"NPC subagent '{caller_agent}' cannot invoke '{tool_name}'.",
                    "NPC subagents may only call 'update_npc_memory' for themselves.",
                )
            return None

        return self._error(
            tool_name,
            "UNAUTHORIZED_AGENT",
            f"Unknown caller agent '{caller_agent}'.",
            "Use 'dm_orchestrator' or a valid NPC agent ID.",
        )

    def execute_tool(
        self,
        caller_agent: str,
        tool_name: str,
        raw_args: dict[str, Any],
    ) -> EngineToolOutcome:
        """Validate caller permissions, parse args via Pydantic, and apply state transition."""
        auth_err = self._check_authorization(caller_agent, tool_name)
        if auth_err is not None:
            return auth_err

        if self.state.status != "in_progress":
            return self._error(
                tool_name,
                "GAME_OVER",
                f"Case is already finished with status '{self.state.status}'.",
                "Start a new session to play again.",
            )

        handlers = {
            "move_to": self._handle_move_to,
            "inspect_object": self._handle_inspect_object,
            "talk_to_npc": self._handle_talk_to_npc,
            "present_evidence": self._handle_present_evidence,
            "update_npc_memory": self._handle_update_npc_memory,
            "submit_accusation": self._handle_submit_accusation,
        }
        handler = handlers.get(tool_name)
        if handler is None:
            return self._error(
                tool_name,
                "VALIDATION_ERROR",
                f"Unknown tool '{tool_name}'.",
                f"Use one of: {', '.join(sorted(handlers.keys()))}.",
            )

        before = self.snapshot_state()
        outcome = handler(caller_agent, raw_args)
        after = self.snapshot_state()
        diffs = compute_state_diff(before, after) if outcome.result.ok else []
        return EngineToolOutcome(
            result=outcome.result,
            diffs=diffs,
            npc_dispatch=outcome.npc_dispatch,
        )

    def record_npc_reply(self, npc_id: str, reply: str) -> list[StateDiffEntry]:
        """Append an NPC subagent's spoken reply to that NPC's witnessed dialogue."""
        npc_state = self.state.npc_states.get(npc_id)
        if npc_state is None:
            return []
        before = self.snapshot_state()
        npc_state.witnessed_dialogue.append(
            DialogueTurn(
                turn=self.state.turn_count,
                speaker="npc",
                content=reply,
            )
        )
        after = self.snapshot_state()
        return compute_state_diff(before, after)

    # --- Tool Handlers ---

    def _handle_move_to(self, _caller: str, raw_args: dict[str, Any]) -> EngineToolOutcome:
        try:
            args = MoveToInput.model_validate(raw_args)
        except ValidationError as exc:
            return self._error(
                "move_to",
                "VALIDATION_ERROR",
                str(exc),
                "Provide a valid 'target_room_id' string.",
            )

        target_room = self.case.get_room(args.target_room_id)
        if target_room is None:
            valid_rooms = ", ".join(r.room_id for r in self.case.rooms)
            return self._error(
                "move_to",
                "UNKNOWN_ROOM",
                f"Room '{args.target_room_id}' does not exist.",
                f"Valid room IDs are: {valid_rooms}.",
            )

        current_room = self.case.get_room(self.state.player_location)
        assert current_room is not None

        if args.target_room_id == current_room.room_id:
            return self._error(
                "move_to",
                "ALREADY_IN_ROOM",
                f"Detective is already in '{current_room.room_id}'.",
                f"Connected rooms from here: {', '.join(current_room.connected_rooms)}.",
            )

        if args.target_room_id not in current_room.connected_rooms:
            return self._error(
                "move_to",
                "ROOM_NOT_ADJACENT",
                f"Cannot move directly from '{current_room.room_id}' to '{args.target_room_id}'.",
                f"Move first to an adjacent room: {', '.join(current_room.connected_rooms)}.",
            )

        previous_room_id = current_room.room_id
        self.state.player_location = target_room.room_id

        visible_objects = [
            ObjectSummary(
                object_id=obj.object_id,
                name=obj.name,
                inspected=obj.object_id in self.state.inspected_objects,
            )
            for obj in target_room.objects
        ]
        present_npcs = [
            NpcSummary(npc_id=npc.npc_id, name=npc.name, role=npc.role)
            for npc in self.case.npcs
            if self.state.npc_states[npc.npc_id].location == target_room.room_id
        ]

        payload = MoveToResult(
            previous_room_id=previous_room_id,
            current_room_id=target_room.room_id,
            room_name=target_room.name,
            room_description=target_room.description,
            connected_rooms=list(target_room.connected_rooms),
            visible_objects=visible_objects,
            present_npcs=present_npcs,
        )
        return EngineToolOutcome(
            result=ToolExecutionResult(ok=True, tool_name="move_to", data=payload.model_dump()),
            diffs=[],
        )

    def _handle_inspect_object(self, _caller: str, raw_args: dict[str, Any]) -> EngineToolOutcome:
        try:
            args = InspectObjectInput.model_validate(raw_args)
        except ValidationError as exc:
            return self._error(
                "inspect_object",
                "VALIDATION_ERROR",
                str(exc),
                "Provide a valid 'object_id' string.",
            )

        located = self.case.find_object(args.object_id)
        if located is None:
            current_room = self.case.get_room(self.state.player_location)
            assert current_room is not None
            local_objs = ", ".join(o.object_id for o in current_room.objects)
            return self._error(
                "inspect_object",
                "UNKNOWN_OBJECT",
                f"Object '{args.object_id}' does not exist in this case.",
                f"Objects in your current room ({current_room.room_id}): {local_objs}.",
            )

        obj_room, obj_def = located
        if obj_room.room_id != self.state.player_location:
            return self._error(
                "inspect_object",
                "OBJECT_NOT_IN_ROOM",
                f"Object '{obj_def.object_id}' is in '{obj_room.room_id}', not '{self.state.player_location}'.",
                f"Use move_to to travel to '{obj_room.room_id}' before inspecting '{obj_def.object_id}'.",
            )

        already_inspected = obj_def.object_id in self.state.inspected_objects
        if not already_inspected:
            self.state.inspected_objects.append(obj_def.object_id)

        unlocked_clue: ClueSummary | None = None
        if obj_def.unlocks_clue_id:
            clue_def = self.case.get_clue(obj_def.unlocks_clue_id)
            assert clue_def is not None
            if obj_def.unlocks_clue_id not in self.state.discovered_clues:
                self.state.discovered_clues.append(obj_def.unlocks_clue_id)
                unlocked_clue = _clue_to_summary(clue_def)

        payload = InspectObjectResult(
            object_id=obj_def.object_id,
            object_name=obj_def.name,
            observation=obj_def.inspect_text,
            already_inspected=already_inspected,
            unlocked_clue=unlocked_clue,
        )
        return EngineToolOutcome(
            result=ToolExecutionResult(
                ok=True,
                tool_name="inspect_object",
                data=payload.model_dump(),
            ),
            diffs=[],
        )

    def _handle_talk_to_npc(self, _caller: str, raw_args: dict[str, Any]) -> EngineToolOutcome:
        try:
            args = TalkToNpcInput.model_validate(raw_args)
        except ValidationError as exc:
            return self._error(
                "talk_to_npc",
                "VALIDATION_ERROR",
                str(exc),
                "Provide valid 'npc_id' and non-empty 'message'.",
            )

        npc_def = self.case.get_npc(args.npc_id)
        if npc_def is None:
            valid_npcs = ", ".join(n.npc_id for n in self.case.npcs)
            return self._error(
                "talk_to_npc",
                "UNKNOWN_NPC",
                f"Suspect '{args.npc_id}' does not exist.",
                f"Valid suspect IDs: {valid_npcs}.",
            )

        npc_state = self.state.npc_states[args.npc_id]
        if npc_state.location != self.state.player_location:
            return self._error(
                "talk_to_npc",
                "NPC_NOT_IN_ROOM",
                f"{npc_def.name} ({npc_def.npc_id}) is in '{npc_state.location}', not '{self.state.player_location}'.",
                f"Move to '{npc_state.location}' before speaking to {npc_def.name}.",
            )

        npc_state.witnessed_dialogue.append(
            DialogueTurn(
                turn=self.state.turn_count,
                speaker="detective",
                content=args.message,
            )
        )

        payload = TalkToNpcResult(
            npc_id=npc_def.npc_id,
            npc_name=npc_def.name,
            npc_reply="",
            trust=npc_state.trust,
            suspicion=npc_state.suspicion,
            memory_updated=False,
        )
        return EngineToolOutcome(
            result=ToolExecutionResult(
                ok=True,
                tool_name="talk_to_npc",
                data=payload.model_dump(),
            ),
            diffs=[],
            npc_dispatch=NpcDispatch(
                npc_id=npc_def.npc_id,
                mode="talk",
                player_message=args.message,
            ),
        )

    def _handle_present_evidence(self, _caller: str, raw_args: dict[str, Any]) -> EngineToolOutcome:
        try:
            args = PresentEvidenceInput.model_validate(raw_args)
        except ValidationError as exc:
            return self._error(
                "present_evidence",
                "VALIDATION_ERROR",
                str(exc),
                "Provide valid 'npc_id', 'clue_id', and 'framing_question'.",
            )

        npc_def = self.case.get_npc(args.npc_id)
        if npc_def is None:
            valid_npcs = ", ".join(n.npc_id for n in self.case.npcs)
            return self._error(
                "present_evidence",
                "UNKNOWN_NPC",
                f"Suspect '{args.npc_id}' does not exist.",
                f"Valid suspect IDs: {valid_npcs}.",
            )

        npc_state = self.state.npc_states[args.npc_id]
        if npc_state.location != self.state.player_location:
            return self._error(
                "present_evidence",
                "NPC_NOT_IN_ROOM",
                f"{npc_def.name} ({npc_def.npc_id}) is in '{npc_state.location}', not '{self.state.player_location}'.",
                f"Move to '{npc_state.location}' before presenting evidence to {npc_def.name}.",
            )

        clue_def = self.case.get_clue(args.clue_id)
        if clue_def is None:
            return self._error(
                "present_evidence",
                "UNKNOWN_CLUE",
                f"Clue '{args.clue_id}' does not exist.",
                f"Owned clues: {', '.join(self.state.discovered_clues) or 'none yet'}.",
            )

        if args.clue_id not in self.state.discovered_clues:
            return self._error(
                "present_evidence",
                "CLUE_NOT_OWNED",
                f"Detective has not discovered clue '{args.clue_id}' yet.",
                f"Only present clues currently in discovered_clues: {', '.join(self.state.discovered_clues) or 'none yet'}.",
            )

        presented_list = self.state.presented_evidence.setdefault(args.npc_id, [])
        already_presented = args.clue_id in presented_list
        if not already_presented:
            presented_list.append(args.clue_id)

        reaction = npc_def.evidence_reactions.get(args.clue_id)
        unlocked_clue: ClueSummary | None = None
        trust_delta = 0
        suspicion_delta = 0
        reaction_guidance: str | None = None

        if reaction is not None:
            reaction_guidance = reaction.reaction_guidance
            if not already_presented:
                old_trust = npc_state.trust
                old_suspicion = npc_state.suspicion
                npc_state.trust = _clamp(npc_state.trust + reaction.trust_delta)
                npc_state.suspicion = _clamp(npc_state.suspicion + reaction.suspicion_delta)
                trust_delta = npc_state.trust - old_trust
                suspicion_delta = npc_state.suspicion - old_suspicion

                if reaction.unlocks_clue_id and reaction.unlocks_clue_id not in self.state.discovered_clues:
                    self.state.discovered_clues.append(reaction.unlocks_clue_id)
                    unlocked_def = self.case.get_clue(reaction.unlocks_clue_id)
                    assert unlocked_def is not None
                    unlocked_clue = _clue_to_summary(unlocked_def)

        npc_state.witnessed_dialogue.append(
            DialogueTurn(
                turn=self.state.turn_count,
                speaker="detective",
                content=f"[Presents {clue_def.title}] {args.framing_question}",
                presented_clue_id=clue_def.clue_id,
            )
        )

        payload = PresentEvidenceResult(
            npc_id=npc_def.npc_id,
            npc_name=npc_def.name,
            clue_id=clue_def.clue_id,
            already_presented=already_presented,
            unlocked_clue=unlocked_clue,
            trust_delta=trust_delta,
            suspicion_delta=suspicion_delta,
            npc_reply="",
        )
        return EngineToolOutcome(
            result=ToolExecutionResult(
                ok=True,
                tool_name="present_evidence",
                data=payload.model_dump(),
            ),
            diffs=[],
            npc_dispatch=NpcDispatch(
                npc_id=npc_def.npc_id,
                mode="present_evidence",
                player_message=args.framing_question,
                presented_clue=_clue_to_summary(clue_def),
                reaction_guidance=reaction_guidance,
                unlocked_clue=unlocked_clue,
                already_presented=already_presented,
                trust_delta=trust_delta,
                suspicion_delta=suspicion_delta,
            ),
        )

    def _handle_update_npc_memory(self, caller: str, raw_args: dict[str, Any]) -> EngineToolOutcome:
        try:
            args = UpdateNpcMemoryInput.model_validate(raw_args)
        except ValidationError as exc:
            return self._error(
                "update_npc_memory",
                "VALIDATION_ERROR",
                str(exc),
                "Provide valid npc_id, memory_summary, importance, and deltas within [-2, 2].",
            )

        if args.npc_id != caller:
            return self._error(
                "update_npc_memory",
                "UNAUTHORIZED_AGENT",
                f"NPC '{caller}' cannot modify memory for '{args.npc_id}'.",
                f"Set npc_id='{caller}' to update only your own episodic memory.",
            )

        npc_state = self.state.npc_states.get(args.npc_id)
        if npc_state is None:
            return self._error(
                "update_npc_memory",
                "UNKNOWN_NPC",
                f"Unknown NPC '{args.npc_id}'.",
                "Use your own valid npc_id.",
            )

        entry = NpcMemoryEntry(
            turn=self.state.turn_count,
            summary=args.memory_summary,
            importance=args.importance,
        )
        npc_state.episodic_memory.append(entry)
        npc_state.trust = _clamp(npc_state.trust + args.trust_delta)
        npc_state.suspicion = _clamp(npc_state.suspicion + args.suspicion_delta)

        payload = UpdateNpcMemoryResult(
            npc_id=args.npc_id,
            recorded_memory=entry,
            new_trust=npc_state.trust,
            new_suspicion=npc_state.suspicion,
        )
        return EngineToolOutcome(
            result=ToolExecutionResult(
                ok=True,
                tool_name="update_npc_memory",
                data=payload.model_dump(),
            ),
            diffs=[],
        )

    def _handle_submit_accusation(self, _caller: str, raw_args: dict[str, Any]) -> EngineToolOutcome:
        try:
            args = SubmitAccusationInput.model_validate(raw_args)
        except ValidationError as exc:
            return self._error(
                "submit_accusation",
                "VALIDATION_ERROR",
                str(exc),
                "Provide suspect_id, at least one owned clue in evidence_clue_ids, and reasoning (>=10 chars).",
            )

        suspect_def = self.case.get_npc(args.suspect_id)
        if suspect_def is None:
            valid_npcs = ", ".join(n.npc_id for n in self.case.npcs)
            return self._error(
                "submit_accusation",
                "UNKNOWN_NPC",
                f"Suspect '{args.suspect_id}' does not exist.",
                f"Choose from: {valid_npcs}.",
            )

        # Deduplicate while preserving order
        cited_clues = list(dict.fromkeys(args.evidence_clue_ids))
        for clue_id in cited_clues:
            if self.case.get_clue(clue_id) is None:
                return self._error(
                    "submit_accusation",
                    "UNKNOWN_CLUE",
                    f"Cited clue '{clue_id}' does not exist.",
                    f"Owned clues: {', '.join(self.state.discovered_clues) or 'none yet'}.",
                )
            if clue_id not in self.state.discovered_clues:
                return self._error(
                    "submit_accusation",
                    "CLUE_NOT_OWNED",
                    f"Cannot cite clue '{clue_id}' because it has not been discovered yet.",
                    f"Only cite owned clues: {', '.join(self.state.discovered_clues) or 'none yet'}.",
                )

        self.state.accusation_attempts += 1
        attempts_remaining = max(0, self.state.max_accusation_attempts - self.state.accusation_attempts)

        culprit_match = args.suspect_id == self.case.solution.culprit_id
        missing_required = [
            req for req in self.case.solution.required_clue_ids if req not in cited_clues
        ]

        if culprit_match and not missing_required:
            self.state.status = "won"
            verdict = f"Case Solved! {self.case.solution.summary}"
            self.state.final_outcome = AccusationOutcome(
                accused_npc_id=args.suspect_id,
                cited_clue_ids=cited_clues,
                reasoning=args.reasoning,
                correct=True,
                verdict_summary=verdict,
            )
            payload = SubmitAccusationResult(
                correct=True,
                game_status="won",
                attempts_remaining=attempts_remaining,
                verdict_summary=verdict,
                missing_required_clues=[],
            )
        else:
            if attempts_remaining == 0:
                self.state.status = "lost"
                verdict = (
                    f"Accusation rejected and no attempts remain. "
                    f"The real solution: {self.case.solution.summary}"
                )
                self.state.final_outcome = AccusationOutcome(
                    accused_npc_id=args.suspect_id,
                    cited_clue_ids=cited_clues,
                    reasoning=args.reasoning,
                    correct=False,
                    verdict_summary=verdict,
                )
            else:
                if culprit_match:
                    verdict = (
                        f"Your case against {suspect_def.name} lacks decisive proof "
                        f"({len(missing_required)} key piece(s) of evidence missing). "
                        f"You have {attempts_remaining} attempt(s) remaining."
                    )
                else:
                    verdict = (
                        f"Your accusation against {suspect_def.name} does not hold up against the facts. "
                        f"You have {attempts_remaining} attempt(s) remaining."
                    )

            payload = SubmitAccusationResult(
                correct=False,
                game_status=self.state.status,
                attempts_remaining=attempts_remaining,
                verdict_summary=verdict,
                missing_required_clues=missing_required if (culprit_match or self.state.status == "lost") else [],
            )

        return EngineToolOutcome(
            result=ToolExecutionResult(
                ok=True,
                tool_name="submit_accusation",
                data=payload.model_dump(),
            ),
            diffs=[],
        )
