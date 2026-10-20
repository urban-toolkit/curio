/**
 * A dataflow's versions, as `TrillGenerator` records them, turned into the
 * items its provenance history shows: numbered in the order they were made,
 * each named by the change that made it.
 */
import type { GraphPreview } from "../api/projectsApi";
import { tryGetNodeDescriptor } from "../registry/nodeRegistry";
import type { HistoryItem } from "./provenanceTree";

/** A version (`provenanceJSON.nodes`). */
export interface RecordedVersion {
  id: string;
  timestamp?: number;
  preview?: GraphPreview | null;
}

/** The change that made one version from another (`provenanceJSON.edges`). */
export interface RecordedChange {
  source: string;
  target: string;
  label?: string;
}

export interface RecordedHistory {
  nodes?: RecordedVersion[];
  edges?: RecordedChange[];
}

/** The history's items, oldest first, numbered from 1. */
export function versionItems(history: RecordedHistory | null | undefined): HistoryItem[] {
  const versions = history?.nodes ?? [];
  const byId = new Map(versions.map((version) => [version.id, version]));
  const madeFrom = new Map<string, RecordedChange>();
  for (const change of history?.edges ?? []) {
    if (!madeFrom.has(change.target) && byId.has(change.source)) madeFrom.set(change.target, change);
  }
  return versions.map((version, i) => {
    const change = madeFrom.get(version.id);
    const at = version.timestamp ? new Date(version.timestamp) : null;
    return {
      id: version.id,
      parentId: change ? change.source : null,
      order: i,
      tag: String(i + 1),
      title: versionTitle(change?.label, change ? byId.get(change.source)?.preview : undefined, version.preview),
      when: at ? at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "",
      tooltip: at ? at.toLocaleString() : undefined,
    };
  });
}

/**
 * What a version is: the change that made it ("Node added"), with the kind of
 * node when it added or removed one ("Node added: Vega-Lite"). The first
 * version is the empty dataflow, or the one a file or an example opened with.
 */
export function versionTitle(
  change: string | undefined,
  before: GraphPreview | null | undefined,
  after: GraphPreview | null | undefined,
): string {
  if (!change) return (after?.nodes?.length ?? 0) === 0 ? "Empty dataflow" : "First version";
  const kind = changedNodeKind(before, after);
  return kind ? `${change}: ${kind}` : change;
}

/** The registered name of the one node a version added or removed; null when
 *  it changed no node, or more than one, or a kind nothing registered. */
export function changedNodeKind(
  before: GraphPreview | null | undefined,
  after: GraphPreview | null | undefined,
): string | null {
  const was = new Set((before?.nodes ?? []).map((node) => node.id));
  const now = new Set((after?.nodes ?? []).map((node) => node.id));
  const added = (after?.nodes ?? []).filter((node) => !was.has(node.id));
  const removed = (before?.nodes ?? []).filter((node) => !now.has(node.id));
  if (added.length + removed.length !== 1) return null;
  const node = added[0] ?? removed[0];
  return typeof node.type === "string" ? tryGetNodeDescriptor(node.type)?.label ?? null : null;
}

/** "4 nodes, 3 connections". */
export function versionCounts(preview: GraphPreview | null | undefined): string {
  const nodes = preview?.nodes?.length ?? 0;
  const edges = preview?.edges?.length ?? 0;
  return `${nodes} ${nodes === 1 ? "node" : "nodes"}, ${edges} ${edges === 1 ? "connection" : "connections"}`;
}
