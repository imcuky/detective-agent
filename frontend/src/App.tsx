import { useCallback, useEffect, useState } from 'react';
import { createSession, fetchHealth, fetchNpcContext, streamTurn } from './api/client';
import { AccusationModal } from './components/AccusationModal';
import { DetectivePane } from './components/DetectivePane';
import { NpcContextModal } from './components/NpcContextModal';
import { TraceInspector } from './components/TraceInspector';
import type {
  ChatEntry,
  HealthResponse,
  NpcContextSnapshot,
  PublicCaseMetadata,
  TraceEvent,
  WorldState,
} from './types/protocol';

export function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [publicCase, setPublicCase] = useState<PublicCaseMetadata | null>(null);
  const [worldState, setWorldState] = useState<WorldState | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [chatLog, setChatLog] = useState<ChatEntry[]>([]);
  const [traceEvents, setTraceEvents] = useState<TraceEvent[]>([]);
  const [activeAgent, setActiveAgent] = useState<string>('idle');
  const [isStreaming, setIsStreaming] = useState(false);
  const [bootError, setBootError] = useState<string | null>(null);

  const [accusationOpen, setAccusationOpen] = useState(false);
  const [inspectedSnapshot, setInspectedSnapshot] = useState<NpcContextSnapshot | null>(null);

  const initNewSession = useCallback(async () => {
    setBootError(null);
    try {
      const [h, created] = await Promise.all([
        fetchHealth().catch(() => null),
        createSession(),
      ]);
      setHealth(h);
      setSessionId(created.session_id);
      setPublicCase(created.public_case);
      setWorldState(created.state);
      setTraceEvents([]);
      setActiveAgent('idle');
      setChatLog([
        {
          id: 'intro',
          kind: 'narrator',
          speakerLabel: 'Case Briefing',
          content: created.public_case.public_intro,
          turn: 0,
        },
      ]);
    } catch (err) {
      setBootError(err instanceof Error ? err.message : 'Unable to connect to Detective Agent API.');
    }
  }, []);

  useEffect(() => {
    void initNewSession();
  }, [initNewSession]);

  const handleSendMessage = useCallback(
    async (message: string) => {
      if (!sessionId || isStreaming) return;
      const nextTurn = (worldState?.turn_count ?? 0) + 1;

      setChatLog((prev) => [
        ...prev,
        {
          id: `det-${Date.now()}`,
          kind: 'detective',
          speakerLabel: 'Detective',
          content: message,
          turn: nextTurn,
        },
      ]);
      setIsStreaming(true);
      setActiveAgent('dm_orchestrator');

      await streamTurn(sessionId, message, {
        onTrace: (event) => {
          setTraceEvents((prev) => [...prev, event]);

          if (event.event_type === 'agent_selected') {
            setActiveAgent(event.active_agent);
          } else if (event.event_type === 'state_diff') {
            setWorldState(event.state_snapshot);
          } else if (event.event_type === 'assistant_message') {
            const isNpc = event.agent_name.startsWith('npc_');
            setChatLog((prev) => [
              ...prev,
              {
                id: event.event_id,
                kind: isNpc ? 'npc' : 'narrator',
                speakerLabel: event.speaker_label,
                agentName: event.agent_name,
                content: event.content,
                turn: event.turn,
              },
            ]);
          } else if (event.event_type === 'turn_completed') {
            setWorldState((prev) =>
              prev ? { ...prev, turn_count: event.turn, status: event.game_status } : prev,
            );
          }
        },
        onError: (errMsg) => {
          setChatLog((prev) => [
            ...prev,
            {
              id: `err-${Date.now()}`,
              kind: 'system',
              speakerLabel: 'System Error',
              content: errMsg,
              turn: nextTurn,
            },
          ]);
        },
        onDone: () => {
          setIsStreaming(false);
        },
      });
    },
    [sessionId, isStreaming, worldState?.turn_count],
  );

  const handleInspectNpcById = useCallback(
    async (npcId: string) => {
      if (!sessionId) return;
      try {
        const snapshot = await fetchNpcContext(sessionId, npcId, true);
        setInspectedSnapshot(snapshot);
      } catch (err) {
        setChatLog((prev) => [
          ...prev,
          {
            id: `ctx-err-${Date.now()}`,
            kind: 'system',
            speakerLabel: 'Context Inspector',
            content: err instanceof Error ? err.message : 'Unable to fetch NPC context.',
            turn: worldState?.turn_count ?? 0,
          },
        ]);
      }
    },
    [sessionId, worldState?.turn_count],
  );

  const handleSubmitAccusation = useCallback(
    (suspectId: string, clueIds: string[], reasoning: string) => {
      const suspectName =
        publicCase?.npcs.find((n) => n.npc_id === suspectId)?.name ?? suspectId;
      const prompt =
        `I submit a formal accusation using submit_accusation against ${suspectName} (${suspectId}). ` +
        `Cited evidence_clue_ids: [${clueIds.join(', ')}]. Reasoning: ${reasoning}`;
      void handleSendMessage(prompt);
    },
    [handleSendMessage, publicCase?.npcs],
  );

  if (bootError) {
    return (
      <main
        style={{
          height: '100vh',
          display: 'grid',
          placeItems: 'center',
          background: 'var(--xray-bg)',
          color: 'var(--xray-text)',
          padding: 24,
        }}
      >
        <div style={{ maxWidth: 460, textAlign: 'center' }}>
          <h1 style={{ fontFamily: 'var(--font-serif)', marginBottom: 8 }}>
            Detective Agent Backend Unreachable
          </h1>
          <p style={{ color: 'var(--xray-text-secondary)', fontSize: 14, lineHeight: 1.5 }}>
            {bootError}
          </p>
          <p style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--xray-amber)' }}>
            Start FastAPI: cd backend &amp;&amp; uv run uvicorn detective_agent.api.main:app --reload
          </p>
          <button type="button" className="xray-btn sky" onClick={() => void initNewSession()}>
            Retry Connection
          </button>
        </div>
      </main>
    );
  }

  if (!publicCase || !worldState) {
    return (
      <main
        style={{
          height: '100vh',
          display: 'grid',
          placeItems: 'center',
          background: 'var(--xray-bg)',
          color: 'var(--xray-text-muted)',
          fontFamily: 'var(--font-mono)',
          fontSize: 13,
        }}
      >
        Loading Case 01: The Midnight Ledger…
      </main>
    );
  }

  return (
    <main className="app-shell">
      <DetectivePane
        publicCase={publicCase}
        state={worldState}
        health={health}
        chatLog={chatLog}
        isStreaming={isStreaming}
        onSendMessage={(msg) => void handleSendMessage(msg)}
        onOpenAccusation={() => setAccusationOpen(true)}
        onInspectNpcContext={(npcId) => void handleInspectNpcById(npcId)}
        onResetSession={() => void initNewSession()}
      />

      <TraceInspector
        events={traceEvents}
        activeAgent={activeAgent}
        isStreaming={isStreaming}
        publicCase={publicCase}
        health={health}
        onInspectSnapshot={(snap) => setInspectedSnapshot(snap)}
        onInspectNpcById={(npcId) => void handleInspectNpcById(npcId)}
      />

      <AccusationModal
        open={accusationOpen}
        publicCase={publicCase}
        state={worldState}
        isBusy={isStreaming}
        onClose={() => setAccusationOpen(false)}
        onSubmit={handleSubmitAccusation}
      />

      <NpcContextModal
        snapshot={inspectedSnapshot}
        onClose={() => setInspectedSnapshot(null)}
      />
    </main>
  );
}

export default App;
