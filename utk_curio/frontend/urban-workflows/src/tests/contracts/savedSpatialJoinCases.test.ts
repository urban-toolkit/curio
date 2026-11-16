/**
 * The cases in contracts/savedSpatialJoin.cases.json, run through the canvas's
 * convertedSavedJoin (contracts/savedSpatialJoin.ts), which hook/codeNodes.ts
 * reads every node of a load and of the doc through.
 * backend/tests/test_projects/test_saved_spatial_join.py runs the same file
 * through projects/saved_joins.converted_node, which every server reader of a
 * saved dataflow reads it through, so a Spatial Join saved before its code
 * reads alike on the canvas and on the server.
 */
import fs from "fs";
import path from "path";

const CONTRACTS = path.join(__dirname, "../../contracts");
const BUILTIN = path.join(__dirname, "../../../../../../packages/curio.builtin@1");

type Fields = Record<string, any>;

interface SavedJoinCase {
  name: string;
  node: Fields;
  converted: Fields;
}

const CASES: SavedJoinCase[] = JSON.parse(
  fs.readFileSync(path.join(CONTRACTS, "savedSpatialJoin.cases.json"), "utf8"),
).cases;

/** Read when a test runs, so a checkout without it fails each test on its own. */
const shared = (): Fields => JSON.parse(fs.readFileSync(path.join(CONTRACTS, "savedSpatialJoin.json"), "utf8"));

/** Loaded when a test runs, for the same reason. */
const twin = () =>
  require("../../contracts/savedSpatialJoin") as {
    convertedSavedJoin: <T>(node: T) => T;
    isSavedJoin: (node: unknown) => boolean;
  };

/** A case's converted node, its `<code>` the template's code and each of its widgets the template's of its place. */
function expected(c: SavedJoinCase): Fields {
  if (c.converted.content !== "<code>") return c.converted;
  const { code, widgets } = shared();
  const metadata = { ...c.converted.metadata };
  metadata.widgets = (metadata.widgets as Fields[]).map((given, k) => ({ ...widgets[k], ...given }));
  return { ...c.converted, content: code, metadata };
}

describe("the contract", () => {
  test("holds the template's code and widgets", () => {
    const manifest = JSON.parse(fs.readFileSync(path.join(BUILTIN, "manifest.json"), "utf8"));
    const template = manifest.templates.find((t: Fields) => t.id === "spatial-join");
    expect(shared().nodeType).toBe(`${manifest.id}/${template.id}`);
    expect(shared().widgets).toEqual(template.widgets);
    expect(shared().code).toBe(fs.readFileSync(path.join(BUILTIN, template.source), "utf8"));
    expect(shared().setting).toBe("spatialJoin");
    expect(shared().widgetOf).toEqual({ predicate: "operation", output: "output" });
  });

  test("the cases convert some nodes and leave some as they are", () => {
    expect(CASES.some((c) => c.converted.content === "<code>")).toBe(true);
    expect(CASES.some((c) => c.converted.content !== "<code>")).toBe(true);
  });
});

describe("convertedSavedJoin", () => {
  test.each(CASES.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    const node = JSON.parse(JSON.stringify(c.node));
    const converted = twin().convertedSavedJoin(node);
    expect(converted).toEqual(expected(c));
    // The node it was given is left as it is, and a converted node converts no further.
    expect(node).toEqual(c.node);
    expect(twin().isSavedJoin(converted)).toBe(false);
    expect(twin().convertedSavedJoin(converted)).toEqual(converted);
  });
});
