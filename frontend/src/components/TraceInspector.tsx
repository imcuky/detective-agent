import {
  Activity,
  AlertOctagon,
  CheckCircle2,
  Eye,
  GitCompare,
  ShieldCheck,
  Terminal,
  Wrench,
  XCircle,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type {
  HealthResponse,
  NpcContextSnapshot,
  PublicCaseMetadata,
  TraceEvent,
} from '../types/protocol';

interface TraceInspectorProps {
  events: TraceEvent[];
  activeAgent: string;
  isStreaming: boolean;
  publicCase: PublicCaseMetadata;
  health: HealthResponse | null;
  onInspectSnapshot: (snapshot: NpcContextSnapshot) => void;
  onInspectNpcById: (npcId: string) => void;
}

type TraceFilter = 'all' | 'tools' | 'diffs' | 'npc';

function formatValue(val: unknown): string {
  if (val === null || val === undefined) return 'null';
  if (typeof val === 'string') return val.length > 96 ? `"${val.slice(0, 96)}…"` : `"${val}"`;
  const str = JSON.stringify(val);
  return str.length > 110 ? `${str.slice(0, 110)}…` : str;
}

export function TraceInspector({
  events,
  activeAgent,
  isStreaming,
  publicCase,
  health,
  onInspectSnapshot,
  onInspectNpcById,
}: TraceInspectorProps) {
  const [filter, setFilter] = useState<TraceFilter>('all');
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [events]);

  const filteredEvents = events.filter((ev) => {
    if (filter === 'all') return ev.event_type !== 'assistant_message';
    if (filter === 'tools') {
      return ev.event_type === 'tool_call_requested' || ev.event_type === 'tool_call_result';
    }
    if (filter === 'diffs') return ev.event_type === 'state_diff';
    if (filter === 'npc') {
      return (
        ev.event_type === 'npc_context_snapshot' ||
        (ev.event_type === 'agent_selected' && ev.active_agent.startsWith('npc_'))
      );
    }
    return true;
  });

  const agentClass = activeAgent.startsWith('npc_')
    ? 'npc'
    : activeAgent === 'dm_orchestrator'
      ? 'dm'
      : '';

  return (
    <aside className="xray-pane" aria-label="Agent X-Ray Trace Inspector">
      <header className="xray-header">
        <div className="xray-top-row">
          <div className="xray-title-wrap">
            <Terminal size={15} color="var(--xray-amber)" />
            <h2 className="xray-title">Agent X-Ray Inspector</h2>
          </div>

          <span className={`active-agent-pill ${agentClass}`}>
            <Activity size={12} />
            {isStreaming ? `ACTIVE: ${activeAgent}` : `LAST: ${activeAgent}`}
          </span>
        </div>

        <div className="xray-controls">
          <div className="filter-tabs" role="tablist" aria-label="Trace event filters">
            {(
              [
                ['all', 'All'],
                ['tools', 'Tools'],
                ['diffs', 'State Diffs'],
                ['npc', 'NPC Isolation'],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={filter === key}
                className={`filter-tab ${filter === key ? 'active' : ''}`}
                onClick={() => setFilter(key)}
              >
                {label}
              </button>
            ))}
          </div>

          {health && (
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10.5,
                color: 'var(--xray-text-muted)',
              }}
            >
              DM:{health.model_dm}
            </span>
          )}
        </div>

        <div className="npc-context-bar">
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10.5,
              color: 'var(--xray-text-muted)',
              textTransform: 'uppercase',
            }}
          >
            Inspect NPC Context:
          </span>
          {publicCase.npcs.map((npc) => (
            <button
              key={npc.npc_id}
              id={`xray-inspect-${npc.npc_id}`}
              type="button"
              className="xray-btn"
              onClick={() => onInspectNpcById(npc.npc_id)}
            >
              <Eye size={11} /> {npc.name.split(' ')[0]}
            </button>
          ))}
        </div>
      </header>

      <div className="trace-scroll">
        {filteredEvents.length === 0 ? (
          <div className="trace-empty">
            No trace events streamed yet. Send a detective action on the left to observe live
            tool calls, deterministic engine validation, JSON state diffs, and isolated NPC
            subagent contexts.
          </div>
        ) : (
          filteredEvents.map((ev) => {
            if (ev.event_type === 'turn_started') {
              return (
                <div key={ev.event_id} className="turn-divider">
                  Turn {ev.turn} · &ldquo;{ev.user_input.slice(0, 48)}
                  {ev.user_input.length > 48 ? '…' : ''}&rdquo;
                </div>
              );
            }

            if (ev.event_type === 'agent_selected') {
              const isNpc = ev.active_agent.startsWith('npc_');
              return (
                <div key={ev.event_id} className="trace-card">
                  <div className="trace-card-head">
                    <span className={`trace-tag ${isNpc ? 'sky' : 'amber'}`}>
                      <Activity size={13} /> AGENT HANDOFF → {ev.active_agent}
                    </span>
                    <span className="trace-meta-right">step {ev.step}</span>
                  </div>
                  <div className="trace-card-body">{ev.reason}</div>
                </div>
              );
            }

            if (ev.event_type === 'tool_call_requested') {
              return (
                <div key={ev.event_id} className="trace-card">
                  <div className="trace-card-head">
                    <span className="trace-tag amber">
                      <Wrench size={13} /> TOOL CALL · {ev.tool_name}
                    </span>
                    <span className="trace-meta-right">
                      {ev.agent_name} · step {ev.step}
                    </span>
                  </div>
                  <div className="trace-card-body">
                    <pre className="code-block">{JSON.stringify(ev.arguments, null, 2)}</pre>
                  </div>
                </div>
              );
            }

            if (ev.event_type === 'tool_call_result') {
              return (
                <div key={ev.event_id} className="trace-card">
                  <div className="trace-card-head">
                    <span className={`trace-tag ${ev.ok ? 'emerald' : 'coral'}`}>
                      {ev.ok ? <CheckCircle2 size={13} /> : <XCircle size={13} />}
                      {ev.ok ? `VALIDATED · ${ev.tool_name}` : `REJECTED · ${ev.tool_name}`}
                    </span>
                    <span className="trace-meta-right">
                      {ev.agent_name} · step {ev.step}
                    </span>
                  </div>
                  <div className="trace-card-body">
                    {ev.ok ? (
                      <pre className="code-block">{JSON.stringify(ev.result, null, 2)}</pre>
                    ) : (
                      <div className="error-box">
                        <div>
                          <strong>{ev.error?.code ?? 'ERROR'}</strong>: {ev.error?.message}
                        </div>
                        <div style={{ color: 'var(--xray-amber)' }}>
                          Recovery hint sent to agent: {ev.error?.recovery_hint}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              );
            }

            if (ev.event_type === 'state_diff') {
              return (
                <div key={ev.event_id} className="trace-card">
                  <div className="trace-card-head">
                    <span className="trace-tag emerald">
                      <GitCompare size={13} /> WORLD STATE DIFF ({ev.changes.length})
                    </span>
                    <span className="trace-meta-right">
                      {ev.agent_name} · step {ev.step}
                    </span>
                  </div>
                  <div className="trace-card-body">
                    <div className="diff-list">
                      {ev.changes.map((chg, idx) => (
                        <div key={`${ev.event_id}-${idx}`} className="diff-row">
                          <span className={`diff-op ${chg.op}`}>{chg.op}</span>
                          <div>
                            <div className="diff-path">{chg.path}</div>
                            <div className="diff-vals">
                              {chg.op === 'add'
                                ? `+ ${formatValue(chg.after)}`
                                : `${formatValue(chg.before)} → ${formatValue(chg.after)}`}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              );
            }

            if (ev.event_type === 'npc_context_snapshot') {
              const snap = ev.snapshot;
              return (
                <div key={ev.event_id} className="trace-card">
                  <div className="trace-card-head">
                    <span className="trace-tag sky">
                      <ShieldCheck size={13} /> ISOLATED CONTEXT · {snap.npc_name}
                    </span>
                    <button
                      type="button"
                      className="xray-btn sky"
                      onClick={() => onInspectSnapshot(snap)}
                    >
                      <Eye size={12} /> Inspect System Context
                    </button>
                  </div>
                  <div className="trace-card-body">
                    Memories visible: <strong>{snap.memory_count}</strong> · Witnessed turns:{' '}
                    <strong>{snap.witnessed_dialogue_count}</strong> · Excluded:{' '}
                    <code>{snap.isolated_from.join(', ')}</code>
                  </div>
                </div>
              );
            }

            if (ev.event_type === 'loop_guard_triggered') {
              return (
                <div key={ev.event_id} className="trace-card">
                  <div className="trace-card-head">
                    <span className="trace-tag coral">
                      <AlertOctagon size={13} /> MAX-STEP GUARD ({ev.max_steps})
                    </span>
                    <span className="trace-meta-right">{ev.agent_name}</span>
                  </div>
                  <div className="trace-card-body">{ev.reason}</div>
                </div>
              );
            }

            if (ev.event_type === 'turn_completed') {
              return (
                <div key={ev.event_id} className="turn-divider">
                  Turn {ev.turn} Done · {ev.total_steps} steps · {ev.game_status}
                </div>
              );
            }

            return null;
          })
        )}
        <div ref={endRef} />
      </div>
    </aside>
  );
}
