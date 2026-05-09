import React, {
  useCallback,
  useEffect,
  useRef,
  useState,
} from 'react';
import { ReactFlowProvider } from 'reactflow';

import { ReplayEngine } from '../../replay/ReplayEngine';
import { ReplayEngineState, SessionSummary, EMPTY_STATE } from '../../replay/ReplayTypes';
import { ReplayCanvas, ReplayCallbacks } from './ReplayCanvas';
import { ReplayControls } from './ReplayControls';

const API_BASE = 'http://localhost:5002';

const AMBER = '#f59e0b';
const BG_MID = '#1E1F23';
const BG_DRK = '#111113';
const BORDER = '#374151';

interface ReplayPageProps {
  onRestore?: (nodes: any[], edges: any[]) => void;
  onClose?: () => void;
  replayCallbacks?: ReplayCallbacks;
}

export const ReplayPage: React.FC<ReplayPageProps> = ({
  onRestore,
  onClose,
  replayCallbacks,
}) => {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionsErr, setSessionsErr] = useState<string | null>(null);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [engineState, setEngineState] = useState<ReplayEngineState>(EMPTY_STATE);

  const engineRef = useRef<ReplayEngine | null>(null);

  if (!engineRef.current) {
    engineRef.current = new ReplayEngine(newState => setEngineState(newState));
  }

  const engine = engineRef.current;

  const NO_OP = useCallback(() => {}, []);

  const NO_OP_PY = useRef({
    run: async () => {},
    stop: () => {},
    reset: () => {},
    isRunning: false,
  }).current;

  const effectiveCbacks: ReplayCallbacks = replayCallbacks ?? {
    outputCallback: NO_OP,
    interactionsCallback: NO_OP,
    propagationCallback: NO_OP,
    pythonInterpreter: NO_OP_PY,
  };

  const fetchSessions = useCallback(() => {
    setSessionsLoading(true);
    setSessionsErr(null);
    fetch(`${API_BASE}/api/log/sessions?limit=100`)
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(data => {
        const list: SessionSummary[] = data.sessions ?? [];
        setSessions(list);
        if (list.length > 0 && selectedId === null) {
          setSelectedId(list[0].session_id);
        }
      })
      .catch(err => setSessionsErr('Could not load sessions: ' + err.message))
      .finally(() => setSessionsLoading(false));
  }, [selectedId]);

  useEffect(() => {
    fetchSessions();
  }, []);

  const handleLoad = useCallback(() => {
    if (selectedId === null) return;
    engine.loadSession(selectedId);
  }, [engine, selectedId]);

  function sessionLabel(s: SessionSummary): string {
    const date = s.session_start.slice(0, 16);
    const evts = s.event_count;
    const state = s.session_end === null
      ? ' [open]'
      : s.session_end === 'AUTO_CLOSED'
        ? ' [auto-closed]'
        : '';

    return `#${s.session_id} | ${date} | ${evts}ev${state}`;
  }

  const grouped = sessions.reduce<Record<string, SessionSummary[]>>((acc, s) => {
    const key = (s as any).workflow_name ?? 'Unnamed';
    if (!acc[key]) acc[key] = [];
    acc[key].push(s);
    return acc;
  }, {});

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        fontFamily: 'Arial, sans-serif',
        background: 'transparent',
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
        <ReactFlowProvider>
          <ReplayCanvas
            engineState={engineState}
            replayCallbacks={effectiveCbacks}
            onClose={onClose}
          />
        </ReactFlowProvider>
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          padding: '9px 14px',
          background: BG_MID,
          color: '#fff',
          flexShrink: 0,
          flexWrap: 'nowrap',
          borderTop: '1px solid #2a2b30',
          boxShadow: '0 -2px 10px rgba(0,0,0,0.42)',
          minHeight: '56px',
        }}
      >
        {sessionsErr ? (
          <span style={{ color: '#fca5a5', fontSize: '11px', flexShrink: 0 }}>
            {sessionsErr}
          </span>
        ) : (
          <select
            value={selectedId ?? ''}
            onChange={e => setSelectedId(e.target.value ? parseInt(e.target.value, 10) : null)}
            disabled={sessionsLoading}
            style={{
              padding: '7px 10px',
              borderRadius: '8px',
              border: `1px solid ${BORDER}`,
              fontSize: '12px',
              minWidth: '250px',
              maxWidth: '340px',
              background: BG_DRK,
              color: '#e5e7eb',
              fontFamily: 'monospace',
              flexShrink: 1,
              opacity: sessionsLoading ? 0.6 : 1,
            }}
          >
            <option value="">— select a session —</option>
            {Object.entries(grouped).map(([name, group]) => (
              <optgroup key={name} label={name}>
                {group.map(s => (
                  <option key={s.session_id} value={s.session_id}>
                    {sessionLabel(s)}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        )}
        <button
          onClick={fetchSessions}
          disabled={sessionsLoading}
          title="Refresh session list"
          style={{
            padding: '8px 12px',
            background: 'transparent',
            color: sessionsLoading ? '#6b7280' : '#9ca3af',
            border: `1px solid ${BORDER}`,
            borderRadius: '8px',
            cursor: sessionsLoading ? 'not-allowed' : 'pointer',
            fontSize: '14px',
            flexShrink: 0,
          }}
        >
          {sessionsLoading ? '…' : '↻'}
        </button>

        <button
          onClick={handleLoad}
          disabled={selectedId === null || engineState.loading}
          style={{
            padding: '8px 18px',
            background: AMBER,
            color: '#111',
            border: 'none',
            borderRadius: '8px',
            cursor: selectedId === null ? 'not-allowed' : 'pointer',
            opacity: selectedId === null ? 0.5 : 1,
            fontWeight: 800,
            fontSize: '13px',
            whiteSpace: 'nowrap',
            flexShrink: 0,
          }}
        >
          {engineState.loading ? 'Loading…' : 'Load'}
        </button>

        <span style={{ width: '1px', height: '28px', background: BORDER, flexShrink: 0 }} />

        <div style={{ flex: 1, minWidth: 0 }}>
          <ReplayControls
            engine={engine}
            engineState={engineState}
            onRestore={onRestore}
            horizontal
          />
        </div>
      </div>
    </div>
  );
};

export default ReplayPage;