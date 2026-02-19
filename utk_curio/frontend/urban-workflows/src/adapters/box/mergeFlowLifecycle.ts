import { useState, useEffect } from 'react';
import { useStoreApi, Edge, Position } from 'reactflow';
import { BoxLifecycleHook, HandleDef } from '../../registry/types';
import { BoxType } from '../../constants';
import { Template, useTemplateContext } from '../../providers/TemplateProvider';

const MERGE_SLOT_COUNT = 5;

export const useMergeFlowLifecycle: BoxLifecycleHook = (data, _boxState) => {
  const store = useStoreApi();
  const [edges, setEdges] = useState<Edge[]>([]);
  const [inputValues, setInputValues] = useState<any[]>(Array(MERGE_SLOT_COUNT).fill(undefined));

  useEffect(() => {
    const unsubscribe = store.subscribe(({ edges: ef }) => {
      setEdges(ef ?? []);
    });
    return () => unsubscribe();
  }, [store]);

  useEffect(() => {
    const outArr = inputValues.filter(v => v !== undefined);
    if (outArr.length > 0) {
      data.outputCallback(data.nodeId, { data: outArr, dataType: 'outputs' });
    }
  }, [inputValues, data.nodeId, data.outputCallback]);

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
        backgroundColor: connected ? 'green' : 'red',
        width: '17px',
        height: '17px',
        borderRadius: '50%',
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
