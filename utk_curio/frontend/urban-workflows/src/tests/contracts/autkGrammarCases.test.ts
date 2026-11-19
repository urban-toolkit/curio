/**
 * The cases in contracts/autkGrammar.cases.json, run through the node's own
 * inputTableName and autkViewProblem (contracts/autkGrammar.ts).
 * backend/tests/test_agents/test_autk_grammar_cases.py runs the same file
 * through contracts.input_table_name and autk_view_problem, so a grammar
 * node and the agents' document check name its inputs alike, and refuse the
 * same documents with the same sentence, one of those autkGrammar.json holds.
 */
import fs from "fs";
import path from "path";

const CONTRACTS = path.join(__dirname, "../../contracts");

interface NameCase {
  position: number;
  name: string;
}

interface ViewCase {
  name: string;
  spec: unknown;
  /** The sentence the document is told, or null. */
  says: string | null;
}

const CASES: { inputTableNames: NameCase[]; views: ViewCase[] } = JSON.parse(
  fs.readFileSync(path.join(CONTRACTS, "autkGrammar.cases.json"), "utf8"),
);

/** Read when a test runs, so a checkout without it fails each test on its own. */
const shared = (): Record<string, unknown> =>
  JSON.parse(fs.readFileSync(path.join(CONTRACTS, "autkGrammar.json"), "utf8"));

/** Loaded when a test runs, for the same reason. */
const autkGrammar = () =>
  require("../../contracts/autkGrammar") as {
    inputTableName: (position: number) => string;
    autkViewProblem: (spec: unknown) => string | null;
  };

/** A sentence of autkGrammar.json's viewRules, as a pattern its filled sentences match. */
const shapeOf = (template: string) =>
  new RegExp(`^${template.replace(/[.*+?^$()|[\]\\]/g, "\\$&").replace(/\{\w+\}/g, ".*")}$`);

describe("the cases", () => {
  test("cover both answers, and every rule of the views with a sentence autkGrammar.json holds", () => {
    const said = CASES.views.flatMap((c) => (c.says === null ? [] : [c.says]));
    expect(said.length).toBeGreaterThan(0);
    expect(said.length).toBeLessThan(CASES.views.length);
    const rules = shared().viewRules as Record<string, string>;
    for (const template of Object.values(rules)) {
      expect(said.some((sentence) => shapeOf(template).test(sentence))).toBe(true);
    }
    expect(CASES.inputTableNames.length).toBeGreaterThan(1);
  });
});

describe("inputTableName", () => {
  test.each(CASES.inputTableNames.map((c) => [c.position, c] as const))(
    "the input on circle %s",
    (_position, c) => {
      expect(c.name).toBe(`${shared().inputTablePrefix}${c.position}`);
      expect(autkGrammar().inputTableName(c.position)).toBe(c.name);
    },
  );
});

describe("autkViewProblem", () => {
  test.each(CASES.views.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    const said = autkGrammar().autkViewProblem(c.spec);
    expect(said).toBe(c.says);
    // Whatever the document, the only sentences it can be told are the file's.
    const rules = Object.values(shared().viewRules as Record<string, string>);
    if (said !== null) expect(rules.some((template) => shapeOf(template).test(said))).toBe(true);
  });
});
