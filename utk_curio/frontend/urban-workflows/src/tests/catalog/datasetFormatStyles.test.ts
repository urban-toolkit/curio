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

/**
 * Every surface that selects a CSS class by dataset format.
 *
 * Keep this list complete. It is not incidental that the two defects this file
 * exists to catch both lived on a surface it did not cover: the canvas dataset
 * palette's `.chip_osm` was byte-identical to `.chip_geojson` (so OSM and
 * GeoJSON rendered the same), and its `.fmt_*` block had no `bundle` or `osm`
 * rule at all — which went unnoticed because nothing rendered `.fmt_*` either.
 */
const SURFACES: Surface[] = [
  {
    // Hub browse card (strip header, active border, tag accent), format
    // filter-rail dot, and browse drawer format badge. Not the card's action
    // link: that reads as text and takes the text colour.
    file: "pages/catalog/CatalogBrowseLayout.module.css",
    prefixes: ["strip", "card", "tagAccent", "dot", "dfmt"],
  },
  {
    // List/row view format badge.
    file: "components/catalog/CatalogKindVisuals.module.css",
    prefixes: ["formatBadge"],
  },
  {
    // Dataset detail panel format chip (also the dataset detail modal).
    file: "components/datasets/catalog/DatasetDetailPanel.module.css",
    prefixes: ["format"],
  },
  {
    // Project-catalog DatasetCard avatar. (No accent bar: a dataset card is the
    // same shape as a package card, which never had one.)
    file: "components/packages/publishing/PackageCard.module.css",
    prefixes: ["avatar"],
  },
  {
    // Canvas dataset palette dropdown. A dark surface, so it renders the same
    // format identity differently — derived from the same `-fg` token rather
    // than from a second set of hexes.
    file: "components/menus/nodes/datasetPalette/DatasetPaletteRows.module.css",
    prefixes: ["chip"],
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

/** The declarations inside one format-keyed rule. */
function ruleBody(css: string, prefix: string, format: string): string {
  const match = css.match(
    new RegExp("\\." + prefix + "_" + format + "(?![\\w-])[^{]*\\{([^}]*)\\}"),
  );
  expect(match).not.toBeNull();
  return (match as RegExpMatchArray)[1];
}

describe("dataset format CSS completeness", () => {
  it("derives at least one format from DATASET_FORMAT_LABEL", () => {
    expect(FORMATS.length).toBeGreaterThan(0);
  });

  test.each(cases)("%s declares .%s_%s", (file, prefix, format) => {
    expect(hasFormatRule(readCss(file), prefix, format)).toBe(true);
  });
});

describe("dataset format colours come from the tokens", () => {
  /**
   * One colour per format, defined once.
   *
   * These rules used to hold literal hexes, and the copies disagreed: GeoTIFF
   * was purple on a browse card, teal in the drawer badge and cyan on an
   * in-canvas card, and it collided exactly with JSON on the card strip and
   * rail dot. Requiring a token reference is what keeps "one format, one
   * colour" true across all six surfaces rather than true by coincidence.
   */
  test.each(cases)("%s .%s_%s resolves to a token", (file, prefix, format) => {
    const body = ruleBody(readCss(file), prefix, format);
    expect(body).toContain("var(--curio-format-" + format + "-");
    expect(body).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
  });

  it("gives every format a distinct fill", () => {
    // GeoTIFF shared JSON's #7A4BD1, so the rail could not tell them apart;
    // OSM shared GeoJSON's green in the canvas palette.
    const tokens = readCss("styles/curioTokens.css");
    const fills = FORMATS.map((format) => {
      const match = tokens.match(
        new RegExp("--curio-format-" + format + "-fg:\\s*(#[0-9a-fA-F]{3,8})"),
      );
      expect(match).not.toBeNull();
      return (match as RegExpMatchArray)[1].toLowerCase();
    });
    expect(new Set(fills).size).toBe(FORMATS.length);
  });
});
