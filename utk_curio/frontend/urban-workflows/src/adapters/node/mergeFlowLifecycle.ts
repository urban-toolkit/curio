import { useState, useEffect, useMemo } from 'react';
import { useEdges, Edge, Position } from 'reactflow';
import { NodeLifecycleHook, HandleDef } from '../../registry/types';
import { NodeType } from '../../constants';
import { Template, useTemplateContext } from '../../providers/TemplateProvider';

const MERGE_SLOT_COUNT = 5;

export const useMergeFlowLifecycle: NodeLifecycleHook = (data, _nodeState) => {
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

  useEffect(() => {
    const outArr = inputValues.filter(v => v !== undefined);
    if (connectedCount > 0 && outArr.length === connectedCount) {
      data.outputCallback(data.nodeId, { data: outArr, dataType: 'outputs' });
    }
  }, [inputValues, connectedCount, data.nodeId, data.outputCallback]);

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

  const setOutputCallbackOverride = (val: any, idx = 0) =>
    setInputValues(prev => {
      const cp = Array.isArray(prev) ? [...prev] : Array(MERGE_SLOT_COUNT).fill(undefined);
      cp[idx] = val;
      return cp;
    });

  const dynamicHandles: HandleDef[] = Array.from({ length: MERGE_SLOT_COUNT }).map((_, idx) => {
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

  return {
    dynamicHandles,
    setOutputCallbackOverride,
  };
}
