import { useState, useEffect, useMemo, useCallback } from 'react';
import { useEdges, Position } from 'reactflow';
import { NodeLifecycleHook, HandleDef } from '../../registry/types';

/**
 * Spatial Join lifecycle — tag each point with the polygon it falls in.
 *
 * Backs the generic `spatial-join` node in curio.builtin@1. The node ships
 * with `containerStyle.noContent: true` (matching Merge Flow), so it renders
 * as a 50×180 icon-only block with two distinct target handles:
 *
 *   - `in_points`   (top of left edge) — a Points FeatureCollection
 *   - `in_polygons` (bottom of left edge) — a Polygon FeatureCollection
 *
 * The polygon tag column is hardcoded to `properties.name`. Polygon
 * datasets using a different field (Chicago's `pri_neigh`, NYC's
 * `BoroName`, etc.) should be renamed via a Data Transformation node
 * upstream before feeding in. Trades configurability for a small,
 * Curio-idiomatic node footprint.
 *
 * Mirrors Merge Flow's `dynamicHandles` + `setOutputCallbackOverride`
 * pattern so each handle's value lands in its own slot, then POSTs both
 * to the `/spatial_join` backend endpoint when both arrive.
 */

const NAME_PROPERTY = 'name';
const API_BASE = `${process.env.BACKEND_URL || ''}/spatial_join`;

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

export const useSpatialJoinLifecycle: NodeLifecycleHook = (data, nodeState) => {
  const [slots, setSlots] = useState<[any | undefined, any | undefined]>([undefined, undefined]);
  const edges = useEdges();

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
    fetch(API_BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ points: rawPoints, polygons: rawPolygons, name_property: NAME_PROPERTY }),
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
        data.outputCallback(data.nodeId, { data: fc, dataType: 'geodataframe' });
        nodeState.setOutput({ code: 'success', content: '' });
      })
      .catch(e => {
        if (e.name === 'AbortError') return;
        nodeState.setOutput({ code: 'error', content: e.message || String(e) });
      });
    return () => controller.abort();
  }, [slots, data, nodeState]);

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

  // No contentComponent — manifest sets `containerStyle.noContent: true`
  // so the node renders as a small icon-only block (matches Merge Flow).
  return { handlesOverride, setOutputCallbackOverride };
};
