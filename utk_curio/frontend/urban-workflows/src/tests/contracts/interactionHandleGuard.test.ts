/**
 * Every module of the frontend tells an interaction handle, and an
 * interaction edge, through the one rule (contracts/interactionEdges.ts): a
 * node's own handle `in/out`, and a view's `in/out@<id>`. A module that wrote
 * the handle out, to compare with it or to make one, would read a view's
 * handle as an input or a data edge. So no module but the rule's spells it or
 * compares a handle with its constant; a module that declares or writes a
 * node's own handle reads the constant.
 *
 * Read with the TypeScript parser, as the other source guards read the files,
 * so a comment or a sentence that names the handle is no use of it. The
 * backend's twin is backend/tests/test_interaction_edges.py.
 */
import fs from "fs";
import path from "path";
import ts from "typescript";

const SRC = path.resolve(__dirname, "../..");
const RULE = "contracts/interactionEdges.ts";
/** A node's own interaction handle, as contracts/interactionEdges.json names it (held to it below). */
const HANDLE = "in/out";
/** What a view's handle starts with: the handle, then the mark. */
const VIEW_HANDLE = `${HANDLE}@`;

/**
 * The modules that may hold the handle's text, each with why. The list is
 * read whole by the last test, so an entry nobody needs is no longer kept.
 */
const ALLOWED: Record<string, string> = {
  "registry/types.ts":
    "ContainerConfig.handleType names which ports a container has: 'in', 'out', or 'in/out' for both, not the interaction handle",
  "registry/packagesClient.ts":
    "writes that handleType from a template's ports: 'in/out' is a template with inputs and outputs",
};

const relative = (file: string) => path.relative(SRC, file).split(path.sep).join("/");

/** Every TypeScript file under src/, the tests, the Jest mocks and type declarations left out. */
function sourceFiles(dir: string = SRC): string[] {
  const files: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (full !== path.join(SRC, "tests") && entry.name !== "jestMocks") files.push(...sourceFiles(full));
    } else if (/\.tsx?$/.test(entry.name) && !/\.(test|spec)\.tsx?$/.test(entry.name) && !entry.name.endsWith(".d.ts")) {
      files.push(full);
    }
  }
  return files;
}

const COMPARISONS = new Set([
  ts.SyntaxKind.EqualsEqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsEqualsToken,
  ts.SyntaxKind.EqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsToken,
]);

/** Whether *node* is the rule's constant, by its name or as a member. */
const isTheConstant = (node: ts.Node) =>
  (ts.isIdentifier(node) && node.text === "INTERACTION_HANDLE")
  || (ts.isPropertyAccessExpression(node) && node.name.text === "INTERACTION_HANDLE");

/** Each place *text*, the file *file*, spells the handle or compares a handle with the rule's constant. */
function findings(file: string, text: string): string[] {
  const kind = file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  const out: string[] = [];
  const at = (node: ts.Node) =>
    `${relative(file)}:${source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1}: ` +
    node.getText(source).split("\n")[0].slice(0, 120);
  const visit = (node: ts.Node): void => {
    // `h === "in/out"`, `{ id: 'in/out' }`, `'in' | 'out' | 'in/out'`, `"in/out@heights"`.
    if (ts.isStringLiteralLike(node) && (node.text === HANDLE || node.text.startsWith(VIEW_HANDLE))) out.push(at(node));
    // `in/out@${id}`, a view's handle made by hand.
    if (ts.isTemplateHead(node) && node.text.startsWith(HANDLE)) out.push(at(node));
    // `h === INTERACTION_HANDLE`: a node's own handle alone, where a view's is one too.
    if (ts.isBinaryExpression(node) && COMPARISONS.has(node.operatorToken.kind)
      && (isTheConstant(node.left) || isTheConstant(node.right))) out.push(at(node));
    ts.forEachChild(node, visit);
  };
  visit(source);
  return out;
}

describe("no module but the rule's spells an interaction handle or compares one", () => {
  const files = sourceFiles();
  const read = (file: string) => fs.readFileSync(file, "utf8");

  test("the handle it looks for is the contract's", () => {
    const contract = JSON.parse(fs.readFileSync(path.join(SRC, "contracts/interactionEdges.json"), "utf8"));
    expect(contract.handle).toBe(HANDLE);
    expect(`${contract.handle}${contract.viewMark}`).toBe(VIEW_HANDLE);
  });

  test("reads the app's code, the rule's module and the readers of interaction edges among it", () => {
    // A guard on the guard: if the walk stopped short, the rule below would pass.
    expect(files.length).toBeGreaterThan(300);
    expect(files.map(relative)).toEqual(expect.arrayContaining([
      RULE,
      "adapters/node/handleHelpers.ts",
      "hook/codeNodes.ts",
      "providers/flow/useConnect.ts",
      "providers/flow/useInteractions.ts",
      "providers/flow/runLevels.ts",
      ...Object.keys(ALLOWED),
    ]));
  });

  test("finds each way of spelling or comparing the handle, and nothing else", () => {
    const probe = [
      "// in/out, named in a comment, is no use of it",
      "if (edge.sourceHandle === 'in/out') {}",
      "const dot = { id: \"in/out\", type: 'source' };",
      "const view = `in/out@${id}`;",
      "const named = 'in/out@heights';",
      "if (h !== INTERACTION_HANDLE) {}",
      "if (INTERACTION_HANDLE == rule.INTERACTION_HANDLE) {}",
      "type Kind = 'in' | 'out' | 'in/out';",
      "const said = 'An in/out connection can only be connected to another in/out connection';",
      "const own = { id: INTERACTION_HANDLE };",
      "const kept = isInteractionHandle(h) ? h : INTERACTION_HANDLE;",
      "const outer = 'in/outer';",
    ].join("\n");
    expect(findings(path.join(SRC, "probe.ts"), probe).map((finding) => finding.split(":")[1])).toEqual([
      "2", "3", "4", "5", "6", "7", "8",
    ]);
  });

  test("no module but the rule's spells the handle or compares a handle with its constant", () => {
    const uses = files
      .filter((file) => relative(file) !== RULE && !(relative(file) in ALLOWED))
      .flatMap((file) => findings(file, read(file)));
    expect(uses).toEqual([]);
  });

  test("the rule's module is there, and every module the list allows still holds the handle", () => {
    expect(fs.existsSync(path.join(SRC, RULE))).toBe(true);
    for (const [file, why] of Object.entries(ALLOWED)) {
      expect(why.length).toBeGreaterThan(0);
      expect([file, findings(path.join(SRC, file), read(path.join(SRC, file))).length > 0]).toEqual([file, true]);
    }
  });
});
