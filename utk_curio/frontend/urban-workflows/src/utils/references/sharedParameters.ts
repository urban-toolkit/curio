/**
 * Shared tags (#662): a Parameter node holds one widget, and any node's code
 * names it as `[!! @name !!]`. A Parameter node has no edge, so the nodes it
 * reaches are found by reading their code, here.
 */
import { effectiveValue, nodeRunKey, normalizeWidgets, type WidgetDef } from "../widgets/widgetModel";
import { getUnversionedFlowNodeType } from "../flowNodeCanonicalType";
import { renameSharedReferences, sharedNamesIn } from "./codeReferences";

/** Kept in sync with `PARAMETER_TYPE` in `execution/workflow_spec.py`. */
export const PARAMETER_NODE_TYPE = "curio.builtin/parameter";

type FlowNodeLike = { id: string; type?: string | null; data?: any };

/** Whether *node*, a canvas node or a spec node, is a Parameter node. */
export function isParameterNode(node: { type?: string | null; data?: any }): boolean {
  return getUnversionedFlowNodeType(node) === PARAMETER_NODE_TYPE;
}

/**
 * The well-formed widgets in *raw*, each read on its own. Unlike a node's own
 * widgets, two with one name are both kept, so a reference to that name says
 * so. Kept in sync with `normalize_shared` in `code_references.py`.
 */
export function normalizeShared(raw: unknown): WidgetDef[] {
  return Array.isArray(raw) ? raw.flatMap((entry) => normalizeWidgets([entry])) : [];
}

/** The widgets the Parameter nodes among the canvas *nodes* hold, in node order. */
export function sharedWidgetsOf(nodes: readonly FlowNodeLike[]): WidgetDef[] {
  return nodes.filter(isParameterNode).flatMap((node) => normalizeShared(node.data?.widgets));
}

/** The same, for the nodes of a saved spec, whose widgets are at `metadata.widgets`. */
export function sharedWidgetsOfSpec(nodes: readonly { type?: string; metadata?: any }[]): WidgetDef[] {
  return nodes.filter(isParameterNode).flatMap((node) => normalizeShared(node.metadata?.widgets));
}

/** A canvas node's code as its editor holds it. */
export function nodeCode(node: FlowNodeLike): string {
  if (typeof node.data?.code === "string") return node.data.code;
  return typeof node.data?.defaultCode === "string" ? node.data.defaultCode : "";
}

/** The nodes among *nodes* whose code names the shared tag *name*. */
export function nodesUsingShared<N extends FlowNodeLike>(nodes: readonly N[], name: string): N[] {
  return nodes.filter((node) => !isParameterNode(node) && sharedNamesIn(nodeCode(node)).includes(name));
}

/**
 * What a run of a node depends on: `nodeRunKey` (its code and its widgets'
 * values), and the values of the shared tags its code names. Code that names
 * none keeps `nodeRunKey`'s key, so no saved result goes stale.
 */
export function runKeyWithShared(code: string, widgets: unknown, shared: WidgetDef[]): string {
  const key = nodeRunKey(code, widgets);
  const names = sharedNamesIn(code);
  if (names.length === 0) return key;
  const values = names.map((name) => [name, shared.filter((w) => w.name === name).map(effectiveValue)]);
  return key + "\u0000@" + JSON.stringify(values);
}

/**
 * *nodes* after the Parameter node named *from* was renamed *to*: each node
 * whose code names it gets the code rewritten, in `data.code` and in
 * `data.defaultCode`, which its editor shows. Other nodes are kept as they are.
 */
export function withSharedRenamed<N extends FlowNodeLike>(nodes: N[], from: string, to: string): N[] {
  return nodes.map((node) => {
    if (isParameterNode(node)) return node;
    const code = nodeCode(node);
    const renamed = renameSharedReferences(code, from, to);
    if (renamed === code) return node;
    return { ...node, data: { ...node.data, code: renamed, defaultCode: renamed } };
  });
}
