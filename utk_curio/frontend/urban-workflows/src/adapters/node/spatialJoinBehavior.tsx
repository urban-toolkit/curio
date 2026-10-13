import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { useEdges, Position } from 'reactflow';
import { NodeBehaviorHook, HandleDef } from '../../registry/types';
import { useFlowContext } from '../../providers/FlowProvider';
import { useToastContext } from '../../providers/ToastProvider';
import { fetchData } from '../../services/api';
import { backendUrl } from '../../utils/backendUrl';
import { inputSlotOf, isDataEdge, slotHandleId } from '../../utils/inputSlots';

/**
 * Spatial Join behavior: pair the rows of two inputs whose shapes meet (#576).
 *
 * Backs the generic `spatial-join` node in curio.builtin@1. Its two input
 * circles are the ones every node has: `in` is input_0 (the top circle, blue)
 * and `in_1` is input_1 (the bottom circle, green). input_0 is the left side of
 * the join and input_1 the right, whatever geometry each holds: the inputs
 * follow the circles, never their geometry type.
 *
 * The body picks the operation (how input_0's shape must meet input_1's) and
 * the output (one row per pair, or input_1's rows with a count), persisted at
 * `metadata.spatialJoin` so they survive a save. The node POSTs both inputs to
 * the `/spatial_join` backend route, which runs geopandas `sjoin`, when both
 * have arrived.
 */

const API_BASE = `${backendUrl()}/spatial_join`;

export type SpatialJoinPredicate =
  'intersects' | 'within' | 'contains' | 'touches' | 'overlaps' | 'crosses' | 'nearest';
export type SpatialJoinOutput = 'pairs' | 'counts';

/** The operations, as the words that finish "Pair each input_0 row with the input_1 rows it ...". */
const PREDICATES: ReadonlyArray<{ value: SpatialJoinPredicate; words: string; hint: string }> = [
  { value: 'intersects', words: 'intersects', hint: 'The shapes share at least one point. A point on an edge counts.' },
  { value: 'within', words: 'is within', hint: "input_0's shape lies inside input_1's. A point on the edge is not within." },
  { value: 'contains', words: 'contains', hint: "input_0's shape holds input_1's. A point on the edge is not contained." },
  { value: 'touches', words: 'touches', hint: 'The shapes meet only along their edges. A point on an edge touches.' },
  { value: 'overlaps', words: 'overlaps', hint: 'Two shapes of one kind share part of themselves, and neither holds the other.' },
  { value: 'crosses', words: 'crosses', hint: 'A line runs through the other shape, partly inside and partly outside it.' },
  { value: 'nearest', words: 'is nearest to', hint: 'The closest input_1 row, with the distance in meters as a distance column.' },
];

/** The saved operation, or intersects, the default the backend also assumes. */
export function resolvePredicate(data: any): SpatialJoinPredicate {
  const raw = data?.spatialJoin?.predicate;
  return PREDICATES.some(p => p.value === raw) ? raw : 'intersects';
}

