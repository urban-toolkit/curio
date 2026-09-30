import fs from "fs";
import path from "path";

/**
 * The Installed libraries status badge stays on one line (#519).
 *
 * The library table is auto-layout, so when its six columns do not fit the
 * browser shrinks the Status column to its longest word and "Cannot import"
 * broke at the space. Source-read, as in planEdgeNames.test.ts: jest maps CSS
 * modules to `identity-obj-proxy`, so a rendered assertion cannot see which
 * rules apply, and jsdom has no table layout to measure.
 */
const CSS = fs.readFileSync(
  path.resolve(__dirname, "../../components/menus/libraries/LibraryManagerWindow.module.css"),
  "utf8",
);

function ruleBody(selector: string): string | null {
  const at = CSS.indexOf("\n" + selector + " {");
  if (at === -1) return null;
  const open = CSS.indexOf("{", at);
  return CSS.slice(open + 1, CSS.indexOf("}", open));
}

test("the error badge does not wrap", () => {
  expect(ruleBody(".statusErrorInline")).toMatch(/white-space:\s*nowrap;/);
});

test("Remove keeps its label on one line too", () => {
  expect(ruleBody(".removeButton")).toMatch(/white-space:\s*nowrap;/);
});
