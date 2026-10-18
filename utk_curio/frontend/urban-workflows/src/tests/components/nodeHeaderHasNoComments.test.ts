/**
 * A node's header has no Comments button, and nothing in the app draws a
 * comment thread on a node: a note on a dataflow is a Note node.
 *
 * Read from the source, as `noContentNodeDelete.test.ts` reads `styles.tsx`:
 * the node container pulls in the whole provider stack. Code comments are
 * stripped first, so prose that names a function is no use of it.
 */
import fs from "fs";
import path from "path";

const SRC = path.resolve(__dirname, "../..");

/** Every TypeScript file under src/, the tests left out. */
function sourceFiles(dir: string = SRC): string[] {
  const files: string[] = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (full !== path.join(SRC, "tests")) files.push(...sourceFiles(full));
    } else if (/\.tsx?$/.test(entry.name) && !/\.(test|spec)\.tsx?$/.test(entry.name)) {
      files.push(full);
    }
  }
  return files;
}

/** A file's code without its comments. */
function code(file: string): string {
  return fs
    .readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

const relative = (file: string) => path.relative(SRC, file).split(path.sep).join("/");

/** A control titled Comments, written as `title="Comments"` or `title={"Comments"}`. */
const COMMENTS_TITLE = /title=\{?\s*["'`]Comments["'`]/;

describe("node comments", () => {
  test("no node header has a Comments button", () => {
    const header = code(path.join(SRC, "components", "styles.tsx"));
    // The header's own controls are read, so the file is the right one.
    expect(header).toContain('title="Minimize"');
    expect(header).toContain('"Pin to dashboard"');
    expect(header).not.toMatch(COMMENTS_TITLE);
    expect(header).not.toMatch(/\bfaComments\b/);
  });

  test("nothing in the app draws a comment thread on a node", () => {
    const traces: Array<[string, RegExp]> = [
      ["the Comments icon", /\bfaComments\b/],
      ["a Comments control", COMMENTS_TITLE],
      ["the comment thread", /\bCommentsList\b/],
      ["the comment mappers", /\butils\/nodeComments\b|\bcommentsFromMetadata\b|\bcommentsToMetadata\b/],
      ["the comment box", /Write a comment/],
    ];
    const found: string[] = [];
    for (const file of sourceFiles()) {
      const text = code(file);
      for (const [what, pattern] of traces) {
        if (pattern.test(text)) found.push(`${relative(file)}: ${what}`);
      }
    }
    expect(found).toEqual([]);
  });
});
