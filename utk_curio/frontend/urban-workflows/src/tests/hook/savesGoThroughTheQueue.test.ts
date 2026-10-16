import fs from "fs";
import path from "path";

/**
 * Every save of the open dataflow goes through the save queue
 * (`requestProjectSave` in useWorkflowOperations), so the browser never sends
 * two PUTs of one dataflow at once (#909, #941). A caller that saved with
 * `saveCurrentProject` itself went out beside whatever the queue was running.
 *
 * Read from the source because most callers need the whole provider stack to
 * render. The queue's order, the pin's save, the autosave and Save have
 * behaviour tests of their own (useWorkflowOperations.saveQueue.test.ts,
 * dashboardPresentation.test.tsx, upMenuSaveQueue.test.tsx).
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

/**
 * The files that may still name `saveCurrentProject`: the queue's own module,
 * the flow context's type and FlowProvider's default value, and the dashboard's
 * Save layout. That one saves directly on purpose: nothing else saves on the
 * dashboard page (the pin's save, the install saves, the autosave and runs on
 * the server all stand down there), its button is disabled while it saves, and
 * it passes `omitOutputs`, which the queue does not carry.
 */
const MAY_NAME_IT = new Set([
  "hook/useWorkflowOperations.ts",
  "providers/flow/flowContextTypes.ts",
  "providers/FlowProvider.tsx",
  "pages/dashboard/DashboardTopBar.tsx",
]);

describe("saving the open dataflow", () => {
  test("goes through the save queue everywhere but the dashboard's Save layout", () => {
    const direct = sourceFiles()
      .filter((file) => !MAY_NAME_IT.has(relative(file)))
      .filter((file) => /\bsaveCurrentProject\b/.test(code(file)))
      .map(relative)
      .sort();

    expect(direct).toEqual([]);
  });

  test("the agent drop and the catalog drawers' first save take the queue", () => {
    // A drop on a node or a connection saves before it attaches, and the Node
    // and Model Catalog drawers save a never-saved dataflow before Add, Remove
    // or Import. That save creates the project: beside another create, it
    // would be a second dataflow.
    expect(code(path.join(SRC, "components/MainCanvas.tsx"))).toMatch(
      /saveProject:\s*requestProjectSave\b/,
    );
    expect(code(path.join(SRC, "components/packages/publishing/NodeCatalogDrawer.tsx"))).toMatch(
      /await requestProjectSave\(\)/,
    );
  });
});
