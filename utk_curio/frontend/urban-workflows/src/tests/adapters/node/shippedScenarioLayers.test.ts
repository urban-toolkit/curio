/**
 * Every shipped map layer drawn in a scenario box's color (#662). A map draws
 * its layers as its document writes them: a layer in its scenario's color
 * writes its input's scenario chip, `"color": "[!! scenario input_1 !!]"`,
 * which the editor resolves to the color of the box that input comes from
 * (utils/references/codeReferences). Over every dataflow in docs/examples, the
 * maps that write one are the routing example's alone, its two routes, each
 * writing its own input's: the two layers Curio's hidden recolor drew in their
 * boxes' colors before the chips, so no shipped map changes color.
 *
 * Curio's `scenario` layer key is gone: no shipped document, dataflow or
 * package file, writes it.
 */
import * as fs from "fs";
import * as path from "path";
import { REPO_ROOT } from "../../_support/workflowPaths";

const EXAMPLES = path.join(REPO_ROOT, "docs", "examples");
const PACKAGES = path.join(REPO_ROOT, "packages");

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

const ROUTING = "docs/examples/dataflows/chicago-rain-wind-routing.json";
const ROUTES_MAP = "6c0e8a4d-3b9f-4d21-a7e5-9f2b6d1c8e40";

test("the shipped maps that write a scenario chip are the routing map alone, each route writing its own input's", () => {
  const autark = autarkTypes();
  expect(autark.has("curio.builtin/autk-grammar")).toBe(true);
  const chip = /\[!!\s*scenario\s+[^\]]*?\s*!!\]/g;
  const written: string[] = [];
  for (const { file, flow } of dataflows()) {
    for (const node of flow.nodes) {
      if (!autark.has(unversioned(node.type)) || typeof node.content !== "string") continue;
      for (const match of node.content.matchAll(chip)) written.push(`${relative(file)} ${node.id} ${match[0]}`);
    }
  }
  expect(written).toEqual([
    `${ROUTING} ${ROUTES_MAP} [!! scenario input_1 !!]`,
    `${ROUTING} ${ROUTES_MAP} [!! scenario input_2 !!]`,
  ]);
  // Each on its route's layer, inside the color's quotes.
  const routes = layersOf(parsed(dataflows().find(({ file }) => relative(file) === ROUTING)!.flow.nodes
    .find((node: any) => node.id === ROUTES_MAP).content));
  expect(routes.map((layer: any) => [layer.dataRef, layer.color])).toEqual([
    ["[!! input_0 !!]", undefined],
    ["[!! input_1 !!]", "[!! scenario input_1 !!]"],
    ["[!! input_2 !!]", "[!! scenario input_2 !!]"],
  ]);
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
