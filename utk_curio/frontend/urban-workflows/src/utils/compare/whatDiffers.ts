/**
 * What a Compare Scenarios node (#662) says about the scenarios it compares,
 * read from the live graph through each scenario's parts (`scenarioParts`):
 *
 * - **What differs:** the levers that differ, paired by lineage. A lever is
 *   known by its own id and its `copiedFrom` list (`duplicateSelection`
 *   writes it); two levers are the same lever in two scenarios when these
 *   meet. A paired lever differs in its
 *   widget values and in its code lines, an Edit Features lever in its edit
 *   list (its code is written from it); one with no partner is listed as only
 *   in the scenarios that have it, with its edits when it is an Edit Features
 *   node.
 * - **Context:** a warning, naming the inputs, when the scenarios read
 *   different fixed context, so their outcomes may differ for reasons outside
 *   them.
 *
 * The first scenario among the inputs is the reference the others are read
 * against.
 */
import { scenarioParts } from "../scenarios/scenarioParts";
import type { Scenario } from "../scenarios/scenarioModel";
import { lineageFromSpec } from "../scenarios/duplicateSelection";
import { effectiveValue, normalizeWidgets, type WidgetValue } from "../widgets/widgetModel";
import { nodeCode } from "../references/sharedParameters";
import { nodeLabel } from "../../components/scenarios/scenarioLabels";
import { listOf, type CompareInput } from "./compareInputs";
import { describeEdit, isEditFeaturesNode, normalizeEditFeatures } from "../editFeatures/editFeatures";

type FlowNodeLike = { id: string; type?: string | null; data?: any };
type FlowEdgeLike = {
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

/** A scenario a node compares, with the circle of its first input. */
export interface ComparedScenario {
  slot: number;
  scenario: Scenario;
}

/** The scenarios among *inputs*, each once, in circle order. */
export function comparedScenarios(inputs: readonly CompareInput[]): ComparedScenario[] {
  const seen = new Set<string>();
  const out: ComparedScenario[] = [];
  for (const input of inputs) {
    if (input.scenario === null || seen.has(input.scenario.id)) continue;
    seen.add(input.scenario.id);
    out.push({ slot: input.slot, scenario: input.scenario });
  }
  return out;
}

/** A node's own id, then the ids it descends from. */
export function lineageKeys(node: FlowNodeLike): string[] {
  return [node.id, ...lineageFromSpec(node.data?.copiedFrom)];
}

/**
 * The levers of *groups* (one list per scenario) that are one lever, paired by
 * lineage: each group holds, per scenario, the ids of its nodes in that lever,
 * in scenario order. Levers meet through any shared id, so a copy of a copy
 * pairs with its original's copy too.
 */
export function pairLevers(groups: readonly { scenarioId: string; levers: readonly FlowNodeLike[] }[]): Map<string, string[]>[] {
  const parent = new Map<string, string>();
  const find = (id: string): string => {
    let root = id;
    while (parent.get(root) !== root) root = parent.get(root)!;
    parent.set(id, root);
    return root;
  };
  const owner = new Map<string, string>();
  const order: string[] = [];
  for (const { levers } of groups) {
    for (const node of levers) {
      if (parent.has(node.id)) continue;
      parent.set(node.id, node.id);
      order.push(node.id);
      for (const key of lineageKeys(node)) {
        const seen = owner.get(key);
        if (seen === undefined) owner.set(key, node.id);
        else parent.set(find(node.id), find(seen));
      }
    }
  }
  const scenarioOf = new Map<string, string>();
  for (const { scenarioId, levers } of groups) for (const node of levers) scenarioOf.set(node.id, scenarioId);

  const byRoot = new Map<string, Map<string, string[]>>();
  for (const id of order) {
    const root = find(id);
    const members = byRoot.get(root) ?? new Map<string, string[]>();
    const scenarioId = scenarioOf.get(id)!;
    members.set(scenarioId, [...(members.get(scenarioId) ?? []), id]);
    byRoot.set(root, members);
  }
  return [...byRoot.values()];
}

/** The lines of *before* and *after* that are not common to both, in order. */
export function changedLines(before: string, after: string): { removed: string[]; added: string[] } {
  const a = before.split("\n").map((line) => line.replace(/\r$/, ""));
  const b = after.split("\n").map((line) => line.replace(/\r$/, ""));
  if (a.length * b.length > 250_000) {
    // Too long to align: what each holds that the other does not.
    const inB = new Set(b);
    const inA = new Set(a);
    return { removed: a.filter((line) => !inB.has(line)), added: b.filter((line) => !inA.has(line)) };
  }
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const removed: string[] = [];
  const added: string[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      i += 1;
      j += 1;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      removed.push(a[i]);
      i += 1;
    } else {
      added.push(b[j]);
      j += 1;
    }
  }
  removed.push(...a.slice(i));
  added.push(...b.slice(j));
  return { removed, added };
}

export interface WidgetChange {
  name: string;
  /** Each scenario's value, in the compared order; undefined where its lever has no such widget. */
  values: { scenarioId: string; value: WidgetValue | undefined }[];
}

export interface CodeChange {
  /** The scenario whose code is read against the reference's. */
  scenarioId: string;
  removed: string[];
  added: string[];
}

export interface EditsChange {
  scenarioId: string;
  /** Its Edit Features node's edits, each in a line, in the order they apply. */
  edits: string[];
}

export interface LeverDifference {
  /** A stable key: the lever's first node id. */
  key: string;
  label: string;
  /** The scenarios that have this lever, when some do not. */
  onlyIn?: string[];
  widgets: WidgetChange[];
  code: CodeChange[];
  /** An Edit Features lever's edits, per scenario, when they differ or only some have it. */
  edits?: EditsChange[];
}

