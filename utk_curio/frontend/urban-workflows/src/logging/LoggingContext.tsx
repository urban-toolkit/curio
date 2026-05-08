import React, {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
} from 'react';

import { EventBuffer }      from './EventBuffer';
import { EventInterceptor }  from './EventInterceptor';
import { SnapshotManager, GraphState } from './SnapshotManager';
import { LogEvent, LoggingContextValue } from './types';

const API = 'http://localhost:5002';

const LoggingContext = createContext<LoggingContextValue>({
  sessionId: null,
  capture:   () => undefined,
  startNewSession: async () => {},
});

interface LoggingProviderProps {
  children:          React.ReactNode;
  workflowId?:       number | null;
  workflowName?:     string;
  userId?:           number;
  getGraphState?:    () => GraphState | null;
}

export function LoggingProvider({
  children,
  workflowId    = null,
  workflowName  = 'DefaultWorkflow',
  userId        = 1,
  getGraphState = () => null,
}: LoggingProviderProps): JSX.Element {

  const [sessionId, setSessionId] = useState<number | null>(null);

  const sessionIdRef = useRef<number | null>(null);

  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;

    const buffer  = EventBuffer.getInstance();
    const snapMgr = SnapshotManager.getInstance();

    buffer.setSessionIdGetter(() => sessionIdRef.current);
    snapMgr.setSessionIdGetter(() => sessionIdRef.current);
    snapMgr.setGraphStateGetter(getGraphState);

    const createSession = () =>
      fetch('http://localhost:5002/api/log/session/start', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ user_id: userId, workflow_id: workflowId, workflow_name: workflowName }),
      })
        .then(r => r.json())
        .then((data: { session_id: number }) => {
          const sid = data.session_id;
          setSessionId(sid);
          sessionIdRef.current = sid;
          buffer.setSessionIdGetter(() => sid);
          snapMgr.setSessionIdGetter(() => sid);
          EventInterceptor.getInstance().capture({
            event_type: 'SESSION_STARTED',
            node_id:    null,
            event_time: EventInterceptor.now(),
            event_data: { userAgent: navigator.userAgent, workflowId: workflowId },
          });
          buffer.flush();
        });

    createSession();

    const handleUnload = () => {
      const sid = sessionIdRef.current;
      if (sid === null) return;

      buffer.flushSync();

      SnapshotManager.getInstance().takeSnapshot(true);

      const endBody = JSON.stringify({
        session_id:  sid,
        session_end: EventInterceptor.now(),
      });

      if (navigator.sendBeacon) {
        const blob = new Blob([endBody], { type: 'application/json' });
        navigator.sendBeacon('http://localhost:5002/api/log/session/end', blob);
      } else {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', 'http://localhost:5002/api/log/session/end', false);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.send(endBody);
      }
    };

    window.addEventListener('beforeunload', handleUnload);

    return () => {
      window.removeEventListener('beforeunload', handleUnload);
    };

  }, []);

  useEffect(() => {
    sessionIdRef.current = sessionId;
    EventBuffer.getInstance().setSessionIdGetter(() => sessionId);
    SnapshotManager.getInstance().setSessionIdGetter(() => sessionId);
  }, [sessionId]);

  useEffect(() => {
    SnapshotManager.getInstance().setGraphStateGetter(getGraphState);
  }, [getGraphState]);

  const capture = (event: LogEvent) => {
    EventInterceptor.getInstance().capture(event);
  };

  const startNewSession = async (newName: string): Promise<void> => {
    const buffer  = EventBuffer.getInstance();
    const snapMgr = SnapshotManager.getInstance();

    // Snapshot + close current session
    snapMgr.takeSnapshot();
    const sid = sessionIdRef.current;
    if (sid !== null) {
      await fetch(`${API}/api/log/session/end`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ session_id: sid, session_end: EventInterceptor.now() }),
      }).catch(() => {});
    }

    // Reset snapshot event counter for the new session
    snapMgr.reset();

    // Start new session
    const res  = await fetch(`${API}/api/log/session/start`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ user_id: userId, workflow_id: workflowId, workflow_name: newName }),
    });
    const data = await res.json();
    const newSid: number = data.session_id;

    setSessionId(newSid);
    sessionIdRef.current = newSid;
    buffer.setSessionIdGetter(() => newSid);
    snapMgr.setSessionIdGetter(() => newSid);
    snapMgr.setGraphStateGetter(getGraphState);

    EventInterceptor.getInstance().capture({
      event_type: 'SESSION_STARTED',
      node_id:    null,
      event_time: EventInterceptor.now(),
      event_data: { userAgent: navigator.userAgent, workflowId: workflowId },
    });

    buffer.flush();
    setTimeout(() => snapMgr.takeSnapshot(), 300);
  };

  return (
    <LoggingContext.Provider value={{ sessionId, capture, startNewSession }}>
      {children}
    </LoggingContext.Provider>
  );
}

export function useLogging(): LoggingContextValue {
  return useContext(LoggingContext);
}