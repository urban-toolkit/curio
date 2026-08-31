/**
 * Wording shared by the three catalog drawers.
 *
 * The Data, Node and Agent drawers all add things to the open dataflow, and all
 * three create and save it first when it has never been persisted (through
 * `FlowProvider.ensureProjectId`). A user meeting that behaviour deserves to be
 * told before the click, in the same words on every surface - the Node drawer
 * and the Agent drawer had already drifted to two spellings of one sentence,
 * and the Data drawer performed the same save while saying nothing at all.
 *
 * `catalogDrawerParity.test.ts` holds the three to this constant.
 */

/** Shown while `projectId` is null, i.e. the dataflow has never been saved. */
export const UNSAVED_DATAFLOW_NOTICE =
  "This dataflow isn't saved yet; adding will save it first.";
