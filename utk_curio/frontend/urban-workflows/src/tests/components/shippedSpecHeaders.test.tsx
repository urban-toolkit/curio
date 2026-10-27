/**
 * Every chip a shipped spec writes is in its node's header (#662).
 *
 * Covered: each Vega-Lite and Autark node of every dataflow in docs/examples,
 * its header built as the canvas builds it (the node's edges, the boxes its
 * inputs come from, its widgets and selection tags), and Scout's 15 chart
 * templates, each with its manifest's widgets, on two inputs from two boxes. A node's or a template's kind is read from the
 * package manifests: a template that draws with the Vega-Lite grammar
 * (`grammarId`), or with the Autark grammar's behavior.
 *
 * The rule: the header's categories start closed, and with a chip's category
 * open the header lists a tag that drags that same chip. Layer and column chips
 * are left to referenceStripInputs and scenarioTags, since their tags list only
 * once the input has run; a node whose chips are all such is left out.
 */
import * as fs from "fs";
import * as path from "path";
import React from "react";
import { cleanup, fireEvent, render } from "@testing-library/react";
import { ReferenceStrip } from "../../components/editing/widgets/WidgetTag";
import {
  STACKED_FIELDS,
  VEGA_LITE,
  findReferences,
  parseReference,
  referenceText,
  type InputScope,
  type ParsedReference,
} from "../../utils/references/codeReferences";
import { inputScopeFor } from "../../utils/references/inputScope";
import { normalizeSelections } from "../../utils/references/selectionTags";
import { inputScenarios } from "../../utils/scenarios/inputScenarios";
import { normalizeScenarios } from "../../utils/scenarios/scenarioModel";
import { normalizeWidgets, type WidgetDef } from "../../utils/widgets/widgetModel";
import type { SelectionTag } from "../../utils/references/selectionTags";
import { REPO_ROOT } from "../_support/workflowPaths";
import { draggedText, headerRow, openCategory, type StripCategory } from "../_support/stripCategories";

const EXAMPLES = path.join(REPO_ROOT, "docs", "examples");
const PACKAGES = path.join(REPO_ROOT, "packages");
const SCOUT = path.join(PACKAGES, "curio.scout@1");

const isObject = (value: unknown): value is Record<string, any> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

const relative = (file: string) => path.relative(REPO_ROOT, file).split(path.sep).join("/");

const unversioned = (type: unknown) => String(type ?? "").replace(/@\d+$/, "");

const jsonFiles = (dir: string): string[] =>
  fs.existsSync(dir) ? fs.readdirSync(dir).filter((name) => name.endsWith(".json")).map((name) => path.join(dir, name)) : [];

/** The node types that draw with each grammar, from every package manifest. */
function grammarTypes(): { vegaLite: Set<string>; autark: Set<string> } {
  const vegaLite = new Set<string>();
  const autark = new Set<string>();
  for (const dir of fs.readdirSync(PACKAGES)) {
    const manifest = path.join(PACKAGES, dir, "manifest.json");
    if (!fs.existsSync(manifest)) continue;
    const doc = JSON.parse(fs.readFileSync(manifest, "utf-8"));
    for (const template of Array.isArray(doc.templates) ? doc.templates : []) {
      if (template?.grammarId === VEGA_LITE) vegaLite.add(`${doc.id}/${template.id}`);
      else if (template?.behavior === "autk-grammar") autark.add(`${doc.id}/${template.id}`);
    }
  }
  return { vegaLite, autark };
}

/** Where the header lists *parsed*'s tag: its category and the tag there. "left out" for a layer or a column chip. */
type Place = { category: StripCategory; selector: string; field?: boolean } | "left out" | null;

function placeOf(parsed: ParsedReference): Place {
  switch (parsed.kind) {
    case "widget":
      return { category: "widgets", selector: `[data-widget-tag="${parsed.name}"]` };
    case "selection":
      return { category: "selections", selector: `[data-selection-tag="${parsed.name}"]` };
    case "input":
      if (parsed.layer !== undefined || parsed.column !== undefined) return "left out";
      return parsed.slot === null ? null : { category: "inputs", selector: `[data-input-tag="${parsed.slot}"]` };
    case "dataset":
      return { category: "inputs", selector: "[data-inputs-tag]" };
    case "stacked":
      // The stacking's own fields list before any input has run; the others are columns.
      return (STACKED_FIELDS as readonly string[]).includes(parsed.column)
        ? { category: "inputs", selector: `[data-inputs-field="${parsed.column}"]`, field: true }
        : "left out";
    case "scenario":
      if (parsed.chip === "colors") return { category: "scenarios", selector: "[data-scenario-swatches]" };
      if (parsed.chip === "text_colors" || parsed.chip === "order") {
        return { category: "scenarios", selector: `[data-scenario-chip="${parsed.chip}"]` };
      }
      if (parsed.chip === "input" && parsed.slot !== null) {
        return { category: "scenarios", selector: `[data-scenario-input="${parsed.slot}"]` };
      }
      return null;
  }
  return null;
}

interface HeaderCase {
  name: string;
  code: string;
  props: {
    nodeId: string;
    widgets: WidgetDef[];
    inputs: InputScope[];
    selections: SelectionTag[];
    grammar?: string;
  };
}

/** Whether *code* writes a chip the rule checks. */
const checksAChip = (code: string) => findReferences(code).some((ref) => placeOf(parseReference(ref.inner)) !== "left out");

