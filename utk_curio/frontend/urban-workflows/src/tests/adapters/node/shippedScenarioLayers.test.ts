/**
 * Every shipped map layer drawn in a scenario box's color (#662): on a map
 * outside every box, a layer whose input comes from a node in a box takes the
 * box's color (adapters/node/autkScenarioColors), unless it is colored by its
 * values. Over every dataflow in docs/examples, that rule recolors exactly the
 * routing example's two routes, each in the box its retired `scenario` key
 * named, so no other shipped map changes color, and no shipped layer from a
 * box keeps its values' colors. A layer on such a map whose input cannot be
 * told from its document counts as recolored, so a new one is looked at here.
 *
 * Curio's `scenario` layer key is gone: no shipped document, dataflow or
 * package file, writes it.
 */
import * as fs from "fs";
import * as path from "path";
import { REPO_ROOT } from "../../_support/workflowPaths";
import { layerScenarios, withScenarioColors } from "../../../adapters/node/autkScenarioColors";
import { normalizeScenarios } from "../../../utils/scenarios/scenarioModel";

const EXAMPLES = path.join(REPO_ROOT, "docs", "examples");
const PACKAGES = path.join(REPO_ROOT, "packages");
/** An input chip as a document writes it: `[!! input_1 !!]`, or a layer of it, `[!! input_1:roads !!]`. */
const CHIP = /^\[!!\s*input_(\d+)(?::([^.\s]+))?\s*!!\]$/;
const PLAIN = /^input_(\d+)$/;

type Recolored = { file: string; node: string; layer: string; box: string | null };

const isObject = (value: unknown): value is Record<string, any> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

const relative = (file: string) => path.relative(REPO_ROOT, file).split(path.sep).join("/");

const jsonFiles = (dir: string): string[] =>
  fs.existsSync(dir) ? fs.readdirSync(dir).filter((name) => name.endsWith(".json")).map((name) => path.join(dir, name)) : [];

/** Every shipped dataflow: the gallery's and the test dataflows. */
function dataflows(): Array<{ file: string; flow: any }> {
  return [...jsonFiles(EXAMPLES), ...jsonFiles(path.join(EXAMPLES, "dataflows"))]
    .map((file) => ({ file, doc: JSON.parse(fs.readFileSync(file, "utf-8")) }))
    .filter(({ doc }) => isObject(doc?.dataflow) && Array.isArray(doc.dataflow.nodes))
    .map(({ file, doc }) => ({ file, flow: doc.dataflow }));
}

/** The node types that draw with the Autark grammar's behavior, from every package manifest. */
function autarkTypes(): Set<string> {
  const types = new Set<string>();
  for (const dir of fs.readdirSync(PACKAGES)) {
    const manifest = path.join(PACKAGES, dir, "manifest.json");
    if (!fs.existsSync(manifest)) continue;
    const doc = JSON.parse(fs.readFileSync(manifest, "utf-8"));
    for (const template of Array.isArray(doc.templates) ? doc.templates : []) {
      if (template?.behavior === "autk-grammar") types.add(`${doc.id}/${template.id}`);
    }
  }
  return types;
}

const unversioned = (type: unknown) => String(type ?? "").replace(/@\d+$/, "");

/** A document's layers, each map's. */
function layersOf(doc: any): any[] {
  const maps = Array.isArray(doc?.map) ? doc.map : doc?.map ? [doc.map] : [];
  return maps.flatMap((map: any) => (Array.isArray(map?.layerRefs) ? map.layerRefs : []));
}

/** Every layerRef anywhere in *value*. */
function layerRefsIn(value: unknown): any[] {
  if (Array.isArray(value)) return value.flatMap(layerRefsIn);
  if (!isObject(value)) return [];
  const own = Array.isArray(value.layerRefs) ? value.layerRefs : [];
  return [...own, ...Object.values(value).flatMap(layerRefsIn)];
}

