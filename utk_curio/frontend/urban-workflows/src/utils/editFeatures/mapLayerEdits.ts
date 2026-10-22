/**
 * An Interaction node and the Autark map it edits on (#662): the data goes
 * Data → Interaction → map on data edges, and an interaction edge (the in/out
 * dots, as two Autark views are linked) joins the node and the map, for
 * selections both ways. The edits reach the map on the data edge only.
 *
 * The node's run hands on its inputs with its edits, every layer under its
 * name (`curio_edit_features`, `by_input`). The map draws the node's own
 * input with the edits its code holds (`mapEditsPreview`), so an edit shows
 * at once, and hands on what it was fed: the edits the last Commit ran.
 */
import { EdgeType, NodeType } from "../../constants";
import { getUnversionedFlowNodeType } from "../flowNodeCanonicalType";
import { readEditFeaturesCode, type EditFeaturesSettings } from "./editFeatures";

/** The circle an edge goes into: `in` is 0, `in_<k>` is k. */
export function circleOf(handle: unknown): number {
  const m = /^in_(\d+)$/.exec(String(handle ?? ""));
  return m ? Number(m[1]) : 0;
}

export const isAutkMap = (node: any) => !!node && getUnversionedFlowNodeType(node) === NodeType.AUTK_GRAMMAR;
/** Whether *node* is an Interaction node (its type id is still Edit Features'). */
export const isInteraction = (node: any) => !!node && getUnversionedFlowNodeType(node) === NodeType.EDIT_FEATURES;

/** Whether *edge* is an interaction edge: the in/out link, not a data edge. */
export function isInteractionEdge(edge: any): boolean {
  return edge?.type === EdgeType.BIDIRECTIONAL_EDGE || (edge?.sourceHandle === "in/out" && edge?.targetHandle === "in/out");
}

/** The code a node's data holds: what its editor floats, else what it loaded with. */
export function nodeCode(data: any): string {
  return typeof data?.code === "string" && data.code !== "" ? data.code : String(data?.defaultCode ?? "");
}

/** The edits an Interaction node's code holds, or undefined when the node cannot read its code. */
export function nodeSettings(node: any): EditFeaturesSettings | undefined {
  const read = readEditFeaturesCode(nodeCode(node?.data));
  return "problem" in read ? undefined : read.settings;
}

/** How many circles feed *nodeId*: one past the highest a data edge goes into. */
export function circlesInto(nodeId: string, edges: readonly any[]): number {
  let circles = 0;
  for (const edge of edges) {
    if (edge.target !== nodeId || isInteractionEdge(edge)) continue;
    circles = Math.max(circles, circleOf(edge.targetHandle) + 1);
  }
  return Math.max(circles, 1);
}

/** Whether a data edge goes from *source* into *target*. */
export function feeds(source: string, target: string, edges: readonly any[]): boolean {
  return edges.some((edge) => edge.source === source && edge.target === target && !isInteractionEdge(edge));
}

/**
 * The Autark map the Interaction node *nodeId* picks and draws on: one it
 * feeds on a data edge and is linked to by an interaction edge, the first
 * such link when there are several. Null when there is none: a map linked but
 * not fed is not one.
 */
export function mapFedBy(nodeId: string, nodes: readonly any[], edges: readonly any[]): string | null {
  return linkedMaps(nodeId, nodes, edges)[0] ?? null;
}

/** Every Autark map *nodeId* feeds and is linked to, in the order of their links. */
export function linkedMaps(nodeId: string, nodes: readonly any[], edges: readonly any[]): string[] {
  const out: string[] = [];
  for (const edge of edges) {
    if (!isInteractionEdge(edge)) continue;
    const other = edge.source === nodeId ? edge.target : edge.target === nodeId ? edge.source : null;
    if (other == null || out.includes(other) || !feeds(nodeId, other, edges)) continue;
    if (isAutkMap(nodes.find((n) => n.id === other))) out.push(other);
  }
  return out;
}

/**
 * What a node is called on the canvas: its header, as renamed
 * (`packageTemplateLabel`, what `nodeDisplayLabel` reads first), else the
 * title the dataflow gave it.
 */
export function nodeName(node: any): string {
  for (const value of [node?.data?.packageTemplateLabel, node?.data?.title]) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

/** What each circle of *nodeId* brought: the name of the node it came from. */
export function circleTitles(nodeId: string, nodes: readonly any[], edges: readonly any[]): Record<number, string> {
  const out: Record<number, string> = {};
  for (const edge of edges) {
    if (edge.target !== nodeId || isInteractionEdge(edge)) continue;
    const name = nodeName(nodes.find((n) => n.id === edge.source));
    if (name) out[circleOf(edge.targetHandle)] = name;
  }
  return out;
}
