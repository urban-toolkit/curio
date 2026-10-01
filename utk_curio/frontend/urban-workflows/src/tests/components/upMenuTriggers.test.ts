import fs from "fs";
import path from "path";

/**
 * The top bar's menu buttons are named "<Menu> menu", and each draws its down
 * arrow in CSS (`.menuCaret`) instead of writing "⏷" after the name. A written
 * arrow needs a font that has it, and a system without one drew a box.
 *
 * Source-read like `upMenuRename.test.ts`: UpMenu needs the whole provider
 * stack to render. ShareMenu renders alone, so its button is asserted in
 * `shareMenu.test.tsx`.
 */

const SRC = path.resolve(__dirname, "../..");
const UP_MENU = fs.readFileSync(
  path.join(SRC, "components/menus/top/UpMenu.tsx"),
  "utf8",
);
const CSS = fs.readFileSync(
  path.join(SRC, "components/menus/top/UpMenu.module.css"),
  "utf8",
);

describe("the top bar's menu buttons", () => {
  it.each(["File", "View", "Data", "Provenance"])(
    "%s is named after its menu and draws its arrow",
    (menu) => {
      const button = new RegExp(
        `<button\\s+className=\\{clsx\\(styles\\.button, styles\\.menuCaret\\)\\}\\s+`
          + `aria-label="${menu} menu"[\\s\\S]*?>\\s*${menu}\\s*</button>`,
      );
      expect(UP_MENU).toMatch(button);
    },
  );

  it("have no Help menu and no tour", () => {
    expect(UP_MENU).not.toContain('aria-label="Help menu"');
    expect(UP_MENU).not.toContain("intro.js");
  });

  it("write no arrow character", () => {
    expect(UP_MENU).not.toContain("⏷");
  });

  it("draw the arrow as generated content, which adds no text", () => {
    const rule = CSS.slice(CSS.indexOf(".menuCaret::after"));
    expect(rule).toMatch(/^\.menuCaret::after \{[^}]*content: "";/);
  });
});