/** *text* as JSON, or nothing. */
function parsed(text: unknown): unknown {
  if (typeof text !== "string") return null;
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/** The circle a node's edge lands on: its handle, `in` for circle 0, `in_k` for circle k. */
function slotOf(edge: any): number {
  const handle = edge.targetHandle ?? (typeof edge.id === "string" ? edge.id.match(/(in(?:_\d+)?)$/)?.[1] : null) ?? "in";
  if (handle === "in") return 0;
  const match = /^in_(\d+)$/.exec(handle);
  return match ? Number(match[1]) : -1;
}

/** The layers the rule recolors in one dataflow, with the box each takes; and,
 * in *kept*, those whose input comes from a box that keep their own colors. */
function recoloredIn(file: string, flow: any, autark: Set<string>, kept: Recolored[] = []): Recolored[] {
  const nodes = flow.nodes.map((node: any) => ({ id: node.id, type: node.type, data: { nodeType: node.type, title: node.title } }));
  const edges = (flow.edges ?? [])
    .filter((edge: any) => edge.type !== "Interaction")
    .map((edge: any) => ({ ...edge, targetHandle: slotOf(edge) === 0 ? "in" : `in_${slotOf(edge)}` }));
  const scenarios = normalizeScenarios(flow.scenarios, nodes.map((node: any) => node.id));
  const found: Recolored[] = [];
  for (const node of flow.nodes) {
    if (!autark.has(unversioned(node.type))) continue;
    const doc = parsed(node.content);
    const layers = layersOf(doc);
    if (layers.length === 0) continue;
    const wired = edges.filter((edge: any) => edge.target === node.id);
    // The table each layer reads, as its chip resolves, and the circle that table came in on.
    const circles: Record<string, number> = {};
    const resolved = layers.map((layer: any) => {
      const ref = String(layer?.dataRef ?? "");
      const chip = CHIP.exec(ref);
      if (chip) {
        const table = chip[2] ?? `input_${chip[1]}`;
        circles[table] = Number(chip[1]);
        return { ...layer, dataRef: table };
      }
      const plain = PLAIN.exec(ref);
      if (plain) circles[ref] = Number(plain[1]);
      // A layer of the one input a node of one circle reads.
      else if (wired.length === 1) circles[ref] = 0;
      return layer;
    });
    const scenarioOf = layerScenarios(node.id, nodes, edges, scenarios, circles);
    const colored = layersOf(withScenarioColors({ map: { layerRefs: resolved } }, scenarioOf));
    // Fail closed: on a map outside every box that a box feeds, a layer whose
    // input this cannot tell is listed, with no box.
    const inBox = scenarios.some((scenario) => scenario.nodes.includes(node.id));
    const fedByBox = !inBox && wired.some((edge: any) => scenarios.some((scenario) => scenario.nodes.includes(edge.source)));
    resolved.forEach((layer: any, i: number) => {
      const box = scenarioOf(layer.dataRef);
      if (box && colored[i] !== layer) {
        expect(colored[i]).toEqual({ ...layer, color: box.color });
        found.push({ file: relative(file), node: node.id, layer: layers[i].dataRef, box: box.id });
      } else if (box) {
        kept.push({ file: relative(file), node: node.id, layer: layers[i].dataRef, box: box.id });
      } else if (fedByBox && !(layer.dataRef in circles)) {
        found.push({ file: relative(file), node: node.id, layer: layers[i].dataRef, box: null });
      }
    });
  }
  return found;
}

const ROUTING = "docs/examples/dataflows/chicago-rain-wind-routing.json";
const ROUTES_MAP = "6c0e8a4d-3b9f-4d21-a7e5-9f2b6d1c8e40";

test("the rule recolors exactly the routing example's two routes, each in the box its old key named", () => {
  const autark = autarkTypes();
  expect(autark.has("curio.builtin/autk-grammar")).toBe(true);
  const kept: Recolored[] = [];
  const found = dataflows().flatMap(({ file, flow }) => recoloredIn(file, flow, autark, kept));
  expect(found).toEqual([
    { file: ROUTING, node: ROUTES_MAP, layer: "[!! input_1 !!]", box: "fastest" },
    { file: ROUTING, node: ROUTES_MAP, layer: "[!! input_2 !!]", box: "weather-aware" },
  ]);
  // No shipped layer from a box is colored by its values.
  expect(kept).toEqual([]);
});

test("no shipped layer writes Curio's old scenario key", () => {
  const keyed: string[] = [];
  for (const { file, flow } of dataflows()) {
    for (const node of flow.nodes) {
      for (const layer of layerRefsIn(parsed(node.content))) {
        if (isObject(layer) && "scenario" in layer) keyed.push(`${relative(file)} ${node.id} ${layer.dataRef}`);
      }
    }
  }
  for (const dir of fs.readdirSync(PACKAGES)) {
    const files = [path.join(PACKAGES, dir, "manifest.json"), ...jsonFiles(path.join(PACKAGES, dir, "sources"))];
    for (const file of files.filter((one) => fs.existsSync(one))) {
      const doc = parsed(fs.readFileSync(file, "utf-8"));
      const inStrings: unknown[] = [];
      const walk = (value: unknown) => {
        if (typeof value === "string" && value.includes("layerRefs")) inStrings.push(parsed(value));
        else if (Array.isArray(value)) value.forEach(walk);
        else if (isObject(value)) Object.values(value).forEach(walk);
      };
      walk(doc);
      for (const layer of [...layerRefsIn(doc), ...inStrings.flatMap(layerRefsIn)]) {
        if (isObject(layer) && "scenario" in layer) keyed.push(`${relative(file)} ${layer.dataRef}`);
      }
    }
  }
  expect(keyed).toEqual([]);
});
