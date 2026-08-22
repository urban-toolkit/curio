import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { NodeBehaviorHook } from '../../../utk_curio/frontend/urban-workflows/src/registry/types';

/**
 * Column Filter — a worked example of a node with its own React interface.
 *
 * This is the reference custom-UI node: small enough to read in one sitting,
 * with no API keys, no Python dependencies, and no backend endpoint of its
 * own. Fork it (or copy it into a package of your own) as the starting point
 * for a node that needs real controls rather than a code editor.
 *
 * What it demonstrates, in the order you meet each problem:
 *
 *   1. A behavior hook is a React custom hook. It receives the node's runtime
 *      `data` plus the shared `nodeState`, and returns only the parts of the
 *      node it wants to override — here `contentComponent`, the JSX rendered
 *      in the node body.
 *   2. Reading upstream data (`resolveInput` below). This is the part that
 *      surprises everyone: `data.input` is usually a *reference* to a sandbox
 *      artifact, not the data itself.
 *   3. Local UI state that does not touch the dataflow until the user asks
 *      for it (`useState` for the column / operator / threshold).
 *   4. Pushing a result downstream (`data.outputCallback`) and reporting
 *      success or failure through `nodeState.setOutput`.
 *
 * See docs/AUTHORING-NODES.md for the surrounding workflow (scaffold, build,
 * install, reload).
 */

/*
 * Read the host's backend URL at runtime.
 *
 * Do NOT use `process.env.BACKEND_URL` in a package bundle: webpack would
 * inline whatever URL your machine had at build time, and the bundle would
 * then point at your laptop for everyone who installs it. Curio's main bundle
 * publishes the live value on `window.curio.backendUrl` for exactly this.
 */
const BACKEND_URL: string =
  (typeof window !== 'undefined' && (window as any).curio?.backendUrl) || '';

