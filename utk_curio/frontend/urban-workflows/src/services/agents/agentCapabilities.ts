/**
 * What an agent declares in its manifest, read to decide what its chat offers.
 *
 * An agent is never recognized by its id: a feature goes to any agent that
 * declares the capability behind it, so a user's own agent that declares what
 * a shipped one does gets the same chat.
 */

/** Plans a dataflow and runs Solve over the plan: the Solve strip. */
export const ORCHESTRATE_CAPABILITY = "dataflow.orchestrate";
/** Builds a node on the canvas: its chat says when a reply changed nothing. */
export const NODE_BUILD_CAPABILITY = "node.build";
/** Records the dataset a node loads: the candidates card's confirm. */
export const DATASET_SELECT_CAPABILITY = "dataset.select";

/** Whether the agent behind *attachment* declares *capability*. */
export function declaresCapability(attachment: { capabilities?: string[] }, capability: string): boolean {
  return (attachment.capabilities ?? []).includes(capability);
}
