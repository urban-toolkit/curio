// The dashboard agent's view of the dashboard: the controls it may set,
// and the widget lists its changes make.
//
// A control is one widget of a pinned tile, a Parameter node's included, named
// `<nodeId>:<widgetName>` so a copy in another scenario is a control of its own.
// The backend (`agents/application/dashboard_chat.py`) checks a change against
// the control it names; `applyAgentChanges` checks it again here, against
// the node as it is now, before anything is written.
import { resolveNodeDisplayLabel } from "./palettePackageFactoryDraft";
import { isParameterNode } from "./references/sharedParameters";
import type { Scenario } from "./scenarios/scenarioModel";
import {
  checkWidgetValue,
  effectiveValue,
  normalizeWidgets,
  type WidgetDef,
  type WidgetValue,
} from "./widgets/widgetModel";

export interface AgentControl {
  id: string;
  nodeId: string;
  node: string;
  scenario: string | null;
  name: string;
  label: string;
  type: WidgetDef["type"];
  options: NonNullable<WidgetDef["options"]>;
  value: WidgetValue;
}

export interface AgentChange {
  id: string;
  value: WidgetValue;
}

interface NodeLike {
  id: string;
  type?: string | null;
  data?: any;
}

export function controlId(nodeId: string, widgetName: string): string {
  return `${nodeId}:${widgetName}`;
}

function nodeLabel(node: NodeLike): string {
  const title = typeof node.data?.title === "string" ? node.data.title.trim() : "";
  if (title) return title;
  let resolved = "";
  try {
    resolved = resolveNodeDisplayLabel(node.data ?? {}) || "";
  } catch {
    resolved = "";
  }
  return resolved || (isParameterNode(node) ? "Parameter" : node.id);
}

/** The widgets of the pinned tiles, in the order the nodes are. */
export function dashboardControls(
  nodes: readonly NodeLike[],
  pins: Record<string, boolean | undefined>,
  scenarios: readonly Scenario[],
): AgentControl[] {
  const scenarioOf = new Map<string, string>();
  for (const scenario of scenarios) {
    for (const nodeId of scenario.nodes) if (!scenarioOf.has(nodeId)) scenarioOf.set(nodeId, scenario.name);
  }
  const controls: AgentControl[] = [];
  for (const node of nodes) {
    if (!pins[node.id]) continue;
    const widgets = normalizeWidgets(node.data?.widgets);
    if (widgets.length === 0) continue;
    const label = nodeLabel(node);
    for (const widget of widgets) {
      controls.push({
        id: controlId(node.id, widget.name),
        nodeId: node.id,
        node: label,
        scenario: scenarioOf.get(node.id) ?? null,
        name: widget.name,
        label: widget.label || widget.name,
        type: widget.type,
        options: widget.options ?? {},
        value: effectiveValue(widget),
      });
    }
  }
  return controls;
}

export interface AppliedChanges {
  /** Each changed node's widgets, as they are written. */
  widgetsByNode: Map<string, WidgetDef[]>;
  /** What changed, for the transcript. */
  applied: { id: string; nodeId: string; label: string; scenario: string | null; from: WidgetValue; to: WidgetValue }[];
  /** Changes that could not be made, and why. */
  skipped: { id: string; problem: string }[];
}

/** The widget lists *changes* make of the nodes as they are now. */
export function applyAgentChanges(
  nodes: readonly NodeLike[],
  controls: readonly AgentControl[],
  changes: readonly AgentChange[],
): AppliedChanges {
  const byId = new Map(controls.map((control) => [control.id, control]));
  const nodeById = new Map(nodes.map((node) => [node.id, node]));
  const widgetsByNode = new Map<string, WidgetDef[]>();
  const applied: AppliedChanges["applied"] = [];
  const skipped: AppliedChanges["skipped"] = [];
  for (const change of changes) {
    const control = byId.get(change.id);
    const node = control ? nodeById.get(control.nodeId) : undefined;
    if (!control || !node) {
      skipped.push({ id: change.id, problem: "The dashboard has no such control." });
      continue;
    }
    const current = widgetsByNode.get(node.id) ?? normalizeWidgets(node.data?.widgets);
    const widget = current.find((w) => w.name === control.name);
    if (!widget) {
      skipped.push({ id: change.id, problem: "That widget is no longer on its node." });
      continue;
    }
    const problem = checkWidgetValue(widget, change.value);
    if (problem) {
      skipped.push({ id: change.id, problem });
      continue;
    }
    widgetsByNode.set(node.id, current.map((w) => (w.name === widget.name ? { ...w, value: change.value } : w)));
    applied.push({
      id: control.id,
      nodeId: node.id,
      label: control.label,
      scenario: control.scenario,
      from: effectiveValue(widget),
      to: change.value,
    });
  }
  return { widgetsByNode, applied, skipped };
}

/** A value as the transcript shows it. */
export function formatValue(value: WidgetValue): string {
  if (value === null || value === undefined) return "nothing";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}
