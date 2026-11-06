import React, { useCallback, useEffect, useState } from 'react';
import { NodeBehaviorHook } from '../../../../../../frontend/urban-workflows/src/registry/types';

/**
 * UI Node: a node with its own React interface.
 *
 * A behavior hook is a React custom hook. It receives the node's runtime
 * `data` and the shared `nodeState`, and returns the pieces of the node it
 * wants to override, here just `contentComponent`, the JSX rendered inside
 * the node body. All the normal rules of hooks apply.
 */

// Read an output with `window.curio.fetchData`, the function Curio's canvas
// reads outputs with: while a dataflow is open, on that dataflow's route, which
// also reads the outputs the dataflow saved, after a new sign-in too. Look it
// up on every read: your bundle can load before Curio publishes it.
function hostFetchData(): ((fileName: string) => Promise<any>) | null {
  const read = typeof window !== 'undefined' ? (window as any).curio?.fetchData : undefined;
  return typeof read === 'function' ? read : null;
}

// For a host that does not publish `window.curio.fetchData`: read `/get` on
// the host's backend URL. Do NOT use `process.env.BACKEND_URL` here, which
// bakes your build machine's URL into the bundle you ship.
const BACKEND_URL: string =
  (typeof window !== 'undefined' && (window as any).curio?.backendUrl) || '';

/** The session token lives in a cookie; `/get` requires it. */
function sessionToken(): string {
  if (typeof document === 'undefined') return '';
  const hit = document.cookie.match(/(?:^|;\s*)session_token=([^;]*)/);
  return hit ? decodeURIComponent(hit[1]) : '';
}

// Keep rows as an output with `window.curio.storeOutput`, which answers the
// reference to hand on in their place, as every node hands on its output: a
// Python or JavaScript node reads only a stored output, and a save records
// only those. On a host that does not publish it, post them to `/storeOutput`.
async function store(nodeId: string, value: { data: any; dataType: string }): Promise<any> {
  const keep = typeof window !== 'undefined' ? (window as any).curio?.storeOutput : undefined;
  if (typeof keep === 'function') return keep(nodeId, value);
  const token = sessionToken();
  const res = await fetch(`${BACKEND_URL}/storeOutput`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ value }),
  });
  const answer = await res.json().catch(() => ({}));
  if (!res.ok || !answer?.output?.path) {
    throw new Error(answer?.error || `Could not keep the output (HTTP ${res.status})`);
  }
  return answer.output;
}

// Payload shapes Curio recognises directly. Anything else is a generic
// envelope wrapped around one of these, so peel until we reach a known type.
const KNOWN_TYPES = new Set(['dataframe', 'geodataframe', 'outputs']);

function unwrap(value: any): any {
  let current = value;
  while (
    current && typeof current === 'object' &&
    typeof current.dataType === 'string' &&
    !KNOWN_TYPES.has(current.dataType) &&
    'data' in current
  ) {
    current = current.data;
  }
  return current;
}

/**
 * Turn whatever landed on `data.input` into real data.
 *
 * Upstream hands you one of two shapes, and a custom-UI node has to cope with
 * both:
 *
 *   { path: 'art-12', dataType: 'dataframe' }  a sandbox artifact reference,
 *                                              which is what every node
 *                                              produces -> read it with
 *                                              `window.curio.fetchData`
 *   { data: {...},    dataType: 'dataframe' }  an inline payload -> use it
 *                                              as-is
 */
async function resolveInput(input: any): Promise<any> {
  if (input == null || input === '') return null;
  const ref = typeof input === 'string' ? input : input.path ?? input.dataset;
  if (typeof ref === 'string' && ref.trim()) {
    const fetchData = hostFetchData();
    if (fetchData) return unwrap(await fetchData(ref.trim()));
    const token = sessionToken();
    const res = await fetch(
      `${BACKEND_URL}/get?fileName=${encodeURIComponent(ref.trim())}`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    );
    if (!res.ok) throw new Error(`Could not read upstream data (HTTP ${res.status})`);
    return unwrap(await res.json());
  }
  return unwrap(input);
}

/** A `dataframe` payload is column-oriented. Curio serialises with
 *  `to_dict(orient='list')`, so each column is an ARRAY; a hand-written
 *  spec may instead use a row map keyed by index. Accept both - a node
 *  that requires the row map sees no data at all from Curio (#194). */
function columnNames(payload: any): string[] {
  const frame = payload?.dataType === 'dataframe' ? payload.data : payload;
  if (!frame || typeof frame !== 'object') return [];
  return Object.keys(frame);
}

export const useUiNodeBehavior: NodeBehaviorHook = (data, nodeState) => {
  const [payload, setPayload] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [column, setColumn] = useState<string>('');

  // Re-resolve whenever upstream produces something new.
  useEffect(() => {
    let cancelled = false;
    setError(null);
    resolveInput(data.input)
      .then((resolved) => {
        if (cancelled) return;
        setPayload(resolved);
        const cols = columnNames(resolved);
        setColumn((prev) => (prev && cols.includes(prev) ? prev : cols[0] ?? ''));
      })
      .catch((e) => {
        if (!cancelled) setError(e.message || String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [data.input]);

  const columns = columnNames(payload);

  // Push a result downstream: keep it, then hand on the reference. `dataType`
  // must match an output port type declared in manifest.json, lowercased.
  const emit = useCallback(async () => {
    const frame = payload?.dataType === 'dataframe' ? payload.data : payload;
    if (!frame || !column) return;
    try {
      const stored = await store(data.nodeId, {
        data: { [column]: frame[column] },
        dataType: 'dataframe',
      });
      data.outputCallback(data.nodeId, stored);
      nodeState.setOutput({ code: 'success', content: '' });
    } catch (e: any) {
      nodeState.setOutput({ code: 'error', content: e.message || String(e) });
    }
  }, [payload, column, data, nodeState]);

  const contentComponent = (
    <div
      style={{
        padding: 12,
        fontSize: 13,
        fontFamily: 'sans-serif',
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
      }}
    >
      <strong>UI Node</strong>
      {error ? (
        <span style={{ color: '#c0392b' }}>{error}</span>
      ) : columns.length === 0 ? (
        <span style={{ color: '#888' }}>Connect a DataFrame upstream and run it.</span>
      ) : (
        <>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ color: '#666', fontSize: 11 }}>Column</span>
            <select value={column} onChange={(e) => setColumn(e.target.value)}>
              {columns.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <button type="button" onClick={emit} disabled={!column}>
            Send this column downstream
          </button>
        </>
      )}
    </div>
  );

  return { contentComponent };
};
