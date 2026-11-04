import fs from "fs";
import path from "path";

/**
 * No tab saves a dataflow it is open on: the doc keeps each change as it is
 * made, so the browser never sends a whole dataflow over the one the server
 * holds (#909, #941, dev/124). A dataflow is sent whole only when one is made
 * from the canvas (a never-saved canvas's first save, Save a copy); a PUT of
 * a dataflow carries a name or categories, as the Projects page and a rename
 * send them, never a spec.
 *
 * Read from the source because most callers need the whole provider stack to
 * render. File > Save, the pin's record and a run's start have behaviour tests
 * of their own (useWorkflowOperations.tabsStopSaving.test.ts,
 * dashboardPresentation.test.tsx, upMenuSave.test.tsx, serverRun.test.tsx).
 */

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

/** A file's code without its comments: a comment naming a function is no call. */
function code(file: string): string {
  return fs
    .readFileSync(file, "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
}

const relative = (file: string) => path.relative(SRC, file).split(path.sep).join("/");

describe("the dataflow a tab is open on", () => {
  test("has no save of its own left: no save queue, no autosave, no save order", () => {
    const naming = sourceFiles()
      .filter((file) => /\b(saveCurrentProject|requestProjectSave|requestAutosave|enqueueSave|nextSaveOrder|saveTab|saveNumber)\b/.test(code(file)))
      .map(relative)
      .sort();

    expect(naming).toEqual([]);
  });

  test("is never sent whole: a PUT carries a name or categories, never a spec", () => {
    const puts = sourceFiles().flatMap((file) => {
      const source = code(file);
      const calls: string[] = [];
      const call = /projectsApi\.update\(/g;
      for (let found = call.exec(source); found; found = call.exec(source)) {
        // The call's arguments, up to the parenthesis that closes it.
        let depth = 0;
        let end = found.index + found[0].length - 1;
        for (; end < source.length; end += 1) {
          if (source[end] === "(") depth += 1;
          else if (source[end] === ")" && (depth -= 1) === 0) break;
        }
        calls.push(`${relative(file)}: ${source.slice(found.index, end + 1).replace(/\s+/g, " ")}`);
      }
      return calls;
    });

    expect(puts.length).toBeGreaterThan(0);
    expect(puts.filter((put) => /\bspec\b|\boutputs\b/.test(put))).toEqual([]);
  });

  test("is acted on by the agent drop and the catalog drawers once the server holds every change", () => {
    // A drop on a node or a connection attaches to what the server holds, and
    // the Node and Model Catalog drawers make a never-saved dataflow before
    // Add, Remove or Import: one create, never beside another.
    expect(code(path.join(SRC, "components/MainCanvas.tsx"))).toMatch(
      /keepDataflow:\s*ensureProjectId\b/,
    );
    expect(code(path.join(SRC, "components/packages/publishing/NodeCatalogDrawer.tsx"))).toMatch(
      /return keepDataflow\(\)/,
    );
  });
});
