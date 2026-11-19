/**
 * The words a node and the agents' document check tell a document whose views
 * autk-grammar refuses (autkGrammar.json's `viewRules`, contracts/autkGrammar
 * `autkViewProblem`) are the grammar's own, read from the build the app
 * bundles: its run refuses the same documents' ids with the same sentence as
 * it starts, and its sentences of links, which it says once it drew, are in
 * its code. The stand-in of `arrangeViews` the node's suites use
 * (_support/autkArrangeViews) places every view where the grammar's does.
 */
import * as fs from "fs";
import * as path from "path";

const mockAutkDb = jest.fn();

jest.mock("@urban-toolkit/autk-grammar", () => require("../_support/autkComputeStandIns").grammarBuild(), { virtual: true });
jest.mock("@urban-toolkit/autk-compute", () => require("../_support/autkComputeStandIns").autkComputeModule, { virtual: true });
jest.mock("@urban-toolkit/autk-core", () => require("../_support/autkComputeStandIns").autkCoreBuild(), { virtual: true });
jest.mock("@urban-toolkit/autk-map", () => require("../_support/autkComputeStandIns").autkMapModule, { virtual: true });
jest.mock("@urban-toolkit/autk-plot", () => require("../_support/autkComputeStandIns").autkPlotModule, { virtual: true });
jest.mock("@urban-toolkit/autk-db", () => ({
  AutkDb: function AutkDb(...a: any[]) { return mockAutkDb(...a); },
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395",
  DEFAULT_WORKSPACE_NAME: "autk",
}), { virtual: true });

import { arrangeViews as standIn } from "../_support/autkArrangeViews";

const CONTRACTS = path.join(__dirname, "../../contracts");
/** The grammar's build, as the app bundles it. */
const BUILD = path.resolve(__dirname, "../../../node_modules/@urban-toolkit/autk-grammar/dist/autk-grammar.umd.cjs");

interface ViewCase {
  name: string;
  spec: unknown;
  says: string | null;
}

const CASES: { views: ViewCase[] } = JSON.parse(fs.readFileSync(path.join(CONTRACTS, "autkGrammar.cases.json"), "utf8"));
const RULES: Record<string, string> = JSON.parse(fs.readFileSync(path.join(CONTRACTS, "autkGrammar.json"), "utf8")).viewRules;

/** The rule a sentence fills, by its name in `viewRules`. */
function ruleOf(sentence: string): string | undefined {
  return Object.keys(RULES).find((name) => new RegExp(
    `^${RULES[name].replace(/[.*+?^$()|[\]\\]/g, "\\$&").replace(/\{\w+\}/g, ".*")}$`,
  ).test(sentence));
}

/** The rules the grammar checks as its run starts; it checks the others, of links, once it drew. */
const AT_THE_START = ["emptyId", "sharedId", "plotsWithoutIds", "plotIdIsDataRef"];

const grammar = () => require("@urban-toolkit/autk-grammar");

describe("the sentences are autk-grammar's", () => {
  const refused = CASES.views.filter((c) => c.says !== null && AT_THE_START.includes(ruleOf(c.says!) ?? ""));

  test("cases refuse each rule the grammar checks as its run starts", () => {
    expect(new Set(refused.map((c) => ruleOf(c.says!)))).toEqual(new Set(AT_THE_START));
  });

  test.each(refused.map((c) => [c.name, c] as const))("its run refuses %s in the same words", async (_name, c) => {
    const run = new (grammar().AutkGrammar)().run(c.spec);
    await expect(run).rejects.toMatchObject({ message: c.says });
  });

  test.each(Object.keys(RULES).filter((name) => !AT_THE_START.includes(name)))(
    "its code says the %s sentence of a link, word for word",
    (name) => {
      // Read as text, a quote escaped in a string of the build is a quote.
      const code = fs.readFileSync(BUILD, "utf8").replace(/\\"/g, '"');
      for (const words of RULES[name].split(/\{\w+\}/)) {
        expect(code.includes(words)).toBe(true);
      }
    },
  );
});

describe("the stand-in arrangeViews", () => {
  const SPECS: unknown[] = [
    {},
    { map: { layerRefs: [] } },
    { map: [{ id: "a", layerRefs: [] }, { layerRefs: [] }], plot: [{ dataRef: "t" }, { id: "p", dataRef: "t" }] },
    { layout: { type: "horizontal", gap: 4 }, map: { layerRefs: [] }, plot: { dataRef: "t" } },
    { layout: { type: "grid" }, map: [{ layerRefs: [] }, { layerRefs: [] }, { layerRefs: [] }] },
    { layout: { type: "grid", columns: 3, gap: 12 }, map: [{ layerRefs: [] }], plot: [{ dataRef: "a" }, { dataRef: "b" }, { dataRef: "c" }] },
    { layout: { type: "vertical", gap: 0 }, plot: [{ id: "x", dataRef: "a" }, { id: "y", dataRef: "a" }] },
  ];
  const REFUSED: unknown[] = [
    { layout: { type: "diagonal" } },
    { layout: { gap: -1 } },
    { layout: { type: "grid", columns: 1.5 } },
    { layout: { type: "grid", columns: 0 } },
  ];

  test.each(SPECS.map((spec) => [JSON.stringify(spec), spec] as const))("places %s as the grammar does", (_shown, spec) => {
    expect(standIn(spec)).toEqual(grammar().arrangeViews(spec));
  });

  test.each(REFUSED.map((spec) => [JSON.stringify(spec), spec] as const))("refuses %s in the grammar's words", (_shown, spec) => {
    let said: string | undefined;
    try {
      grammar().arrangeViews(spec);
    } catch (err) {
      said = (err as Error).message;
    }
    expect(said).toBeDefined();
    expect(() => standIn(spec)).toThrow(said);
  });
});
