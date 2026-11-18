/**
 * The "keys" cases of contracts/autkGrammar.cases.json, run through the
 * node's own autkKeyProblem (contracts/autkGrammar.ts): a document that writes
 * a key autk-grammar 5 renamed is told its new name, and one that writes a key
 * a node does not run yet is told so, both with where it is written, as is one
 * whose compute pass reads a raster its own data writes (autkRasterPassProblem).
 * backend/tests/test_agents/test_autk_grammar_keys.py runs the same cases
 * through contracts.autk_key_problem, which the agents' document check uses,
 * so the node and the check refuse the same documents with the same sentence.
 */
import fs from "fs";
import path from "path";

const CONTRACTS = path.join(__dirname, "../../contracts");

interface KeyCase {
  name: string;
  spec: unknown;
  /** The sentence the document is told, or null. */
  says: string | null;
}

interface KeyRule {
  in: string;
  key: string;
  value?: string;
  what?: string;
  renamedTo?: string;
}

const CASES: { keys: KeyCase[] } = JSON.parse(
  fs.readFileSync(path.join(CONTRACTS, "autkGrammar.cases.json"), "utf8"),
);

/** Read when a test runs, so a checkout without it fails each test on its own. */
const shared = (): {
  renamedKeys: KeyRule[];
  notRunYet: KeyRule[];
  renamedKey: string;
  notRunYetKey: string;
} => JSON.parse(fs.readFileSync(path.join(CONTRACTS, "autkGrammar.json"), "utf8"));

/** Loaded when a test runs, for the same reason. */
const autkGrammar = () =>
  require("../../contracts/autkGrammar") as {
    autkKeyProblem: (spec: unknown) => string | null;
    autkRasterPassProblem: (spec: unknown, rasters: Iterable<{ name: string; workspace?: string }>) => string | null;
  };

describe("the key cases", () => {
  test("refuse every key the file names, and run documents that write none", () => {
    const { renamedKeys, notRunYet } = shared();
    const said = CASES.keys.map((c) => c.says ?? "");
    for (const rule of renamedKeys) {
      expect(said.some((s) => s.includes(`"${rule.key}"`) && s.includes(`"${rule.renamedTo}"`))).toBe(true);
    }
    for (const rule of notRunYet) {
      expect(said.some((s) => s.includes(`uses ${rule.what}`))).toBe(true);
    }
    expect(CASES.keys.filter((c) => c.says === null).length).toBeGreaterThan(1);
  });
});

describe("autkKeyProblem", () => {
  test.each(CASES.keys.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(autkGrammar().autkKeyProblem(c.spec)).toBe(c.says);
  });

  test("tells a document only the file's sentences", () => {
    const { renamedKey, notRunYetKey } = shared();
    const shapes = [renamedKey, notRunYetKey].map(
      (template) => new RegExp(`^${template.replace(/[.*+?^$()|[\]\\]/g, "\\$&").replace(/\{\w+\}/g, ".*")}$`),
    );
    for (const c of CASES.keys) {
      const said = autkGrammar().autkKeyProblem(c.spec);
      if (said !== null) expect(shapes.some((shape) => shape.test(said))).toBe(true);
    }
  });
});

// A pass over a raster the node's input brings is a pass the document alone
// cannot tell apart from one over a layer, so the node asks with the input's
// rasters, and is told what a pass over the document's own raster is told.
describe("autkRasterPassProblem", () => {
  const PASS = { attributes: { t: "band_1" }, wgslFunction: "return t;", outputColumnName: "warming" };

  const INPUT_0 = [{ name: "input_0" }];

  test("a pass over a raster the input brings is named, with where it is written", () => {
    expect(autkGrammar().autkRasterPassProblem(
      { compute: [{ dataRef: "table_osm_parks", ...PASS }, { dataRef: "input_0", ...PASS }] },
      INPUT_0,
    )).toBe('This spec uses a compute pass over the raster "input_0" at compute[1], which Curio does not run yet.');
    // One pass written alone is the pass.
    expect(autkGrammar().autkRasterPassProblem({ compute: { dataRef: "input_0", ...PASS } }, INPUT_0)).toBe(
      'This spec uses a compute pass over the raster "input_0" at compute, which Curio does not run yet.',
    );
  });

  test("passes over layers, and a map of the raster, are run", () => {
    expect(autkGrammar().autkRasterPassProblem({ compute: [{ dataRef: "table_osm_parks", ...PASS }] }, INPUT_0)).toBeNull();
    expect(autkGrammar().autkRasterPassProblem(
      { map: { layerRefs: [{ dataRef: "input_0", getFnv: "band_1" }] } },
      INPUT_0,
    )).toBeNull();
  });

  // A pass reads the table of its own workspace, and a raster the input brings
  // is in the workspace it came in: the default one, named or not, is one.
  test("a pass over a raster in the raster's workspace is named, and one in another workspace is run", () => {
    const east = [{ name: "input_0", workspace: "east" }];
    expect(autkGrammar().autkRasterPassProblem({ compute: [{ dataRef: "input_0", workspace: "east", ...PASS }] }, east)).toBe(
      'This spec uses a compute pass over the raster "input_0" at compute[0], which Curio does not run yet.',
    );
    expect(autkGrammar().autkRasterPassProblem({ compute: [{ dataRef: "input_0", ...PASS }] }, east)).toBeNull();
    expect(autkGrammar().autkRasterPassProblem({ compute: [{ dataRef: "input_0", workspace: "east", ...PASS }] }, INPUT_0)).toBeNull();
    expect(autkGrammar().autkRasterPassProblem({ compute: [{ dataRef: "input_0", workspace: "autk", ...PASS }] }, INPUT_0)).toBe(
      'This spec uses a compute pass over the raster "input_0" at compute[0], which Curio does not run yet.',
    );
  });
});
