import { Check, Copy, ShieldCheck, X } from 'lucide-react';
import { useState } from 'react';
import type { NpcContextSnapshot } from '../types/protocol';

interface NpcContextModalProps {
  snapshot: NpcContextSnapshot | null;
  onClose: () => void;
}

export function NpcContextModal({ snapshot, onClose }: NpcContextModalProps) {
  const [copied, setCopied] = useState(false);

  if (!snapshot) return null;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(snapshot.system_prompt);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard may be unavailable in restricted contexts
    }
  };

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="npc-context-modal-title"
      onClick={onClose}
    >
      <div className="modal-panel dark" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2 id="npc-context-modal-title" className="modal-title">
              Isolated NPC Context — {snapshot.npc_name} ({snapshot.npc_id})
            </h2>
            <div style={{ fontSize: 12, color: 'var(--xray-text-muted)', marginTop: 2 }}>
              Turn {snapshot.turn} · {snapshot.memory_count} episodic memories ·{' '}
              {snapshot.witnessed_dialogue_count} witnessed dialogue turns
            </div>
          </div>
          <button
            type="button"
            className="xray-btn"
            onClick={onClose}
            aria-label="Close NPC context modal"
          >
            <X size={14} /> Close
          </button>
        </div>

        <div className="modal-body">
          <div className="isolation-banner">
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontWeight: 600 }}>
              <ShieldCheck size={15} /> Context Isolation Enforced
            </div>
            <div style={{ marginTop: 4 }}>
              Explicitly excluded from this subagent&apos;s prompt:{' '}
              <strong>{snapshot.isolated_from.join(', ')}</strong>
            </div>
          </div>

          <div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: 6,
              }}
            >
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11.5,
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                  color: 'var(--xray-sky)',
                }}
              >
                Exact System Prompt Visible to {snapshot.npc_name}
              </span>
              <button type="button" className="xray-btn" onClick={handleCopy}>
                {copied ? <Check size={12} /> : <Copy size={12} />}
                {copied ? 'Copied' : 'Copy Prompt'}
              </button>
            </div>
            <pre className="code-block" style={{ maxHeight: 320 }}>
              {snapshot.system_prompt}
            </pre>
          </div>

          <div>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11.5,
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
                color: 'var(--xray-amber)',
                marginBottom: 6,
              }}
            >
              Witnessed Dialogue Passed to Subagent ({snapshot.dialogue_messages.length})
            </div>
            <pre className="code-block" style={{ maxHeight: 180 }}>
              {JSON.stringify(snapshot.dialogue_messages, null, 2)}
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
}
