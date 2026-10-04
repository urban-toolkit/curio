import type { Node } from 'reactflow';

/**
 * A node drawn hidden: still MOUNTED, with `display: none`, and neither
 * draggable nor selectable. The dashboard hides its unpinned nodes this way
 * and the canvas hides the members of a collapsed scenario (#662).
 *
 * React Flow's own `hidden` unmounts the node component, which would stop its
 * behaviour hooks: an unpinned Data Pool re-derives a tile's data from the
 * restored outputs, and a collapsed scenario's members keep running.
 */
export function hideNode<N extends Node>(node: N): N {
  return {
    ...node,
    style: { ...(node.style ?? {}), display: 'none' },
    draggable: false,
    selectable: false,
  };
}

/**
 * Whether *node* is drawn hidden. React Flow never measures such a node, so a
 * fit or a hit test that waits for its size, or reads its old one, leaves it out.
 */
export function isDrawnHidden(node: { style?: { display?: unknown } | null }): boolean {
  return node.style?.display === 'none';
}