/** Each Vega-Lite and Autark node of every shipped dataflow, as its header is built on the canvas. */
function dataflowCases(): HeaderCase[] {
  const { vegaLite, autark } = grammarTypes();
  const files = [...jsonFiles(EXAMPLES), ...jsonFiles(path.join(EXAMPLES, "dataflows"))];
  const cases: HeaderCase[] = [];
  for (const file of files) {
    const doc = JSON.parse(fs.readFileSync(file, "utf-8"));
    const flow = doc?.dataflow;
    if (!isObject(flow) || !Array.isArray(flow.nodes)) continue;
    const nodes = flow.nodes as any[];
    const edges = (Array.isArray(flow.edges) ? flow.edges : []) as any[];
    // As the canvas holds them: a node's title is what an input's label names.
    const canvasNodes = nodes.map((node) => ({ id: node.id, type: node.type, data: { title: node.title, nodeType: node.type } }));
    const scenarios = normalizeScenarios(flow.scenarios, nodes.map((node) => node.id));
    for (const node of nodes) {
      const type = unversioned(node.type);
      if (!vegaLite.has(type) && !autark.has(type)) continue;
      const code = typeof node.content === "string" ? node.content : "";
      if (!checksAChip(code)) continue;
      const labels = new Map(
        inputScenarios(node.id, canvasNodes, edges, scenarios).map((input) => [input.slot, input.label]),
      );
      const inputs = inputScopeFor(node.id, edges, canvasNodes, () => undefined, (data) => data?.title ?? null, () => undefined)
        .map((input) => (labels.has(input.slot) ? { ...input, scenario: labels.get(input.slot) } : input));
      cases.push({
        // The whole id: some dataflows' ids share their first characters.
        name: `${relative(file)}, ${node.title ?? type} (${node.id})`,
        code,
        props: {
          nodeId: `${relative(file)}:${node.id}`,
          widgets: normalizeWidgets(node.metadata?.widgets),
          inputs,
          selections: normalizeSelections(node.metadata?.selections),
          grammar: vegaLite.has(type) ? VEGA_LITE : undefined,
        },
      });
    }
  }
  return cases;
}

/** Two inputs, each from its own box, as a chart dropped after two scenarios gets them. */
const TWO_BOXED: InputScope[] = [
  { slot: 0, label: "Shadow", scenario: { scenario: "existing", name: "Existing", color: "#2a9d8f", rank: 0 } },
  { slot: 1, label: "Shadow", scenario: { scenario: "towers-removed", name: "Towers removed", color: "#e76f51", rank: 1 } },
];

/** Scout's chart templates, each with its manifest's widgets, on two boxed inputs. */
function templateCases(): HeaderCase[] {
  const manifest = JSON.parse(fs.readFileSync(path.join(SCOUT, "manifest.json"), "utf-8"));
  return (manifest.templates as any[])
    .filter((template) => template.grammarId === VEGA_LITE)
    .map((template) => ({
      name: `packages/curio.scout@1/${template.source}`,
      code: fs.readFileSync(path.join(SCOUT, template.source), "utf-8"),
      props: {
        nodeId: `curio.scout/${template.id}`,
        widgets: normalizeWidgets(template.widgets),
        inputs: TWO_BOXED,
        selections: [],
        grammar: VEGA_LITE,
      },
    }));
}

const DATAFLOW_CASES = dataflowCases();
const TEMPLATE_CASES = templateCases();

afterEach(cleanup);

test("the cases are the shipped specs that write chips: several dataflows' nodes and Scout's 15 charts", () => {
  expect(TEMPLATE_CASES).toHaveLength(15);
  expect(TEMPLATE_CASES.every((entry) => entry.code.includes("[!! inputs !!]"))).toBe(true);
  expect(DATAFLOW_CASES.length).toBeGreaterThan(20);
  expect(DATAFLOW_CASES.some((entry) => entry.props.grammar === undefined)).toBe(true);
  expect(DATAFLOW_CASES.some((entry) => entry.code.includes("[!! scenario "))).toBe(true);
});

test.each([...DATAFLOW_CASES, ...TEMPLATE_CASES].map((entry) => [entry.name, entry] as const))(
  "%s: every chip its spec writes is in its header, and drags that chip",
  (_name, entry) => {
    const view = render(<ReferenceStrip {...entry.props} language="json" onInsert={() => {}} />);
    const row = headerRow(view.container);
    expect(row.length).toBeGreaterThan(0);
    expect(row.filter((category) => category.open)).toEqual([]);
    const missing: string[] = [];
    for (const ref of findReferences(entry.code)) {
      const written = referenceText(ref.inner);
      const place = placeOf(parseReference(ref.inner));
      if (place === "left out") continue;
      if (place === null) {
        missing.push(`${written}: no tag can drag it`);
        continue;
      }
      if (!row.some((category) => category.category === place.category)) {
        missing.push(`${written}: the header has no ${place.category} category`);
        continue;
      }
      const chips = openCategory(view.container, place.category);
      if (place.field) {
        const fields = chips.querySelector('[aria-label="Show the fields of inputs"]');
        if (fields) fireEvent.click(fields);
      }
      const tag = chips.querySelector(place.selector);
      if (!tag) {
        missing.push(`${written}: no ${place.selector} under ${place.category}`);
        continue;
      }
      const dragged = draggedText(tag);
      if (dragged !== written) missing.push(`${written}: its tag under ${place.category} drags ${dragged}`);
    }
    expect(missing).toEqual([]);
  },
);
