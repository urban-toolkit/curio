/**
 * Who is who in a dataflow's collaboration room.
 *
 * The room tells its participants apart by participant id, one per socket,
 * never by account: two tabs of one account, or two hosted guests on the one
 * guest account, are two participants. Every "is this me?" on the canvas asks
 * here: a node's lock chip among them.
 *
 * Each participant carries the role its account has on the dataflow, decided
 * on the server (`projects/access.py`): the owner and the editors the owner
 * invited edit, everyone else watches.
 */

/** A participant's role on the open dataflow. */
export type RoomRole = "owner" | "editor" | "watcher";

/** What a lock or a room member names its participant by. */
export interface ParticipantRef {
  participant_id?: string | null;
}

/** Whether `ref` is this tab's own participant, `own`. Nothing is this tab's
 *  before its join answers with its id. */
export function isOwnParticipant(
  own: string | null | undefined,
  ref: ParticipantRef | null | undefined,
): boolean {
  return Boolean(own && ref?.participant_id && ref.participant_id === own);
}

/** Whether a role edits the dataflow. */
export function canEditRole(role: RoomRole | null | undefined): boolean {
  return role === "owner" || role === "editor";
}

/** Who a tab is on the open dataflow. */
export type CanvasRole = "owner" | "editor" | "watcher";

/**
 * The role a tab has on the open dataflow.
 *
 * The owner's tab, and that of a dataflow not saved yet, is the owner's.
 * Another account's dataflow, opened from its link (`viewerMode` "shared"), is
 * edited only with collaboration on, by an account its room says edits it: an
 * editor the owner invited. Before the join answers, after a refusal, and
 * with collaboration off, the tab watches.
 *
 * Saving stays the owner's: a tab saves the dataflow only on `viewerMode`
 * "owner", whatever this says.
 */
export function canvasRole(
  viewerMode: "owner" | "shared" | undefined,
  collab: { enabled: boolean; role?: RoomRole | null },
): CanvasRole {
  if (viewerMode !== "shared") return "owner";
  return collab.enabled && canEditRole(collab.role) ? "editor" : "watcher";
}

/** Whether a tab in the room sends its changes to the dataflow's doc: the
 *  rule `canvasRole` keeps for the canvas, on the room's role. The owner's
 *  tab does; an editor's only with collaboration on, as its canvas watches
 *  without it; a watcher's never does. */
export function writesDoc(role: RoomRole | null | undefined, enabled: boolean): boolean {
  return role === "owner" || (enabled && role === "editor");
}

/** The role `participantId` has among `users`, the room's list, or null when
 *  it is not in it. */
export function roleIn(
  users: ReadonlyArray<ParticipantRef & { role?: RoomRole }>,
  participantId: string | null | undefined,
): RoomRole | null {
  if (!participantId) return null;
  return users.find((user) => user.participant_id === participantId)?.role ?? null;
}

