/**
 * The cases in contracts/docMarkup.cases.json, run through the views' own
 * docParts and plainDoc (contracts/docMarkup.ts).
 * backend/tests/test_packages/test_doc_markup_cases.py runs the same file
 * through function_nodes.plain_doc, so a hover under Functions, a package's
 * details and the description of a node made from a function read a
 * docstring's marks alike, from the one pattern docMarkup.json holds.
 */
import fs from "fs";
import path from "path";

const CONTRACTS = path.join(__dirname, "../../contracts");

interface MarkupCase {
  name: string;
  doc: string;
  /** Each part as [kind, words], in order. */
  parts: [string, string][];
}

const CASES: MarkupCase[] = JSON.parse(fs.readFileSync(path.join(CONTRACTS, "docMarkup.cases.json"), "utf8")).cases;

/** Read when a test runs, so a checkout without it fails each test on its own. */
const shared = (): { pattern: string; groups: string[] } =>
  JSON.parse(fs.readFileSync(path.join(CONTRACTS, "docMarkup.json"), "utf8"));

/** Loaded when a test runs, for the same reason. */
const docMarkup = () =>
  require("../../contracts/docMarkup") as {
    docParts: (doc: string) => { kind: string; text: string }[];
    plainDoc: (doc: string) => string;
  };

describe("the cases", () => {
  test("cover every kind of mark the pattern's groups hold, and words no mark sets", () => {
    const kinds = new Set(CASES.flatMap((c) => c.parts.map(([kind]) => kind)));
    expect([...kinds].sort()).toEqual(["code", "emphasis", "strong", "text"]);
    expect([...new Set(shared().groups)].sort()).toEqual(["code", "emphasis", "strong"]);
    expect(CASES.some((c) => c.parts.length === 1 && c.parts[0][0] === "text" && /[*`]/.test(c.doc))).toBe(true);
  });
});

describe("docParts and plainDoc", () => {
  test.each(CASES.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    expect(docMarkup().docParts(c.doc)).toEqual(c.parts.map(([kind, text]) => ({ kind, text })));
    expect(docMarkup().plainDoc(c.doc)).toBe(c.parts.map(([, text]) => text).join(""));
  });
});
