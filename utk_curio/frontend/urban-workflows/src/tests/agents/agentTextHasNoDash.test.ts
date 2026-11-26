/**
 * No text the agents' components show holds an en or em dash: every string,
 * template literal and JSX text under components/agents/, read with the
 * TypeScript parser, so a comment that holds one is no text shown, and a
 * dash written as an escape ("—") is still one. A colon, a comma, a
 * semicolon or parentheses say it instead. The review card's own guard
 * (content/agentReviewCardDashes.test.ts) reads its files by line; this one
 * reads every component of the agents.
 */
import fs from "fs";
import path from "path";
import ts from "typescript";

const SRC = path.resolve(__dirname, "../..");
const AGENTS = path.join(SRC, "components", "agents");
const DASH = /[–—]/;

const relative = (file: string) => path.relative(SRC, file).split(path.sep).join("/");

/** Every TypeScript file under components/agents/, its tests left out. */
function sourceFiles(dir: string = AGENTS): string[] {
  const files: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...sourceFiles(full));
    else if (/\.tsx?$/.test(entry.name) && !/\.(test|spec)\.tsx?$/.test(entry.name) && !entry.name.endsWith(".d.ts")) {
      files.push(full);
    }
  }
  return files;
}

/** Each text *text*, the file *file*, shows: its strings, template literals
 * and JSX text, as their values read, with a dash. */
function dashes(file: string, text: string): string[] {
  const kind = file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  const found: string[] = [];
  const visit = (node: ts.Node): void => {
    const value =
      ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateLiteralToken(node) || ts.isJsxText(node)
        ? node.text
        : null;
    if (value !== null && DASH.test(value)) {
      const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
      found.push(`${relative(file)}:${line}: ${value.trim().slice(0, 120)}`);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return found;
}

describe("the agents' components show no en or em dash", () => {
  const files = sourceFiles();

  test("reads every component of the agents", () => {
    // A guard on the guard: a walk that stopped short would pass.
    expect(files.length).toBeGreaterThan(50);
    expect(files.map(relative)).toEqual(
      expect.arrayContaining([
        "components/agents/content/AgentDatasetCandidatesCard.tsx",
        "components/agents/content/reviewCard/ValidationBlock.tsx",
      ]),
    );
  });

  test("finds a dash in each kind of text, and none in a comment", () => {
    const probe = [
      "// a comment — is no text shown",
      "/* nor is this one – */",
      'const a = "one — two";',
      "const b = 'one \\u2014 two';",
      "const c = `one — ${a} two – three`;",
      "const d = <span>one — two</span>;",
      'const e = "no dash: none";',
    ].join("\n");
    expect(dashes(path.join(AGENTS, "probe.tsx"), probe)).toHaveLength(5);
  });

  test("no string, template literal or JSX text holds one", () => {
    expect(files.flatMap((file) => dashes(file, fs.readFileSync(file, "utf8")))).toEqual([]);
  });
});
