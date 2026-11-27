export type GameStatus = 'in_progress' | 'won' | 'lost';

export interface NpcMemoryEntry {
  turn: number;
  summary: string;
  importance: 'low' | 'medium' | 'high';
}

export interface DialogueTurn {
  turn: number;
  speaker: 'detective' | 'npc';
  content: string;
  presented_clue_id: string | null;
}

export interface NpcRuntimeState {
  npc_id: string;
  location: string;
  trust: number;
  suspicion: number;
  episodic_memory: NpcMemoryEntry[];
  witnessed_dialogue: DialogueTurn[];
}

export interface AccusationOutcome {
  accused_npc_id: string;
  cited_clue_ids: string[];
  reasoning: string;
  correct: boolean;
  verdict_summary: string;
}

export interface WorldState {
  case_id: string;
  turn_count: number;
  status: GameStatus;
  player_location: string;
  inspected_objects: string[];
  discovered_clues: string[];
  presented_evidence: Record<string, string[]>;
  npc_states: Record<string, NpcRuntimeState>;
  accusation_attempts: number;
  max_accusation_attempts: number;
  final_outcome: AccusationOutcome | null;
}

export interface PublicObjectMeta {
  object_id: string;
  name: string;
  description: string;
}

export interface PublicRoomMeta {
  room_id: string;
  name: string;
  description: string;
  connected_rooms: string[];
  objects: PublicObjectMeta[];
}

export interface PublicNpcMeta {
  npc_id: string;
  name: string;
  role: string;
  starting_room_id: string;
  public_profile: string;
}

export interface ClueMeta {
  clue_id: string;
  title: string;
  category: 'physical' | 'testimony';
  summary: string;
}

export interface PublicCaseMetadata {
  case_id: string;
  title: string;
  public_intro: string;
  starting_room_id: string;
  max_accusation_attempts: number;
  rooms: PublicRoomMeta[];
  npcs: PublicNpcMeta[];
  clues_catalog: Record<string, ClueMeta>;
}

export interface ToolError {
  code: string;
  message: string;
  recovery_hint: string;
}

export interface StateDiffEntry {
  path: string;
  op: 'add' | 'remove' | 'replace';
  before: unknown;
  after: unknown;
}

export interface NpcContextSnapshot {
  npc_id: string;
  npc_name: string;
  turn: number;
  system_prompt: string;
  dialogue_messages: Array<{ role: string; content: string }>;
  memory_count: number;
  witnessed_dialogue_count: number;
  isolated_from: string[];
}

interface BaseTraceEvent {
  event_id: string;
  turn: number;
  step: number;
  timestamp: string;
  agent_name: string;
}

export interface TurnStartedEvent extends BaseTraceEvent {
  event_type: 'turn_started';
  user_input: string;
}

export interface AgentSelectedEvent extends BaseTraceEvent {
  event_type: 'agent_selected';
  active_agent: string;
  reason: string;
}

export interface ToolCallRequestedEvent extends BaseTraceEvent {
  event_type: 'tool_call_requested';
  call_id: string;
  tool_name: string;
  arguments: Record<string, unknown>;
}

export interface ToolCallResultEvent extends BaseTraceEvent {
  event_type: 'tool_call_result';
  call_id: string;
  tool_name: string;
  ok: boolean;
  result: Record<string, unknown> | null;
  error: ToolError | null;
}

export interface StateDiffEvent extends BaseTraceEvent {
  event_type: 'state_diff';
  changes: StateDiffEntry[];
  state_snapshot: WorldState;
}

export interface NpcContextSnapshotEvent extends BaseTraceEvent {
  event_type: 'npc_context_snapshot';
  snapshot: NpcContextSnapshot;
}

export interface AssistantMessageEvent extends BaseTraceEvent {
  event_type: 'assistant_message';
  speaker_label: string;
  content: string;
  is_final: boolean;
}

export interface LoopGuardTriggeredEvent extends BaseTraceEvent {
  event_type: 'loop_guard_triggered';
  max_steps: number;
  reason: string;
}

export interface TurnCompletedEvent extends BaseTraceEvent {
  event_type: 'turn_completed';
  game_status: GameStatus;
  total_steps: number;
}

export type TraceEvent =
  | TurnStartedEvent
  | AgentSelectedEvent
  | ToolCallRequestedEvent
  | ToolCallResultEvent
  | StateDiffEvent
  | NpcContextSnapshotEvent
  | AssistantMessageEvent
  | LoopGuardTriggeredEvent
  | TurnCompletedEvent;

export interface ChatEntry {
  id: string;
  kind: 'detective' | 'narrator' | 'npc' | 'system';
  speakerLabel: string;
  agentName?: string;
  content: string;
  turn: number;
}

export interface HealthResponse {
  status: string;
  case_id: string;
  model_dm: string;
  model_npc: string;
  gemini_configured: boolean;
}

export interface CreateSessionResponse {
  session_id: string;
  public_case: PublicCaseMetadata;
  state: WorldState;
}
