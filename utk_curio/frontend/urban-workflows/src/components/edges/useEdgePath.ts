// The path an edge draws: a bezier between nodes on the canvas or, in the
// notebook view, a bracket out to its lane in the bar and back.
import { getBezierPath, useStore, type Position } from "reactflow";
import { useNotebookViewContext } from "../../providers/flow/notebookViewContext";
import { notebookArcPath } from "../../utils/notebookLayout";

interface EdgeGeometry {
  id: string;
  source: string;
  target: string;
  sourceX: number;
  sourceY: number;
  targetX: number;
  targetY: number;
  sourcePosition: Position;
  targetPosition: Position;
}

export function useEdgePath(edge: EdgeGeometry): {
  path: string;
  labelX: number;
  labelY: number;
  /** In the notebook view, the edge touches a selected cell and is drawn dark. */
  emphasized: boolean;
} {
  const notebook = useNotebookViewContext();
  const laneX = notebook.on ? notebook.laneX.get(edge.id) : undefined;
  // A cell's connections can be followed through the bar: select the cell and
  // its arcs stand out from the others running past it.
  const emphasized = useStore((s) =>
    laneX !== undefined &&
    (!!s.nodeInternals.get(edge.source)?.selected || !!s.nodeInternals.get(edge.target)?.selected));

  if (laneX !== undefined) {
    const [path, labelX, labelY] = notebookArcPath(edge.sourceX, edge.sourceY, edge.targetX, edge.targetY, laneX);
    return { path, labelX, labelY, emphasized };
  }
  const [path, labelX, labelY] = getBezierPath({
    sourceX: edge.sourceX,
    sourceY: edge.sourceY,
    sourcePosition: edge.sourcePosition,
    targetX: edge.targetX,
    targetY: edge.targetY,
    targetPosition: edge.targetPosition,
  });
  return { path, labelX, labelY, emphasized: false };
}
