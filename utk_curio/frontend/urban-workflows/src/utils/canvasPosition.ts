/**
 * Where a node sits on the canvas, whichever view is showing it.
 *
 * The dashboard and the notebook view move nodes to their own slots and keep
 * the canvas spot in `data.workflowPosition`; a save writes that spot, and
 * anything that places a node by canvas geometry reads it the same way.
 */
export function canvasPositionOf(node: { position: { x: number; y: number }; data?: any }): { x: number; y: number } {
  return node.data?.workflowPosition ?? node.position;
}
