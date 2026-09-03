import fs from "fs";
import path from "path";

/**
 * #240: the tour described a control the Data Loading node does not have.
 *
 * "you can create an array for basic datasets or import data from a file" was
 * written against an uploader that lived in `WidgetsEditor`, was commented out
 * at some point, and is now deleted. A user following the tour looked for a
 * file picker inside the node and found a code editor.
 *
 * Source-read, like `upMenuRename.test.ts` on this same component: UpMenu needs
 * the whole provider stack to mount, and intro.js renders into the document
 * only after a real click. The copy is asserted against the live app by
 * `test_tutorial_copy_e2e.py`.
 */

const SRC = path.resolve(__dirname, "../..");
const UP_MENU = fs.readFileSync(
  path.join(SRC, "components/menus/top/UpMenu.tsx"),
  "utf8",
);
const WIDGETS_EDITOR = fs.readFileSync(
  path.join(SRC, "components/editing/WidgetsEditor.tsx"),
  "utf8",
);

const steps = () => {
  const start = UP_MENU.indexOf("intro.setOptions({");
  const end = UP_MENU.indexOf("showStepNumbers", start);
  expect(start).toBeGreaterThan(-1);
  expect(end).toBeGreaterThan(start);
  return UP_MENU.slice(start, end);
};

const loadingStep = () => {
  const body = steps();
  const at = body.indexOf('element: "#step-loading"');
  expect(at).toBeGreaterThan(-1);
  return body.slice(at, body.indexOf("},", at));
};

describe("the tutorial's Data Loading step", () => {
  it("no longer promises importing data from a file in the node", () => {
    expect(loadingStep()).not.toMatch(/import data from a file/i);
  });

  it("says plainly that the node holds code, not a picker", () => {
    expect(loadingStep()).toMatch(/not a file picker/i);
  });

  it("names the two routes a file can actually take", () => {
    const step = loadingStep();
    expect(step).toMatch(/Data Catalog/);
    // The `[!! var$FILE !!]` marker is the in-node option, and it is the only
    // thing that renders WidgetType.FILE.
    expect(step).toContain("$FILE");
  });

  it("keeps the palette anchor several e2e suites locate the tile through", () => {
    // test_data_pool_scroll_e2e.py, test_tools_rail_fits.py, usertest.py and
    // stress.py all reach the Data Loading tile via this id.
    expect(steps()).toContain('element: "#step-loading"');
  });
});

describe("the tutorial's Data Catalog step", () => {
  it("exists, and follows the Data Loading step that points at it", () => {
    const body = steps();
    const loading = body.indexOf('element: "#step-loading"');
    const catalog = body.indexOf("Files live in the Data Catalog");
    const analysis = body.indexOf('element: "#step-analysis"');
    expect(catalog).toBeGreaterThan(loading);
    expect(catalog).toBeLessThan(analysis);
  });

  it("describes the import then drag flow", () => {
    const body = steps();
    expect(body).toMatch(/import a CSV or GeoJSON/i);
    expect(body).toMatch(/drag the dataset onto the canvas/i);
  });
});

describe("the uploader the old copy described", () => {
  it("is gone from WidgetsEditor rather than left commented out", () => {
    // It sat after `export default`, so it was unreachable and unmaintained,
    // and it is what made the tour's promise look plausible on a source read.
    expect(WIDGETS_EDITOR).not.toContain("csv-upload-widget");
    expect(WIDGETS_EDITOR).not.toContain("handleFileSelect");
    expect(WIDGETS_EDITOR).not.toContain("uploadResult");
  });

  it("took its orphaned state and imports with it", () => {
    expect(WIDGETS_EDITOR).not.toContain("selectedFile");
    expect(WIDGETS_EDITOR).not.toContain("NodeType");
  });

  it("left the live FILE widget alone", () => {
    // A node's own code can still declare `[!! var$FILE !!]`, and that branch
    // is the only real file input the editor has.
    expect(WIDGETS_EDITOR).toContain("WidgetType.FILE");
    expect(WIDGETS_EDITOR).toContain('type="file"');
  });
});
