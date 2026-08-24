import fs from "fs";
import path from "path";

/**
 * Guards against the catalog browse motion coming back.
 *
 * `/catalog/nodes` and `/catalog/data` are separate routes, so every tab switch
 * unmounts one page and mounts the other — and both pages auto-select their
 * first item once the fetch resolves. The detail drawer therefore went from
 * absent to present on every switch, replaying two 300ms transitions at once:
 * the page grid's third column expanding 0px → 320px, and the drawer panel
 * sliding in from `translate3d(100%, 0, 0)`. Both are gone; the layout is final
 * on first paint.
 *
 * The drawer's unmount used to be gated on `transitionend`, so the shell had to
 * lose that gate along with the CSS — otherwise a closed drawer would stay
 * mounted forever. That coupling is why the TSX is asserted on here too.
 *
 * These are absences, and CSS modules go through `identity-obj-proxy` in jest,
 * so — following `removedCatalogChrome.test.ts` — the sources are read from
 * disk rather than imported.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

describe("the catalog browse pages stay motionless", () => {
  test("the page grid does not animate its columns open", () => {
    const css = read("pages/catalog/CatalogBrowseLayout.module.css");
    expect(css).not.toMatch(/transition:[^;]*grid-template-columns/);
    expect(css).toContain(".pageWithDrawer");
  });

  test("the detail drawer does not slide in from the right", () => {
    const css = read("pages/catalog/CatalogBrowseLayout.module.css");
    expect(css).not.toMatch(/translate3d/);
    expect(css).not.toMatch(/transition:[^;]*transform/);
    expect(css).not.toContain(".browseDrawerOpen");
    expect(css).not.toContain("will-change");
  });

  test("the drawer shell unmounts outright, not on a transition end", () => {
    const tsx = read("pages/catalog/CatalogBrowseDrawerShell.tsx");
    expect(tsx).not.toMatch(/onTransitionEnd|TransitionEvent/);
    expect(tsx).not.toMatch(/requestAnimationFrame/);
    expect(tsx).not.toMatch(/browseDrawerOpen/);
    // The grid slot must still be driven, or the column never widens.
    expect(tsx).toMatch(/onLayoutChange\?\.\(presented\)/);
  });
});
