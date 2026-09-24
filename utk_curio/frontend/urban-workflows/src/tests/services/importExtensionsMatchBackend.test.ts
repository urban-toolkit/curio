import fs from "fs";
import path from "path";
import { IMPORTABLE_DATASET_EXTENSIONS } from "../../services/datasetCatalog/datasetCatalogTypes";

/**
 * The import picker and the server must agree on what can be imported.
 *
 * `IMPORTABLE_DATASET_EXTENSIONS` feeds the file picker's `accept` attribute.
 * The server decides for real, from `SUPPORTED_SUFFIXES` plus the two
 * converted-on-import formats. The two lists were kept in step by a comment
 * saying "keep in lockstep with the backend" and nothing else, so drift in
 * either direction was invisible until a user hit it: a file the picker offers
 * and the server rejects reads as a broken upload, and one the server would
 * take but the picker filters out reads as an unsupported format.
 *
 * Reads the Python rather than duplicating the list, for the same reason
 * `datasetFormatStyles.test.ts` reads the CSS: a copy of the answer cannot
 * detect a change in the answer.
 */

const CONSTANTS_PY = path.resolve(
  __dirname,
  "../../../../../backend/app/datasets/domain/constants.py",
);

function pythonList(source: string, name: string): string[] {
  // Matches a dict literal (`SUPPORTED_SUFFIXES = {...}`) or a tuple
  // (`OSM_PBF_SUFFIXES = (...)`), and collects every quoted ".xyz" inside.
  const block = source.match(new RegExp(`${name}\\s*=\\s*[\\{\\(]([^\\}\\)]*)[\\}\\)]`));
  expect(block).not.toBeNull();
  return [...(block as RegExpMatchArray)[1].matchAll(/"(\.[A-Za-z0-9.]+)"/g)].map(
    (m) => m[1],
  );
}

describe("the import picker matches the server", () => {
  const source = fs.readFileSync(CONSTANTS_PY, "utf8");

  it("offers every suffix the server stores directly", () => {
    for (const suffix of pythonList(source, "SUPPORTED_SUFFIXES")) {
      expect(IMPORTABLE_DATASET_EXTENSIONS).toContain(suffix);
    }
  });

  it("offers every suffix the server converts on import", () => {
    for (const name of ["OSM_PBF_SUFFIXES", "GPKG_SUFFIXES"]) {
      for (const suffix of pythonList(source, name)) {
        expect(IMPORTABLE_DATASET_EXTENSIONS).toContain(suffix);
      }
    }
  });

  it("offers nothing the server would refuse", () => {
    const accepted = new Set([
      ...pythonList(source, "SUPPORTED_SUFFIXES"),
      ...pythonList(source, "OSM_PBF_SUFFIXES"),
      ...pythonList(source, "GPKG_SUFFIXES"),
    ]);
    for (const offered of IMPORTABLE_DATASET_EXTENSIONS) {
      // ".osm.pbf" is a compound spelling of ".pbf", which the server matches by
      // its final suffix; the picker lists both so the common filename is
      // recognisable in the dialog.
      const effective = offered === ".osm.pbf" ? ".pbf" : offered;
      expect(accepted).toContain(effective);
    }
  });
});