export interface WhatDiffers {
  differences: LeverDifference[];
  /** Levers every compared scenario has, alike in their widgets and code. */
  same: number;
}

/** An Edit Features node's edits, a line each (none for another node). */
function editLines(node: FlowNodeLike | undefined): string[] {
  if (!node || !isEditFeaturesNode(node)) return [];
  const settings = normalizeEditFeatures(node.data?.editFeatures);
  return (settings?.edits ?? []).map((edit) => describeEdit(edit, settings?.key));
}

function widgetValues(node: FlowNodeLike): Map<string, WidgetValue> {
  return new Map(normalizeWidgets(node.data?.widgets).map((widget) => [widget.name, effectiveValue(widget)]));
}

/** The levers that differ between the *compared* scenarios. */
export function whatDiffers(
  compared: readonly ComparedScenario[],
  nodes: readonly FlowNodeLike[],
  edges: readonly FlowEdgeLike[],
): WhatDiffers {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const groups = compared.map(({ scenario }) => ({
    scenarioId: scenario.id,
    levers: scenarioParts(scenario, nodes, edges).levers.map((id) => byId.get(id)!),
  }));
  const differences: LeverDifference[] = [];
  let same = 0;

  for (const members of pairLevers(groups)) {
    const firstIds = compared.map(({ scenario }) => members.get(scenario.id)?.[0]);
    const present = compared.filter((_, i) => firstIds[i] !== undefined).map(({ scenario }) => scenario.id);
    const key = [...members.values()][0][0];
    const label = nodeLabel(byId.get(firstIds.find((id) => id !== undefined) ?? key), key);
    if (present.length < compared.length) {
      const edits = compared.flatMap(({ scenario }, i) => {
        const node = firstIds[i] !== undefined ? byId.get(firstIds[i]!) : undefined;
        const lines = editLines(node);
        return node && isEditFeaturesNode(node) && lines.length > 0 ? [{ scenarioId: scenario.id, edits: lines }] : [];
      });
      differences.push({ key, label, onlyIn: present, widgets: [], code: [], ...(edits.length > 0 ? { edits } : {}) });
      continue;
    }
    const levers = firstIds.map((id) => byId.get(id!)!);
    if (levers.every((lever) => isEditFeaturesNode(lever))) {
      // Its code is written from its edit list: the list is what differs.
      const lists = levers.map((lever) => JSON.stringify(normalizeEditFeatures(lever.data?.editFeatures) ?? null));
      if (lists.every((list) => list === lists[0])) {
        same += 1;
        continue;
      }
      const edits = compared.map(({ scenario }, i) => ({ scenarioId: scenario.id, edits: editLines(levers[i]) }));
      differences.push({ key, label, widgets: [], code: [], edits });
      continue;
    }
    const values = levers.map(widgetValues);
    const names: string[] = [];
    for (const map of values) for (const name of map.keys()) if (!names.includes(name)) names.push(name);
    const widgets: WidgetChange[] = [];
    for (const name of names) {
      const shown = values.map((map) => (map.has(name) ? JSON.stringify(map.get(name)) : undefined));
      if (shown.every((text) => text === shown[0])) continue;
      widgets.push({
        name,
        values: compared.map(({ scenario }, i) => ({ scenarioId: scenario.id, value: values[i].get(name) })),
      });
    }
    const reference = nodeCode(levers[0]);
    const code: CodeChange[] = [];
    levers.slice(1).forEach((lever, i) => {
      const { removed, added } = changedLines(reference, nodeCode(lever));
      if (removed.length > 0 || added.length > 0) {
        code.push({ scenarioId: compared[i + 1].scenario.id, removed, added });
      }
    });
    if (widgets.length === 0 && code.length === 0) same += 1;
    else differences.push({ key, label, widgets, code });
  }
  return { differences, same };
}

/** Each node's name, with its id's start when another node shares the name. */
function namesOf(ids: readonly string[], nodes: readonly FlowNodeLike[]): string[] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const counts = new Map<string, number>();
  for (const node of nodes) {
    const name = nodeLabel(node, node.id);
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return ids.map((id) => {
    const name = nodeLabel(byId.get(id), id);
    return (counts.get(name) ?? 0) > 1 ? `${name} (${id.slice(0, 4)})` : name;
  });
}

/**
 * Why the *compared* scenarios' outcomes may differ for reasons outside them:
 * one sentence for each scenario whose fixed context is not the reference's,
 * naming both inputs and the context only one of them reads. Empty when they
 * all read the same context.
 */
export function contextWarnings(
  compared: readonly ComparedScenario[],
  nodes: readonly FlowNodeLike[],
  edges: readonly FlowEdgeLike[],
): string[] {
  if (compared.length < 2) return [];
  const contexts = compared.map(({ scenario }) => scenarioParts(scenario, nodes, edges).context);
  const [reference, ...rest] = compared;
  const warnings: string[] = [];
  rest.forEach((other, i) => {
    const mine = new Set(contexts[i + 1]);
    const theirs = new Set(contexts[0]);
    const onlyMine = contexts[i + 1].filter((id) => !theirs.has(id));
    const onlyTheirs = contexts[0].filter((id) => !mine.has(id));
    if (onlyMine.length === 0 && onlyTheirs.length === 0) return;
    const parts: string[] = [];
    if (onlyMine.length > 0) parts.push(`only input_${other.slot} reads ${listOf(namesOf(onlyMine, nodes))}`);
    if (onlyTheirs.length > 0) parts.push(`only input_${reference.slot} reads ${listOf(namesOf(onlyTheirs, nodes))}`);
    warnings.push(
      `input_${other.slot} (${other.scenario.name}) and input_${reference.slot} (${reference.scenario.name}) read different context: ${parts.join("; ")}.`,
    );
  });
  return warnings;
}
