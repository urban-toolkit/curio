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
 *
 * An agent at work is a participant too, run by the server, which names it
 * the same way in its lock and in its awareness state's `user`: `agent`, who
 * it is and who asked it (`agentHolding`). Its lock is the room's soft lock,
 * named after it, with `writes`, what it writes into the node; its awareness
 * says which node it is writing (`collab/agentHolds`).
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
 * edited by an account its room says edits it: an editor the owner invited.
 * Before the join answers, and after a refusal, the tab watches.
 *
 * Saving stays the owner's: a tab saves the dataflow only on `viewerMode`
 * "owner", whatever this says.
 */
export function canvasRole(
  viewerMode: "owner" | "shared" | undefined,
  collab: { role?: RoomRole | null },
): CanvasRole {
  if (viewerMode !== "shared") return "owner";
  return canEditRole(collab.role) ? "editor" : "watcher";
}

/** Whether a tab in the room sends its changes to the dataflow's doc: the
 *  rule `canvasRole` keeps for the canvas, on the room's role. The owner's
 *  tab and an editor's do; a watcher's never does. */
export function writesDoc(role: RoomRole | null | undefined): boolean {
  return canEditRole(role);
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

/** What an agent's lock says it writes into its node. */
export type AgentWrites = "code" | "spec" | "widgets" | "settings";

const AGENT_WRITES: ReadonlySet<string> = new Set<AgentWrites>(["code", "spec", "widgets", "settings"]);

/** An agent at work on a node, as its lock or its awareness names it. */
export interface AgentHold {
  /** The agent's participant in the room. */
  participantId: string | null;
  /** Its attachment to the dataflow, whose chat is its. */
  attachmentId: string | null;
  /** Its name, from its manifest: the lock is named after it. */
  name: string;
  /** Its category, which gives its glyph and its tint. */
  category: string | null;
  /** The name of whoever asked it. */
  askedBy: string | null;
  /** What it writes into the node; null for anything else. */
  writes: AgentWrites | null;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

/** The agent *lock* names, a lock of the room's or an agent peer's awareness
 *  `user` with its `writes`; null for a person's. An agent's carries
 *  `agent`, `{attachmentId, coord, category, askedBy: {account, name}}`,
 *  beside its `name` and `participant_id`. */
export function agentHolding(lock: unknown): AgentHold | null {
  if (!lock || typeof lock !== "object") return null;
  const { agent, name, participant_id: participantId, writes } = lock as Record<string, unknown>;
  if (!agent || typeof agent !== "object") return null;
  const { attachmentId, category, askedBy } = agent as { attachmentId?: unknown; category?: unknown; askedBy?: unknown };
  const asker = askedBy && typeof askedBy === "object" ? (askedBy as Record<string, unknown>) : {};
  return {
    participantId: text(participantId),
    attachmentId: text(attachmentId),
    name: text(name) ?? "An agent",
    category: text(category),
    askedBy: text(asker.name) ?? text(asker.account),
    writes: typeof writes === "string" && AGENT_WRITES.has(writes) ? (writes as AgentWrites) : null,
  };
}

/** An agent as the room names it: "Node Builder (asked by Ana)". */
export function agentWithAsker(hold: Pick<AgentHold, "name" | "askedBy">): string {
  return hold.askedBy ? `${hold.name} (asked by ${hold.askedBy})` : hold.name;
}

