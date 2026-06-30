import fs from "fs";
import path from "path";
import { DATASET_FORMAT_LABEL, DatasetFormat } from "../../services/datasetCatalog";

/**
 * Completeness guard for format-keyed CSS.
 *
 * Several catalog surfaces resolve a CSS class dynamically from a dataset's
 * format, e.g. `styles[`strip_${dataset.format}`]`. When a new format is added
 * to `DatasetFormat` / `DATASET_FORMAT_LABEL` but a matching CSS rule is
 * forgotten, the class silently resolves to "" and the element renders
 * unstyled — which is exactly how the "bundle" header strip ended up invisible
 * (white text on a transparent bar).
 *
 * CSS modules are mapped to `identity-obj-proxy` in jest (see package.json
 * `moduleNameMapper`), so importing a module yields the class name regardless of
 * whether the rule exists — an import-based assertion can't detect the gap.
 * Instead we read the source CSS from disk and assert each format-keyed rule is
 * actually declared.
 *
 * `DATASET_FORMAT_LABEL` is typed `Record<DatasetFormat, string>`, so its keys
 * are guaranteed to match the type; iterating them keeps this test in lockstep
 * with the format union.
 */

const SRC_ROOT = path.resolve(__dirname, "../..");

const FORMATS = Object.keys(DATASET_FORMAT_LABEL) as DatasetFormat[];

interface Surface {
  /** CSS module path relative to src/ */
  file: string;
  /** class-name prefixes resolved dynamically by format (`<prefix>_<format>`) */
  prefixes: string[];
}

/** Every surface that selects a CSS class by dataset format. */
const SURFACES: Surface[] = [
  {
    // Hub browse card (strip header, active border, tag accent, link),
    // format filter-rail dot, and browse drawer format badge.
    file: "pages/catalog/CatalogBrowseLayout.module.css",
    prefixes: ["strip", "card", "tagAccent", "link", "dot", "dfmt"],
  },
  {
    // List/row view format badge.
    file: "components/catalog/CatalogKindVisuals.module.css",
    prefixes: ["formatBadge"],
  },
  {
    // Dataset detail panel format chip.
    file: "components/datasets/catalog/DatasetDetailPanel.module.css",
    prefixes: ["format"],
  },
  {
    // Project-catalog DatasetCard avatar + accent bar.
    file: "components/packages/publishing/PackageCard.module.css",
    prefixes: ["avatar", "accent"],
  },
];

const cssCache = new Map<string, string>();
function readCss(relPath: string): string {
  let css = cssCache.get(relPath);
  if (css === undefined) {
    css = fs.readFileSync(path.join(SRC_ROOT, relPath), "utf8");
    cssCache.set(relPath, css);
  }
  return css;
}

function hasFormatRule(css: string, prefix: string, format: string): boolean {
  // Match `.<prefix>_<format>` not followed by another identifier char, so
  // `.strip_json` does not also satisfy a lookup for `.strip_jsonish` and exact
  // format names are required.
  return new RegExp(`\\.${prefix}_${format}(?![\\w-])`).test(css);
}

type Case = [file: string, prefix: string, format: DatasetFormat];
const cases: Case[] = SURFACES.flatMap(({ file, prefixes }) =>
  prefixes.flatMap((prefix) => FORMATS.map((format): Case => [file, prefix, format])),
);

describe("dataset format CSS completeness", () => {
  it("derives at least one format from DATASET_FORMAT_LABEL", () => {
    expect(FORMATS.length).toBeGreaterThan(0);
  });

  test.each(cases)("%s declares .%s_%s", (file, prefix, format) => {
    expect(hasFormatRule(readCss(file), prefix, format)).toBe(true);
  });
});
