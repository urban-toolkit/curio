/**
 * The writers of nodes whose code is their state, by node id.
 *
 * A node whose behavior keeps its state in its code (a Map Editor node, whose
 * code is its edit list) makes each change to that code its own way: the
 * entry in its Provenance drawer, the stale marks on the nodes below it, the
 * dataflow left Unsaved. It registers that writer here while it is on the
 * canvas, so code written from outside the node, an agent's applied change
 * (`applyNodeContent`), is made the way the node makes its own changes.
 */

/** Writes *code* into the node, as a change made by *author*, which names its entry. */
export type NodeCodeWriter = (code: string, author: string) => void;

const writers = new Map<string, NodeCodeWriter>();

/** Registers *writer* for *nodeId*; the function it returns takes it off again. */
export function registerNodeCodeWriter(nodeId: string, writer: NodeCodeWriter): () => void {
  writers.set(nodeId, writer);
  return () => {
    if (writers.get(nodeId) === writer) writers.delete(nodeId);
  };
}

/** The writer *nodeId*'s behavior registered, if any. */
export function nodeCodeWriter(nodeId: string): NodeCodeWriter | undefined {
  return writers.get(nodeId);
}
