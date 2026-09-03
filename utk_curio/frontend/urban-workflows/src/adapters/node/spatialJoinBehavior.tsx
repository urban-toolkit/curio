import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { useEdges, Position } from 'reactflow';
import { NodeBehaviorHook, HandleDef } from '../../registry/types';
import { useFlowContext } from '../../providers/FlowProvider';
import { useToastContext } from '../../providers/ToastProvider';
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
  useEffect(() => {
    if (Array.isArray(data.input)) {
      setSlots(prev => {
        const next: [any | undefined, any | undefined] = [prev[0], prev[1]];
        for (let i = 0; i < Math.min(data.input.length, 2); i++) {
          next[i] = data.input[i];
        }
        return next;
      });
    } else if (data.input !== undefined && data.input !== '' && data.input !== null) {
      const v = unwrap(data.input);
      const kind = classifyFC(v);
      if (kind === 'points') setSlots(prev => [v, prev[1]]);
      else if (kind === 'polygons') setSlots(prev => [prev[0], v]);
    }
  }, [data.input]);

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
        const tagged = features.filter(f => f?.properties?.neighborhood_name != null).length;
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
      ? `Tagged ${lastResult.tagged} of ${lastResult.total} points with \`${nameProperty}\`.`
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
          <span>Polygon property used as the tag</span>
          <input
            type="text"
            list={datalistId}
            value={draft}
            placeholder={DEFAULT_NAME_PROPERTY}
            aria-label="Polygon property used as the tag"
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
