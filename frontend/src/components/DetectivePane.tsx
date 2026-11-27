import {
  AlertTriangle,
  ArrowRight,
  Check,
  Eye,
  FileSearch,
  MessageSquare,
  RotateCcw,
  Scale,
  Send,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { ChatEntry, HealthResponse, PublicCaseMetadata, WorldState } from '../types/protocol';

interface DetectivePaneProps {
  publicCase: PublicCaseMetadata;
  state: WorldState;
  health: HealthResponse | null;
  chatLog: ChatEntry[];
  isStreaming: boolean;
  onSendMessage: (message: string) => void;
  onOpenAccusation: () => void;
  onInspectNpcContext: (npcId: string) => void;
  onResetSession: () => void;
}

export function DetectivePane({
  publicCase,
  state,
  health,
  chatLog,
  isStreaming,
  onSendMessage,
  onOpenAccusation,
  onInspectNpcContext,
  onResetSession,
}: DetectivePaneProps) {
  const [input, setInput] = useState('');
  const [selectedClueId, setSelectedClueId] = useState<string | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatLog, isStreaming]);

  const currentRoom = publicCase.rooms.find((r) => r.room_id === state.player_location);
  const roomNameById = Object.fromEntries(publicCase.rooms.map((r) => [r.room_id, r.name]));

  const presentNpcs = publicCase.npcs.filter(
    (npc) => state.npc_states[npc.npc_id]?.location === state.player_location,
  );

  const ownedClues = state.discovered_clues
    .map((cid) => publicCase.clues_catalog[cid])
    .filter(Boolean);

  const selectedClue = selectedClueId ? publicCase.clues_catalog[selectedClueId] : null;
  const gameFinished = state.status !== 'in_progress';

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isStreaming || gameFinished) return;
    setInput('');
    onSendMessage(trimmed);
  };

  return (
    <section className="detective-pane" aria-label="Detective Investigation Workspace">
      <header className="case-header">
        <div className="case-title-group">
          <span className="case-kicker">Case 01 · Deterministic Mystery</span>
          <h1 className="case-title">{publicCase.title}</h1>
        </div>

        <div className="header-actions">
          <span className={`status-badge ${state.status}`}>
            Turn {state.turn_count} ·{' '}
            {state.status === 'in_progress'
              ? 'Active'
              : state.status === 'won'
                ? 'Case Solved'
                : 'Case Failed'}
          </span>
          <button
            id="btn-open-accusation"
            type="button"
            className="btn btn-crimson"
            disabled={isStreaming || gameFinished}
            onClick={onOpenAccusation}
          >
            <Scale size={14} /> Accuse
          </button>
          <button
            id="btn-reset-case"
            type="button"
            className="btn"
            disabled={isStreaming}
            onClick={onResetSession}
            title="Start a fresh investigation session"
          >
            <RotateCcw size={14} /> Reset
          </button>
        </div>
      </header>

      {health && !health.gemini_configured && (
        <div className="config-banner" role="alert">
          <AlertTriangle size={16} style={{ flexShrink: 0 }} />
          <span>
            <strong>GEMINI_API_KEY</strong> is not configured on the backend. Add it to{' '}
            <code>backend/.env</code> and restart uvicorn to run live Gemini turns.
          </span>
        </div>
      )}

      {currentRoom && (
        <div className="scene-panel">
          <div className="scene-location-row">
            <div>
              <div className="room-title">{currentRoom.name}</div>
              <p className="room-desc">{currentRoom.description}</p>
            </div>
          </div>

          <div className="quick-actions-grid">
            <div className="action-group">
              <span className="action-label">Move To</span>
              <div className="chip-row">
                {currentRoom.connected_rooms.map((roomId) => (
                  <button
                    key={roomId}
                    id={`quick-move-${roomId}`}
                    type="button"
                    className="action-chip"
                    disabled={isStreaming || gameFinished}
                    onClick={() => onSendMessage(`Move to ${roomNameById[roomId] ?? roomId} (${roomId}).`)}
                  >
                    <ArrowRight size={13} /> {roomNameById[roomId] ?? roomId}
                  </button>
                ))}
              </div>
            </div>

            <div className="action-group">
              <span className="action-label">Inspect Objects</span>
              <div className="chip-row">
                {currentRoom.objects.map((obj) => {
                  const inspected = state.inspected_objects.includes(obj.object_id);
                  return (
                    <button
                      key={obj.object_id}
                      id={`quick-inspect-${obj.object_id}`}
                      type="button"
                      className={`action-chip ${inspected ? 'inspected' : ''}`}
                      disabled={isStreaming || gameFinished}
                      onClick={() =>
                        onSendMessage(`Inspect ${obj.name} (${obj.object_id}) carefully.`)
                      }
                    >
                      {inspected ? <Check size={13} /> : <FileSearch size={13} />}
                      {obj.name}
                    </button>
                  );
                })}
              </div>
            </div>

            {presentNpcs.length > 0 && (
              <div className="action-group">
                <span className="action-label">Suspects Present</span>
                <div className="chip-row">
                  {presentNpcs.map((npc) => {
                    const ns = state.npc_states[npc.npc_id];
                    return (
                      <div key={npc.npc_id} className="suspect-pill">
                        <strong>{npc.name}</strong>
                        <span className="suspect-meters">
                          <span className="meter-tag">T:{ns?.trust ?? 0}/10</span>
                          <span className="meter-tag">S:{ns?.suspicion ?? 0}/10</span>
                        </span>
                        <button
                          id={`quick-talk-${npc.npc_id}`}
                          type="button"
                          className="btn btn-ghost-sm"
                          disabled={isStreaming || gameFinished}
                          onClick={() =>
                            setInput(`Ask ${npc.name} (${npc.npc_id}) where they were at 11:00 PM.`)
                          }
                        >
                          <MessageSquare size={12} /> Ask
                        </button>
                        <button
                          id={`quick-context-${npc.npc_id}`}
                          type="button"
                          className="btn btn-ghost-sm"
                          onClick={() => onInspectNpcContext(npc.npc_id)}
                          title={`Inspect exact system prompt visible to ${npc.name}`}
                        >
                          <Eye size={12} />
                        </button>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      <div className="transcript-scroll" aria-live="polite">
        {chatLog.map((entry) => (
          <article key={entry.id} className={`chat-entry ${entry.kind}`}>
            <div className="chat-meta">
              <span>{entry.speakerLabel}</span>
              {entry.turn > 0 && <span>· Turn {entry.turn}</span>}
              {entry.kind === 'npc' && entry.agentName && (
                <button
                  type="button"
                  className="btn btn-ghost-sm"
                  onClick={() => onInspectNpcContext(entry.agentName!)}
                >
                  <Eye size={11} /> Inspect Context
                </button>
              )}
            </div>
            <div className="chat-bubble">{entry.content}</div>
          </article>
        ))}

        {isStreaming && (
          <div className="chat-entry narrator">
            <div className="chat-meta">Agent Loop Active</div>
            <div className="chat-bubble" style={{ color: 'var(--ink-muted)' }}>
              Investigating… watch the Agent X-Ray pane on the right for live tool calls &amp; state diffs.
            </div>
          </div>
        )}

        {state.final_outcome && (
          <div className={`verdict-banner ${state.status}`}>
            <strong>{state.final_outcome.correct ? 'Case Solved!' : 'Investigation Closed'}</strong>
            <p style={{ margin: '6px 0 0', fontSize: 13.5, lineHeight: 1.5 }}>
              {state.final_outcome.verdict_summary}
            </p>
          </div>
        )}

        <div ref={transcriptEndRef} />
      </div>

      <div className="clues-tray">
        <div className="clues-header">
          <span>Collected Clues ({ownedClues.length} / 6)</span>
          <span style={{ fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
            {ownedClues.length > 0
              ? 'Click a clue to view details or present it to a suspect here'
              : 'Inspect objects to uncover physical evidence'}
          </span>
        </div>

        {ownedClues.length > 0 && (
          <div className="clues-list">
            {ownedClues.map((clue) => (
              <button
                key={clue.clue_id}
                id={`clue-chip-${clue.clue_id}`}
                type="button"
                className={`clue-chip ${selectedClueId === clue.clue_id ? 'selected' : ''}`}
                onClick={() =>
                  setSelectedClueId((prev) => (prev === clue.clue_id ? null : clue.clue_id))
                }
              >
                <span className="clue-cat">{clue.category}</span>
                {clue.title}
              </button>
            ))}
          </div>
        )}

        {selectedClue && (
          <div className="clue-detail-bar">
            <div>
              <strong style={{ color: 'var(--ink-primary)' }}>{selectedClue.title}:</strong>{' '}
              {selectedClue.summary}
            </div>
            {presentNpcs.length > 0 && !gameFinished && (
              <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                {presentNpcs.map((npc) => (
                  <button
                    key={npc.npc_id}
                    type="button"
                    className="btn btn-primary"
                    disabled={isStreaming}
                    onClick={() => {
                      onSendMessage(
                        `Present evidence "${selectedClue.title}" (${selectedClue.clue_id}) to ${npc.name} (${npc.npc_id}) and demand an explanation.`,
                      );
                      setSelectedClueId(null);
                    }}
                  >
                    Present to {npc.name.split(' ')[0]}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <form className="composer-form" onSubmit={handleSubmit}>
        <input
          id="detective-chat-input"
          type="text"
          className="composer-input"
          placeholder={
            gameFinished
              ? 'Case closed. Click Reset to start a new investigation.'
              : 'Tell the detective what to do (e.g., "Examine the oak desk" or "Confront Evelyn with the crimson thread")...'
          }
          value={input}
          disabled={isStreaming || gameFinished}
          onChange={(e) => setInput(e.target.value)}
        />
        <button
          id="btn-send-turn"
          type="submit"
          className="btn btn-primary"
          disabled={isStreaming || gameFinished || !input.trim()}
        >
          <Send size={14} /> Send
        </button>
      </form>
    </section>
  );
}
