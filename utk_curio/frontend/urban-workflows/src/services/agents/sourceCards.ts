import type { AgentDatasetSourceRecord, AgentSessionTurn } from "./types";

/**
 * A card of a node's candidates follows its Dataset Finder's record, as the
 * listing has it (`sourceRecord`), one rule for the Finder's own chat and for
 * every chat that asked for the candidates. Each card carries the id of the
 * search that minted it (`discoveryId`); the record names the card it offers
 * now (`discoveryId`) and the card the pick was made on (`pickedFrom`).
 */

/** Where a card of a node's candidates stands. */
export type SourceCardStanding =
  /** Its rows and Use this source: the record asks for this card's pick. */
  | { kind: "live" }
  /** The pick was made on this card, and the node waits for no more of it. */
  | { kind: "recorded" }
  /** A newer search replaced its candidates: the record offers another card. */
  | { kind: "superseded" }
  /** Nothing is to pick on it any more, for *why*: its Finder was taken off
   * the node, the node is gone, the node's source is grounded without a pick
   * (a skip), or the record that asked is gone (its Finder's chat cleared). */
  | { kind: "closed"; why: "finder-gone" | "node-gone" | "skipped" | "no-record" };

/** The chats besides the Finder's that hold the card on offer now: the
 * record's `askers`, else the one chat that asked (`askedBy`). */
export function askersOf(record: AgentDatasetSourceRecord | null | undefined): string[] {
  if (record?.askers && record.askers.length) return record.askers;
  return record?.askedBy ? [record.askedBy] : [];
}

/** Whether the record holds a pick the user has nothing left to do for: a
 * pick that resolved the node, downloads or waits for its install, while the
 * node no longer waits for the user's pick (*waitsForPick*: the Finder's
 * `waitsForYou` names the node). */
function holdsAPick(record: AgentDatasetSourceRecord | null | undefined, waitsForPick: boolean): boolean {
  return (record?.picks ?? []).length > 0 && record?.status !== "candidates-pending" && !waitsForPick;
}

/**
 * Where the card *discoveryId* of a node's candidates stands, by its Finder's
 * *record* (null when the Finder keeps none). *finderPresent* is false once
 * the Finder is no longer on the dataflow, and *nodePresent* false once the
 * node is not on the canvas. A card or a record from before cards had ids
 * keeps the rule it had: Recorded once the record holds a pick the user has
 * nothing left to do for, else live. A skip closes any card.
 */
export function sourceCardStanding(opts: {
  discoveryId?: string | null;
  record?: AgentDatasetSourceRecord | null;
  waitsForPick: boolean;
  finderPresent?: boolean;
  nodePresent?: boolean;
}): SourceCardStanding {
  const { discoveryId = null, record = null, waitsForPick, finderPresent = true, nodePresent = true } = opts;
  if (!finderPresent) return { kind: "closed", why: nodePresent ? "finder-gone" : "node-gone" };
  if (record?.status === "not-needed") return { kind: "closed", why: "skipped" };
  if (discoveryId && record?.discoveryId) {
    if (record.pickedFrom === discoveryId && holdsAPick(record, waitsForPick)) return { kind: "recorded" };
    return record.discoveryId === discoveryId ? { kind: "live" } : { kind: "superseded" };
  }
  if (!discoveryId && record?.discoveryId) return { kind: "superseded" };
  if (discoveryId && !record) return { kind: "closed", why: "no-record" };
  // A card or a record from before cards had ids.
  return holdsAPick(record, waitsForPick) ? { kind: "recorded" } : { kind: "live" };
}

/** The ids of the candidates cards a chat's *turns* hold, its own Finder's
 * cards and the cards of the candidates it asked for. */
export function sourceCardIds(turns: AgentSessionTurn[]): Set<string> {
  const ids = new Set<string>();
  for (const turn of turns) {
    for (const part of turn.content ?? []) {
      if ((part.type === "sourcePick" || part.type === "datasetCandidates") && "discoveryId" in part) {
        const id = (part as { discoveryId?: string }).discoveryId;
        if (id) ids.add(id);
      }
    }
  }
  return ids;
}
