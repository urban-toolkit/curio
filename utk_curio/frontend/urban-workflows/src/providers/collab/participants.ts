/**
 * Who is who in a dataflow's collaboration room.
 *
 * The room tells its participants apart by participant id, one per socket,
 * never by account: two tabs of one account, or two hosted guests on the one
 * guest account, are two participants. Every "is this me?" on the canvas asks
 * here: a node's lock chip, a proposal's buttons, an applied change's skip.
 *
 * Each participant carries the role its account has on the dataflow, decided
 * on the server (`projects/access.py`): the owner and the editors the owner
 * invited edit, everyone else watches.
 */

/** A participant's role on the open dataflow. */
export type RoomRole = "owner" | "editor" | "watcher";

/** What a lock, a proposal or a room member names its participant by. */
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

/** The role `participantId` has among `users`, the room's list, or null when
 *  it is not in it. */
export function roleIn(
  users: ReadonlyArray<ParticipantRef & { role?: RoomRole }>,
  participantId: string | null | undefined,
): RoomRole | null {
  if (!participantId) return null;
  return users.find((user) => user.participant_id === participantId)?.role ?? null;
}

/** The others in the room who edit the dataflow: whom a proposed change waits
 *  for. A watcher has no vote. */
export function otherEditors<T extends ParticipantRef & { role?: RoomRole }>(
  users: ReadonlyArray<T>,
  own: string | null | undefined,
): T[] {
  return users.filter((user) => !isOwnParticipant(own, user) && canEditRole(user.role));
}
