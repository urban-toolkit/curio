import fs from "fs";
import path from "path";

/**
 * #238: every way of picking a bad dataflow file has to reach the user.
 *
 * The parsing itself is covered by `tests/utils/dataflowImport.test.ts`. What
 * is left is the wiring, and neither caller can be mounted cheaply: UpMenu
 * needs the whole provider stack (see `upMenuRename.test.ts` on the same
 * component) and ProjectsList needs the router plus the projects API. So this
 * is a source read, and it exists to stop a `console.error` quietly coming back
 * as the only report of a failure.
 *
 * Since #751 the menu reads and checks the file, and `ProjectLoader` puts it
 * on the canvas as the new dataflow (`projectLoaderOpensDataflowFile.test.tsx`
 * mounts that half), so a replay that throws is reported there.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

const UP_MENU = read("components/menus/top/UpMenu.tsx");
const PROJECT_LOADER = read("components/ProjectLoader.tsx");
const PROJECTS_LIST = read("pages/projects/ProjectsList.tsx");

const slice = (src: string, from: string, to: string) => {
  const start = src.indexOf(from);
  const end = src.indexOf(to, start + 1);
  expect(start).toBeGreaterThan(-1);
  expect(end).toBeGreaterThan(start);
  return src.slice(start, end);
};

describe("File > Load dataflow", () => {
  const handler = () =>
    slice(UP_MENU, "const handleFileUpload", "const exportAsJupyterNotebook");
  // Where the picked file becomes the new dataflow (#751).
  const opener = () =>
    slice(PROJECT_LOADER, "takeOpenedDataflowFile();", "[id, openedFileRevision]");

  it("goes through the shared parser instead of a bare JSON.parse", () => {
    expect(handler()).toContain("parseDataflowFile(");
    expect(handler()).not.toContain("JSON.parse(");
  });

  it("no longer gates on the MIME type alone", () => {
    // `file.type === "application/json"` refused valid .json files on Windows,
    // where the type is often reported empty.
    expect(handler()).toContain("looksLikeJsonFile(file)");
    expect(handler()).not.toContain('file.type === "application/json"');
  });

  it("toasts on every failure path", () => {
    // wrong kind of file, unparseable content, a read error, and a replay that
    // threw: four, and none of them silent.
    const body = handler();
    expect(body).toContain("showToast(NOT_JSON_FILE_MESSAGE");
    expect(body).toContain("showToast(parsed.message");
    expect(body).toContain("showToast(UNREADABLE_FILE_MESSAGE");
    expect(opener()).toContain("showToast(loadFailedMessage(err)");
  });

  it("leaves no console.error as the only report of a failure", () => {
    for (const body of [handler(), opener()]) {
      const logs = body.match(/console\.error\(/g) ?? [];
      const toasts = body.match(/showToast\(/g) ?? [];
      expect(toasts.length).toBeGreaterThanOrEqual(logs.length);
    }
  });

  it("keeps installing the dataflow's declared packages on success", () => {
    // The dependency warm-up is the reason importing is not just loadTrill;
    // routing the failures must not have dropped it.
    const body = opener();
    expect(body).toContain("ensureWorkflowDeps(spec)");
    expect(body.indexOf("loadTrill(spec)")).toBeGreaterThan(-1);
    expect(body.indexOf("loadTrill(spec)")).toBeLessThan(body.indexOf("ensureWorkflowDeps(spec)"));
  });

  it("opens the file as a new dataflow, the way File > New starts one (#751)", () => {
    // Loading into the open dataflow made the next save write the file's nodes
    // into that dataflow's project, under its name: the file was listed
    // nowhere, and the open dataflow lost its own nodes.
    const body = handler();
    expect(body).toMatch(/leaveWithGuard\([\s\S]*startNewDataflow\(parsed\.spec\)/);
    expect(body).not.toContain("loadTrill(");
    expect(slice(UP_MENU, "const handleNewWorkflow", "const handleSave")).toContain(
      "startNewDataflow()",
    );
    const start = slice(UP_MENU, "const startNewDataflow", "const handleNewWorkflow");
    for (const step of ["discardProject()", "cleanCanvas()", "openDataflowFile(file)"]) {
      expect(start).toContain(step);
    }
    // Handed over before the route changes, so the loader finds it there.
    expect(start.indexOf("openDataflowFile(file)")).toBeLessThan(
      start.indexOf('navigate("/dataflow/new")'),
    );
  });
});

describe("importing a Jupyter notebook from the projects page", () => {
  const handler = () =>
    slice(PROJECTS_LIST, "const handleNotebookImport", "\n  return (");

  it("reports a notebook that is not valid JSON", () => {
    expect(handler()).toMatch(/showToast\([\s\S]*not valid JSON/);
  });

  it("reports a notebook that could not be converted", () => {
    expect(handler()).toContain("could not be converted into a dataflow");
  });

  it("reports a file it could not read", () => {
    expect(handler()).toContain("showToast(UNREADABLE_FILE_MESSAGE");
  });
});
