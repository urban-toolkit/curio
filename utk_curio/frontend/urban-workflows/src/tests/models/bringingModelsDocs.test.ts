/**
 * Does docs/BRINGING-MODELS.md name only what exists?
 *
 * The guide takes a model from PyTorch or TensorFlow to a model package and
 * the node that runs it. Here every link it gives reaches a file and every
 * anchor a heading; every manifest field, widget field, widget kind and widget
 * option it names is in docs/schemas/node-package.v4.json; every helper it
 * names is one node code gets; its worked example shows the Local Relief
 * package's own code, manifest and widget; the widgets it lists for the
 * shipped models are theirs; and the SCOUT results it states are the ones the
 * SCOUT tests pin. The backend suite runs in the CI image, which ships no
 * guides, so this check lives here.
 */
import * as fs from "fs";
import * as path from "path";

import { WIDGET_KINDS, checkWidgetDef } from "../../utils/widgets/widgetModel";

const REPO_ROOT = path.join(__dirname, "..", "..", "..", "..", "..", "..");
const DOCS = path.join(REPO_ROOT, "docs");
const GUIDE = path.join(DOCS, "BRINGING-MODELS.md");
const SCHEMA = path.join(DOCS, "schemas", "node-package.v4.json");
const LOCAL_RELIEF = path.join(DOCS, "bring-your-own-model", "model.example.local-relief@1");
const PACKAGE_TESTS = path.join(REPO_ROOT, "utk_curio", "backend", "tests", "test_packages");
/** Where node code's helpers are defined. */
const HELPER_SOURCES = [
  "utk_curio/sandbox/util/catalog_helpers.py",
  "utk_curio/sandbox/util/collections.py",
  "utk_curio/sandbox/util/vision.py",
  "utk_curio/sandbox/app/worker.py",
];
/** What the guide must not name: APIs, fields and files that do not exist. */
const GONE = [
  "model.entry",
  "curio_save_",
  "curio_computed_path",
  "--models-root",
  "CURIO_MODELS_ROOT",
  "legendTitle",
  "`task`",
  "\"task\"",
  "within 1 gray level",
  "scout.shadow@1",
  "scout.routing@1",
  "mosaic.py",
  "test_bring_your_own_model",
];

type Json = null | boolean | number | string | Json[] | { [key: string]: Json };

function read(file: string): string {
  return fs.readFileSync(file, "utf-8");
}

function guide(): string {
  return read(GUIDE);
}

function readJson(file: string): { [key: string]: Json } {
  return JSON.parse(read(file));
}

function schemaDefs(): { [key: string]: { [key: string]: Json } } {
  return readJson(SCHEMA)["$defs"] as { [key: string]: { [key: string]: Json } };
}

function propertyNames(def: { [key: string]: Json }): string[] {
  return Object.keys(def["properties"] as { [key: string]: Json });
}

/** The lines of *text*, each with whether it is inside a fenced code block. */
function linesWithFences(text: string): Array<{ line: string; inCode: boolean }> {
  let inCode = false;
  return text.split("\n").map((line) => {
    if (line.trimStart().startsWith("```")) {
      inCode = !inCode;
      return { line, inCode: true };
    }
    return { line, inCode };
  });
}

/** The fenced code blocks of *text*: their language and their body. */
function codeBlocks(text: string): Array<{ lang: string; body: string }> {
  const blocks: Array<{ lang: string; body: string }> = [];
  let current: { lang: string; lines: string[] } | null = null;
  for (const line of text.split("\n")) {
    const fence = line.trimStart();
    if (fence.startsWith("```")) {
      if (current) {
        blocks.push({ lang: current.lang, body: current.lines.join("\n") });
        current = null;
      } else {
        current = { lang: fence.slice(3).trim(), lines: [] };
      }
    } else if (current) {
      current.lines.push(line);
    }
  }
  return blocks;
}

/** The text of *text* outside fenced code blocks. */
function prose(text: string): string {
  return linesWithFences(text).filter((entry) => !entry.inCode).map((entry) => entry.line).join("\n");
}

/** A heading's anchor, as GitHub writes it. */
function slug(heading: string): string {
  return heading.trim().toLowerCase().replace(/[^a-z0-9_\s-]/g, "").replace(/\s/g, "-");
}

