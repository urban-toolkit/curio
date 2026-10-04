import fs from "fs";
import path from "path";

/**
 * The scenario commands (#662) live in the View menu, after Minimize Nodes:
 * the canvas bar has no room for a menu of their own beside every catalog's
 * label at 1280px (`test_canvas_header_e2e.py`). File can save the whole
 * dataflow as a scenario. Both are edits, so a shared viewer sees neither.
 *
 * Source-read like `upMenuTriggers.test.ts`: UpMenu needs the whole provider
 * stack to render.
 */

const SRC = path.resolve(__dirname, "../..");
const UP_MENU = fs.readFileSync(path.join(SRC, "components/menus/top/UpMenu.tsx"), "utf8");

const menuSource = (label: string, next: RegExp | string) => {
  const start = UP_MENU.search(new RegExp(`<HeaderMenu\\s+label="${label}"`));
  const rest = UP_MENU.slice(start);
  const end = typeof next === "string" ? rest.indexOf(next) : rest.search(next);
  expect(start).toBeGreaterThan(-1);
  expect(end).toBeGreaterThan(0);
  return rest.slice(0, end);
};

describe("the scenario commands", () => {
  test("add no item to the canvas bar", () => {
    expect(UP_MENU).not.toMatch(/<HeaderMenu\s+label="Scenarios"/);
  });

  test.each(["Save selection as scenario", "Duplicate selection", "Duplicate as scenario", "Show scenarios"])(
    "View offers %s, to an editor only",
    (item) => {
      const view = menuSource("View", 'data-testid="provenance-btn"');
      const scenarios = view.slice(view.search(/\{!isSharedView && \(/));
      expect(view).toMatch(/\{!isSharedView && \(/);
      expect(scenarios).toContain(item);
    },
  );

  test("File saves the whole dataflow as a scenario, for an editor only", () => {
    const file = menuSource("File", /<HeaderMenu\s+label="View"/);
    expect(file).toMatch(/\{!isSharedView && \(\s*<HeaderMenuItem[^>]*saveDataflowAsScenario[\s\S]*?Save dataflow as scenario/);
  });
});
