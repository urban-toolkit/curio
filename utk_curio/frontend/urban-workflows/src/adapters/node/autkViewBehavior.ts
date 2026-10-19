/**
 * The Autark node as the canvas registers it (registry/builtinBehaviors):
 * autkGrammarBehavior's hook, with the selection tags on the node emptied
 * each time a run has drawn it (#884).
 *
 * A run draws the node's map or plot anew, and a pick or a brush made in it
 * does not come back: autk-grammar lights again only the rows a Data Pool
 * flags in its input and the rows a linked chart selects. A node reading one
 * of its tags would otherwise go on reading a pick the node no longer shows.
 * A Vega-Lite chart puts a point selection back from its tags instead
 * (hook/useVega); putting a pick back on a map is autkGrammarBehavior's to do.
 */
import { useEffect, useRef } from 'react';
import type { NodeBehaviorHook } from '../../registry/types';
import { useFlowContext } from '../../providers/FlowProvider';
import { useAutkGrammarBehavior } from './autkGrammarBehavior';

export const useAutkViewBehavior: NodeBehaviorHook = (data, nodeState) => {
  const behavior = useAutkGrammarBehavior(data, nodeState);
  const { clearSelectionTagsOf } = useFlowContext();
  const clearRef = useRef(clearSelectionTagsOf);
  clearRef.current = clearSelectionTagsOf;
  // A draw that ends after the node left the page empties nothing: a node of
  // the same id may be on the canvas by then (a dataflow opened again in place).
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const { applyGrammar } = behavior;
  if (!applyGrammar) return behavior;
  return {
    ...behavior,
    applyGrammar: async (spec: string) => {
      await applyGrammar(spec);
      if (mountedRef.current) clearRef.current?.(data.nodeId);
    },
  };
};
