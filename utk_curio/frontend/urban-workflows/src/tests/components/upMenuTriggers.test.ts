import fs from "fs";
import path from "path";

/**
 * The canvas bar's menus: File, View and Share. Each is a `HeaderMenu`, whose
 * trigger is named "<Menu> menu" and draws its down arrow in CSS
 * (`.menuCaret`) instead of writing "⏷" after the name. A written arrow needs
 * a font that has it, and a system without one drew a box.
 *
 * The catalogs are not a menu any more: the old "Data" menu hid all five, and
 * the Discovery Catalog could be reached no other way. Provenance is a row of
 * the View menu, not a menu of its own: its menu held one row with its own
 * name, and the button that replaced it gave its room to the Scenario Catalog.
 *
 * Source-read like `upMenuRename.test.ts`: UpMenu needs the whole provider
 * stack to render. `HeaderMenu` renders alone, so its trigger is asserted in
 * `headerMenu.test.tsx`, ShareMenu's in `shareMenu.test.tsx`, and the catalog
 * buttons in `catalogButtons.test.tsx`.
 */

const SRC = path.resolve(__dirname, "../..");
const UP_MENU = fs.readFileSync(
  path.join(SRC, "components/menus/top/UpMenu.tsx"),
  "utf8",
);
const HEADER_MENU = fs.readFileSync(
  path.join(SRC, "components/menus/top/HeaderMenu.tsx"),
  "utf8",
);
const CSS = fs.readFileSync(
  path.join(SRC, "components/layout/GlobalPageHeader.module.css"),
  "utf8",
);

describe("the top bar's menu buttons", () => {
  it.each(["File", "View"])("%s is a HeaderMenu", (menu) => {
    expect(UP_MENU).toMatch(new RegExp(`<HeaderMenu\\s+label="${menu}"`));
  });

  it("Share is the shared ShareMenu", () => {
    expect(UP_MENU).toMatch(/<ShareMenu\b/);
  });

  it("a HeaderMenu trigger is named after its menu and draws its arrow", () => {
    expect(HEADER_MENU).toContain("aria-label={`${label} menu`}");
    expect(HEADER_MENU).toMatch(/className=\{clsx\(headerStyles\.barButton, headerStyles\.menuCaret/);
  });

  it("have no Data, Provenance or Help menu, and no tour", () => {
    for (const gone of ["Data", "Provenance", "Help"]) {
      expect(UP_MENU).not.toContain(`label="${gone}"`);
      expect(UP_MENU).not.toContain(`aria-label="${gone} menu"`);
    }
    expect(UP_MENU).not.toContain("intro.js");
  });

  it("put the catalogs on the bar itself, and Provenance in the View menu", () => {
    expect(UP_MENU).toContain("<CatalogButtons");
    const start = UP_MENU.search(/<HeaderMenu\s+label="View"/);
    const view = UP_MENU.slice(start, UP_MENU.indexOf("</HeaderMenu>", start));
    expect(view).toMatch(/<HeaderMenuItem[^>]*onClick=\{openTrillProvenanceModal\}[^>]*>\s*Provenance\s*</);
    expect(view).toContain('testId="provenance-menu-item"');
    expect(UP_MENU).not.toContain("provenance-btn");
  });

  it("write no arrow character", () => {
    expect(UP_MENU).not.toContain("⏷");
    expect(HEADER_MENU).not.toContain("⏷");
  });

  it("draw the arrow as generated content, which adds no text", () => {
    const rule = CSS.slice(CSS.indexOf(".menuCaret::after"));
    expect(rule).toMatch(/^\.menuCaret::after \{[^}]*content: "";/);
  });
});
