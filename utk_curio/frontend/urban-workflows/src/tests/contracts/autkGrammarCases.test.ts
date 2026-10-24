/**
 * The cases in contracts/autkGrammar.cases.json, run through the node's own
 * inputTableName and autkOneViewProblem (contracts/autkGrammar.ts).
 * backend/tests/test_agents/test_autk_grammar_cases.py runs the same file
 * through contracts.input_table_name and autk_one_view_problem, so a grammar
 * node and the agents' document check name its inputs alike, and refuse the
 * same documents with the same sentence, the one autkGrammar.json holds.
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
  /** The key in autkGrammar.json of what the document is told, or null. */
  problem: string | null;
}

const CASES: { inputTableNames: NameCase[]; oneView: ViewCase[] } = JSON.parse(
  fs.readFileSync(path.join(CONTRACTS, "autkGrammar.cases.json"), "utf8"),
);

/** Read when a test runs, so a checkout without it fails each test on its own. */
const shared = (): Record<string, unknown> =>
  JSON.parse(fs.readFileSync(path.join(CONTRACTS, "autkGrammar.json"), "utf8"));

/** Loaded when a test runs, for the same reason. */
const autkGrammar = () =>
  require("../../contracts/autkGrammar") as {
    inputTableName: (position: number) => string;
    autkOneViewProblem: (spec: unknown) => string | null;
  };

describe("the cases", () => {
  test("cover both answers, and name a sentence autkGrammar.json holds", () => {
    const named = CASES.oneView.flatMap((c) => (c.problem === null ? [] : [c.problem]));
    expect(named.length).toBeGreaterThan(0);
    expect(named.length).toBeLessThan(CASES.oneView.length);
    for (const key of named) expect(typeof shared()[key]).toBe("string");
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

describe("autkOneViewProblem", () => {
  test.each(CASES.oneView.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    const sentences = shared();
    const expected = c.problem === null ? null : sentences[c.problem];
    expect(expected === null || typeof expected === "string").toBe(true);
    expect(autkGrammar().autkOneViewProblem(c.spec)).toBe(expected);
    // Whatever the document, the only sentence it can be told is the file's.
    expect([null, sentences.oneView]).toContain(autkGrammar().autkOneViewProblem(c.spec));
  });
});
