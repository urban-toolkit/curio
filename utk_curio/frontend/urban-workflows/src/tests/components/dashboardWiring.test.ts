/**
 * The wiring that holds the dashboard together, asserted against the source.
 *
 * Each of these is one line in a large file (the route table, a 1400-line node
 * container, the dataflow's bar) whose render pulls in the whole provider
 * stack, and each one fails silently when it drifts: a route that loses its
 * `presentation` flag renders the canvas's editor chrome on a share link, a tile
 * whose handle class drifts from the selector cannot be dragged, and a bar that
 * regains a toggle brings back the canvas mode this replaced. The same approach
 * as `noContentNodeDelete.test.ts`, for the same reason.
 */
import fs from "fs";
import path from "path";

import { DASHBOARD_TILE_DRAG_HANDLE } from "../../utils/dashboardLayout";

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

describe("the route", () => {
  const index = read("index.tsx");

  it("serves /dashboard/:id behind the same sign-in as the canvas", () => {
    expect(index).toMatch(/path="\/dashboard\/:id"\s*element=\{\s*<RequireAuth>\s*<DashboardRoute \/>/);
  });

  it("mounts the page in presentation mode", () => {
    expect(index).toContain("<DataflowProviders presentation>");
    expect(index).toContain("<DashboardPage />");
  });

  it("and the canvas without it", () => {
    expect(index).toMatch(/<DataflowProviders>\s*<MainCanvas \/>\s*<\/DataflowProviders>/);
  });
});

describe("the provider stack", () => {
  const providers = read("components/DataflowProviders.tsx");

  it("hands the flag to the provider and to the loader", () => {
    expect(providers).toContain("<FlowProvider dashboardOn={presentation}>");
    expect(providers).toContain("<ProjectLoader presentation={presentation}>");
  });

  it("leaves collaboration out of a dashboard", () => {
    expect(providers).toContain(
      "{presentation ? body : <CollaborationProvider>{body}</CollaborationProvider>}",
    );
  });
});

describe("the dataflow's bar", () => {
  const upMenu = read("components/menus/top/UpMenu.tsx");

  it("reaches the dashboard through Share, and no longer toggles a mode", () => {
    expect(upMenu).toContain("<ShareMenu");
    expect(upMenu).toMatch(/<ShareMenu[\s\S]*?includeOpenDashboard[\s\S]*?\/>/);
    expect(upMenu).not.toContain("Dashboard Mode");
    expect(upMenu).not.toContain("setDashBoardMode");
    expect(upMenu).not.toContain("dashboardOn");
  });

  it("puts Share before the save status, where a user reads left to right", () => {
    const share = upMenu.indexOf("<ShareMenu");
    const saveStatus = upMenu.indexOf("data-curio-save-state=");
    expect(share).toBeGreaterThan(-1);
    expect(saveStatus).toBeGreaterThan(share);
  });
});

describe("a tile", () => {
  it("is dragged by the band that carries the handle class", () => {
    const styles = read("components/styles.tsx");
    const handleClass = DASHBOARD_TILE_DRAG_HANDLE.replace(/^\./, "");
    expect(styles).toContain(`className="${handleClass}"`);
  });

  it("nothing still refers to the canvas mode this replaced", () => {
    for (const file of [
      "providers/FlowProvider.tsx",
      "components/MainCanvas.tsx",
      "hook/useWorkflowOperations.ts",
    ]) {
      const source = read(file);
      for (const gone of [
        "setDashBoardMode",
        "DashboardPanel",
        "updatePositionDashboard",
        "updatePositionWorkflow",
        "setPositionsInDashboard",
        "setPositionsInWorkflow",
        "handleDashboardToggle",
      ]) {
        expect({ file, gone, found: source.includes(gone) }).toEqual({ file, gone, found: false });
      }
    }
  });
});
