import { useEffect, useMemo, useCallback } from 'react';
import { useEdges, Edge, Position } from 'reactflow';
import { NodeLifecycleHook, HandleDef } from '../../registry/types';
import { buildMergeOutputArray, connectedMergeSlotIndices } from '../../utils/mergeFlowUtils';

const MERGE_SLOT_COUNT = 5;

export const useMergeFlowLifecycle: NodeLifecycleHook = (data, nodeState) => {
  // `useEdges()` reads the current graph on the first render. A manual
  // `useStoreApi().subscribe` only fires on *future* updates, so `connectedCount`
  // stayed 0 on mount and the merge never called `outputCallback`.
  const edges = useEdges();

  const connectedCount = useMemo(
    () => connectedMergeSlotIndices(edges, data.nodeId).length,
    [edges, data.nodeId],
  );

  const tryEmitMergedOutput = useCallback(() => {
    const outArr = buildMergeOutputArray(data.input, edges, data.nodeId);
    if (connectedCount > 0 && outArr.length === connectedCount) {
      if (typeof data.outputCallback === 'function') {
        data.outputCallback(data.nodeId, { data: outArr, dataType: 'outputs' });
      }
      return true;
    }
    return false;
  }, [data.input, data.outputCallback, data.nodeId, connectedCount, edges]);

  // Manual run / upstream completion: propagate when every wired slot is filled.
  useEffect(() => {
    tryEmitMergedOutput();
  }, [tryEmitMergedOutput]);

  // Play-All / triggerExec: emit synchronously so the downstream node receives
  // `data.input` before Play All advances past this merge level.
  const sendCodeOverride = useCallback((_code?: string) => {
    if (tryEmitMergedOutput()) return;
    const outArr = buildMergeOutputArray(data.input, edges, data.nodeId);
    nodeState.setOutput({
      code: 'error',
      content:
        `Merge Flow: ${outArr.length} of ${connectedCount} inputs are ready. ` +
        `Run all upstream nodes before using Play All.`,
    });
  }, [tryEmitMergedOutput, data.input, edges, data.nodeId, connectedCount, nodeState.setOutput]);

  const setOutputCallbackOverride = useCallback((_val: unknown, _idx = 0) => {
    // Slot-indexed hook kept for parity with spatial-join; merge data flows
    // through FlowProvider `data.input` + `tryEmitMergedOutput` above.
  }, []);

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
    disablePlay: true,
  };
};
