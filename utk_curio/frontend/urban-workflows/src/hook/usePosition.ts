import { useCallback } from "react";
import { useFlowContext } from "../providers/FlowProvider";

interface IUsePosition {
  getPosition: () => { x: number; y: number };
}

export function usePosition(): IUsePosition {
  const { nodes } = useFlowContext();

  const getPosition = useCallback(() => {
    if (nodes.length === 0) {
      return {
        x: 100,
        y: 100,
      };
    }
    const maxX = Math.max(...nodes.map((node) => node.position.x));
    const maxY = Math.max(...nodes.map((node) => node.position.y));
    return {
      x: maxX + 800,
      y: maxY,
    };
  }, [nodes]);

  return { getPosition };
}
