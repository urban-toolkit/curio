import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useEdges, Position } from 'reactflow';
import { NodeBehaviorHook, HandleDef } from '../../registry/types';
import { useFlowContext } from '../../providers/FlowProvider';
import { useToastContext } from '../../providers/ToastProvider';
import { fetchData } from '../../services/api';
import { backendUrl } from '../../utils/backendUrl';

/**
 * Spatial Join behavior — tag each point with the polygon it falls in.
 *
 * Backs the generic `spatial-join` node in curio.builtin@1. Two distinct
 * target handles:
 *
 *   - `in_points`   (top of left edge) — a Points FeatureCollection
 *   - `in_polygons` (bottom of left edge) — a Polygon FeatureCollection
 *
 * The polygon tag column is configurable (#262). It was hardcoded to
 * `properties.name`, with the manifest telling the user to rename their field
 * upstream with a Data Transformation node - a workaround presented as the
 * design, while the backend had accepted `name_property` all along. The node
 * now has a small body with the one control: which polygon property carries
 * the tag, persisted at `metadata.spatialJoin.nameProperty` so it survives a
 * save. The backend also says when no polygon carries the chosen property,
 * instead of silently tagging everything `polygon_<i>`.
 *
 * Mirrors Merge Flow's `dynamicHandles` + `setOutputCallbackOverride`
 * pattern so each handle's value lands in its own slot, then POSTs both
 * to the `/spatial_join` backend endpoint when both arrive.
 */

const DEFAULT_NAME_PROPERTY = 'name';
const API_BASE = `${backendUrl()}/spatial_join`;

// Heuristic for the single-handle fallback (when the framework hands us a
// scalar instead of a slot-indexed array): polygons have Polygon /
// MultiPolygon geometries; points have Point geometries.
function classifyFC(fc: any): 'points' | 'polygons' | 'unknown' {
  if (!fc || typeof fc !== 'object') return 'unknown';
  const features = Array.isArray(fc?.features) ? fc.features : null;
  if (!features || features.length === 0) return 'unknown';
  for (const f of features) {
    const t = f?.geometry?.type;
    if (t === 'Point') return 'points';
    if (t === 'Polygon' || t === 'MultiPolygon') return 'polygons';
  }
  return 'unknown';
}

// Curio's GEODATAFRAME wrapper is `{ data: <payload>, dataType: '...' }`.
// Unwrap before shipping to the join endpoint.
function unwrap(value: any): any {
  if (value && typeof value === 'object' && value.dataType && value.data !== undefined) {
    return value.data;
  }
  return value;
}

// What an upstream Python node hands us is an artifact reference,
// `{ path, dataType }` (normalizeFlowInput), never the rows. `classifyFC` can
// make nothing of that, so a join fed by any sandbox node never fired: only an
// inline FeatureCollection (HF CV Inference's, a JS node's) ever reached a
// slot, and example 10's polygons, which come out of a Data Transformation
// node, never did. Resolve the reference through /get first; the envelope that
// comes back is `{ dataType, data, schema }` and `data` is the FeatureCollection.
async function resolveInput(value: any): Promise<any> {
  if (value && typeof value === 'object' && typeof value.path === 'string' && value.data === undefined) {
    const envelope = await fetchData(value.path);
    return envelope?.data ?? envelope;
  }
  return unwrap(value);
}

/** Distinct property names across the first *limit* polygon features, for the datalist. */
export function polygonPropertyNames(fc: any, limit = 20): string[] {
  const features = Array.isArray(fc?.features) ? fc.features.slice(0, limit) : [];
  const names = new Set<string>();
  for (const f of features) {
    const props = f?.properties;
    if (props && typeof props === 'object') {
      for (const k of Object.keys(props)) names.add(k);
    }
  }
  return Array.from(names).sort();
}

/** The persisted choice, or the default the backend also assumes. */
export function resolveNameProperty(data: any): string {
  const raw = data?.spatialJoin?.nameProperty;
  const trimmed = typeof raw === 'string' ? raw.trim() : '';
  return trimmed || DEFAULT_NAME_PROPERTY;
}

