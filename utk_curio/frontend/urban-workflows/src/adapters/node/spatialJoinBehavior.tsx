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
 * now has a small body with the one control: a list of the polygons' columns
 * to pick the tag from, persisted at `metadata.spatialJoin.nameProperty` so it
 * survives a save. The backend also says when no polygon carries the chosen
 * column, instead of silently tagging everything `polygon_<i>`.
 *
 * Each input lands in its own slot, by its geometry, and the node POSTs both
 * to the `/spatial_join` backend endpoint when both arrive.
 */

const DEFAULT_NAME_PROPERTY = 'name';
const API_BASE = `${backendUrl()}/spatial_join`;

// Which slot an input fills, by its geometry rather than the port it came in
// on: polygons have Polygon / MultiPolygon geometries; points have Point
// geometries.
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

/**
 * Distinct property names across every polygon feature, for the column list.
 * All of them, not a sample: the list is the only way to pick a column, so one
 * that only later features carry would be out of reach.
 */
export function polygonPropertyNames(fc: any): string[] {
  const features = Array.isArray(fc?.features) ? fc.features : [];
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

export type SpatialJoinOutput = 'points' | 'polygons';

/** The two input handles' colours, repeated as swatches wherever the text names them. */
export const POINTS_HANDLE_COLOR = '#3b82f6';
export const POLYGONS_HANDLE_COLOR = '#22c55e';

/** A small hollow ring in a handle's colour, inline with the text that names it: the look of the handle before it is wired. */
function HandleSwatch({ color }: { color: string }) {
  return (
    <span
      aria-hidden="true"
      data-curio-handle-swatch={color}
      style={{
        display: 'inline-block', width: 10, height: 10, borderRadius: '50%',
        boxSizing: 'border-box', backgroundColor: '#ffffff', border: `2px solid ${color}`,
        verticalAlign: 'middle', marginRight: 4,
      }}
    />
  );
}

/** Which shape the node emits: the tagged points (default) or the polygons with counts. */
export function resolveOutputMode(data: any): SpatialJoinOutput {
  return data?.spatialJoin?.output === 'polygons' ? 'polygons' : 'points';
}

export const useSpatialJoinBehavior: NodeBehaviorHook = (data, nodeState) => {
  const [slots, setSlots] = useState<[any | undefined, any | undefined]>([undefined, undefined]);
  const edges = useEdges();
  const { updateDataNode, dashboardOn } = useFlowContext();
  const { showToast } = useToastContext();

  const nameProperty = resolveNameProperty(data);
  const outputMode = resolveOutputMode(data);
  // What the last join reported: how many points found a polygon, and the
  // backend's warnings (e.g. no polygon carries the chosen property).
  const [lastResult, setLastResult] = useState<{ tagged: number; total: number; column: string; output: SpatialJoinOutput; warnings: string[] } | null>(null);

  const commitNameProperty = useCallback((value: string) => {
    const next = value.trim() || DEFAULT_NAME_PROPERTY;
    if (next === nameProperty) return;
    // Persisted on the node so TrillGenerator writes it (metadata.spatialJoin).
    updateDataNode(data.nodeId, { ...data, spatialJoin: { ...(data as any).spatialJoin, nameProperty: next } });
  }, [data, nameProperty, updateDataNode]);

  const commitOutputMode = useCallback((value: SpatialJoinOutput) => {
    if (value === outputMode) return;
    updateDataNode(data.nodeId, { ...data, spatialJoin: { ...(data as any).spatialJoin, output: value } });
  }, [data, outputMode, updateDataNode]);

  const pointsConnected = useMemo(
    () => edges.some(e => e.target === data.nodeId && e.targetHandle === 'in_points'),
    [edges, data.nodeId],
  );
  const polygonsConnected = useMemo(
    () => edges.some(e => e.target === data.nodeId && e.targetHandle === 'in_polygons'),
    [edges, data.nodeId],
  );

  // Each input reaches its port's entry in `data.portInputs`, where it stays
  // (FlowProvider keeps one per handle), and lands in its slot by its
  // geometry. A later arrival must NOT cancel an earlier one that is still
  // resolving: with the polygons loader first and the points loader right
  // behind it (example 15's order, and the generic canvas test's), the points
  // reference arrived while the polygon artifact was still downloading, a
  // cleanup-style cancel dropped it, and the join waited forever for polygons
  // it had already been handed. Instead, each resolution carries a sequence
  // number and only a newer resolution of the SAME slot may overwrite an
  // older one; unmount is the only thing that stops a result from landing.
  const aliveRef = useRef(true);
  const resolveSeqRef = useRef(0);
  const appliedSeqRef = useRef<[number, number]>([0, 0]);

  // What a Run All waits on, as it waits for a Data Pool's fetch: the inputs
  // still being fetched, the join they start, and the join's last outcome.
  // Without them the run counted the join as done the moment it asked, moved
  // on to the charts, and they compiled before the join had answered: "0 rows
  // arrived", over a chart that drew a moment later (#151).
  const slotsRef = useRef<[any | undefined, any | undefined]>([undefined, undefined]);
  const pendingInputsRef = useRef<Set<Promise<unknown>>>(new Set());
  const inflightRef = useRef<Promise<void> | null>(null);
  const outcomeRef = useRef<{ code: 'success' | 'error'; content: string } | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  // Read by the join when it starts; `data` changes identity on every node
  // update, including our own updateDataNode.
  const latestRef = useRef({ data, nameProperty, outputMode, dashboardOn, showToast });
  latestRef.current = { data, nameProperty, outputMode, dashboardOn, showToast };
  useEffect(() => () => {
    aliveRef.current = false;
    controllerRef.current?.abort();
  }, []);

  // Post the join for the slots as they are now, if both are filled. Started
  // the moment the second one lands, not on the next render, so a Run All that
  // asks right after sees it running.
  const startJoin = useCallback(() => {
    const rawPoints = unwrap(slotsRef.current[0]);
    const rawPolygons = unwrap(slotsRef.current[1]);
    if (!rawPoints || !rawPolygons) return;
    const { data: node, nameProperty: property, outputMode: mode, dashboardOn: onDashboard, showToast: toast } = latestRef.current;
    // Never from a dashboard. Restoring a saved dataflow fills both slots with
    // no user action, so this would post a join to the server because somebody
    // opened a page to look at it: a computation nobody asked for, on a page
    // that is supposed to need no server at all, and one that throws for a
    // visitor holding a link. A dashboard shows what was saved or it shows the
    // node's empty state; it never computes.
    if (onDashboard) return;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    outcomeRef.current = null;
    setLastResult(null);
    const settled: Promise<void> = fetch(API_BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ points: rawPoints, polygons: rawPolygons, name_property: property, output: mode }),
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
        if (!aliveRef.current) return;
        const features: any[] = Array.isArray(fc?.features) ? fc.features : [];
        // The backend names the tag column after the polygon column, or
        // `<column>_polygon` when the points already had one; it says which.
        const column: string = typeof fc?.metadata?.tag_column === 'string' ? fc.metadata.tag_column : property;
        const output: SpatialJoinOutput = fc?.metadata?.output === 'polygons' ? 'polygons' : 'points';
        const tagged = output === 'polygons'
          ? features.filter(f => (f?.properties?.point_count ?? 0) > 0).length
          : features.filter(f => f?.properties?.[column] != null).length;
        const warnings: string[] = Array.isArray(fc?.metadata?.warnings) ? fc.metadata.warnings : [];
        setLastResult({ tagged, total: features.length, column, output, warnings });
        // Downstream first, then the outcome: the outcome is what tells a run
        // this node is done, and the nodes it feeds must have the rows by then.
        node.outputCallback(node.nodeId, { data: fc, dataType: 'geodataframe' });
        // A warning is still a completed join - downstream gets data - but the
        // node says so where the user is looking, and once as a toast.
        outcomeRef.current = { code: 'success', content: warnings.join('\n') };
        nodeState.setOutput({ ...outcomeRef.current });
        for (const w of warnings) toast(w, 'warning');
      })
      .catch(e => {
        if (e.name === 'AbortError' || !aliveRef.current) return;
        outcomeRef.current = { code: 'error', content: e.message || String(e) };
        nodeState.setOutput({ ...outcomeRef.current });
      })
      .finally(() => {
        if (inflightRef.current === settled) inflightRef.current = null;
      });
    inflightRef.current = settled;
    // nodeState is stable for the node's lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setSlot = useCallback((idx: 0 | 1, value: any) => {
    const next: [any | undefined, any | undefined] = [slotsRef.current[0], slotsRef.current[1]];
    next[idx] = value;
    slotsRef.current = next;
    setSlots(next);
    startJoin();
  }, [startJoin]);

  const placeResolved = useCallback((v: any, seq: number) => {
    if (!aliveRef.current) return;
    const kind = classifyFC(v);
    const idx: 0 | 1 | null = kind === 'points' ? 0 : kind === 'polygons' ? 1 : null;
    if (idx === null || seq < appliedSeqRef.current[idx]) return;
    appliedSeqRef.current[idx] = seq;
    setSlot(idx, v);
  }, [setSlot]);

  // What each port holds, read port by port. Not `data.input`: that names only
  // the latest arrival, and when both inputs landed in one render (a Run All
  // of example 10 handed a join the Data Transformation's polygons and a
  // Simple View's points 50 ms apart) this effect saw only the second, and the
  // join said "has no polygons to join" when the run asked it. A port's value
  // is resolved once, when it changes.
  const portInputs = data.portInputs;
  const seenPortsRef = useRef<Record<string, unknown>>({});
  useEffect(() => {
    const ports = portInputs ?? {};
    const seen = seenPortsRef.current;
    for (const handle of Object.keys(seen)) {
      if (!(handle in ports)) delete seen[handle];
    }
    const onError = (e: any) => {
      if (!aliveRef.current) return;
      outcomeRef.current = { code: 'error', content: e?.message || String(e) };
      nodeState.setOutput({ ...outcomeRef.current });
    };
    for (const [handle, value] of Object.entries(ports)) {
      if (seen[handle] === value) continue;
      seen[handle] = value;
      if (value === undefined || value === '' || value === null) continue;
      const seq = ++resolveSeqRef.current;
      const resolving: Promise<unknown> = resolveInput(value)
        .then(v => placeResolved(v, seq))
        .catch(onError)
        .finally(() => { pendingInputsRef.current.delete(resolving); });
      pendingInputsRef.current.add(resolving);
    }
    // nodeState is stable for the node's lifetime; only a new input re-resolves.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [portInputs, placeResolved]);

  // No `setOutputCallbackOverride`. Both inputs arrive through `data.portInputs`,
  // above; UniversalNode calls that override with the node's OWN status (the
  // "exec" a run marks it with, the reason a run skipped it). As a slot setter
  // it put `{ code: "exec" }` in the points slot the moment a run asked, and
  // the join posted that as its points: "Tagged 0 of 0 points", and every
  // chart it fed got 0 rows.

  // A changed setting joins the same inputs again.
  useEffect(() => {
    startJoin();
  }, [nameProperty, outputMode, dashboardOn, startJoin]);

  // What a Run All calls, as it calls the Data Pool's: the run counts this node
  // done when its outcome lands, which for a join still running is when the
  // join answers (UniversalNode signals on the outcome).
  const sendCodeOverride = useCallback(async () => {
    // Inputs still being fetched start the join when they land.
    while (pendingInputsRef.current.size > 0) {
      await Promise.allSettled(Array.from(pendingInputsRef.current));
    }
    if (inflightRef.current) {
      await inflightRef.current;
      return;
    }
    // Nothing running: the join already answered for these inputs, or it has
    // nothing to join. Say so again: the run listens only from when it asked.
    if (outcomeRef.current) {
      nodeState.setOutput({ ...outcomeRef.current });
      return;
    }
    const missing = [!slotsRef.current[0] && 'points', !slotsRef.current[1] && 'polygons'].filter(Boolean);
    nodeState.setOutput({
      code: 'error',
      content: missing.length
        ? `The Spatial Join has no ${missing.join(' or ')} to join: connect ${missing.length > 1 ? 'them' : 'it'} and run the nodes feeding it.`
        : 'The Spatial Join could not run here.',
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const polygonColumns = useMemo(() => polygonPropertyNames(unwrap(slots[1])), [slots]);
  // The chosen column stays in the list when the polygons lack it or have not
  // arrived yet: a select whose value is none of its options shows the first
  // one while the node joins on another.
  const columnMissing = !polygonColumns.includes(nameProperty);

  const contentComponent = React.useMemo<React.ReactNode>(() => {
    const blue = <><HandleSwatch color={POINTS_HANDLE_COLOR} />blue circle</>;
    const green = <><HandleSwatch color={POLYGONS_HANDLE_COLOR} />green circle</>;
    const status: React.ReactNode = lastResult
      ? lastResult.output === 'polygons'
        ? `${lastResult.tagged} of ${lastResult.total} polygons received points; each polygon now carries point_count.`
        : `Tagged ${lastResult.tagged} of ${lastResult.total} points; the polygons' \`${nameProperty}\` is now the points' \`${lastResult.column}\` column.`
      : !slots[0] && !slots[1]
        ? <>Connect points to the {blue} and polygons to the {green}, then run the nodes feeding this one.</>
        : !slots[0]
          ? <>Waiting for the points input ({blue}).</>
          : !slots[1]
            ? <>Waiting for the polygons input ({green}).</>
            : 'Joining\u2026';
    return (
      <div
        className="nodrag nopan nowheel"
        data-curio-spatial-join-body="true"
        style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '8px 10px', fontSize: 12, lineHeight: 1.4 }}
      >
        <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          {/* Each word wears its circle, whatever the status line says. */}
          <span data-curio-spatial-join-column-label="true">
            Tag each <HandleSwatch color={POINTS_HANDLE_COLOR} />point with this{' '}
            <HandleSwatch color={POLYGONS_HANDLE_COLOR} />polygon column
          </span>
          <select
            value={nameProperty}
            disabled={polygonColumns.length === 0}
            aria-label="Tag each point with this polygon column"
            onChange={e => commitNameProperty(e.target.value)}
            style={{ padding: '3px 6px', fontSize: 12 }}
          >
            {columnMissing && (
              <option value={nameProperty}>
                {polygonColumns.length > 0 ? `${nameProperty} (not in the polygons)` : nameProperty}
              </option>
            )}
            {polygonColumns.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          {polygonColumns.length === 0 && (
            <span style={{ opacity: 0.7, fontSize: 11 }}>
              The polygons' columns are listed once they arrive.
            </span>
          )}
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span>Output</span>
          <select
            value={outputMode}
            aria-label="Output"
            onChange={e => commitOutputMode(e.target.value === 'polygons' ? 'polygons' : 'points')}
            style={{ padding: '3px 6px', fontSize: 12 }}
          >
            <option value="points">Points, tagged with the polygon column</option>
            <option value="polygons">Polygons, with the count of points inside</option>
          </select>
          <span style={{ opacity: 0.7, fontSize: 11 }}>
            {outputMode === 'polygons'
              ? <>Each polygon comes out with a <code>point_count</code>: draw it as a choropleth, or chart the counts.</>
              : <>Each point comes out with that column of its polygon, under the same name, plus a <code>{'<column>_point_count'}</code>.</>}
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
  }, [polygonColumns, columnMissing, lastResult, nameProperty, outputMode, slots, commitNameProperty, commitOutputMode]);

  // Two distinct input handles on the left edge: points (top), polygons (bottom).
  // Plus the single output handle on the right. We use `handlesOverride`
  // (not `dynamicHandles`) so the default `standardInOut()` "in" handle from
  // packagesClient is fully replaced — otherwise it leaks through at top:50%
  // as an unwanted gray circle. Which slot an input fills is decided by its
  // geometry (classifyFC), not by the handle it came in on.
  const handlesOverride: HandleDef[] = [
    {
      id: 'in_points',
      type: 'target',
      position: Position.Left,
      style: {
        top: '33%', width: '12px', height: '12px', borderRadius: '50%',
        boxSizing: 'border-box',
        backgroundColor: pointsConnected ? POINTS_HANDLE_COLOR : '#ffffff',
        // The ring wears the colour before anything is wired, so the text that
        // says "the blue circle" points at something visibly blue; it fills in
        // once an edge arrives.
        border: `2px solid ${POINTS_HANDLE_COLOR}`,
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
        backgroundColor: polygonsConnected ? POLYGONS_HANDLE_COLOR : '#ffffff',
        border: `2px solid ${POLYGONS_HANDLE_COLOR}`,
        zIndex: 10, pointerEvents: 'auto',
      },
    },
    {
      id: 'out',
      type: 'source',
      position: Position.Right,
    },
  ];

  return { handlesOverride, sendCodeOverride, contentComponent };
};
