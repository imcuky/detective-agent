import { Scale, X } from 'lucide-react';
import { useState } from 'react';
import type { PublicCaseMetadata, WorldState } from '../types/protocol';

interface AccusationModalProps {
  open: boolean;
  publicCase: PublicCaseMetadata;
  state: WorldState;
  isBusy: boolean;
  onClose: () => void;
  onSubmit: (suspectId: string, clueIds: string[], reasoning: string) => void;
}

export function AccusationModal({
  open,
  publicCase,
  state,
  isBusy,
  onClose,
  onSubmit,
}: AccusationModalProps) {
  const [suspectId, setSuspectId] = useState<string>(publicCase.npcs[0]?.npc_id ?? '');
  const [selectedClues, setSelectedClues] = useState<string[]>([]);
  const [reasoning, setReasoning] = useState<string>('');

  if (!open) return null;

  const toggleClue = (clueId: string) => {
    setSelectedClues((prev) =>
      prev.includes(clueId) ? prev.filter((id) => id !== clueId) : [...prev, clueId],
    );
  };

  const ownedClues = state.discovered_clues
    .map((id) => publicCase.clues_catalog[id])
    .filter(Boolean);

  const attemptsRemaining = Math.max(0, state.max_accusation_attempts - state.accusation_attempts);
  const canSubmit =
    !isBusy &&
    state.status === 'in_progress' &&
    Boolean(suspectId) &&
    selectedClues.length > 0 &&
    reasoning.trim().length >= 10;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    onSubmit(suspectId, selectedClues, reasoning.trim());
    onClose();
  };

  return (
    <div
      className="modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="accusation-modal-title"
      onClick={onClose}
    >
      <form className="modal-panel light" onSubmit={handleSubmit} onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <h2
              id="accusation-modal-title"
              className="modal-title"
              style={{ fontFamily: 'var(--font-serif)', fontSize: 21 }}
            >
              Submit Formal Accusation
            </h2>
            <div style={{ fontSize: 12.5, color: 'var(--ink-secondary)', marginTop: 2 }}>
              Attempts remaining: <strong>{attemptsRemaining}</strong> of {state.max_accusation_attempts}.
              You must name the killer and cite decisive owned evidence.
            </div>
          </div>
          <button type="button" className="btn" onClick={onClose} aria-label="Close accusation modal">
            <X size={14} />
          </button>
        </div>

        <div className="modal-body">
          <div>
            <div className="action-label" style={{ marginBottom: 6 }}>
              1. Accused Suspect
            </div>
            <div className="suspect-radio-grid">
              {publicCase.npcs.map((npc) => (
                <label
                  key={npc.npc_id}
                  className={`suspect-option ${suspectId === npc.npc_id ? 'selected' : ''}`}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 7, fontWeight: 600 }}>
                    <input
                      type="radio"
                      name="accused-suspect"
                      value={npc.npc_id}
                      checked={suspectId === npc.npc_id}
                      onChange={() => setSuspectId(npc.npc_id)}
                    />
                    {npc.name}
                  </div>
                  <span style={{ fontSize: 11.5, color: 'var(--ink-secondary)' }}>{npc.role}</span>
                </label>
              ))}
            </div>
          </div>

          <div>
            <div className="action-label" style={{ marginBottom: 6 }}>
              2. Supporting Evidence ({selectedClues.length} selected of {ownedClues.length} owned)
            </div>
            {ownedClues.length === 0 ? (
              <div style={{ fontSize: 13, color: 'var(--accent-crimson)' }}>
                You haven&apos;t discovered any clues yet. Inspect objects and confront suspects first.
              </div>
            ) : (
              <div className="clue-checkbox-list">
                {ownedClues.map((clue) => (
                  <label key={clue.clue_id} className="clue-checkbox-item">
                    <input
                      type="checkbox"
                      checked={selectedClues.includes(clue.clue_id)}
                      onChange={() => toggleClue(clue.clue_id)}
                      style={{ marginTop: 3 }}
                    />
                    <div>
                      <div style={{ fontWeight: 600 }}>
                        {clue.title}{' '}
                        <span className="clue-cat">{clue.category}</span>
                      </div>
                      <div style={{ fontSize: 12, color: 'var(--ink-secondary)', marginTop: 2 }}>
                        {clue.summary}
                      </div>
                    </div>
                  </label>
                ))}
              </div>
            )}
          </div>

          <div>
            <label htmlFor="accusation-reasoning" className="action-label" style={{ display: 'block', marginBottom: 6 }}>
              3. Detective&apos;s Reasoning (Motive, Means, Opportunity — min 10 chars)
            </label>
            <textarea
              id="accusation-reasoning"
              className="reasoning-textarea"
              placeholder="Explain how the suspect carried out the murder and how the cited clues prove it..."
              value={reasoning}
              onChange={(e) => setReasoning(e.target.value)}
            />
          </div>
        </div>

        <div className="modal-footer">
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-crimson" disabled={!canSubmit}>
            <Scale size={14} /> Present Accusation
          </button>
        </div>
      </form>
    </div>
  );
}
