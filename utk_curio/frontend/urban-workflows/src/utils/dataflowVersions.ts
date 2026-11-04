/**
 * A dataflow's versions, as `TrillGenerator` records them or the server keeps
 * them, turned into the items its provenance history shows: numbered in the
 * order they were made, each named by the change that made it.
 */
import type { ServerVersion } from "../api/historyApi";
import type { GraphPreview } from "../api/projectsApi";
import { tryGetNodeDescriptor } from "../registry/nodeRegistry";
import type { HistoryItem } from "./provenanceTree";

/** The kinds of version that add or remove nodes and connections, which a
 *  title names by the kind of node (`versionTitle`). */
const GRAPH_KINDS = new Set(["load", "imported", "graph"]);

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
 * The versions the server keeps, oldest first, numbered from 1. A version
 * that added or removed a node is named as `versionItems` names it; one a
 * put-back made names the version it put back ("Put back version 8"); any
 * other by what changed ("Ana edited", "Saved").
 */
export function serverVersionItems(versions: readonly ServerVersion[]): HistoryItem[] {
  const byId = new Map(versions.map((version) => [version.id, version]));
  const tags = new Map(versions.map((version, i) => [version.id, String(i + 1)]));
  return versions.map((version, i) => {
    const parent = version.parent != null ? byId.get(version.parent) : undefined;
    const at = version.at ? new Date(version.at) : null;
    return {
      id: version.id,
      parentId: parent ? parent.id : null,
      order: i,
      tag: tags.get(version.id) ?? String(i + 1),
      title: serverVersionTitle(version, parent, tags),
      when: at ? at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "",
      tooltip: at ? at.toLocaleString() : undefined,
    };
  });
}

function serverVersionTitle(
  version: ServerVersion,
  parent: ServerVersion | undefined,
  tags: ReadonlyMap<string, string>,
): string {
  if (version.kind === "putBack") {
    const restored = version.restores ? tags.get(version.restores) : undefined;
    return restored ? `Put back version ${restored}` : "Put back";
  }
  if (GRAPH_KINDS.has(version.kind) || !version.what) {
    return versionTitle(version.what || undefined, parent?.preview, version.preview);
  }
  return version.what;
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
