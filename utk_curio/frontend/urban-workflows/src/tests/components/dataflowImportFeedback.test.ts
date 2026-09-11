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
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

const UP_MENU = read("components/menus/top/UpMenu.tsx");
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
    const body = handler();
    // wrong kind of file, unparseable content, a replay that threw, and a read
    // error: four, and none of them silent.
    expect(body).toContain("showToast(NOT_JSON_FILE_MESSAGE");
    expect(body).toContain("showToast(parsed.message");
    expect(body).toContain("showToast(loadFailedMessage(err)");
    expect(body).toContain("showToast(UNREADABLE_FILE_MESSAGE");
  });

  it("leaves no console.error as the only report of a failure", () => {
    const body = handler();
    const logs = body.match(/console\.error\(/g) ?? [];
    const toasts = body.match(/showToast\(/g) ?? [];
    expect(toasts.length).toBeGreaterThanOrEqual(logs.length);
  });

  it("keeps installing the dataflow's declared packages on success", () => {
    // The dependency warm-up is the reason importing is not just loadTrill;
    // routing the failures must not have dropped it.
    expect(handler()).toContain("ensureWorkflowDeps(parsed.spec)");
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