/** Every heading anchor of a Markdown file, with GitHub's suffixes for repeats. */
function anchors(text: string): Set<string> {
  const seen = new Map<string, number>();
  const out = new Set<string>();
  for (const { line, inCode } of linesWithFences(text)) {
    const match = !inCode && line.match(/^#{1,6}\s+(.*)$/);
    if (!match) continue;
    const base = slug(match[1]);
    const count = seen.get(base) ?? 0;
    out.add(count === 0 ? base : `${base}-${count}`);
    seen.set(base, count + 1);
  }
  return out;
}

/** The "## " section whose heading matches *title*, up to the next "## " heading. */
function section(text: string, title: RegExp): string {
  const lines = text.split("\n");
  const start = lines.findIndex((line) => line.startsWith("## ") && title.test(line));
  if (start < 0) throw new Error(`BRINGING-MODELS.md has no section ${title}`);
  const rest = lines.slice(start + 1);
  const end = rest.findIndex((line) => line.startsWith("## "));
  return (end < 0 ? rest : rest.slice(0, end)).join("\n");
}

/** The bullets of the list that follows the line matching *intro*, each with
 *  its continuation lines joined. */
function bulletsAfter(text: string, intro: RegExp): string[] {
  const lines = text.split("\n");
  const start = lines.findIndex((line) => intro.test(line));
  if (start < 0) throw new Error(`no list after ${intro}`);
  const bullets: string[] = [];
  for (const line of lines.slice(start + 1)) {
    if (line.startsWith("- ")) bullets.push(line.slice(2));
    else if (line.startsWith("  ") && bullets.length > 0) bullets[bullets.length - 1] += ` ${line.trim()}`;
    else if (line.trim() === "" && bullets.length === 0) continue;
    else break;
  }
  if (bullets.length === 0) throw new Error(`the list after ${intro} is empty`);
  return bullets;
}

/** The names in backticks in *text*. */
function ticked(text: string): string[] {
  return Array.from(text.matchAll(/`([^`]+)`/g), (match) => match[1]);
}

/** The names in backticks before a bullet's first colon: the fields it is about. */
function bulletFields(bullet: string): string[] {
  return ticked(bullet.split(": ")[0]);
}

/** Whether every key and item of *part* is in *whole*, recursively. */
function isDeepSubset(part: Json, whole: Json): boolean {
  if (Array.isArray(part)) {
    if (!Array.isArray(whole) || part.length !== whole.length) return false;
    const items: Json[] = whole;
    return part.every((item, i) => isDeepSubset(item, items[i]));
  }
  if (part !== null && typeof part === "object") {
    if (whole === null || typeof whole !== "object" || Array.isArray(whole)) return false;
    return Object.keys(part).every((key) => key in whole && isDeepSubset(part[key], whole[key]));
  }
  return part === whole;
}

function localReliefManifest(): { [key: string]: Json } {
  return readJson(path.join(LOCAL_RELIEF, "manifest.json"));
}

function firstTemplate(manifest: { [key: string]: Json }): { [key: string]: Json } {
  return (manifest["templates"] as Json[])[0] as { [key: string]: Json };
}

/** A Python constant of a test module, as its source writes it. */
function pythonConstant(source: string, name: string): string {
  const match = source.match(new RegExp(`^${name} = (.+)$`, "m"));
  if (!match) throw new Error(`no ${name} = ... in the test module`);
  return match[1].trim();
}

describe("docs/BRINGING-MODELS.md", () => {
  test("every link reaches a file of the repository, and every anchor a heading", () => {
    const text = guide();
    const own = anchors(text);
    const links = Array.from(prose(text).matchAll(/\]\(([^)\s]+)\)/g), (match) => match[1]);
    expect(links.length).toBeGreaterThan(20);
    const broken: string[] = [];
    for (const link of links) {
      if (/^(https?:|mailto:)/.test(link)) continue;
      const [target, anchor] = link.split("#");
      if (target === "") {
        if (!own.has(anchor)) broken.push(link);
        continue;
      }
      const file = path.resolve(DOCS, decodeURIComponent(target));
      if (!fs.existsSync(file)) {
        broken.push(link);
      } else if (anchor !== undefined && !anchors(read(file)).has(anchor)) {
        broken.push(link);
      }
    }
    expect(broken).toEqual([]);
  });

  test("the model block fields it names are the schema's, the required ones among them", () => {
    const manifest = section(guide(), /Make the model package/);
    const named = bulletsAfter(manifest, /^The `model` block/).flatMap(bulletFields);
    const model = schemaDefs()["model"];
    expect(named.filter((field) => !propertyNames(model).includes(field))).toEqual([]);
    for (const field of model["required"] as string[]) expect(named).toContain(field);
    expect(manifest).toContain('"kind": "model"');
  });

  test("the widget fields it names are the schema's widget's", () => {
    const widgets = section(guide(), /Widgets: what the user sets/);
    const named = bulletsAfter(widgets, /^Each widget has/).flatMap(bulletFields);
    const widget = schemaDefs()["widget"];
    expect(named.filter((field) => !propertyNames(widget).includes(field))).toEqual([]);
    for (const field of widget["required"] as string[]) expect(named).toContain(field);
  });

  test("the widget kinds it names are every kind the schema takes and the Widgets tab offers", () => {
    const widgets = section(guide(), /Widgets: what the user sets/);
    const typeBullet = bulletsAfter(widgets, /^Each widget has/).find((bullet) => bulletFields(bullet)[0] === "type");
    expect(typeBullet).toBeDefined();
    const kinds = ticked((typeBullet as string).split(": ").slice(1).join(": "));
    const widget = schemaDefs()["widget"] as { properties: { type: { enum: string[] } } };
    const schemaKinds = widget.properties.type.enum;
    expect([...kinds].sort()).toEqual([...schemaKinds].sort());
    expect([...WIDGET_KINDS].sort()).toEqual([...schemaKinds].sort());
    expect(typeBullet).toContain(`${schemaKinds.length} kinds`);
  });

  test("the widget options it names are the schema's options", () => {
    const widgets = section(guide(), /Widgets: what the user sets/);
    const optionsBullet = bulletsAfter(widgets, /^Each widget has/).find(
      (bullet) => bulletFields(bullet)[0] === "options",
    );
    expect(optionsBullet).toBeDefined();
    const named = ticked((optionsBullet as string).split(": ").slice(1).join(": "));
    const widget = schemaDefs()["widget"] as {
      properties: {
        type: { enum: string[] };
        options: { properties: { [key: string]: Json; display: { enum: string[] } } };
      };
    };
    const keys = Object.keys(widget.properties.options.properties);
    const displays = widget.properties.options.properties.display.enum;
    const known = new Set([...keys, ...displays, ...widget.properties.type.enum]);
    expect(named.filter((name) => !known.has(name))).toEqual([]);
    for (const name of [...keys, ...displays]) expect(named).toContain(name);
  });

  test("a widget named like an input is refused, as it says", () => {
    const widgets = section(guide(), /Widgets: what the user sets/);
    expect(widgets).toContain("`input_0`");
    expect(checkWidgetDef({ name: "input_0", type: "number", default: 1 }, [])).toBe(
      "input_0 names one of the node's inputs. Pick another name.",
    );
  });

  test("the helpers it names are defined where node code gets them", () => {
    const text = guide();
    const sources = HELPER_SOURCES.map((file) => read(path.join(REPO_ROOT, file))).join("\n");
    const helpers = Array.from(new Set(Array.from(text.matchAll(/\b(curio_[a-z_]+)\(/g), (match) => match[1])));
    expect(helpers).toEqual(expect.arrayContaining(["curio_load_model", "curio_output_file"]));
    expect(helpers.filter((name) => !new RegExp(`def ${name}\\(`).test(sources))).toEqual([]);
    expect(text).toContain("model.run(");
    expect(read(path.join(REPO_ROOT, HELPER_SOURCES[0]))).toMatch(/class CurioModel[\s\S]*def run\(self, feeds/);
  });

  test("the worked example shows Local Relief's own manifest, node code, module and widget", () => {
    const blocks = codeBlocks(guide());
    const manifest = localReliefManifest();

    const shownManifest = blocks.find((block) => block.lang === "json" && block.body.includes('"kind": "model"'));
    expect(shownManifest).toBeDefined();
    expect(isDeepSubset(JSON.parse((shownManifest as { body: string }).body), manifest)).toBe(true);

    const template = firstTemplate(manifest);
    const source = read(path.join(LOCAL_RELIEF, template["source"] as string));
    const cell = source.replace(/^"""[\s\S]*?"""\n/, "").trim();
    const shownCell = blocks.find(
      (block) => block.lang === "python" && block.body.includes('curio_load_model("model.example.local-relief")'),
    );
    expect(shownCell).toBeDefined();
    expect((shownCell as { body: string }).body.trim()).toBe(cell);

    const module = read(path.join(LOCAL_RELIEF, "sources", "local_relief", "run.py")).split("\n").map((line) => line.trim());
    const shownModule = blocks.find((block) => block.lang === "python" && block.body.includes("def local_relief("));
    expect(shownModule).toBeDefined();
    const invented = (shownModule as { body: string }).body
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line !== "" && !line.startsWith("#") && !module.includes(line));
    expect(invented).toEqual([]);

    const shownWidget = blocks.find((block) => block.lang === "json" && block.body.trimStart().startsWith('{ "name": "min_height"'));
    expect(shownWidget).toBeDefined();
    expect(JSON.parse((shownWidget as { body: string }).body)).toEqual((template["widgets"] as Json[])[0]);
  });

  test("the widgets it lists for each model's node are that node's own", () => {
    const widgets = section(guide(), /Widgets: what the user sets/);
    const rows = widgets.split("\n").filter((line) => /^\| \*\*.*@1`\) \|/.test(line));
    expect(rows.length).toBe(3);
    const kinds = schemaDefs()["widget"] as { properties: { type: { enum: string[] } } };
    for (const row of rows) {
      const dir = ticked(row).find((name) => name.endsWith("@1")) as string;
      const folder = fs.existsSync(path.join(REPO_ROOT, "packages", dir))
        ? path.join(REPO_ROOT, "packages", dir)
        : path.join(DOCS, "bring-your-own-model", dir);
      const declared = (firstTemplate(readJson(path.join(folder, "manifest.json")))["widgets"] as Array<{
        name: string;
        type: string;
      }>);
      const names = declared.map((widget) => widget.name);
      for (const widget of declared) {
        expect(ticked(row)).toContain(widget.name);
        expect(ticked(row)).toContain(widget.type);
      }
      const allowed = new Set([dir, ...names, ...kinds.properties.type.enum]);
      expect(ticked(row).filter((name) => !allowed.has(name))).toEqual([]);
    }
    const shownSeason = codeBlocks(widgets).find((block) => block.body.trimStart().startsWith('{ "name": "season"'));
    expect(shownSeason).toBeDefined();
    const deepUmbra = readJson(path.join(REPO_ROOT, "packages", "model.scout.deep-umbra@1", "manifest.json"));
    expect(JSON.parse((shownSeason as { body: string }).body)).toEqual((firstTemplate(deepUmbra)["widgets"] as Json[])[0]);
  });

  test("the SCOUT results it states are the ones the SCOUT tests pin", () => {
    const text = guide();
    const shadow = read(path.join(PACKAGE_TESTS, "test_scout_shadow.py"));
    const levels = Number(pythonConstant(shadow, "MAX_LEVELS"));
    const share = Math.round(Number(pythonConstant(shadow, "MAX_SHARE")) * 1000) / 10;
    const mean = Number(pythonConstant(shadow, "MAX_MEAN_MINUTES"));
    const median = Number(pythonConstant(shadow, "MAX_MEDIAN_MINUTES"));
    expect(text).toContain(`within ${levels} gray levels`);
    expect(text).toContain(`on at most ${share}% of its pixels`);
    expect(text).toContain(`within ${mean} and ${median} minutes`);

    const routing = read(path.join(PACKAGE_TESTS, "test_scout_routing.py"));
    const tolerance = Number(pythonConstant(routing, "TOLERANCE"));
    const cases = (routing.match(/^CASES = \[([\s\S]*?)\]/m) as RegExpMatchArray)[1].match(/"[^"]+"/g) as string[];
    expect(text).toContain(`each of SCOUT's ${cases.length} recorded runs`);
    expect(text).toContain(`within ${tolerance} of SCOUT's`);
  });

  test("it names nothing that is gone", () => {
    const text = guide();
    expect(GONE.filter((name) => text.includes(name))).toEqual([]);
  });

  test("the docs index, the Model Catalog guide and the authoring guide link to it", () => {
    for (const name of ["README.md", "MODEL-CATALOG.md", "AUTHORING-NODES.md"]) {
      expect(read(path.join(DOCS, name))).toContain("](BRINGING-MODELS.md");
    }
  });
});
