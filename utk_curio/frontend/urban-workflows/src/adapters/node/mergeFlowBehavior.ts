import { useState, useEffect, useMemo, useCallback } from 'react';
import { useEdges, Edge, Position } from 'reactflow';
import { NodeBehaviorHook, HandleDef } from '../../registry/types';
import { NodeType } from '../../constants';
import { Starter, useStarterContext } from '../../providers/StarterProvider';

const MERGE_SLOT_COUNT = 5;

export const useMergeFlowBehavior: NodeBehaviorHook = (data, nodeState) => {
  // Read live edges from React Flow's store. This was previously done via a
  // manual `useStoreApi().subscribe`, but `store.subscribe` only fires on
  // *future* state changes — not the current state. So on first mount the
  // local `edges` state stayed `[]`, `connectedCount` stayed `0`, and the
  // output effect below never satisfied its `connectedCount > 0` guard, so
  // `outputCallback` was never called. Downstream nodes (e.g. a package code
  // node wired through this merge) then saw `data.input === ""` and ran
  // their user code with `arg = None`. `useEdges()` is the canonical React
  // Flow hook for this and gives a value on the very first render.
  const edges = useEdges();
  const [inputValues, setInputValues] = useState<any[]>(Array(MERGE_SLOT_COUNT).fill(undefined));

  const connectedCount = useMemo(
    () => edges.filter(e => e.target === data.nodeId && e.targetHandle?.startsWith('in_')).length,
    [edges, data.nodeId]
  );

  // Bundle the connected slots and emit them as a single 'outputs' value — but
  // ONLY once every connected slot holds a REAL upstream output. On connect
  // (during a fresh load) `applyOutput` seeds each slot with the empty-string
  // placeholder `""` (FlowProvider: `sourceEntry?.output ?? ""`) before the
  // source node has executed. Counting only non-`undefined` slots let those `""`
  // placeholders through, so the merge emitted `{data:["",""], dataType:'outputs'}`
  // prematurely — and a downstream code node then crashed in the sandbox on
  // `""['path']`. Treat ""/null as not-yet-produced so the merge emits only once
  // every input is a real ref.
  const emitIfReady = useCallback((slots: any[]) => {
    const isReady = (v: any) => v !== undefined && v !== null && v !== "";
    const outArr = (Array.isArray(slots) ? slots : []).filter(isReady);
    if (connectedCount > 0 && outArr.length === connectedCount
        && typeof data.outputCallback === 'function') {
      data.outputCallback(data.nodeId, { data: outArr, dataType: 'outputs' });
    }
  }, [connectedCount, data.nodeId, data.outputCallback]);

  // Reactive emit: fire as soon as the last slot fills (live editing).
  useEffect(() => {
    emitIfReady(inputValues);
  }, [inputValues, emitIfReady]);

  // Run-All path: a merge has no user code, so by default `UniversalNode` sees
  // no `sendCode` and calls `signalNodeExecDone` the instant `triggerExec` bumps
  // at the merge's scheduler level — advancing the run to the downstream node
  // BEFORE this merge's output has propagated, so that node executes with a null
  // input (`arg=None`). Exposing `sendCodeOverride` makes `UniversalNode` treat
  // the merge as a code node and skip that premature signal; `signalNodeExecDone`
  // then fires from `FlowProvider.applyNewOutput` only AFTER the emit below has
  // set the downstream node's `data.input`. Read the live slots straight from
  // `data.input` (set synchronously by `applyNewOutput` as upstream nodes
  // finish). This mirrors the Data Pool's `sendCodeOverride` for its async fetch.
  const sendCodeOverride = useCallback(async () => {
    emitIfReady(Array.isArray(data.input) ? data.input : inputValues);
    nodeState.setOutput({ code: 'success', content: '' });
  }, [emitIfReady, data.input, inputValues, nodeState]);

  useEffect(() => {
    if (Array.isArray(data.input)) {
      setInputValues(prev => {
        const cp = Array.isArray(prev) ? [...prev] : Array(MERGE_SLOT_COUNT).fill(undefined);
        data.input!.forEach((val: any, i: number) => {
          if (i < cp.length) cp[i] = val;
        });
        return cp;
      });
    }
  }, [data.input]);

  const setOutputCallbackOverride = (val: any, idx = 0) => {
    // UniversalNode wires this same override in as the node's STATUS setter
    // (`setOutputCallback = behavior.setOutputCallbackOverride ?? nodeState.setOutput`)
    // and calls `setOutputCallback({ code: 'exec', content: '' })` right before it
    // runs `sendCode` (UniversalNode.tsx). Now that the merge exposes
    // `sendCodeOverride`, that path fires — and without this guard it would land
    // the {code,content} status object in slot 0, so a downstream code node then
    // executes with the status as its input (e.g. `arg[0]` = {code:'exec'} →
    // "'dict' object has no attribute 'read'"). Real slot values are data refs
    // (path/dataType/data), never status objects, so drop anything status-shaped.
    if (val && typeof val === 'object'
        && 'code' in val && 'content' in val
        && !('path' in val) && !('dataType' in val) && !('data' in val)) {
      return;
    }
    setInputValues(prev => {
      const cp = Array.isArray(prev) ? [...prev] : Array(MERGE_SLOT_COUNT).fill(undefined);
      cp[idx] = val;
      return cp;
    });
  };

  // Build the 5 input slot handles + the single output handle, fully replacing
  // `adapter.handles`. We use `handlesOverride` rather than `dynamicHandles`
  // so the default `standardInOut()` "in" handle (which sits at top:50%) is
  // suppressed — otherwise it leaks through and overlays slot 3.
  const inputHandles: HandleDef[] = Array.from({ length: MERGE_SLOT_COUNT }).map((_, idx) => {
    const handleId = `in_${idx}`;
    const connected = edges.some(e => e.target === data.nodeId && e.targetHandle === handleId);
    return {
      id: handleId,
      type: 'target' as const,
      position: Position.Left,
      style: {
        top: `${((idx + 1) * 100) / 6}%`,
        width: '12px',
        height: '12px',
        borderRadius: '50%',
        boxSizing: 'border-box',
        backgroundColor: connected ? '#8e44ad' : '#ffffff',
        border: connected ? '2px solid #8e44ad' : '2px solid #b8b8b8',
        zIndex: 10,
        pointerEvents: 'auto' as const,
      },
      isConnectableOverride: (_data: any, isConnectable: boolean, _edges: Edge[]) =>
        isConnectable && !connected && (_data.suggestionType == undefined || _data.suggestionType === 'none'),
    };
  });

  const handlesOverride: HandleDef[] = [
    ...inputHandles,
    { id: 'out', type: 'source', position: Position.Right },
  ];

  return {
    handlesOverride,
    setOutputCallbackOverride,
    sendCodeOverride,
  };
}
