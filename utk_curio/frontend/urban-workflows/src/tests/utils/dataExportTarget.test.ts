/**
 * The name a Data Export node's file downloads under (#226).
 *
 * The node's code writes the file and its output is the file's name. A file
 * named in File name, or by code of its own, downloads under that name. A
 * file `curio_export` named by default (`data_export.<ext>`, File name left
 * empty) takes the name of what feeds the node, with the file's extension:
 * the input dataset's name, else the feeding node's label, else data_export.
 * Three exports from one dataflow therefore do not collide in the download
 * folder under a single filename.
 */
import {
  DEFAULT_STEM,
  exportDownloadName,
  exportFileName,
  sanitizeExportStem,
} from "../../utils/dataExportTarget";

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

describe("exportFileName", () => {
  test("is the name of the file an output names: the name itself, or a path's last part", () => {
    expect(exportFileName("trees.csv")).toBe("trees.csv");
    expect(exportFileName("/srv/curio/data/outputs/1792000000000_0a1b2c3d/trees.parquet")).toBe("trees.parquet");
    expect(exportFileName("C:\\data\\trees.csv")).toBe("trees.csv");
  });

  test("is empty for an output that names no file", () => {
    for (const value of [undefined, null, 42, "", {}, "/srv/outputs/"]) {
      expect(exportFileName(value)).toBe("");
    }
  });
});

describe("exportDownloadName", () => {
  test("the stem curio_export gives an unnamed file is data_export", () => {
    expect(DEFAULT_STEM).toBe("data_export");
  });

  test("a file named in File name, or by code of its own, keeps its name", () => {
    expect(exportDownloadName("trees.csv", { dataset: "parks.csv" }, "Trip Summary")).toBe("trees.csv");
    expect(exportDownloadName("/srv/outputs/1792000000000_0a1b2c3d/report.parquet", null, "Trip Summary")).toBe(
      "report.parquet",
    );
  });

  test("a file named by default takes the input dataset's name, with the file's extension", () => {
    expect(exportDownloadName("data_export.geojson", { dataset: "chicago_boundary.parquet" }, "Loader")).toBe(
      "chicago_boundary.geojson",
    );
    expect(exportDownloadName("data_export.tif", { dataset: "heights.tif" })).toBe("heights.tif");
  });

  test("falls back to the producing node's name", () => {
    // A computed output has no dataset filename of its own.
    expect(exportDownloadName("data_export.csv", {}, "Trip Summary")).toBe("Trip_Summary.csv");
  });

  test("falls back to the default stem when nothing names the input", () => {
    expect(exportDownloadName("data_export.csv", null)).toBe("data_export.csv");
    expect(exportDownloadName("data_export.json", undefined, null)).toBe("data_export.json");
  });

  test("a dataset name that sanitizes away does not win over the node name", () => {
    expect(exportDownloadName("data_export.csv", { dataset: "...." }, "Fallback")).toBe("Fallback.csv");
  });

  test("an output that names no file has no download name", () => {
    expect(exportDownloadName("", { dataset: "x.csv" }, "Node")).toBe("");
    expect(exportDownloadName(42, { dataset: "x.csv" }, "Node")).toBe("");
  });
});
