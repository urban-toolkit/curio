/**
 * What the Data Export node will hand you (#226).
 *
 * The node asked for a format in a dropdown and then wrote every file as
 * ``data_export`` regardless of its input. Both were guesses it could make
 * itself: the payload already declares its shape, and the input already has a
 * name. Three exports from one dataflow therefore collided in the download
 * folder under a single filename.
 */
import {
  EXPORT_MIME,
  exportFormatFor,
  resolveExportTarget,
  sanitizeExportStem,
} from "../../utils/dataExportTarget";

describe("exportFormatFor", () => {
  test("follows the payload's declared shape", () => {
    expect(exportFormatFor("geodataframe")).toBe("geojson");
    expect(exportFormatFor("dataframe")).toBe("csv");
  });

  test("is case- and whitespace-tolerant", () => {
    // dataType reaches the frontend from the sandbox, so it is not worth
    // depending on its exact casing.
    expect(exportFormatFor(" GeoDataFrame ")).toBe("geojson");
  });

  test("falls back to json for anything else", () => {
    // Including raster and scalar payloads: there is no better shape to make
    // of them, and offering CSV for a raster was a choice that could only fail.
    for (const kind of ["raster", "value", "list", "", undefined, null, 42]) {
      expect(exportFormatFor(kind)).toBe("json");
    }
  });

  test("every format has a mime type", () => {
    for (const format of ["csv", "geojson", "json"] as const) {
      expect(EXPORT_MIME[format]).toBeTruthy();
    }
  });
});

describe("sanitizeExportStem", () => {
  test("keeps an ordinary title readable", () => {
    expect(sanitizeExportStem("Chicago Community Areas")).toBe("Chicago_Community_Areas");
  });

  test("strips path separators", () => {
    // A dataset title is user text and lands here as a filename.
    expect(sanitizeExportStem("../../etc/passwd")).toBe("etc_passwd");
  });

  test("strips characters a filename cannot carry", () => {
    expect(sanitizeExportStem('re:port<1>|"x"?')).toBe("report1x");
  });

  test("does not produce a hidden or empty name", () => {
    expect(sanitizeExportStem("...")).toBe("");
    expect(sanitizeExportStem("   ")).toBe("");
    expect(sanitizeExportStem(undefined)).toBe("");
  });

  test("caps a very long title", () => {
    expect(sanitizeExportStem("a".repeat(200))).toHaveLength(80);
  });
});

describe("resolveExportTarget", () => {
  test("names the file after the input dataset", () => {
    expect(
      resolveExportTarget({ dataType: "geodataframe", dataset: "chicago_boundary.parquet" }),
    ).toEqual({ format: "geojson", filename: "chicago_boundary.geojson" });
  });

  test("falls back to the producing node's name", () => {
    // A computed output has no dataset filename of its own.
    expect(resolveExportTarget({ dataType: "dataframe" }, "Trip Summary")).toEqual({
      format: "csv",
      filename: "Trip_Summary.csv",
    });
  });

  test("falls back to the old stem when nothing names the input", () => {
    // The previous behaviour for every export, kept as the last resort so an
    // unnamed input still produces something sensible.
    expect(resolveExportTarget({ dataType: "dataframe" }).filename).toBe("data_export.csv");
    expect(resolveExportTarget(null).filename).toBe("data_export.json");
  });

  test("a dataset name that sanitizes away does not win over the node name", () => {
    expect(resolveExportTarget({ dataType: "dataframe", dataset: "...." }, "Fallback").filename).toBe(
      "Fallback.csv",
    );
  });
});