export const useSpatialJoinBehavior: NodeBehaviorHook = (data, nodeState) => {
  const [slots, setSlots] = useState<[any | undefined, any | undefined]>([undefined, undefined]);
  const edges = useEdges();
  const { updateDataNode } = useFlowContext();
  const { showToast } = useToastContext();

  const nameProperty = resolveNameProperty(data);
  // What the last join reported: how many points found a polygon, and the
  // backend's warnings (e.g. no polygon carries the chosen property).
  const [lastResult, setLastResult] = useState<{ tagged: number; total: number; warnings: string[] } | null>(null);
  // Draft of the property box; committed on blur / Enter.
  const [draft, setDraft] = useState<string>(nameProperty);
  useEffect(() => { setDraft(nameProperty); }, [nameProperty]);

  const commitNameProperty = useCallback((value: string) => {
    const next = value.trim() || DEFAULT_NAME_PROPERTY;
    setDraft(next);
    if (next === nameProperty) return;
    // Persisted on the node so TrillGenerator writes it (metadata.spatialJoin).
    updateDataNode(data.nodeId, { ...data, spatialJoin: { ...(data as any).spatialJoin, nameProperty: next } });
  }, [data, nameProperty, updateDataNode]);

  const pointsConnected = useMemo(
    () => edges.some(e => e.target === data.nodeId && e.targetHandle === 'in_points'),
    [edges, data.nodeId],
  );
  const polygonsConnected = useMemo(
    () => edges.some(e => e.target === data.nodeId && e.targetHandle === 'in_polygons'),
    [edges, data.nodeId],
  );

  // Two paths for inbound input:
  //   - framework hands us an array indexed by handle (when dynamicHandles
  //     are declared), OR
  //   - framework hands us a single scalar; classify by geometry type.
  // The two inputs arrive as successive `data.input` values, one per upstream
  // run, and each has to land in its own slot. So a later arrival must NOT
  // cancel an earlier one that is still resolving: with the polygons loader
  // first and the points loader right behind it (example 15's order, and the
  // generic canvas test's), the points reference arrived while the polygon
  // artifact was still downloading, a cleanup-style cancel dropped it, and the
  // join waited forever for polygons it had already been handed. Instead, each
  // resolution carries a sequence number and only a newer resolution of the
  // SAME slot may overwrite an older one; unmount is the only thing that stops
  // a result from landing.
  const aliveRef = useRef(true);
  useEffect(() => () => { aliveRef.current = false; }, []);
  const resolveSeqRef = useRef(0);
  const appliedSeqRef = useRef<[number, number]>([0, 0]);
  const placeResolved = useCallback((v: any, seq: number) => {
    if (!aliveRef.current) return;
    const kind = classifyFC(v);
    const idx: 0 | 1 | null = kind === 'points' ? 0 : kind === 'polygons' ? 1 : null;
    if (idx === null || seq < appliedSeqRef.current[idx]) return;
    appliedSeqRef.current[idx] = seq;
    setSlots(prev => {
      const next: [any | undefined, any | undefined] = [prev[0], prev[1]];
      next[idx] = v;
      return next;
    });
  }, []);

  useEffect(() => {
    if (data.input === undefined || data.input === '' || data.input === null) return;
    const seq = ++resolveSeqRef.current;
    const onError = (e: any) => {
      if (aliveRef.current) nodeState.setOutput({ code: 'error', content: e?.message || String(e) });
    };
    if (Array.isArray(data.input)) {
      Promise.all(data.input.slice(0, 2).map(resolveInput))
        .then(values => { values.forEach(v => placeResolved(v, seq)); })
        .catch(onError);
    } else {
      resolveInput(data.input).then(v => placeResolved(v, seq)).catch(onError);
    }
    // nodeState is stable for the node's lifetime; only a new input re-resolves.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.input, placeResolved]);

  // Slot-indexed override (Merge-Flow pattern) — the framework calls this
  // with (value, slotIdx) when each handle's upstream output arrives.
  const setOutputCallbackOverride = useCallback((val: any, idx = 0) => {
    setSlots(prev => {
      const next: [any | undefined, any | undefined] = [prev[0], prev[1]];
      if (idx === 0 || idx === 1) next[idx] = val;
      return next;
    });
  }, []);

  // Fire the join whenever both slots are populated.
  useEffect(() => {
    const rawPoints = unwrap(slots[0]);
    const rawPolygons = unwrap(slots[1]);
    if (!rawPoints || !rawPolygons) return;
    const controller = new AbortController();
    setLastResult(null);
    fetch(API_BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ points: rawPoints, polygons: rawPolygons, name_property: nameProperty }),
      signal: controller.signal,
    })
      .then(async r => {
        if (!r.ok) {
          const b = await r.json().catch(() => ({}));
          throw new Error(b.hint || b.error || `HTTP ${r.status}`);
        }
        return r.json();
      })
      .then(fc => {
        const features: any[] = Array.isArray(fc?.features) ? fc.features : [];
        const tagged = features.filter(f => f?.properties?.joined != null).length;
        const warnings: string[] = Array.isArray(fc?.metadata?.warnings) ? fc.metadata.warnings : [];
        setLastResult({ tagged, total: features.length, warnings });
        data.outputCallback(data.nodeId, { data: fc, dataType: 'geodataframe' });
        // A warning is still a completed join - downstream gets data - but the
        // node says so where the user is looking, and once as a toast.
        nodeState.setOutput({ code: 'success', content: warnings.join('\n') });
        for (const w of warnings) showToast(w, 'warning');
      })
      .catch(e => {
        if (e.name === 'AbortError') return;
        nodeState.setOutput({ code: 'error', content: e.message || String(e) });
      });
    return () => controller.abort();
    // `data` is deliberately not a dep: it changes identity on every node
    // update (including our own updateDataNode), which would re-fire the join
    // with the same inputs. The property is a dep in its own right.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slots, nameProperty]);

  const polygonProps = useMemo(() => polygonPropertyNames(unwrap(slots[1])), [slots]);
  const datalistId = `spatial-join-props-${data.nodeId}`;

  const contentComponent = React.useMemo<React.ReactNode>(() => {
    const status = lastResult
      ? `Tagged ${lastResult.tagged} of ${lastResult.total} points with \`${nameProperty}\`, in a new \`joined\` column.`
      : !slots[0] && !slots[1]
        ? 'Connect points (top) and polygons (bottom), then run the nodes feeding this one.'
        : !slots[0]
          ? 'Waiting for the points input (top handle).'
          : !slots[1]
            ? 'Waiting for the polygons input (bottom handle).'
            : 'Joining\u2026';
    return (
      <div
        className="nodrag nopan nowheel"
        data-curio-spatial-join-body="true"
        style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '8px 10px', fontSize: 12, lineHeight: 1.4 }}
      >
        <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span>Tag each point with this polygon property</span>
          <input
            type="text"
            list={datalistId}
            value={draft}
            placeholder={DEFAULT_NAME_PROPERTY}
            aria-label="Tag each point with this polygon property"
            onChange={e => setDraft(e.target.value)}
            onBlur={e => commitNameProperty(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') { e.preventDefault(); commitNameProperty((e.target as HTMLInputElement).value); }
            }}
            style={{ padding: '3px 6px', fontSize: 12 }}
          />
          <datalist id={datalistId}>
            {polygonProps.map(p => <option key={p} value={p} />)}
          </datalist>
          <span style={{ opacity: 0.7, fontSize: 11 }}>
            Every point gets a <code>joined</code> column holding this property of the
            polygon it falls in. <code>{DEFAULT_NAME_PROPERTY}</code> by default; pick from the
            polygons' own properties once they arrive.
          </span>
        </label>
        <span data-curio-spatial-join-status="true" style={{ opacity: 0.85 }}>{status}</span>
        {lastResult?.warnings.map((w, i) => (
          <span
            key={i}
            role="alert"
            data-curio-spatial-join-warning="true"
            style={{
              padding: '4px 8px',
              borderRadius: 4,
              background: 'var(--curio-warning-bg, #fff4d6)',
              color: 'var(--curio-warning-text, #7a5a00)',
            }}
          >
            {w}
          </span>
        ))}
      </div>
    );
  }, [draft, datalistId, polygonProps, lastResult, nameProperty, slots, commitNameProperty]);

  // Two distinct input handles on the left edge: points (top), polygons (bottom).
  // Plus the single output handle on the right. We use `handlesOverride`
  // (not `dynamicHandles`) so the default `standardInOut()` "in" handle from
  // packagesClient is fully replaced — otherwise it leaks through at top:50%
  // as an unwanted gray circle.
  //
  // Input-handle indices here match the slot index the framework passes back
  // to `setOutputCallbackOverride`.
  const handlesOverride: HandleDef[] = [
    {
      id: 'in_points',
      type: 'target',
      position: Position.Left,
      style: {
        top: '33%', width: '12px', height: '12px', borderRadius: '50%',
        boxSizing: 'border-box',
        backgroundColor: pointsConnected ? '#3b82f6' : '#ffffff',
        border: pointsConnected ? '2px solid #3b82f6' : '2px solid #b8b8b8',
        zIndex: 10, pointerEvents: 'auto',
      },
    },
    {
      id: 'in_polygons',
      type: 'target',
      position: Position.Left,
      style: {
        top: '66%', width: '12px', height: '12px', borderRadius: '50%',
        boxSizing: 'border-box',
        backgroundColor: polygonsConnected ? '#22c55e' : '#ffffff',
        border: polygonsConnected ? '2px solid #22c55e' : '2px solid #b8b8b8',
        zIndex: 10, pointerEvents: 'auto',
      },
    },
    {
      id: 'out',
      type: 'source',
      position: Position.Right,
    },
  ];

  return { handlesOverride, setOutputCallbackOverride, contentComponent };
};
