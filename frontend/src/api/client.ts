import type {
  CreateSessionResponse,
  HealthResponse,
  NpcContextSnapshot,
  TraceEvent,
} from '../types/protocol';

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '';

export async function fetchHealth(): Promise<HealthResponse> {
  const resp = await fetch(`${API_BASE}/api/health`);
  if (!resp.ok) {
    throw new Error(`Health check failed (${resp.status})`);
  }
  return (await resp.json()) as HealthResponse;
}

export async function createSession(): Promise<CreateSessionResponse> {
  const resp = await fetch(`${API_BASE}/api/sessions`, { method: 'POST' });
  if (!resp.ok) {
    throw new Error(`Failed to create session (${resp.status})`);
  }
  return (await resp.json()) as CreateSessionResponse;
}

export async function fetchNpcContext(
  sessionId: string,
  npcId: string,
  preview = true,
): Promise<NpcContextSnapshot> {
  const resp = await fetch(
    `${API_BASE}/api/sessions/${sessionId}/npc-context/${npcId}?preview=${preview ? 'true' : 'false'}`,
  );
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(`Failed to fetch NPC context (${resp.status}): ${detail}`);
  }
  return (await resp.json()) as NpcContextSnapshot;
}

export interface StreamTurnCallbacks {
  onTrace: (event: TraceEvent) => void;
  onError: (message: string) => void;
  onDone: () => void;
}

/**
 * Stream SSE TraceEvents from POST /api/sessions/{sessionId}/turn.
 */
export async function streamTurn(
  sessionId: string,
  message: string,
  callbacks: StreamTurnCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/sessions/${sessionId}/turn`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({ message }),
    signal,
  });

  if (!resp.ok || !resp.body) {
    const errText = await resp.text().catch(() => '');
    callbacks.onError(`Turn request failed (${resp.status}): ${errText || resp.statusText}`);
    callbacks.onDone();
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  const dispatchFrame = (rawFrame: string) => {
    const lines = rawFrame.split(/\r?\n/);
    let eventName = 'message';
    const dataParts: string[] = [];

    for (const line of lines) {
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith('data:')) {
        dataParts.push(line.slice(5).trim());
      }
    }

    if (dataParts.length === 0) return;
    const rawData = dataParts.join('\n');

    try {
      const parsed = JSON.parse(rawData);
      if (eventName === 'error') {
        callbacks.onError(parsed.message ?? 'Unknown streaming error');
      } else if (eventName === 'trace') {
        callbacks.onTrace(parsed as TraceEvent);
      }
    } catch {
      callbacks.onError(`Malformed SSE payload: ${rawData}`);
    }
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const frames = buffer.split(/\r?\n\r?\n/);
      buffer = frames.pop() ?? '';
      for (const frame of frames) {
        if (frame.trim()) {
          dispatchFrame(frame);
        }
      }
    }
    if (buffer.trim()) {
      dispatchFrame(buffer);
    }
  } finally {
    callbacks.onDone();
  }
}