/** The session token lives in a cookie; the artifact endpoint requires it. */
function sessionToken(): string {
  if (typeof document === 'undefined') return '';
  const hit = document.cookie.match(/(?:^|;\s*)session_token=([^;]*)/);
  return hit ? decodeURIComponent(hit[1]) : '';
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
 *                                              which is what every Python or
 *                                              JS node produces -> fetch it
 *   { data: {...},    dataType: 'dataframe' }  an inline payload, which is what
 *                                              another custom-UI node produces
 *                                              -> use it as-is
 *
 * A node that only handles the second shape appears to work when wired to
 * another custom-UI node and then silently does nothing behind a Data Loading
 * node. Handle both.
 */
async function resolveInput(input: any): Promise<any> {
  if (input == null || input === '') return null;
  const ref = typeof input === 'string' ? input : input.path ?? input.dataset;
  if (typeof ref === 'string' && ref.trim()) {
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

/*
 * A `dataframe` payload is column-oriented, the shape pandas'
 * `DataFrame.to_dict()` produces:
 *
 *   { "population": { "0": 2746, "1": 8804 }, "name": { "0": "Chicago", ... } }
 *
 * Row keys are strings and every column carries the same set of them.
 */
type Frame = Record<string, Record<string, unknown>>;

function asFrame(payload: any): Frame | null {
  const frame = payload?.dataType === 'dataframe' ? payload.data : payload;
  if (!frame || typeof frame !== 'object' || Array.isArray(frame)) return null;
  const columns = Object.keys(frame);
  if (columns.length === 0) return null;
  // Every value must itself be a row map, otherwise this is some other shape.
  const looksRight = columns.every(
    (c) => frame[c] && typeof frame[c] === 'object' && !Array.isArray(frame[c]),
  );
  return looksRight ? (frame as Frame) : null;
}

function rowKeys(frame: Frame): string[] {
  const first = Object.keys(frame)[0];
  return first ? Object.keys(frame[first]) : [];
}

/** Columns whose values are numbers — the only ones worth thresholding. */
function numericColumns(frame: Frame): string[] {
  return Object.keys(frame).filter((column) => {
    const values = Object.values(frame[column]);
    const seen = values.filter((v) => v != null);
    return seen.length > 0 && seen.every((v) => typeof v === 'number');
  });
}

type Operator = '>' | '>=' | '<' | '<=';

const COMPARE: Record<Operator, (value: number, threshold: number) => boolean> = {
  '>': (v, t) => v > t,
  '>=': (v, t) => v >= t,
  '<': (v, t) => v < t,
  '<=': (v, t) => v <= t,
};

const S: Record<string, React.CSSProperties> = {
  root: {
    padding: '12px 14px',
    fontFamily: '"Roboto","Helvetica","Arial",sans-serif',
    fontSize: 13,
    color: '#333',
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  title: { fontSize: 14, fontWeight: 600, color: '#1a1a2e' },
  hint: { color: '#888', fontSize: 12, lineHeight: 1.4 },
  error: { color: '#c0392b', fontSize: 12, lineHeight: 1.4 },
  field: { display: 'flex', flexDirection: 'column', gap: 3 },
  fieldLabel: {
    fontSize: 10,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    color: '#94a3b8',
  },
  control: {
    padding: '5px 7px',
    border: '1px solid #cbd5e1',
    borderRadius: 6,
    fontSize: 12,
    background: '#fff',
  },
  row: { display: 'flex', gap: 8 },
  summary: {
    background: '#f8fafc',
    border: '1px solid #e2e8f0',
    borderRadius: 8,
    padding: '8px 10px',
    fontSize: 12,
    color: '#475569',
  },
  button: {
    padding: '8px 12px',
    border: '1px solid #bbf7d0',
    borderRadius: 8,
    background: '#f0fdf4',
    color: '#166534',
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
  },
  buttonDisabled: {
    padding: '8px 12px',
    border: '1px solid #e5e7eb',
    borderRadius: 8,
    background: '#f3f4f6',
    color: '#9ca3af',
    fontSize: 12,
    fontWeight: 600,
    cursor: 'not-allowed',
  },
};

export const useColumnFilterBehavior: NodeBehaviorHook = (data, nodeState) => {
  const [frame, setFrame] = useState<Frame | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [column, setColumn] = useState<string>('');
  const [operator, setOperator] = useState<Operator>('>');
  const [threshold, setThreshold] = useState<string>('0');

  // Re-resolve whenever upstream produces something new. The `cancelled` flag
  // is the standard guard against a slow fetch resolving after the node has
  // moved on to a newer input.
  useEffect(() => {
    let cancelled = false;
    setError(null);
    resolveInput(data.input)
      .then((resolved) => {
        if (cancelled) return;
        const next = asFrame(resolved);
        setFrame(next);
        if (next) {
          const numeric = numericColumns(next);
          setColumn((prev) => (prev && numeric.includes(prev) ? prev : numeric[0] ?? ''));
        }
      })
      .catch((e) => {
        if (!cancelled) setError(e.message || String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [data.input]);

  const numeric = useMemo(() => (frame ? numericColumns(frame) : []), [frame]);

  // Which rows pass the current filter. Recomputed as the user types, but
  // nothing leaves the node until they press the button.
  const matching = useMemo(() => {
    if (!frame || !column) return null;
    const limit = Number(threshold);
    if (!Number.isFinite(limit)) return null;
    const compare = COMPARE[operator];
    return rowKeys(frame).filter((key) => {
      const value = frame[column][key];
      return typeof value === 'number' && compare(value, limit);
    });
  }, [frame, column, operator, threshold]);

  const totalRows = frame ? rowKeys(frame).length : 0;

  const emit = useCallback(() => {
    if (!frame || !matching) return;
    try {
      // Rebuild the column-oriented frame with only the matching row keys, so
      // downstream nodes receive the same shape they would from pandas.
      const filtered: Frame = {};
      for (const name of Object.keys(frame)) {
        const source = frame[name];
        const kept: Record<string, unknown> = {};
        for (const key of matching) kept[key] = source[key];
        filtered[name] = kept;
      }
      data.outputCallback(data.nodeId, { data: filtered, dataType: 'dataframe' });
      nodeState.setOutput({
        code: 'success',
        content: `${matching.length} of ${totalRows} rows sent downstream.`,
      });
    } catch (e: any) {
      nodeState.setOutput({ code: 'error', content: e.message || String(e) });
    }
  }, [frame, matching, totalRows, data, nodeState]);

  let body: React.ReactNode;
  if (error) {
    body = <span style={S.error}>{error}</span>;
  } else if (!frame) {
    body = (
      <span style={S.hint}>
        Connect a DataFrame upstream and run that node. Any Data Loading or Data
        Transformation node works.
      </span>
    );
  } else if (numeric.length === 0) {
    body = (
      <span style={S.hint}>
        This DataFrame has no numeric columns to filter on.
      </span>
    );
  } else {
    body = (
      <>
        <div style={S.field}>
          <span style={S.fieldLabel}>Column</span>
          <select
            style={S.control}
            value={column}
            onChange={(e) => setColumn(e.target.value)}
          >
            {numeric.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>

        <div style={S.row}>
          <div style={{ ...S.field, flex: '0 0 84px' }}>
            <span style={S.fieldLabel}>Keep</span>
            <select
              style={S.control}
              value={operator}
              onChange={(e) => setOperator(e.target.value as Operator)}
            >
              <option value=">">&gt;</option>
              <option value=">=">&ge;</option>
              <option value="<">&lt;</option>
              <option value="<=">&le;</option>
            </select>
          </div>
          <div style={{ ...S.field, flex: 1 }}>
            <span style={S.fieldLabel}>Threshold</span>
            <input
              style={S.control}
              type="number"
              value={threshold}
              onChange={(e) => setThreshold(e.target.value)}
            />
          </div>
        </div>

        <div style={S.summary}>
          {matching == null
            ? 'Enter a number to filter on.'
            : `${matching.length} of ${totalRows} rows match.`}
        </div>

        <button
          type="button"
          style={matching && matching.length > 0 ? S.button : S.buttonDisabled}
          disabled={!matching || matching.length === 0}
          onClick={emit}
        >
          Send matching rows downstream
        </button>
      </>
    );
  }

  const contentComponent = (
    <div style={S.root} className="nowheel">
      <div style={S.title}>Column Filter</div>
      {body}
    </div>
  );

  return { contentComponent };
};
