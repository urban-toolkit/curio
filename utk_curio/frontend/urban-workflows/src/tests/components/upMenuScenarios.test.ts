import fs from "fs";
import path from "path";

/**
 * The Scenarios menu (#662) sits on the canvas bar between Provenance and
 * Share, and File can save the whole dataflow as a scenario. Both are edits,
 * so a shared viewer sees neither.
 *
 * Source-read like `upMenuTriggers.test.ts`: UpMenu needs the whole provider
 * stack to render.
 */

const SRC = path.resolve(__dirname, "../..");
const UP_MENU = fs.readFileSync(path.join(SRC, "components/menus/top/UpMenu.tsx"), "utf8");

describe("the Scenarios menu", () => {
  test("is a HeaderMenu between the Provenance button and Share", () => {
    const provenance = UP_MENU.indexOf('data-testid="provenance-btn"');
    const scenarios = UP_MENU.search(/<HeaderMenu\s+label="Scenarios"/);
    const share = UP_MENU.indexOf("<ShareMenu");
    expect(provenance).toBeGreaterThan(-1);
    expect(scenarios).toBeGreaterThan(provenance);
    expect(share).toBeGreaterThan(scenarios);
  });

  test.each(["Save selection as scenario", "Duplicate selection", "Duplicate as scenario"])(
    "offers %s",
    (item) => {
      const menu = UP_MENU.slice(UP_MENU.search(/<HeaderMenu\s+label="Scenarios"/), UP_MENU.indexOf("<ShareMenu"));
      expect(menu).toContain(item);
    },
  );

  test("is hidden from a shared viewer", () => {
    expect(UP_MENU).toMatch(/\{!isSharedView && \(\s*<HeaderMenu\s+label="Scenarios"/);
  });

  test("File saves the whole dataflow as a scenario, for an editor only", () => {
    const file = UP_MENU.slice(UP_MENU.search(/<HeaderMenu\s+label="File"/), UP_MENU.search(/<HeaderMenu\s+label="View"/));
    expect(file).toMatch(/\{!isSharedView && \(\s*<HeaderMenuItem[^>]*saveDataflowAsScenario[\s\S]*?Save dataflow as scenario/);
  });
});
