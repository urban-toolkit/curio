import fs from "fs";
import path from "path";

/**
 * The Dataset Catalog's bundle preview must scroll a wide table, not clip it
 * (#345).
 *
 * The second surface #203 left behind. `DatasetBundlePreview` already renders
 * `TabularPreviewTable`, so it inherits two thirds of that fix - `overflowX:
 * visible` on the MUI container and `min-width: max-content` on the table, both
 * pinned in `TabularPreviewTable.test.tsx`. Those two only work if the
 * consumer's own wrapper owns the scroll, and this one declared
 * `overflow: hidden`: the columns overflowed exactly as intended and were then
 * cut off with no way to reach them.
 *
 * Source-read for the reason `chipHoverContrast.test.ts` records: jest maps CSS
 * modules to `identity-obj-proxy`, so a rendered assertion cannot see which
 * rules a class carries.
 */
const CSS = fs.readFileSync(
  path.resolve(
    __dirname,
    "../../components/datasets/catalog/DatasetBundlePreview.module.css",
  ),
  "utf8",
);

const SIBLING = fs.readFileSync(
  path.resolve(
    __dirname,
    "../../components/datasets/catalog/DatasetTablePreview.module.css",
  ),
  "utf8",
);

function ruleBody(css: string, selector: string): string | null {
  const at = css.indexOf("\n" + selector + " {");
  if (at === -1) return null;
  const open = css.indexOf("{", at);
  const close = css.indexOf("}", open);
  return close === -1 ? null : css.slice(open + 1, close);
}

describe("the bundle preview's table wrapper", () => {
  it("scrolls rather than clipping", () => {
    const wrap = ruleBody(CSS, ".tableWrap") ?? "";
    expect(wrap).toContain("overflow: auto");
    expect(wrap).not.toContain("overflow: hidden");
  });

  it("keeps the rounded border it was also using overflow for", () => {
    // `overflow: hidden` was doing double duty here. `auto` clips to the
    // border-radius just as well, but the radius has to still be declared.
    const wrap = ruleBody(CSS, ".tableWrap") ?? "";
    expect(wrap).toContain("border-radius");
    expect(wrap).toContain("border:");
  });

  it("styles its scrollbar the way the sibling preview does", () => {
    // DatasetTablePreview is the same component getting this right; matching it
    // keeps one thin scrollbar idiom across the two panels rather than two.
    expect(ruleBody(CSS, ".tableWrap")).toContain("scrollbar-width: thin");
    expect(ruleBody(CSS, ".tableWrap::-webkit-scrollbar")).not.toBeNull();
    expect(ruleBody(SIBLING, ".tableWrap")).toContain("scrollbar-width: thin");
  });
});