/** Which shape the node emits: one row per pair (default) or input_1's rows with a count. */
export function resolveOutputMode(data: any): SpatialJoinOutput {
  return data?.spatialJoin?.output === 'counts' ? 'counts' : 'pairs';
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
// `{ path, dataType }` (normalizeFlowInput), never the rows. Resolve it
// through /get first; the envelope that comes back is
// `{ dataType, data, schema }` and `data` is the FeatureCollection.
async function resolveInput(value: any): Promise<any> {
  if (value && typeof value === 'object' && typeof value.path === 'string' && value.data === undefined) {
    const envelope = await fetchData(value.path);
    return envelope?.data ?? envelope;
  }
  return unwrap(value);
}

/** The two input circles' colours, repeated as swatches wherever the text names them. */
export const INPUT_0_COLOR = '#3b82f6';
export const INPUT_1_COLOR = '#22c55e';

/** A small hollow ring in a circle's colour, inline with the text that names it: the look of the circle before it is wired. */
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

type JoinResult = {
  output: SpatialJoinOutput;
  pairs: number;
  matchedLeft: number;
  leftRows: number;
  matchedRight: number;
  rightRows: number;
  warnings: string[];
};

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? '' : 's'}`;
}

export const useSpatialJoinBehavior: NodeBehaviorHook = (data, nodeState) => {
  const [slots, setSlots] = useState<[any | undefined, any | undefined]>([undefined, undefined]);
  const edges = useEdges();
  const { updateDataNode, dashboardOn } = useFlowContext();
  const { showToast } = useToastContext();

  const predicate = resolvePredicate(data);
  const outputMode = resolveOutputMode(data);
  // What the last join reported: its pair and row counts, and the backend's
  // warnings (e.g. an operation that can never match these shapes).
  const [lastResult, setLastResult] = useState<JoinResult | null>(null);

  const commitPredicate = useCallback((value: SpatialJoinPredicate) => {
    if (value === predicate) return;
    // Persisted on the node so TrillGenerator writes it (metadata.spatialJoin).
    updateDataNode(data.nodeId, { ...data, spatialJoin: { ...(data as any).spatialJoin, predicate: value } });
  }, [data, predicate, updateDataNode]);

  const commitOutputMode = useCallback((value: SpatialJoinOutput) => {
    if (value === outputMode) return;
    updateDataNode(data.nodeId, { ...data, spatialJoin: { ...(data as any).spatialJoin, output: value } });
  }, [data, outputMode, updateDataNode]);

  const wired = useMemo(() => {
    const circles = edges
      .filter(e => e.target === data.nodeId && isDataEdge(e))
      .map(e => inputSlotOf(e.targetHandle));
    return [circles.includes(0), circles.includes(1)] as const;
  }, [edges, data.nodeId]);

  // Each input reaches its circle's entry in `data.portInputs`, where it stays
  // (FlowProvider keeps one per handle), and lands in that circle's slot. A
  // later arrival must NOT cancel an earlier one that is still resolving: with
  // one input's artifact still downloading when the other lands, a
  // cleanup-style cancel dropped it and the join waited forever for an input
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
  const latestRef = useRef({ data, predicate, outputMode, dashboardOn, showToast });
  latestRef.current = { data, predicate, outputMode, dashboardOn, showToast };
  useEffect(() => () => {
    aliveRef.current = false;
    controllerRef.current?.abort();
  }, []);

  // Post the join for the slots as they are now, if both are filled. Started
  // the moment the second one lands, not on the next render, so a Run All that
  // asks right after sees it running.
  const startJoin = useCallback(() => {
    const left = unwrap(slotsRef.current[0]);
    const right = unwrap(slotsRef.current[1]);
    if (!left || !right) return;
    const { data: node, predicate: operation, outputMode: mode, dashboardOn: onDashboard, showToast: toast } = latestRef.current;
    // Never from a dashboard (#609). Restoring a saved dataflow fills both
    // slots with no user action, so this would post a join to the server
    // because somebody opened a page to look at it: a computation nobody asked
    // for, on a page that is supposed to need no server at all, and one that
    // throws for a visitor holding a link. A dashboard shows what was saved or
    // it shows the node's empty state; it never computes.
    if (onDashboard) return;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    outcomeRef.current = null;
    setLastResult(null);
    const settled: Promise<void> = fetch(API_BASE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ left, right, predicate: operation, output: mode }),
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
        const meta = fc?.metadata ?? {};
        const count = (v: unknown) => (typeof v === 'number' ? v : 0);
        const warnings: string[] = Array.isArray(meta.warnings) ? meta.warnings : [];
        setLastResult({
          output: meta.output === 'counts' ? 'counts' : 'pairs',
          pairs: count(meta.pairs),
          matchedLeft: count(meta.matched_left),
          leftRows: count(meta.left_rows),
          matchedRight: count(meta.matched_right),
          rightRows: count(meta.right_rows),
          warnings,
        });
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

  const placeResolved = useCallback((idx: 0 | 1, v: any, seq: number) => {
    if (!aliveRef.current || seq < appliedSeqRef.current[idx]) return;
    appliedSeqRef.current[idx] = seq;
    setSlot(idx, v);
  }, [setSlot]);

  // What each circle holds, read circle by circle. Not `data.input`: that
  // names only the latest arrival, and when both inputs landed in one render
  // (a Run All of example 10 handed a join the Data Transformation's polygons
  // and a Simple View's points 50 ms apart) this effect saw only the second,
  // and the join said it had nothing to join when the run asked it. A
  // circle's value is resolved once, when it changes.
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
      const idx = inputSlotOf(handle);
      if (idx !== 0 && idx !== 1) continue;
      if (seen[handle] === value) continue;
      seen[handle] = value;
      if (value === undefined || value === '' || value === null) continue;
      const seq = ++resolveSeqRef.current;
      const resolving: Promise<unknown> = resolveInput(value)
        .then(v => placeResolved(idx, v, seq))
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
  // it put `{ code: "exec" }` in an input slot the moment a run asked, and the
  // join posted that as its input: every chart it fed got 0 rows.

  // A changed setting joins the same inputs again.
  useEffect(() => {
    startJoin();
  }, [predicate, outputMode, dashboardOn, startJoin]);

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
    const missing = [!slotsRef.current[0] && 'input_0', !slotsRef.current[1] && 'input_1'].filter(Boolean);
    nodeState.setOutput({
      code: 'error',
      content: missing.length
        ? `The Spatial Join has no ${missing.join(' or ')} to join: connect ${missing.length > 1 ? 'them' : 'it'} and run the nodes feeding ${missing.length > 1 ? 'them' : 'it'}.`
        : 'The Spatial Join could not run here.',
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const contentComponent = React.useMemo<React.ReactNode>(() => {
    const blue = <><HandleSwatch color={INPUT_0_COLOR} />blue circle</>;
    const green = <><HandleSwatch color={INPUT_1_COLOR} />green circle</>;
    const status: React.ReactNode = lastResult
      ? lastResult.output === 'counts'
        ? `${lastResult.matchedRight} of ${lastResult.rightRows} input_1 rows have pairs (${lastResult.pairs} in all); each row carries point_count.`
        : `${plural(lastResult.pairs, 'pair')}: ${lastResult.matchedLeft} of ${lastResult.leftRows} input_0 rows matched.`
      : !slots[0] && !slots[1]
        ? <>Connect input_0 to the {blue} and input_1 to the {green}, then run the nodes feeding this one.</>
        : !slots[0]
          ? <>Waiting for input_0 ({blue}).</>
          : !slots[1]
            ? <>Waiting for input_1 ({green}).</>
            : 'Joining…';
    const operation = PREDICATES.find(p => p.value === predicate)!;
    return (
      <div
        className="nodrag nopan nowheel"
        data-curio-spatial-join-body="true"
        style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: '8px 10px', fontSize: 12, lineHeight: 1.4 }}
      >
        <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          {/* Each input wears its circle, whatever the status line says. */}
          <span data-curio-spatial-join-operation-label="true">
            Pair each <HandleSwatch color={INPUT_0_COLOR} />input_0 row with the{' '}
            <HandleSwatch color={INPUT_1_COLOR} />input_1 rows it
          </span>
          <select
            value={predicate}
            aria-label="Operation"
            onChange={e => commitPredicate(e.target.value as SpatialJoinPredicate)}
            style={{ padding: '3px 6px', fontSize: 12 }}
          >
            {PREDICATES.map(p => <option key={p.value} value={p.value}>{p.words}</option>)}
          </select>
          <span style={{ opacity: 0.7, fontSize: 11 }}>{operation.hint}</span>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span>Output</span>
          <select
            value={outputMode}
            aria-label="Output"
            onChange={e => commitOutputMode(e.target.value === 'counts' ? 'counts' : 'pairs')}
            style={{ padding: '3px 6px', fontSize: 12 }}
          >
            <option value="pairs">One row per pair, with input_1&apos;s columns</option>
            <option value="counts">input_1&apos;s rows, each with a count of its pairs</option>
          </select>
          <span style={{ opacity: 0.7, fontSize: 11 }}>
            {outputMode === 'counts'
              ? <>Each input_1 row comes out with <code>point_count</code>, the input_0 rows paired with it.</>
              : <>An input_1 column whose name input_0 already has comes in as <code>{'<column>_right'}</code>.</>}
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
  }, [lastResult, predicate, outputMode, slots, commitPredicate, commitOutputMode]);

  // The two input circles on the left edge, `in` (top) and `in_1` (bottom),
  // plus the single output handle on the right. `handlesOverride` (not
  // `dynamicHandles`) replaces the default `standardInOut()` handles from
  // packagesClient, so no third circle leaks through at top:50%.
  const circle = (slot: 0 | 1, top: string, color: string): HandleDef => ({
    id: slotHandleId(slot),
    type: 'target',
    position: Position.Left,
    style: {
      top, width: '12px', height: '12px', borderRadius: '50%',
      boxSizing: 'border-box',
      // The ring wears the colour before anything is wired, so the text that
      // says "the blue circle" points at something visibly blue; it fills in
      // once an edge arrives.
      backgroundColor: wired[slot] ? color : '#ffffff',
      border: `2px solid ${color}`,
      zIndex: 10, pointerEvents: 'auto',
    },
  });
  const handlesOverride: HandleDef[] = [
    circle(0, '33%', INPUT_0_COLOR),
    circle(1, '66%', INPUT_1_COLOR),
    {
      id: 'out',
      type: 'source',
      position: Position.Right,
    },
  ];

  return { handlesOverride, sendCodeOverride, contentComponent };
};
